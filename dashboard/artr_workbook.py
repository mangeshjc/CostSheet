"""Build the full multi-tab ARTR workbook in Google Sheets.

Produces one Google Sheet that mirrors the ARTR side of ARTR_Data_FY26-27.xlsb:
  * data tab   "ARTR Master Data"  (live, from the ERP conversion)
  * reference  "Conso Customers", "Sample- Export"  (static snapshots)
  * report tabs (TPT throughput, Conso, Month Wise, Check Point, ...) recreated
    as REAL Google Sheets pivot tables pointing at the data tab, so they
    recompute automatically every time.

The pivot definitions (rows / columns / page filters / value & calculated
fields) were reverse-engineered from the workbook's own pivot tables.
"""
import json
from io import BytesIO
from pathlib import Path

from django.conf import settings
from googleapiclient.http import MediaIoBaseUpload

from .google_drive import (
    GSHEET_MIME,
    XLSX_MIME,
    GoogleDriveError,
    _drive_service,
    _sheets_service,
    load_credentials,
)

REF_DIR = Path(__file__).resolve().parent / "artr_reference"
DATA_TAB = "ARTR Master Data"

# Calculated-field formulas (Google Sheets pivot syntax; field names in quotes
# resolve to the SUM of that field within the group, matching the Excel pivots).
F_ASP = "=IFERROR('Actual Sales Value With Charges'/'Item Qty',0)"
F_TPT = ("=IFERROR(('Actual Sales Value With Charges'-'Total Consumption Value to be considered in CS')"
         "/'Actual Sales Value With Charges',0)")
F_MATCONS = ("=IFERROR('Total Consumption Value to be considered in CS'"
             "/'Actual Sales Value With Charges',0)")
F_MATCOST = "=IFERROR('Total Consumption Value to be considered in CS'/'Item Qty',0)"
F_TPTAMT = "='Actual Sales Value With Charges'-'Total Consumption Value to be considered in CS'"
F_FINAL = "='Item/Service Amount'+'Item/Service Charges'"


def _s(col):
    return {"sum": col}


def _f(formula):
    return {"formula": formula}


# Each report tab: rows, columns, page filters (field -> value to keep), and
# ordered value fields. "Values" placeholder in the Excel layout is dropped —
# Sheets positions the value block itself.
PIVOT_SPECS = [
    {
        "title": "Check Point",
        "rows": ["Item/Service Account Description"], "cols": [], "filters": {},
        "values": [
            ("Sum of Item/Service Amount", _s("Item/Service Amount")),
            ("Sum of Item/Service Charges", _s("Item/Service Charges")),
            ("Sum of Actual Sales Value With Charges", _s("Actual Sales Value With Charges")),
        ],
    },
    {
        "title": "Month Wise",
        "rows": ["Party Account Description"], "cols": [], "filters": {},
        "values": [
            ("Item Qty", _s("Item Qty")),
            ("Item/Service Amount", _s("Item/Service Amount")),
            ("Sum of Item/Service Charges", _s("Item/Service Charges")),
            ("Sum of Final Sales Value", _f(F_FINAL)),
        ],
    },
    {
        "title": "TPT- Conso",
        "rows": ["Item Group", "Item/Service Code"], "cols": [],
        "filters": {"Item Type": "Finished Goods"},
        "values": [
            ("ASP", _f(F_ASP)), ("Throughput %", _f(F_TPT)),
            ("Volume", _s("Item Qty")),
            ("Sales Value", _s("Actual Sales Value With Charges")),
            ("Mat Cost", _f(F_MATCOST)),
            ("Sum of Total Consumption Value", _s("Total Consumption Value to be considered in CS")),
        ],
    },
    {
        "title": "TPT-Fleetguard",
        "rows": ["Item Group", "Item/Service Code"], "cols": ["Month"],
        "filters": {"Item Type": "Finished Goods", "Sales Category FG": "Fleetguard"},
        "values": [("ASP", _f(F_ASP)), ("Volume", _s("Item Qty")), ("Throughput %", _f(F_TPT))],
    },
    {
        "title": "TPT-OEM",
        "rows": ["Item Group", "Item/Service Code"], "cols": ["Month"],
        "filters": {"Item Type": "Finished Goods"},
        "values": [("Throughput %", _f(F_TPT))],
    },
    {
        "title": "TPT-Export",
        "rows": ["Item Group", "Item/Service Code"], "cols": ["Month", "Sales Category FG"],
        "filters": {"Item Type": "Finished Goods"},
        "values": [("Throughput %", _f(F_TPT))],
    },
    {
        "title": "TPT-After Market",
        "rows": ["Item Group", "Item/Service Code"], "cols": ["Month"],
        "filters": {"Item Type": "Finished Goods", "Sales Category FG": "After Market"},
        "values": [("Throughput %", _f(F_TPT))],
    },
    {
        "title": "TPT- Customer",
        "rows": ["Rev Party Description"], "cols": [], "filters": {},
        "values": [
            ("ASP", _f(F_ASP)), ("Throughput %", _f(F_TPT)),
            ("Volume", _s("Item Qty")),
            ("Sales Value", _s("Actual Sales Value With Charges")),
        ],
    },
    {
        "title": "Customer State",
        "rows": ["Rev Party Description", "Item Group"], "cols": ["State"], "filters": {},
        "values": [
            ("ASP", _f(F_ASP)), ("Throughput %", _f(F_TPT)),
            ("Volume", _s("Item Qty")),
            ("Sales Value", _s("Actual Sales Value With Charges")),
        ],
    },
    {
        "title": "ASP V1",
        "rows": ["Item Group", "Item/Service Code"], "cols": ["Month", "Sales Category"],
        "filters": {"Item Type": "Finished Goods"},
        "values": [("ASP", _f(F_ASP))],
    },
    {
        "title": "Conso",
        "rows": ["Transaction Site Code", "Voucher Type", "Month", "Quarter",
                 "Document Reference", "Sales Category", "Party Group Description",
                 "Rev Party Description", "Party Description", "Item Group",
                 "Item/Service Code", "HSN/SAC Code", "Item Type"], "cols": [], "filters": {},
        "values": [
            ("Sum of Item Qty", _s("Item Qty")),
            ("Sum of Item/Service Amount", _s("Item/Service Amount")),
            ("Sum of Item/Service Charges", _s("Item/Service Charges")),
            ("Sum of Actual Sales Value With Charges", _s("Actual Sales Value With Charges")),
            ("Sum of Total Consumption Value", _s("Total Consumption Value to be considered in CS")),
            ("ASP", _f(F_ASP)), ("Mat Cost", _f(F_MATCOST)),
            ("Material Consumption %", _f(F_MATCONS)), ("Throughput %", _f(F_TPT)),
        ],
    },
    {
        "title": "HSN Code and List of Produc ",
        "rows": ["Item Group", "HSN/SAC Code"], "cols": ["Transaction Site Code"],
        "filters": {"Accounting Site Code": "JCPL01"},
        "values": [
            ("Sales Value", _s("Actual Sales Value With Charges")),
            ("Sum of Item Qty", _s("Item Qty")),
        ],
    },
    {
        "title": "HSN Code and List of Produc (2)",
        "rows": ["Rev Party Description", "Item Group", "HSN/SAC Code"], "cols": [], "filters": {},
        "values": [
            ("Sales Value", _s("Actual Sales Value With Charges")),
            ("Sum of Item Qty", _s("Item Qty")),
        ],
    },
]


def _load_snapshot(name):
    with open(REF_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


def _build_xlsx(header, data_rows):
    """Data + reference tabs as an in-memory xlsx."""
    from openpyxl import Workbook

    wb = Workbook(write_only=True)
    ws = wb.create_sheet(DATA_TAB)
    ws.append(list(header))
    for r in data_rows:
        ws.append(list(r))

    for tab, snap in (("Conso Customers", "snap_conso_customers.json"),
                      ("Sample- Export", "snap_sample_export.json")):
        sh = wb.create_sheet(tab[:31])
        for row in _load_snapshot(snap):
            sh.append(["" if c is None else c for c in row])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _pivot_request(spec, data_sheet_id, target_sheet_id, header, n_rows):
    idx = {name: i for i, name in enumerate(header)}
    n_cols = len(header)

    def offset(field):
        if field not in idx:
            raise GoogleDriveError(f"Pivot '{spec['title']}' references unknown column '{field}'.")
        return idx[field]

    rows = [{"sourceColumnOffset": offset(f), "showTotals": True,
             "sortOrder": "ASCENDING"} for f in spec["rows"]]
    cols = [{"sourceColumnOffset": offset(f), "showTotals": True,
             "sortOrder": "ASCENDING"} for f in spec["cols"]]

    values = []
    for name, v in spec["values"]:
        if "sum" in v:
            values.append({"name": name, "summarizeFunction": "SUM",
                           "sourceColumnOffset": offset(v["sum"])})
        else:
            values.append({"name": name, "summarizeFunction": "CUSTOM",
                           "formula": v["formula"]})

    filter_specs = []
    for field, keep in spec["filters"].items():
        filter_specs.append({
            "columnOffsetIndex": offset(field),
            "filterCriteria": {"visibleValues": [keep]},
        })

    pivot = {
        "source": {"sheetId": data_sheet_id, "startRowIndex": 0, "startColumnIndex": 0,
                   "endRowIndex": n_rows + 1, "endColumnIndex": n_cols},
        "rows": rows, "columns": cols, "values": values,
        "valueLayout": "HORIZONTAL",
    }
    if filter_specs:
        pivot["filterSpecs"] = filter_specs

    return {
        "updateCells": {
            "rows": [{"values": [{"pivotTable": pivot}]}],
            "fields": "pivotTable",
            "start": {"sheetId": target_sheet_id, "rowIndex": 0, "columnIndex": 0},
        }
    }


def create_artr_workbook(header, data_rows, name, creds=None, folder_id=None):
    """Create the full multi-tab ARTR Google Sheet. Returns
    {'file_id','name','sheet_url','tabs'}."""
    if creds is None:
        creds = load_credentials()
    folder_id = folder_id or settings.GOOGLE_DRIVE_FOLDER_ID
    if not folder_id:
        raise GoogleDriveError("No Drive folder configured to save the result.")

    # 1) upload data + reference tabs as a converted Google Sheet
    buf = _build_xlsx(header, data_rows)
    drive = _drive_service(creds)
    # single-shot (non-resumable) multipart upload — fewer round-trips for a
    # moderate file, so the convert finishes faster.
    media = MediaIoBaseUpload(buf, mimetype=XLSX_MIME, resumable=False)
    metadata = {"name": name, "mimeType": GSHEET_MIME, "parents": [folder_id]}
    try:
        created = (drive.files().create(body=metadata, media_body=media,
                   fields="id, name, webViewLink", supportsAllDrives=True).execute())
    except Exception as exc:  # noqa: BLE001
        raise GoogleDriveError(f"Could not save the workbook to Drive: {exc}") from exc
    file_id = created["id"]

    sheets = _sheets_service(creds)
    meta = sheets.spreadsheets().get(spreadsheetId=file_id,
                                     fields="sheets.properties").execute()
    data_sheet_id = next(
        s["properties"]["sheetId"] for s in meta["sheets"]
        if s["properties"]["title"] == DATA_TAB
    )

    # 2) add a sheet + live pivot for each report, in one batch
    requests = []
    for i, spec in enumerate(PIVOT_SPECS):
        target_id = 2000 + i
        requests.append({"addSheet": {"properties": {
            "sheetId": target_id, "title": spec["title"]}}})
        requests.append(_pivot_request(spec, data_sheet_id, target_id,
                                        header, len(data_rows)))
    try:
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=file_id, body={"requests": requests}).execute()
    except Exception as exc:  # noqa: BLE001
        raise GoogleDriveError(f"Could not build the pivot report tabs: {exc}") from exc

    tabs = [DATA_TAB, "Conso Customers", "Sample- Export"] + [s["title"] for s in PIVOT_SPECS]
    return {
        "file_id": file_id,
        "name": created["name"],
        "sheet_url": created["webViewLink"],
        "tabs": tabs,
    }
