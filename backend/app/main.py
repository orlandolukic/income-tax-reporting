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
from app.global_settings import router as global_settings_router  # noqa: E402
from app.logging_config import get_logger, setup_logging  # noqa: E402
from app.pb1 import router as pb1_router  # noqa: E402
from app.migration import check_table_policies, router as migration_router  # noqa: E402
from app.reporting_years import router as reporting_years_router  # noqa: E402

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not database_enabled():
        # All data is in PostgreSQL; there is no mode without it (the Excel files are never read).
        logger.critical("DATABASE_URL is not set (backend/.env): the app needs its PostgreSQL database; not starting")
        raise RuntimeError("DATABASE_URL is not set")
    logger.info("Data source: PostgreSQL (%s); no Excel files are read", describe_database())
    try:
        check_table_policies()
    except RuntimeError as exc:
        logger.critical("%s; not starting", exc)
        raise
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
app.include_router(global_settings_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    logger.debug("Health check requested")
    return {"status": "ok", "message": "Application is running"}
