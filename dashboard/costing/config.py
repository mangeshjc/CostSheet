"""Canonical structure of a monthly costing period.

FOLDER_TREE  – the Drive folder layout created for every period (mirrors the
               existing "N. <Month> YTD" package exactly, spelling and all).
SOURCE_FILES – the ERP exports uploaded each month (Layer 1).
DATA_FILES   – the derived workbooks the app builds (Layer 2) and the final
               cost sheet (Layer 3), each pointing at its converter + inputs.

Everything downstream reads these lists, so the pipeline scales by editing
config rather than code.
"""

# --- Drive folder layout (nested dict: name -> subtree) ----------------------
FOLDER_TREE = {
    "01. ERP Source File": {},
    "02. Sales, Cinsumption and Productiond data File": {},
    "03. Expense": {
        "Expense not routed though JVR": {
            "APTR": {},
            "Depreciation": {},
        },
    },
    "04. Other data": {
        "Labour hour": {},
        "Packing Routed through BOM": {},
    },
}

# Convenience path constants (POSIX-style, relative to the period folder).
F_ERP = "01. ERP Source File"
F_SCP = "02. Sales, Cinsumption and Productiond data File"
F_EXPENSE = "03. Expense"
F_APTR = "03. Expense/Expense not routed though JVR/APTR"
F_DEPR = "03. Expense/Expense not routed though JVR/Depreciation"
F_OTHER = "04. Other data"
F_LABOUR = "04. Other data/Labour hour"
F_BOM = "04. Other data/Packing Routed through BOM"


# --- Layer 1: ERP source files (uploaded monthly) ----------------------------
# `match` = case-insensitive substrings that identify the file from its name.
SOURCE_FILES = [
    {"key": "ar_tax_register", "name": "AR Tax Register", "folder": F_ERP,
     "match": ["ar_tax_register", "ar tax register"],
     "report_tab": "Detail", "feeds": ["artr_data"]},
    {"key": "ap_tax_register", "name": "AP Tax Register", "folder": F_ERP,
     "match": ["ap_tax_register", "ap tax register"],
     "report_tab": "Detail", "feeds": ["aptr"]},
    {"key": "stock_ledger", "name": "Stock Ledger Report", "folder": F_ERP,
     "match": ["stock_ledger", "stock ledger"],
     "report_tab": "Stock Ledger", "feeds": ["artr_data"]},
    {"key": "journal_voucher", "name": "Journal Voucher Report", "folder": F_ERP,
     "match": ["journal_voucher", "journal voucher"],
     "report_tab": "Journal Voucher", "feeds": ["jvr_data"]},
    {"key": "asset_register", "name": "Asset Register", "folder": F_ERP,
     "match": ["asset register"],
     "report_tab": "REPORT", "feeds": ["depreciation"]},
    {"key": "trial_balance", "name": "Trial Balance", "folder": F_ERP,
     "match": ["trial_balance", "trial balance"],
     "report_tab": "Trial Balance", "feeds": ["horizontal_cs"]},
]

# Manual / external inputs (from other departments) uploaded per period.
MANUAL_INPUTS = [
    {"key": "labour_hours", "name": "Labour Hrs Utilization", "folder": F_LABOUR,
     "match": ["labour hrs", "labour hour"]},
    {"key": "bom_packing", "name": "BOM Routed Packing Material", "folder": F_BOM,
     "match": ["bom routed packing", "packing material list"]},
]


# --- Layer 2 & 3: derived data files the app builds --------------------------
# `converter` = key registered in registry.py. `sources` / `data_inputs` name
# upstream keys, giving the build DAG.
DATA_FILES = [
    {"key": "artr_data", "name": "ARTR_Data", "folder": F_SCP,
     "converter": "artr", "status": "built",
     "sources": ["ar_tax_register", "stock_ledger"], "data_inputs": []},
    {"key": "jvr_data", "name": "JVR_Data", "folder": F_EXPENSE,
     "converter": "jvr", "status": "planned",
     "sources": ["journal_voucher"], "data_inputs": []},
    {"key": "aptr", "name": "APTR", "folder": F_APTR,
     "converter": "aptr", "status": "planned",
     "sources": ["ap_tax_register"], "data_inputs": []},
    {"key": "sales_dashboard", "name": "Sales Dashboard & Reconciliation",
     "folder": F_SCP, "converter": "sales_dashboard", "status": "planned",
     "sources": ["ar_tax_register"], "data_inputs": ["artr_data"]},
    {"key": "depreciation", "name": "Depreciation Working", "folder": F_DEPR,
     "converter": "depreciation", "status": "planned",
     "sources": ["asset_register"], "data_inputs": []},
    {"key": "horizontal_cs", "name": "Horizontal CS", "folder": ".",
     "converter": "horizontal_cs", "status": "planned",
     "sources": ["trial_balance"],
     "data_inputs": ["artr_data", "jvr_data", "aptr", "depreciation",
                     "labour_hours", "bom_packing"]},
]


def by_key(items, key):
    return next((it for it in items if it["key"] == key), None)


def source_by_filename(filename):
    """Best-effort match an uploaded file to a SOURCE_FILES / MANUAL_INPUTS entry."""
    low = filename.lower()
    for entry in SOURCE_FILES + MANUAL_INPUTS:
        if any(m in low for m in entry["match"]):
            return entry
    return None
