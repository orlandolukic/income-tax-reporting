from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.auth import router as auth_router
from app.companies import router as companies_router
from app.edits_store import init_db
from app.logging_config import get_logger, setup_logging
from app.pb1 import router as pb1_router
from app.reporting_years import router as reporting_years_router

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Backend started")
    yield
    logger.info("Backend stopped")


app = FastAPI(title="tim-automation", lifespan=lifespan)

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


@app.get("/api/health")
def health() -> dict[str, str]:
    logger.debug("Health check requested")
    return {"status": "ok", "message": "Application is running"}
