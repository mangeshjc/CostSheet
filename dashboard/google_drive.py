"""Upload an Excel file into a Google Drive folder and convert it to a Sheet.

Uses OAuth user credentials (see the ``google_auth`` management command for the
one-time sign-in). Because the credentials belong to the signed-in user, the
created Google Sheet is owned by that user and lands in their My Drive folder.
"""
import json
import socket
from pathlib import Path

from django.conf import settings
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# Large spreadsheets (e.g. the 48-sheet Horizontal CS) need more than the
# default socket timeout for metadata/value reads.
socket.setdefaulttimeout(180)

# Full Drive scope so we can drop the new file into an existing folder.
SCOPES = ["https://www.googleapis.com/auth/drive"]

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLS_MIME = "application/vnd.ms-excel"
GSHEET_MIME = "application/vnd.google-apps.spreadsheet"


class GoogleDriveError(Exception):
    """Raised when the upload/conversion cannot be completed."""


def redirect_uri():
    """The exact redirect URI the sign-in flow will use.

    Must be registered verbatim under the OAuth client's *Authorized redirect
    URIs* in the Cloud Console, or Google rejects sign-in with
    ``Error 400: redirect_uri_mismatch``.
    """
    return f"http://localhost:{settings.GOOGLE_OAUTH_REDIRECT_PORT}/"


def client_config():
    """Build the OAuth client config dict from settings."""
    return {
        "installed": {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri()],
        }
    }


def _cache_refreshed_token(creds):
    """Write a freshly refreshed token back to the token file, if we use one.

    Best effort. A hosted deployment supplies credentials through the
    environment and has no durable filesystem, and losing the cached copy only
    costs one extra refresh next time.
    """
    if settings.GOOGLE_TOKEN_JSON:
        return
    try:
        Path(settings.GOOGLE_TOKEN_FILE).write_text(creds.to_json())
    except OSError:
        pass


def load_credentials():
    """Load the OAuth credentials, refreshing them if needed.

    Credentials come from ``settings.GOOGLE_TOKEN_JSON`` when it is set -- how a
    hosted deployment supplies them -- and otherwise from the token file cached
    by the ``google_auth`` command.
    """
    token_json = (settings.GOOGLE_TOKEN_JSON or "").strip()
    token_file = Path(settings.GOOGLE_TOKEN_FILE)

    if token_json:
        try:
            creds = Credentials.from_authorized_user_info(
                json.loads(token_json), SCOPES
            )
        except Exception as exc:  # noqa: BLE001
            raise GoogleDriveError(
                f"GOOGLE_TOKEN_JSON is not valid credential JSON: {exc}. It must "
                "hold the whole contents of google_token.json -- run "
                "'python manage.py google_token_env' to print it."
            ) from exc
    elif token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    else:
        raise GoogleDriveError(
            "Not signed in to Google yet. Run:  python manage.py google_auth  "
            "(a browser window will open once to grant access). On a hosted "
            "deployment, set the GOOGLE_TOKEN_JSON environment variable instead."
        )

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:  # noqa: BLE001
                raise GoogleDriveError(
                    f"Google sign-in expired and could not refresh: {exc}. "
                    "Run 'python manage.py google_auth' again."
                ) from exc
            _cache_refreshed_token(creds)
        else:
            raise GoogleDriveError(
                "Google sign-in is invalid. Run 'python manage.py google_auth' again."
            )
    return creds


def upload_and_convert(file_obj, filename):
    """Upload ``file_obj`` (an Excel file) to the configured Drive folder,
    converting it to a native Google Sheet.

    Returns a dict with the new file's id, name, and web link.
    """
    folder_id = settings.GOOGLE_DRIVE_FOLDER_ID
    if not folder_id:
        raise GoogleDriveError(
            "No Drive folder configured. Set GOOGLE_DRIVE_FOLDER_ID in settings.py."
        )

    creds = load_credentials()
    try:
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as exc:  # noqa: BLE001
        raise GoogleDriveError(f"Could not connect to Google Drive: {exc}") from exc

    source_mime = XLS_MIME if filename.lower().endswith(".xls") else XLSX_MIME
    sheet_name = filename.rsplit(".", 1)[0]

    file_obj.seek(0)
    media = MediaIoBaseUpload(file_obj, mimetype=source_mime, resumable=False)
    metadata = {
        "name": sheet_name,
        "mimeType": GSHEET_MIME,  # requesting this converts the upload to a Sheet
        "parents": [folder_id],
    }

    try:
        created = (
            service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id, name, webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise GoogleDriveError(
            f"Could not upload/convert the file in Google Drive: {exc}"
        ) from exc

    return {
        "file_id": created.get("id"),
        "name": created.get("name"),
        "sheet_url": created.get("webViewLink"),
    }


# ---------------------------------------------------------------------------
# ERP Files page: browse a folder's Google Sheets and read their data
# ---------------------------------------------------------------------------
FOLDER_MIME = "application/vnd.google-apps.folder"


def _drive_service(creds):
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _sheets_service(creds):
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def resolve_source_folder_id(creds):
    """Return the ERP source folder id, looking it up by name if not set."""
    folder_id = settings.GOOGLE_ERP_SOURCE_FOLDER_ID
    if folder_id:
        return folder_id

    name = settings.GOOGLE_ERP_SOURCE_FOLDER_NAME
    service = _drive_service(creds)
    safe = name.replace("'", "\\'")
    query = (
        f"name = '{safe}' and mimeType = '{FOLDER_MIME}' and trashed = false"
    )
    try:
        resp = (
            service.files()
            .list(q=query, fields="files(id, name)", pageSize=10,
                  supportsAllDrives=True, includeItemsFromAllDrives=True)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise GoogleDriveError(f"Could not search Drive for the folder: {exc}") from exc

    files = resp.get("files", [])
    if not files:
        raise GoogleDriveError(
            f"No Drive folder named '{name}' was found. Set "
            "GOOGLE_ERP_SOURCE_FOLDER_ID in settings.py to the folder's id."
        )
    return files[0]["id"]


def list_folder_sheets(creds=None):
    """List the Google Sheets inside the ERP source folder.

    Returns (folder_id, [{'id', 'name'}, ...]) sorted by name.
    """
    if creds is None:
        creds = load_credentials()
    folder_id = resolve_source_folder_id(creds)
    service = _drive_service(creds)
    query = (
        f"'{folder_id}' in parents and mimeType = '{GSHEET_MIME}' "
        "and trashed = false"
    )
    try:
        resp = (
            service.files()
            .list(q=query, fields="files(id, name)", pageSize=200,
                  orderBy="name", supportsAllDrives=True,
                  includeItemsFromAllDrives=True)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise GoogleDriveError(f"Could not list files in the folder: {exc}") from exc

    return folder_id, resp.get("files", [])


# Tab lists are cached (in-process + on disk): fetching all worksheet titles
# loads the whole spreadsheet model server-side and is very slow for large
# workbooks (e.g. the 48-sheet Horizontal CS). The tab list never changes for a
# given file, so we fetch it once and reuse it.
_TAB_CACHE = {}
_TAB_CACHE_FILE = Path(settings.GOOGLE_TAB_CACHE_FILE)


def _tab_cache_load():
    try:
        return json.loads(_TAB_CACHE_FILE.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _tab_cache_save(disk):
    try:
        _TAB_CACHE_FILE.write_text(json.dumps(disk))
    except Exception:  # noqa: BLE001
        pass


def get_sheet_tabs(file_id, creds=None, refresh=False):
    """Return the worksheet titles of a Google Sheet (cached in-process + on disk)."""
    if not refresh and file_id in _TAB_CACHE:
        return _TAB_CACHE[file_id]
    disk = _tab_cache_load()
    if not refresh and file_id in disk:
        _TAB_CACHE[file_id] = disk[file_id]
        return disk[file_id]

    if creds is None:
        creds = load_credentials()
    service = _sheets_service(creds)
    try:
        meta = (
            service.spreadsheets()
            .get(spreadsheetId=file_id, fields="sheets.properties.title")
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise GoogleDriveError(f"Could not open that Google Sheet: {exc}") from exc
    tabs = [s["properties"]["title"] for s in meta.get("sheets", [])]
    _TAB_CACHE[file_id] = tabs
    disk[file_id] = tabs
    _tab_cache_save(disk)
    return tabs


def read_tab_values(file_id, tab, creds=None, max_rows=300):
    """Read only the first ``max_rows`` rows of one tab (fast, avoids the slow
    whole-model metadata read). Returns {'rows','url','truncated','title'}."""
    if creds is None:
        creds = load_credentials()
    service = _sheets_service(creds)
    try:
        values = (
            service.spreadsheets().values()
            .get(spreadsheetId=file_id, range=f"'{tab}'!1:{max_rows}")
            .execute().get("values", [])
        )
    except Exception as exc:  # noqa: BLE001
        raise GoogleDriveError(f"Could not read '{tab}': {exc}") from exc
    width = max((len(r) for r in values), default=0)
    rows = [r + [""] * (width - len(r)) for r in values]
    return {
        "rows": rows, "title": tab, "truncated": False,
        "url": f"https://docs.google.com/spreadsheets/d/{file_id}/edit#gid=0",
    }


def fetch_all_values(file_id, tab, creds=None, unformatted=True):
    """Return every value of one worksheet as a list of rows (no row cap).

    With ``unformatted=True`` numbers come back as numbers and dates as Excel
    serial numbers, which is what the ARTR converter needs.
    """
    if creds is None:
        creds = load_credentials()
    service = _sheets_service(creds)
    render = "UNFORMATTED_VALUE" if unformatted else "FORMATTED_VALUE"
    try:
        values = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=file_id, range=tab,
                 valueRenderOption=render, dateTimeRenderOption="SERIAL_NUMBER")
            .execute()
            .get("values", [])
        )
    except Exception as exc:  # noqa: BLE001
        raise GoogleDriveError(f"Could not read the sheet data: {exc}") from exc
    return values


def find_existing_workbook(name_prefix, folder_id, creds=None):
    """Return the most recent Google Sheet in `folder_id` whose name starts with
    `name_prefix`, or None. Used to avoid rebuilding a workbook that already exists."""
    if creds is None:
        creds = load_credentials()
    service = _drive_service(creds)
    safe = name_prefix.replace("'", "\\'")
    q = (f"name contains '{safe}' and '{folder_id}' in parents "
         f"and mimeType = '{GSHEET_MIME}' and trashed = false")
    try:
        resp = (service.files().list(
            q=q, fields="files(id, name, webViewLink, createdTime)",
            orderBy="createdTime desc", pageSize=10,
            supportsAllDrives=True, includeItemsFromAllDrives=True).execute())
    except Exception:  # noqa: BLE001
        return None
    for f in resp.get("files", []):
        if f["name"].startswith(name_prefix):
            return f
    return None


def list_office_sources(name_contains, creds=None):
    """List Office spreadsheet files (xlsx/xlsm, not already Google Sheets) whose
    name contains `name_contains`. Used for the Sales Dashboard picker."""
    if creds is None:
        creds = load_credentials()
    service = _drive_service(creds)
    safe = name_contains.replace("'", "\\'")
    q = (f"name contains '{safe}' and trashed = false "
         f"and mimeType != '{GSHEET_MIME}' and mimeType != '{FOLDER_MIME}'")
    try:
        resp = (service.files().list(
            q=q, fields="files(id, name, mimeType)", orderBy="name", pageSize=50,
            supportsAllDrives=True, includeItemsFromAllDrives=True).execute())
    except Exception as exc:  # noqa: BLE001
        raise GoogleDriveError(f"Could not list source files: {exc}") from exc
    # keep spreadsheet-like files only
    out = []
    for f in resp.get("files", []):
        mt = f.get("mimeType", "")
        if "sheet" in mt or "excel" in mt or f["name"].lower().endswith((".xlsx", ".xlsm", ".xlsb")):
            out.append({"id": f["id"], "name": f["name"]})
    return out


def convert_office_to_sheet(src_id, name, folder_id, creds=None):
    """Convert an .xlsx/.xlsm file to a native Google Sheet in `folder_id`,
    reusing an already-converted copy of the same name if present."""
    if creds is None:
        creds = load_credentials()
    existing = find_existing_workbook(name, folder_id, creds)
    if existing:
        return existing["id"]
    service = _drive_service(creds)
    try:
        c = service.files().copy(
            fileId=src_id,
            body={"name": name, "mimeType": GSHEET_MIME, "parents": [folder_id]},
            fields="id", supportsAllDrives=True).execute()
    except Exception as exc:  # noqa: BLE001
        raise GoogleDriveError(
            f"Could not convert '{name}' to a Google Sheet: {exc}") from exc
    return c["id"]


def read_sheet_data(file_id, tab=None, creds=None, max_rows=500):
    """Read one worksheet of a Google Sheet.

    Returns {'title', 'tabs', 'active_tab', 'rows', 'url', 'truncated'}.
    """
    if creds is None:
        creds = load_credentials()
    service = _sheets_service(creds)
    try:
        meta = (
            service.spreadsheets()
            .get(spreadsheetId=file_id,
                 fields="properties.title,sheets.properties.title")
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise GoogleDriveError(f"Could not open that Google Sheet: {exc}") from exc

    tabs = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if not tabs:
        raise GoogleDriveError("That Google Sheet has no worksheets.")
    active_tab = tab if tab in tabs else tabs[0]

    try:
        values = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=file_id, range=active_tab)
            .execute()
            .get("values", [])
        )
    except Exception as exc:  # noqa: BLE001
        raise GoogleDriveError(f"Could not read the sheet data: {exc}") from exc

    truncated = len(values) > max_rows
    rows = values[:max_rows]
    # Pad rows so every row has the same number of columns as the widest row.
    width = max((len(r) for r in rows), default=0)
    rows = [r + [""] * (width - len(r)) for r in rows]

    return {
        "title": meta.get("properties", {}).get("title", ""),
        "tabs": tabs,
        "active_tab": active_tab,
        "rows": rows,
        "url": f"https://docs.google.com/spreadsheets/d/{file_id}/edit",
        "truncated": truncated,
    }


def find_artr_tab(file_id, creds=None):
    """Return the worksheet in an ERP export that holds the ARTR detail table."""
    if creds is None:
        creds = load_credentials()
    tabs = get_sheet_tabs(file_id, creds)
    if not tabs:
        raise GoogleDriveError("The selected file has no worksheets.")
    candidates = sorted(tabs, key=lambda t: 0 if "detail" in t.lower() else 1)
    service = _sheets_service(creds)
    for t in candidates:
        try:
            vals = (
                service.spreadsheets().values()
                .get(spreadsheetId=file_id, range=f"'{t}'!A1:E25")
                .execute().get("values", [])
            )
        except Exception:  # noqa: BLE001
            continue
        for row in vals:
            if any(str(c).strip() == "Accounting Site Code" for c in row):
                return t
    return candidates[0]


def create_sheet_from_rows(header, rows, name, creds=None, folder_id=None,
                           worksheet_title="ARTR Master V2"):
    """Write (header + rows) to an in-memory xlsx and upload it to Drive as a
    new native Google Sheet. Returns {'file_id', 'name', 'sheet_url'}."""
    from io import BytesIO
    from openpyxl import Workbook

    if creds is None:
        creds = load_credentials()
    folder_id = folder_id or settings.GOOGLE_DRIVE_FOLDER_ID
    if not folder_id:
        raise GoogleDriveError("No Drive folder configured to save the result.")

    wb = Workbook(write_only=True)
    ws = wb.create_sheet(worksheet_title[:31])
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    service = _drive_service(creds)
    media = MediaIoBaseUpload(buf, mimetype=XLSX_MIME, resumable=True)
    metadata = {"name": name, "mimeType": GSHEET_MIME, "parents": [folder_id]}
    try:
        created = (
            service.files()
            .create(body=metadata, media_body=media,
                    fields="id, name, webViewLink", supportsAllDrives=True)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise GoogleDriveError(f"Could not save the converted sheet to Drive: {exc}") from exc

    return {
        "file_id": created.get("id"),
        "name": created.get("name"),
        "sheet_url": created.get("webViewLink"),
    }
