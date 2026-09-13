"""Google Sheets as the application database.

A single control spreadsheet holds one tab per table. Rows are plain values;
the first row of every tab is its header. This module is a thin, generic
table layer (create / append / read / update) over the Sheets API so the rest
of the app never touches spreadsheet mechanics.
"""
from datetime import datetime, timezone

from django.conf import settings

from ..google_drive import (
    GoogleDriveError,
    _drive_service,
    _sheets_service,
    load_credentials,
)

# table name -> ordered columns
TABLES = {
    "Periods": ["period_id", "name", "folder_id", "status", "created_at"],
    "SourceFiles": ["period_id", "file_type", "name", "drive_file_id",
                    "sheet_id", "status", "uploaded_at"],
    "DataFiles": ["period_id", "data_key", "name", "sheet_id", "status",
                  "updated_at"],
    "RunLog": ["period_id", "stage", "status", "message", "at"],
}

DB_NAME = "Costing App DB"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SheetDB:
    """Thin table layer over one control spreadsheet."""

    def __init__(self, spreadsheet_id, creds=None):
        self.id = spreadsheet_id
        self.creds = creds or load_credentials()
        self._svc = _sheets_service(self.creds)

    # -- provisioning ---------------------------------------------------------
    @classmethod
    def create(cls, folder_id, creds=None):
        """Create the control spreadsheet (with all tabs + headers) in a Drive
        folder and return a connected SheetDB."""
        creds = creds or load_credentials()
        svc = _sheets_service(creds)
        body = {
            "properties": {"title": DB_NAME},
            "sheets": [{"properties": {"title": t}} for t in TABLES],
        }
        ss = svc.spreadsheets().create(body=body, fields="spreadsheetId").execute()
        sid = ss["spreadsheetId"]
        # move it into the costing folder
        drive = _drive_service(creds)
        drive.files().update(fileId=sid, addParents=folder_id,
                             fields="id", supportsAllDrives=True).execute()
        db = cls(sid, creds)
        # write header rows
        data = [{"range": f"'{t}'!A1", "values": [cols]}
                for t, cols in TABLES.items()]
        svc.spreadsheets().values().batchUpdate(
            spreadsheetId=sid,
            body={"valueInputOption": "RAW", "data": data}).execute()
        return db

    # -- generic table ops ----------------------------------------------------
    def _cols(self, table):
        if table not in TABLES:
            raise GoogleDriveError(f"Unknown table '{table}'.")
        return TABLES[table]

    def read(self, table):
        """Return all rows of `table` as a list of dicts."""
        cols = self._cols(table)
        values = (self._svc.spreadsheets().values()
                  .get(spreadsheetId=self.id, range=f"'{table}'")
                  .execute().get("values", []))
        rows = []
        for r in values[1:]:  # skip header
            r = r + [""] * (len(cols) - len(r))
            rows.append(dict(zip(cols, r)))
        return rows

    def append(self, table, record):
        """Append one record (dict keyed by column) to `table`."""
        cols = self._cols(table)
        row = [record.get(c, "") for c in cols]
        self._svc.spreadsheets().values().append(
            spreadsheetId=self.id, range=f"'{table}'",
            valueInputOption="RAW", insertDataOption="INSERT_ROWS",
            body={"values": [row]}).execute()
        return record

    def update(self, table, key_field, key_value, updates):
        """Update the first row where key_field == key_value. Returns True if
        a row was updated."""
        cols = self._cols(table)
        values = (self._svc.spreadsheets().values()
                  .get(spreadsheetId=self.id, range=f"'{table}'")
                  .execute().get("values", []))
        kidx = cols.index(key_field)
        for i, r in enumerate(values[1:], start=2):  # sheet row number
            if kidx < len(r) and r[kidx] == str(key_value):
                merged = dict(zip(cols, r + [""] * (len(cols) - len(r))))
                merged.update(updates)
                row = [merged.get(c, "") for c in cols]
                self._svc.spreadsheets().values().update(
                    spreadsheetId=self.id, range=f"'{table}'!A{i}",
                    valueInputOption="RAW", body={"values": [row]}).execute()
                return True
        return False

    # -- convenience ----------------------------------------------------------
    def log(self, period_id, stage, status, message=""):
        self.append("RunLog", {"period_id": period_id, "stage": stage,
                               "status": status, "message": message,
                               "at": now_iso()})


def get_db(creds=None):
    """Connect to the configured control spreadsheet."""
    if not settings.GOOGLE_COSTING_DB_SHEET_ID:
        raise GoogleDriveError(
            "No control spreadsheet configured. Run "
            "'python manage.py costing_init' first, then set "
            "GOOGLE_COSTING_DB_SHEET_ID in settings.py."
        )
    return SheetDB(settings.GOOGLE_COSTING_DB_SHEET_ID, creds)
