"""FastAPI application: middleware, lifespan events, and router mounting."""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from src.api.dependencies import (
    init_llm_client_singleton,
    load_dataset_singleton,
    release_dataset_singleton,
)
from src.api.routes import router

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: startup & shutdown hooks
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup and shutdown logic."""
    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info("Starting %s v%s ...", settings.APP_TITLE, settings.APP_VERSION)
    load_dataset_singleton()
    init_llm_client_singleton()
    logger.info("Application ready.")
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("Shutting down — releasing resources.")
    release_dataset_singleton()


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    description=(
        "AI-powered restaurant recommendation engine backed by Groq LPU™ inference. "
        "Provides deterministic multi-criteria filtering, anti-hallucination grounding, "
        "and subjective nuance matching."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_response_time_header(request: Request, call_next) -> Response:
    """Attach X-Response-Time header (milliseconds) to every response."""
    t_start = time.perf_counter()
    response: Response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - t_start) * 1000, 1)
    response.headers["X-Response-Time"] = f"{elapsed_ms}ms"
    return response


# ---------------------------------------------------------------------------
# Mount Routers & Static Frontend (Phase 5 UI)
# ---------------------------------------------------------------------------

from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app.include_router(router)

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_index():
        """Serve Phase 5 Web Application UI."""
        index_file = FRONTEND_DIR / "index.html"
        return FileResponse(index_file)
