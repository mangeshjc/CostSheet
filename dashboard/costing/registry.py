"""Converter registry — one converter per derived data file.

A converter turns upstream inputs (converted ERP source Sheets + reference maps
+ already-built data files) into a Google Sheet in the period folder. They all
share the ``BaseConverter`` contract, so the orchestrator treats every data
file identically and the pipeline grows by registering a class.
"""


class ConverterError(Exception):
    pass


class BaseConverter:
    """Contract for building one data file of a period.

    Subclasses set ``key`` (matches DATA_FILES) and implement ``build``.
    """
    key = None

    def build(self, ctx):
        """Build the data file. ``ctx`` is a BuildContext (see orchestrator).
        Return {'sheet_id', 'name', 'url', 'tabs'}."""
        raise NotImplementedError


_REGISTRY = {}


def register(cls):
    if not cls.key:
        raise ConverterError(f"{cls.__name__} must set a `key`.")
    _REGISTRY[cls.key] = cls()
    return cls


def get_converter(key):
    return _REGISTRY.get(key)


def available():
    return sorted(_REGISTRY)


# --- ARTR converter (implemented) --------------------------------------------
@register
class ARTRConverter(BaseConverter):
    key = "artr"

    def build(self, ctx):
        from ..artr_converter import convert_artr
        from ..artr_workbook import create_artr_workbook
        from ..google_drive import fetch_all_values, find_artr_tab

        src = ctx.source_sheet_id("ar_tax_register")
        tab = find_artr_tab(src, ctx.creds)
        raw = fetch_all_values(src, tab, creds=ctx.creds)
        header, rows = convert_artr(raw)
        res = create_artr_workbook(
            header, rows, ctx.output_name("ARTR_Data"),
            creds=ctx.creds, folder_id=ctx.folder_id("02. Sales, Cinsumption and Productiond data File"),
        )
        return {"sheet_id": res["file_id"], "name": res["name"],
                "url": res["sheet_url"], "tabs": res["tabs"]}


# --- Planned converters (declared so the DAG is complete; fill in per phase) --
class _Planned(BaseConverter):
    phase = ""

    def build(self, ctx):  # noqa: D401
        raise ConverterError(
            f"The '{self.key}' converter is not implemented yet ({self.phase})."
        )


@register
class JVRConverter(_Planned):
    key = "jvr"
    phase = "Phase 3 — journal expenses → Cost Sheet Heads"


@register
class APTRConverter(_Planned):
    key = "aptr"
    phase = "Phase 3 — purchase expenses → categories"


@register
class SalesDashboardConverter(_Planned):
    key = "sales_dashboard"
    phase = "Phase 4"


@register
class DepreciationConverter(_Planned):
    key = "depreciation"
    phase = "Phase 5"


@register
class HorizontalCSConverter(_Planned):
    key = "horizontal_cs"
    phase = "Phase 6 — final cost sheet consolidation"
