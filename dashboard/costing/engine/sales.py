"""Stage s01 — Sales: Revised Sales Register + reconciliation.

Direct Python port of the `BuildRevisedSalesRegister` VBA macro (Sales Dashboard,
Module1), per §4.1 of the build strategy. Turns the raw/original sales register
into the cost-sheet sales base:

    pass_base   = Item Type == "Finished Goods"
                  AND Voucher Type in {Sales Invoice, SalesReturn}
                  AND Sales Category != "Scrap Sales"
    is_trading  = Item Group in {Butterfly Clamp, Pipe Clamp, Mini Clip}
                  OR Item/Service Code in {FD M18 B15 08-12/10-16/12-20 WH}

    Revised Sales Register = pass_base AND NOT is_trading
    Trading Item           = pass_base AND is_trading
    Everything else is an exclusion, bucketed for the reconciliation.
"""

KEEP_VOUCHER = {"sales invoice", "salesreturn", "sales return"}
DROP_GROUP = {"butterfly clamp", "pipe clamp", "mini clip"}
DROP_CODE = {"fd m18 b15 08-12 wh", "fd m18 b15 10-16 wh", "fd m18 b15 12-20 wh"}

# columns the rule set needs (matched by header name, order-independent)
NEEDED = ["Item Type", "Voucher Type", "Sales Category", "Item Group",
          "Item/Service Code"]


class SalesStageError(Exception):
    pass


def _norm(v):
    return "" if v is None else str(v).strip().lower()


def _find_header(rows):
    for i, row in enumerate(rows[:15]):
        names = {str(c).strip() for c in row}
        if "Item Type" in names and "Voucher Type" in names:
            return i
    raise SalesStageError(
        "Could not find the sales-register header (needs 'Item Type' and "
        "'Voucher Type'). Is this an Original Sales Register / ARTR sales export?"
    )


def build_revised_sales(raw_rows):
    """Run stage s01 on raw sheet values (list of rows incl. header block).

    Returns a dict with header, revised/trading/excluded row lists, the
    reconciliation buckets, and a zero-check.
    """
    if not raw_rows:
        raise SalesStageError("The sales register is empty.")
    h = _find_header(raw_rows)
    header = [str(c).strip() for c in raw_rows[h]]
    idx = {name: i for i, name in enumerate(header)}
    missing = [n for n in NEEDED if n not in idx]
    if missing:
        raise SalesStageError("Missing columns: " + ", ".join(missing))

    def get(row, name):
        i = idx[name]
        return row[i] if i < len(row) else ""

    revised, trading, excluded = [], [], []
    buckets = {"Non-Finished Goods": 0, "Excluded Voucher": 0, "Scrap Sales": 0,
               "Trading (Group)": 0, "Trading (Code)": 0}

    for row in raw_rows[h + 1:]:
        # skip blank / subtotal rows
        if not any(str(c).strip() for c in row):
            continue
        itype = _norm(get(row, "Item Type"))
        vou = _norm(get(row, "Voucher Type"))
        cat = _norm(get(row, "Sales Category"))
        grp = _norm(get(row, "Item Group"))
        code = _norm(get(row, "Item/Service Code"))
        # a real data row must at least name a voucher type or item
        if not vou and not code and not itype:
            continue

        if itype != "finished goods":
            buckets["Non-Finished Goods"] += 1; excluded.append(row); continue
        if vou not in KEEP_VOUCHER:
            buckets["Excluded Voucher"] += 1; excluded.append(row); continue
        if cat == "scrap sales":
            buckets["Scrap Sales"] += 1; excluded.append(row); continue
        # pass_base is now True
        if grp in DROP_GROUP:
            buckets["Trading (Group)"] += 1; trading.append(row); continue
        if code in DROP_CODE:
            buckets["Trading (Code)"] += 1; trading.append(row); continue
        revised.append(row)

    total = len(revised) + len(trading) + len(excluded)
    reconciliation = {
        "Original (data rows)": total,
        "Revised (retained)": len(revised),
        "Trading Items": len(trading),
        "Other Exclusions": len(excluded),
        "buckets": buckets,
        # Original − Revised − Trading − Exclusions  (must be 0)
        "check": total - len(revised) - len(trading) - len(excluded),
    }
    return {
        "header": header,
        "revised": revised,
        "trading": trading,
        "excluded": excluded,
        "reconciliation": reconciliation,
    }
