"""Financial reporting years: the years in the database (imported or constructed)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import require_user
from app.gfi_store import get_gfi_store
from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["reporting-years"])


class ReportingYearsResponse(BaseModel):
    years: list[int]


@router.get("/reporting-years")
def reporting_years(username: str = Depends(require_user)) -> ReportingYearsResponse:
    years = get_gfi_store().years()
    if years:
        logger.debug("Reporting years: %s", years)
    else:
        logger.warning("No GFI data in the database")
    return ReportingYearsResponse(years=years)
