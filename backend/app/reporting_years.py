"""Financial reporting years (GFI).

Each reporting year has an Excel workbook named "<year> GFI <anything>.xlsx",
e.g. "2025 GFI TOKK 1.xlsx". The available years are taken from these file names.
Workbooks are read from GFI_DATA_DIR (default: the project root).
"""

import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import require_user
from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["reporting-years"])

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2]
GFI_FILE_PATTERN = re.compile(r"^(\d{4}) GFI .*\.xlsx$", re.IGNORECASE)


class ReportingYearsResponse(BaseModel):
    years: list[int]


def get_data_dir() -> Path:
    return Path(os.getenv("GFI_DATA_DIR", DEFAULT_DATA_DIR))


def find_workbooks(data_dir: Path) -> dict[int, list[Path]]:
    """Map each reporting year to its GFI workbook files (sorted by name)."""
    if not data_dir.is_dir():
        logger.error("GFI data directory not found: %s", data_dir)
        return {}
    workbooks: dict[int, list[Path]] = {}
    for path in sorted(data_dir.iterdir()):
        # Skip Excel's temporary lock files ("~$...") created while a workbook is open.
        if path.name.startswith("~$"):
            continue
        match = GFI_FILE_PATTERN.match(path.name)
        if match and path.is_file():
            workbooks.setdefault(int(match.group(1)), []).append(path)
    return workbooks


def find_reporting_years(data_dir: Path) -> list[int]:
    """Return the distinct years of GFI workbooks in data_dir, newest first."""
    return sorted(find_workbooks(data_dir), reverse=True)


def get_workbook_path(year: int) -> Path:
    """Return the workbook for a year, or raise 404 if there is none."""
    paths = find_workbooks(get_data_dir()).get(year)
    if not paths:
        logger.warning("No GFI workbook for reporting year %s", year)
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No workbook for reporting year {year}")
    if len(paths) > 1:
        logger.warning(
            "Multiple GFI workbooks for %s, using %s: %s", year, paths[0].name, [p.name for p in paths]
        )
    return paths[0]


@router.get("/reporting-years")
def reporting_years(username: str = Depends(require_user)) -> ReportingYearsResponse:
    data_dir = get_data_dir()
    years = find_reporting_years(data_dir)
    if years:
        logger.debug("Reporting years found in %s: %s", data_dir, years)
    else:
        logger.warning("No GFI workbooks found in %s", data_dir)
    return ReportingYearsResponse(years=years)
