"""Period lifecycle + build orchestration.

Ties the pieces together: create a period (Drive folders + DB row), register
uploaded source files, and run a data-file converter, logging each step to the
Sheets database.
"""
from ..google_drive import GoogleDriveError, load_credentials
from . import config
from .drive_store import create_period_tree, folder_for
from .registry import ConverterError, get_converter
from .sheet_db import get_db, now_iso


def new_period(name, creds=None):
    """Create the Drive folder tree and register the period in the DB."""
    creds = creds or load_credentials()
    tree = create_period_tree(name, creds)
    period_id = tree["period_folder_id"]
    db = get_db(creds)
    if not any(p["period_id"] == period_id for p in db.read("Periods")):
        db.append("Periods", {
            "period_id": period_id, "name": name,
            "folder_id": period_id, "status": "open", "created_at": now_iso(),
        })
    db.log(period_id, "period", "created", name)
    return {"period_id": period_id, "name": name, "folders": tree["folders"]}


def register_source(period_id, file_type, name, drive_file_id, sheet_id, creds=None):
    """Record an uploaded/converted ERP source file for a period."""
    db = get_db(creds)
    db.append("SourceFiles", {
        "period_id": period_id, "file_type": file_type, "name": name,
        "drive_file_id": drive_file_id, "sheet_id": sheet_id,
        "status": "ready", "uploaded_at": now_iso(),
    })
    db.log(period_id, f"source:{file_type}", "uploaded", name)


class BuildContext:
    """Everything a converter needs, resolved for one period."""

    def __init__(self, period, creds=None):
        self.period = period
        self.period_id = period["period_id"]
        self.name = period["name"]
        self.folders = period["folders"]
        self.creds = creds or load_credentials()
        self.db = get_db(self.creds)
        self._sources = {s["file_type"]: s for s in self.db.read("SourceFiles")
                         if s["period_id"] == self.period_id}

    def source_sheet_id(self, file_type):
        s = self._sources.get(file_type)
        if not s or not s.get("sheet_id"):
            raise ConverterError(
                f"Source '{file_type}' has not been uploaded/converted for "
                f"period '{self.name}'."
            )
        return s["sheet_id"]

    def folder_id(self, relative_path):
        return folder_for(self.folders, relative_path)

    def output_name(self, base):
        return f"{base}_{self.name}"


def build_data_file(period, data_key, creds=None):
    """Run the converter for one data file and record the result."""
    creds = creds or load_credentials()
    spec = config.by_key(config.DATA_FILES, data_key)
    if not spec:
        raise ConverterError(f"Unknown data file '{data_key}'.")
    converter = get_converter(spec["converter"])
    if converter is None:
        raise ConverterError(f"No converter registered for '{spec['converter']}'.")

    ctx = BuildContext(period, creds)
    ctx.db.log(ctx.period_id, f"build:{data_key}", "started", spec["name"])
    try:
        result = converter.build(ctx)
    except (ConverterError, GoogleDriveError) as exc:
        ctx.db.log(ctx.period_id, f"build:{data_key}", "failed", str(exc))
        raise

    ctx.db.append("DataFiles", {
        "period_id": ctx.period_id, "data_key": data_key,
        "name": result["name"], "sheet_id": result["sheet_id"],
        "status": "built", "updated_at": now_iso(),
    })
    ctx.db.log(ctx.period_id, f"build:{data_key}", "built", result["name"])
    return result
