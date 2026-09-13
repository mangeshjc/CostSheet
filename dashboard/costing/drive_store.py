"""Drive storage for the costing pipeline: one folder tree per period."""
from django.conf import settings

from ..google_drive import (
    FOLDER_MIME,
    GoogleDriveError,
    _drive_service,
    load_credentials,
)
from .config import FOLDER_TREE

ROOT_NAME = "Costing"


def _find_child_folder(service, name, parent_id):
    safe = name.replace("'", "\\'")
    q = (f"name = '{safe}' and mimeType = '{FOLDER_MIME}' "
         f"and '{parent_id}' in parents and trashed = false")
    resp = (service.files().list(q=q, fields="files(id,name)", pageSize=5,
            supportsAllDrives=True, includeItemsFromAllDrives=True).execute())
    files = resp.get("files", [])
    return files[0]["id"] if files else None


def get_or_create_folder(name, parent_id, creds=None, service=None):
    """Return the id of the child folder `name` under `parent_id`, creating it
    if absent."""
    if service is None:
        service = _drive_service(creds or load_credentials())
    existing = _find_child_folder(service, name, parent_id)
    if existing:
        return existing
    meta = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
    created = service.files().create(body=meta, fields="id",
                                     supportsAllDrives=True).execute()
    return created["id"]


def get_root_folder_id(creds=None, service=None):
    """The app's Costing root folder (from settings, else created in My Drive)."""
    if settings.GOOGLE_COSTING_ROOT_FOLDER_ID:
        return settings.GOOGLE_COSTING_ROOT_FOLDER_ID
    if service is None:
        service = _drive_service(creds or load_credentials())
    return get_or_create_folder(ROOT_NAME, "root", service=service)


def _create_tree(service, tree, parent_id, prefix, out):
    for name, subtree in tree.items():
        fid = get_or_create_folder(name, parent_id, service=service)
        path = f"{prefix}/{name}" if prefix else name
        out[path] = fid
        if subtree:
            _create_tree(service, subtree, fid, path, out)


def create_period_tree(period_name, creds=None):
    """Create <root>/<period_name>/<full subfolder tree>. Idempotent.

    Returns {'period_folder_id', 'folders': {relative_path: folder_id, ...}}.
    """
    if creds is None:
        creds = load_credentials()
    service = _drive_service(creds)
    root_id = get_root_folder_id(service=service)
    period_id = get_or_create_folder(period_name, root_id, service=service)
    folders = {".": period_id}
    _create_tree(service, FOLDER_TREE, period_id, "", folders)
    return {"period_folder_id": period_id, "folders": folders}


def folder_for(period_folders, relative_path):
    """Resolve a config folder path (e.g. F_APTR) to its Drive id for a period."""
    fid = period_folders.get(relative_path)
    if not fid:
        raise GoogleDriveError(f"Period is missing the folder '{relative_path}'.")
    return fid
