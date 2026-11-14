"""FastAPI application: middleware, lifespan events, and router mounting."""
import logging
import re
import time
import uuid
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
    allow_origins=[o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()] or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time", "X-Cache", "Retry-After"],
)


_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{6,80}$")


@app.middleware("http")
async def add_request_metadata(request: Request, call_next) -> Response:
    """Assign a request ID (reusing a sane incoming X-Request-ID / Vercel ID) and
    attach X-Request-ID and X-Response-Time (ms) headers to every response."""
    incoming = request.headers.get("x-request-id") or request.headers.get("x-vercel-id") or ""
    request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex[:16]
    request.state.request_id = request_id

    t_start = time.perf_counter()
    response: Response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - t_start) * 1000, 1)
    response.headers["X-Response-Time"] = f"{elapsed_ms}ms"
    response.headers["X-Request-ID"] = request_id
    return response


# ---------------------------------------------------------------------------
# Mount Routers & Static Frontend (Phase 5 UI)
# ---------------------------------------------------------------------------

from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse

app.include_router(router)

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"

# Only these files are served under /static (allow-list), so nothing else that
# lands in frontend/ is published by accident.
PUBLIC_ASSETS = {"app.js", "style.css", "tailwind.css", "favicon.svg", "og-image.png"}

if FRONTEND_DIR.is_dir():

    @app.get("/static/{filename}", include_in_schema=False)
    async def serve_asset(filename: str):
        """Serve an allow-listed frontend asset."""
        if filename not in PUBLIC_ASSETS:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(FRONTEND_DIR / filename)

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        """Browsers request /favicon.ico by default; serve the SVG icon."""
        return FileResponse(FRONTEND_DIR / "favicon.svg", media_type="image/svg+xml")

    @app.get("/", include_in_schema=False)
    async def serve_index():
        """Serve Phase 5 Web Application UI."""
        index_file = FRONTEND_DIR / "index.html"
        return FileResponse(index_file)
