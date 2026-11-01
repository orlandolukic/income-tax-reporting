"""PB-1 detail page API.

Every company gets the same PB-1 table (template from "<year> PB-1.xls"). The amounts
from the file are shown only for the company the file belongs to, matched by identity:
the company name in the PB-1 file must match exactly one GFI company (name compared
without legal form / city / case), and that company's PIB is the owner. The position of
the company in the GFI table is never used for matching.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import require_user
from app.gfi_workbook import SourceTable, load_source_table
from app.logging_config import get_logger
from app.pb1_workbook import (
    VALUE_COLUMNS,
    CellValue,
    Pb1Workbook,
    find_pb1_workbook,
    load_pb1_workbook,
    normalize_company_name,
)
from app.reporting_years import get_data_dir, get_workbook_path

logger = get_logger(__name__)

router = APIRouter(prefix="/api/reporting-years/{year}/companies/{row}", tags=["pb1"])

NAME_HEADER = "NAZIV"
PIB_HEADER = "PIB"


class Company(BaseModel):
    row: int  # Excel row in the GFI workbook
    name: str
    pib: str | None


class Pb1Column(BaseModel):
    key: str
    header: str | None
    width: int  # characters, from the Excel sheet


class Pb1CellOut(BaseModel):
    value: CellValue = None
    format: str | None = None  # omitted for "General"
    bold: bool = False


class Pb1RowOut(BaseModel):
    row: int
    cells: dict[str, Pb1CellOut]


class Pb1Table(BaseModel):
    company: Company
    workbook: str
    sheet: str
    has_values: bool  # True when the file's amounts belong to this company
    columns: list[Pb1Column]
    rows: list[Pb1RowOut]


def _column_for(source: SourceTable, header: str) -> str | None:
    return next((k for k, h in source.headers.items() if h and h.strip().upper() == header), None)


def _company_at(source: SourceTable, row: int) -> Company:
    name_col, pib_col = _column_for(source, NAME_HEADER), _column_for(source, PIB_HEADER)
    cells = source.rows.get(row)
    name = cells[name_col].value if cells and name_col else None
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No company in row {row}")
    pib = cells[pib_col].value if pib_col else None
    return Company(row=row, name=name.strip(), pib=None if pib in (None, "") else str(pib).strip())


def _owner_identity(source: SourceTable, pb1: Pb1Workbook) -> tuple[str, str | None] | None:
    """(normalized name, PIB) of the GFI company the PB-1 amounts belong to, or None."""
    if not pb1.company_name:
        return None
    target = normalize_company_name(pb1.company_name)
    name_col, pib_col = _column_for(source, NAME_HEADER), _column_for(source, PIB_HEADER)
    matches = set()
    for cells in source.rows.values():
        name = cells[name_col].value if name_col else None
        if isinstance(name, str) and normalize_company_name(name) == target:
            pib = cells[pib_col].value if pib_col else None
            matches.add(None if pib in (None, "") else str(pib).strip())
    if len(matches) != 1:
        logger.warning(
            "PB-1 company %r in %s matches %d GFI companies; values are not assigned",
            pb1.company_name, pb1.workbook, len(matches),
        )
        return None
    return target, matches.pop()


@router.get("/pb1", response_model_exclude_defaults=True)
def get_pb1(year: int, row: int, username: str = Depends(require_user)) -> Pb1Table:
    source = load_source_table(get_workbook_path(year))
    company = _company_at(source, row)

    path = find_pb1_workbook(get_data_dir(), year)
    if path is None:
        logger.warning("No PB-1 template for reporting year %s", year)
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No PB-1 template for reporting year {year}")
    try:
        pb1 = load_pb1_workbook(path)
    except Exception:
        logger.exception("Failed to read PB-1 workbook %s", path.name)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Unable to read the PB-1 workbook")

    owner = _owner_identity(source, pb1)
    has_values = owner == (normalize_company_name(company.name), company.pib)

    rows = []
    for row_number, cells in pb1.rows.items():
        out = {}
        for key, cell in cells.items():
            # Amount columns are empty for every company except the owner of the file.
            value = cell.value if (key not in VALUE_COLUMNS or has_values) else None
            out[key] = Pb1CellOut(
                value=value,
                format=None if cell.number_format == "General" else cell.number_format,
                bold=cell.bold,
            )
        rows.append(Pb1RowOut(row=row_number, cells=out))

    columns = [Pb1Column(key=k, header=pb1.headers[k], width=pb1.column_widths[k]) for k in pb1.headers]
    logger.info("PB-1 for '%s' (row %d, %s): %s", company.name, row, year, "values" if has_values else "empty template")
    return Pb1Table(
        company=company, workbook=pb1.workbook, sheet=pb1.sheet,
        has_values=has_values, columns=columns, rows=rows,
    )
