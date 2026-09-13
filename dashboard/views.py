from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie

from django.conf import settings

from .forms import ERPUploadForm
from .google_drive import (
    GoogleDriveError,
    get_sheet_tabs,
    list_folder_sheets,
    load_credentials,
    read_sheet_data,
    read_tab_values,
    upload_and_convert,
)


def _workbook_context(request, wb_id, creds):
    """Read a converted workbook's tabs (cached) + selected tab for the viewer."""
    tabs = get_sheet_tabs(wb_id, creds)
    active_tab = request.GET.get("tab") or (tabs[0] if tabs else None)
    if active_tab not in tabs:
        active_tab = tabs[0] if tabs else None
    sheet = read_tab_values(wb_id, active_tab, creds=creds, max_rows=300)
    return {
        "file_id": wb_id, "url": sheet["url"], "tabs": tabs,
        "active_tab": active_tab, "sheet": sheet,
        "payload": {"tab": active_tab, "rows": sheet["rows"]},
    }


def horizontal_cs(request):
    """View the final Horizontal Cost Sheet (converted, as-is) as a dashboard."""
    ctx = {"active": "horizontal_cs", "title": "Horizontal Cost Sheet",
           "workbook": None}
    wb_id = getattr(settings, "GOOGLE_HORIZONTAL_CS_SHEET_ID", "")
    if not wb_id:
        ctx["error"] = ("Horizontal Cost Sheet is not configured yet. Set "
                        "GOOGLE_HORIZONTAL_CS_SHEET_ID in settings.py.")
        return render(request, "dashboard/workbook_view.html", ctx)
    try:
        ctx["workbook"] = _workbook_context(request, wb_id, load_credentials())
    except GoogleDriveError as exc:
        ctx["error"] = str(exc)
    return render(request, "dashboard/workbook_view.html", ctx)


def dashboard(request):
    stats = [
        {"label": "Total Revenue", "value": "₹48,290", "delta": "+12.5%", "up": True},
        {"label": "Active Users", "value": "2,340", "delta": "+3.2%", "up": True},
        {"label": "New Orders", "value": "1,120", "delta": "-1.8%", "up": False},
        {"label": "Refunds", "value": "₹1,204", "delta": "-0.4%", "up": True},
    ]
    recent = [
        {"id": "#1042", "customer": "Aria Patel", "amount": "₹320.00", "status": "Paid"},
        {"id": "#1041", "customer": "Liam Chen", "amount": "₹149.99", "status": "Pending"},
        {"id": "#1040", "customer": "Noah Kim", "amount": "₹89.50", "status": "Paid"},
        {"id": "#1039", "customer": "Mia Torres", "amount": "₹540.00", "status": "Refunded"},
        {"id": "#1038", "customer": "Ethan Ross", "amount": "₹210.75", "status": "Paid"},
    ]
    return render(request, "dashboard/dashboard.html", {
        "active": "dashboard",
        "stats": stats,
        "recent": recent,
    })


def analytics(request):
    return render(request, "dashboard/analytics.html", {"active": "analytics"})


def orders(request):
    return render(request, "dashboard/orders.html", {"active": "orders"})


def customers(request):
    return render(request, "dashboard/customers.html", {"active": "customers"})


def settings_view(request):
    return render(request, "dashboard/settings.html", {"active": "settings"})


def upload_erp(request):
    result = None
    if request.method == "POST":
        form = ERPUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded = form.cleaned_data["excel_file"]
            try:
                result = upload_and_convert(uploaded, uploaded.name)
            except GoogleDriveError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f"Uploaded '{uploaded.name}' and converted it to the Google "
                    f"Sheet \"{result['name']}\" in your Drive folder.",
                )
                # Re-render with a fresh form and keep the result summary.
                return render(
                    request,
                    "dashboard/upload_erp.html",
                    {"active": "upload", "form": ERPUploadForm(), "result": result},
                )
    else:
        form = ERPUploadForm()

    return render(
        request,
        "dashboard/upload_erp.html",
        {"active": "upload", "form": form, "result": result},
    )


@ensure_csrf_cookie
def artr_data(request):
    from datetime import datetime

    from django.conf import settings

    from .artr_converter import ConversionError, convert_artr
    from .artr_workbook import create_artr_workbook
    from .google_drive import (
        fetch_all_values,
        find_artr_tab,
        get_sheet_tabs,
        list_folder_sheets,
        read_sheet_data,
    )

    context = {
        "active": "artr",
        "section_title": "ARTR_Data_FY26-27",
        "files": [],
        "selected": None,
        "workbook": None,
    }

    try:
        creds = load_credentials()
        _folder_id, files = list_folder_sheets(creds)
        context["files"] = files
    except GoogleDriveError as exc:
        context["error"] = str(exc)
        return render(request, "dashboard/artr_data.html", context)

    # --- Convert: build the full multi-tab workbook, then redirect (PRG) ---
    if request.method == "POST":
        selected = request.POST.get("file") or ""
        source = next((f for f in files if f["id"] == selected), None)
        if source is None:
            context["selected"] = selected
            context["error"] = "Please choose an ERP source file from the list."
            return render(request, "dashboard/artr_data.html", context)
        try:
            tab = find_artr_tab(selected, creds)
            raw = fetch_all_values(selected, tab, creds=creds)
            header, rows = convert_artr(raw)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            out_folder = (settings.GOOGLE_ARTR_OUTPUT_FOLDER_ID
                          or settings.GOOGLE_DRIVE_FOLDER_ID)
            wb = create_artr_workbook(
                header, rows, f"ARTR_Data_{source['name']}_{stamp}",
                creds=creds, folder_id=out_folder,
            )
            messages.success(
                request,
                f"Converted '{source['name']}' → {len(rows)} rows. Built "
                f"{len(wb['tabs'])} sheets in \"{wb['name']}\".",
            )
            return redirect(f"{request.path}?wb={wb['file_id']}")
        except (GoogleDriveError, ConversionError) as exc:
            context["selected"] = selected
            context["error"] = str(exc)
            return render(request, "dashboard/artr_data.html", context)

    # --- View a previously built workbook (its tabs + selected tab's data) ---
    wb_id = request.GET.get("wb")
    if wb_id:
        try:
            tabs = get_sheet_tabs(wb_id, creds)
            active_tab = request.GET.get("tab") or (tabs[0] if tabs else None)
            sheet = read_sheet_data(wb_id, tab=active_tab, creds=creds, max_rows=300)
            context["workbook"] = {
                "file_id": wb_id,
                "url": sheet["url"],
                "tabs": tabs,
                "active_tab": active_tab,
                "sheet": sheet,
                "payload": {"tab": active_tab, "rows": sheet["rows"]},
            }
        except GoogleDriveError as exc:
            context["error"] = str(exc)

    return render(request, "dashboard/artr_data.html", context)


def artr_build(request):
    """AJAX endpoint: build the ARTR workbook and return JSON {wb, tabs, rows}.
    Keeps the page responsive so a loading animation can run during the build."""
    from datetime import datetime

    from django.conf import settings
    from django.http import JsonResponse

    from .artr_converter import ConversionError, convert_artr
    from .artr_workbook import create_artr_workbook
    from .google_drive import (
        fetch_all_values,
        find_artr_tab,
        find_existing_workbook,
        list_folder_sheets,
    )

    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    try:
        creds = load_credentials()
        _folder_id, files = list_folder_sheets(creds)
        selected = request.POST.get("file") or ""
        source = next((f for f in files if f["id"] == selected), None)
        if source is None:
            return JsonResponse({"error": "Please choose an ERP source file."}, status=400)

        out_folder = (settings.GOOGLE_ARTR_OUTPUT_FOLDER_ID
                      or settings.GOOGLE_DRIVE_FOLDER_ID)
        name_prefix = f"ARTR_Data_{source['name']}"
        force = request.POST.get("force") == "1"

        # Reuse an already-built workbook for this source unless a rebuild is forced.
        if not force:
            existing = find_existing_workbook(name_prefix, out_folder, creds)
            if existing:
                return JsonResponse({"wb": existing["id"], "reused": True,
                                     "name": existing["name"]})

        tab = find_artr_tab(selected, creds)
        raw = fetch_all_values(selected, tab, creds=creds)
        header, rows = convert_artr(raw)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        wb = create_artr_workbook(header, rows, f"{name_prefix}_{stamp}",
                                  creds=creds, folder_id=out_folder)
        return JsonResponse({"wb": wb["file_id"], "tabs": len(wb["tabs"]),
                             "rows": len(rows), "name": wb["name"], "reused": False})
    except (GoogleDriveError, ConversionError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": f"Unexpected error: {exc}"}, status=500)


def sales_stage(request):
    """Stage s01 (Sales) — compute the Revised Sales Register with the Python
    engine (ported VBA §4.1) and show it with a reconciliation that must tie to 0."""
    from .costing.engine.sales import SalesStageError, build_revised_sales
    from .google_drive import fetch_all_values

    ctx = {"active": "sales_stage", "title": "Sales — Revised Register (engine)"}
    sid = getattr(settings, "GOOGLE_SALES_DASHBOARD_SHEET_ID", "")
    if not sid:
        ctx["error"] = "Sales source not configured (GOOGLE_SALES_DASHBOARD_SHEET_ID)."
        return render(request, "dashboard/sales_stage.html", ctx)
    try:
        creds = load_credentials()
        raw = fetch_all_values(sid, "Original Sales Register", creds=creds,
                               unformatted=False)
        result = build_revised_sales(raw)
        recon = result["reconciliation"]
        ctx["buckets"] = recon["buckets"]
        ctx["check_value"] = recon["check"]
        ctx["check_ok"] = recon["check"] == 0
        ctx["recon_original"] = recon["Original (data rows)"]
        ctx["recon_trading"] = recon["Trading Items"]
        ctx["recon_excl"] = recon["Other Exclusions"]
        grid = [result["header"]] + result["revised"][:400]
        ctx["payload"] = {"tab": "Revised Sales Register", "rows": grid}
        ctx["revised_total"] = len(result["revised"])
        ctx["revised_shown"] = min(400, len(result["revised"]))
    except (GoogleDriveError, SalesStageError) as exc:
        ctx["error"] = str(exc)
    return render(request, "dashboard/sales_stage.html", ctx)


def sales_recon(request):
    """Sales Dashboard & Reconciliation — ARTR-style page: pick the file from a
    dropdown, convert it to a Google Sheet (reuse if already done), show as a
    dashboard."""
    from .google_drive import convert_office_to_sheet, list_office_sources

    ctx = {"active": "sales_recon",
           "title": "Sales Dashboard & Reconciliation",
           "files": [], "selected": None, "workbook": None}
    try:
        creds = load_credentials()
        files = list_office_sources("Sales Dashboard", creds)
        ctx["files"] = files
    except GoogleDriveError as exc:
        ctx["error"] = str(exc)
        return render(request, "dashboard/sales_recon.html", ctx)

    out_folder = (settings.GOOGLE_ARTR_OUTPUT_FOLDER_ID
                  or settings.GOOGLE_DRIVE_FOLDER_ID)

    if request.method == "POST":
        selected = request.POST.get("file") or ""
        source = next((f for f in files if f["id"] == selected), None)
        if source is None:
            ctx["selected"] = selected
            ctx["error"] = "Please choose a file from the list."
            return render(request, "dashboard/sales_recon.html", ctx)
        try:
            wb_id = convert_office_to_sheet(selected, f"{source['name']} (Sheet)",
                                            out_folder, creds)
            return redirect(f"{request.path}?wb={wb_id}")
        except GoogleDriveError as exc:
            ctx["selected"] = selected
            ctx["error"] = str(exc)
            return render(request, "dashboard/sales_recon.html", ctx)

    # default to the pre-converted workbook so the file is visible immediately
    wb_id = request.GET.get("wb") or getattr(settings, "GOOGLE_SALES_DASHBOARD_SHEET_ID", "")
    if wb_id:
        try:
            ctx["workbook"] = _workbook_context(request, wb_id, creds)
        except GoogleDriveError as exc:
            ctx["error"] = str(exc)
    return render(request, "dashboard/sales_recon.html", ctx)


def erp_files(request):
    """List Google Sheets in the ERP source folder and view a selected one."""
    context = {"active": "erp_files", "files": [], "selected": None, "sheet": None}
    selected_id = request.GET.get("file") or ""
    selected_tab = request.GET.get("tab") or None

    try:
        creds = load_credentials()
        _folder_id, files = list_folder_sheets(creds)
        context["files"] = files

        if selected_id and any(f["id"] == selected_id for f in files):
            context["selected"] = selected_id
            context["sheet"] = read_sheet_data(
                selected_id, tab=selected_tab, creds=creds
            )
    except GoogleDriveError as exc:
        context["error"] = str(exc)

    return render(request, "dashboard/erp_files.html", context)
