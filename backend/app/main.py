from contextlib import asynccontextmanager

from app.settings import load_settings

# Load backend/.env before anything reads the environment (LOG_LEVEL, DATABASE_URL, ...).
load_settings()

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402

from app.auth import router as auth_router  # noqa: E402
from app.companies import router as companies_router  # noqa: E402
from app.db import database_enabled, describe_database  # noqa: E402
from app.edits_store import init_db  # noqa: E402
from app.logging_config import get_logger, setup_logging  # noqa: E402
from app.pb1 import router as pb1_router  # noqa: E402
from app.migration import router as migration_router
from app.reporting_years import router as reporting_years_router  # noqa: E402

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if database_enabled():
        logger.info("GFI data source: PostgreSQL (%s)", describe_database())
    else:
        # No database configured: GFI from the Excel workbooks, edits in SQLite.
        init_db()
        logger.info("GFI data source: Excel workbooks + SQLite edits (DATABASE_URL not set)")
    logger.info("Backend started")
    yield
    logger.info("Backend stopped")


app = FastAPI(title="Income Tax Reporting", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# The company table JSON is large and compresses well.
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(auth_router)
app.include_router(reporting_years_router)
app.include_router(companies_router)
app.include_router(pb1_router)
app.include_router(migration_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    logger.debug("Health check requested")
    return {"status": "ok", "message": "Application is running"}
