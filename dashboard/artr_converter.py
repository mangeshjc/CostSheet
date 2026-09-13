"""Convert an ERP "AR Tax Register - Detail" export into the ARTR Master V2 layout.

This reproduces the logic of ARTR_Data_FY26-27.xlsb:

  raw ERP export (171 cols)
    -> select/rename to 46 canonical columns + derive Month/Quarter/Sales Category
       /Sales Category FG/Rev Party Description        (the "ARTR Master Data" stage)
    -> add 14 derived rate/category columns             (the "ARTR Master V2" stage)

Rate lookups (SLR landed rate, DPR receipt/issue rates) use reference tables
extracted once from the workbook and stored under ``artr_reference/``. Category
lookups use the small Conso Customers / Sample-Export maps stored there too.

The external "After Market CN Dashboard" workbook is not available, so the CN
Impact column defaults to "NA" exactly as the original formula does when the
lookup misses.
"""
import json
from datetime import date, timedelta
from pathlib import Path

REF_DIR = Path(__file__).resolve().parent / "artr_reference"
_EXCEL_EPOCH = date(1899, 12, 30)  # Excel's day 0 (accounts for the 1900 leap bug)

# --- canonical output columns -------------------------------------------------
# 46 base columns (order matches the workbook's ARTR Master sheets)...
BASE_COLUMNS = [
    "Accounting Site Code", "Transaction Site Code", "Voucher Type",
    "Voucher Sub Type", "Voucher Status", "Month", "Quarter",
    "Accounting Period", "Voucher Number", "Voucher Date",
    "Invoice Reference Number (IRN)", "Document Reference", "Party Group",
    "Sales Category", "Sales Category FG", "Party Group Description",
    "Party Category", "Party Category Description", "Party Code",
    "Rev Party Description", "Party Description", "Party Account Code",
    "Party Account Description", "State", "Customer PO Number",
    "Customer PO Date", "Sales Shipment Number", "Sales Shipment Date",
    "Item Group", "Item Group Description", "Item Category",
    "Item Category Description", "Item Name", "Item/Service Code",
    "Item/Service Description", "Item/Service Account Code",
    "Item/Service Account Description", "HSN/SAC Code", "Item Qty",
    "Item/Service Rate", "Item/Service Amount", "Item/Service Charges",
    "GST Taxable Value", "Total CGST", "Total SGST", "Total IGST",
]
# ...plus 14 derived columns.
DERIVED_COLUMNS = [
    "Concatenate for LR", "FG LR1", "DPR Rate",
    "Final Rates (DPR & LR against Sales Shipment)", "Average Rate Sales",
    "Derived Consumption Rate (Available for Item)",
    "Total Consumption Value to be considered in CS", "Concatenate for CN Impact",
    "Amount \n(Value) -CN Impact", "Actual Sales Value With Charges",
    "Sales Category for AOP", "Item Type", "Revise Voucher Date", "Sales Type",
]
OUTPUT_COLUMNS = BASE_COLUMNS + DERIVED_COLUMNS

# Canonical base column -> the header it copies from in the raw ERP export.
# (The 5 columns absent here are derived: Month, Quarter, Sales Category,
#  Sales Category FG, Rev Party Description.)
RAW_SOURCE = {
    "Accounting Site Code": "Accounting Site Code",
    "Transaction Site Code": "Transaction Site Code",
    "Voucher Type": "Voucher Type",
    "Voucher Sub Type": "Voucher Sub Type",
    "Voucher Status": "Voucher Status",
    "Accounting Period": "Accounting Period",
    "Voucher Number": "Voucher Number",
    "Voucher Date": "Voucher Date",
    "Invoice Reference Number (IRN)": "Invoice Reference Number (IRN)",
    "Document Reference": "Document Reference",
    "Party Group": "Party Group",
    "Party Group Description": "Party Group Description",
    "Party Category": "Party Category",
    "Party Category Description": "Party Category Description",
    "Party Code": "Party Code",
    "Party Description": "Party Description",
    "Party Account Code": "Party Account Code",
    "Party Account Description": "Party Account Description",
    "State": "State",
    "Customer PO Number": "Customer PO Number",
    "Customer PO Date": "Customer PO Date",
    "Sales Shipment Number": "Sales Shipment Number",
    "Sales Shipment Date": "Sales Shipment Date",
    "Item Group": "Item Group",
    "Item Group Description": "Item Group Description",
    "Item Category": "Item Category",
    "Item Category Description": "Item Category Description",
    "Item Name": "Item Name",
    "Item/Service Code": "Item/Service Code",
    "Item/Service Description": "Item/Service Description",
    "Item/Service Account Code": "Item/Service Account Code",
    "Item/Service Account Description": "Item/Service Account Description",
    "HSN/SAC Code": "HSN/SAC Code",
    "Item Qty": "Item Qty",
    "Item/Service Rate": "Item/Service Rate",
    "Item/Service Amount": "Item/Service Amount",
    "Item/Service Charges": "Item/Service Charges",
    "GST Taxable Value": "GST Taxable Value",
    "Total CGST": "Total CGST",
    "Total SGST": "Total SGST",
    "Total IGST": "Total IGST",
}


class ConversionError(Exception):
    """Raised when the ERP export cannot be converted."""


# --- reference data (lazy-loaded) ---------------------------------------------
_refs = {}


def _refs_all():
    if not _refs:
        def load(name):
            with open(REF_DIR / name, encoding="utf-8") as fh:
                return json.load(fh)
        _refs.update(
            slr=load("slr_landed_rate.json"),
            dpr_recv=load("dpr_receipt_rate.json"),
            dpr_issue=load("dpr_issue_rate.json"),
            aop=load("aop_category.json"),
            sales_cat=load("sales_category.json"),
            rev_party=load("rev_party.json"),
            item_type=load("item_type.json"),
            sample=load("sample_export.json"),
        )
    return _refs


# --- small helpers ------------------------------------------------------------
def _num(v):
    """Best-effort float; returns None if not numeric."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _gen(v):
    """Excel 'General' text of a value: 2000.0 -> '2000', 14.5 -> '14.5'."""
    n = _num(v)
    if n is None:
        return "" if v is None else str(v)
    if n == int(n):
        return str(int(n))
    return repr(n).rstrip("0").rstrip(".")


def _serial_to_date(v):
    n = _num(v)
    if n is None:
        return None
    try:
        return _EXCEL_EPOCH + timedelta(days=int(n))
    except (ValueError, OverflowError):
        return None


def _find_header_row(rows):
    """Locate the header row of the raw ERP export (the one naming the columns)."""
    for i, row in enumerate(rows[:25]):
        cells = {str(c).strip() for c in row}
        if "Accounting Site Code" in cells and "Voucher Number" in cells:
            return i
    raise ConversionError(
        "Could not find the ERP header row (expected columns like "
        "'Accounting Site Code' and 'Voucher Number'). Is this an "
        "AR Tax Register detail export?"
    )


# --- main conversion ----------------------------------------------------------
def convert_artr(raw_values):
    """Convert raw ERP rows (list of lists, incl. header) to the ARTR Master V2
    layout. Returns (output_header, output_rows)."""
    if not raw_values:
        raise ConversionError("The selected file has no data.")

    hidx = _find_header_row(raw_values)
    header = [str(c).strip() for c in raw_values[hidx]]
    col = {name: i for i, name in enumerate(header)}

    missing = [src for src in set(RAW_SOURCE.values()) if src not in col]
    if missing:
        raise ConversionError(
            "The file is missing expected ERP columns: " + ", ".join(sorted(missing)[:8])
        )

    r = _refs_all()
    out_rows = []

    for raw in raw_values[hidx + 1:]:
        if not any(str(c).strip() for c in raw):
            continue  # skip blank rows

        def g(canon):
            src = RAW_SOURCE[canon]
            i = col[src]
            return raw[i] if i < len(raw) else None

        rec = {c: g(c) for c in RAW_SOURCE}

        # --- stage 1 derived base columns ---
        vdate = _serial_to_date(rec["Voucher Date"])
        rec["Month"] = vdate.strftime("%b-%y") if vdate else ""
        if vdate:
            q = {1: "Q4", 2: "Q4", 3: "Q4", 4: "Q1", 5: "Q1", 6: "Q1",
                 7: "Q2", 8: "Q2", 9: "Q2", 10: "Q3", 11: "Q3", 12: "Q3"}
            rec["Quarter"] = q.get(vdate.month, "NA")
        else:
            rec["Quarter"] = "NA"

        pad = str(rec["Party Account Description"] or "")
        rec["Sales Category"] = r["sales_cat"].get(pad, "Not There")
        pcd = str(rec["Party Category Description"] or "")
        rec["Sales Category FG"] = "Fleetguard" if pcd == "Fleetguard" else rec["Sales Category"]
        pdesc = str(rec["Party Description"] or "")
        rec["Rev Party Description"] = r["rev_party"].get(pdesc, rec["Party Description"])

        # --- stage 2 derived (rate/category) columns ---
        party_code = str(rec["Party Code"] or "")
        item_code = str(rec["Item/Service Code"] or "")
        item_cat = str(rec["Item Category"] or "")
        pgd = str(rec["Party Group Description"] or "")
        qty = _num(rec["Item Qty"])
        amount = _num(rec["Item/Service Amount"]) or 0.0
        charges = _num(rec["Item/Service Charges"]) or 0.0

        ship_serial = _gen(rec["Sales Shipment Date"])
        concat_lr = f"{ship_serial}{party_code}{item_code}{_gen(rec['Item Qty'])}"
        rec["Concatenate for LR"] = concat_lr

        lr = r["slr"].get(concat_lr, "No Rate")
        rec["FG LR1"] = lr
        dpr = r["dpr_recv"].get(item_code, "No Rate")
        rec["DPR Rate"] = dpr
        if pgd == "Scrap Sales":
            final_rate = 0
        elif dpr == "No Rate" or dpr == 0:
            final_rate = lr
        else:
            final_rate = dpr
        rec["Final Rates (DPR & LR against Sales Shipment)"] = final_rate
        avg = r["dpr_issue"].get(item_code, "No Rate")
        rec["Average Rate Sales"] = avg
        derived_rate = final_rate if final_rate != "No Rate" else avg
        rec["Derived Consumption Rate (Available for Item)"] = derived_rate
        if isinstance(derived_rate, (int, float)) and qty is not None:
            rec["Total Consumption Value to be considered in CS"] = derived_rate * qty
        else:
            rec["Total Consumption Value to be considered in CS"] = 0

        vdate_serial = _gen(rec["Voucher Date"])
        rec["Concatenate for CN Impact"] = (
            f"{vdate_serial}{party_code}{item_code}{_gen(rec['Item Qty'])}{_gen(rec['Item/Service Amount'])}"
        )
        vtype = str(rec["Voucher Type"] or "")
        if vtype == "Credit Note" and pgd == "After Market":
            cn = "Ignore CN"
        else:
            cn = "NA"  # external CN Dashboard unavailable -> formula's default
        rec["Amount \n(Value) -CN Impact"] = cn
        if cn == "Ignore CN":
            rec["Actual Sales Value With Charges"] = 0
        elif cn == "NA":
            rec["Actual Sales Value With Charges"] = amount + charges
        else:
            rec["Actual Sales Value With Charges"] = _num(cn) + charges if _num(cn) is not None else amount + charges

        rec["Sales Category for AOP"] = r["aop"].get(pad, "Not There")
        rec["Item Type"] = r["item_type"].get(item_cat, "Finished Goods")
        rec["Revise Voucher Date"] = rec["Voucher Date"]  # manual in original; default to voucher date
        rec["Sales Type"] = r["sample"].get(str(rec["Voucher Number"] or ""), "Actual")

        out_rows.append([rec.get(c) for c in OUTPUT_COLUMNS])

    if not out_rows:
        raise ConversionError("No data rows were found below the header.")

    return OUTPUT_COLUMNS, out_rows
