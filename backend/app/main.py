"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.routers import upload, chat, documents


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: setup and teardown."""
    import asyncio
    import logging

    # Startup: ensure data directories exist
    settings.ensure_dirs()

    # If using local embeddings, warm up the model in the background.
    # This reduces the first indexing latency spike (model download/load).
    if settings.embedding_provider == "local":
        logger = logging.getLogger(__name__)

        async def _warmup():
            try:
                from app.services.embedding import get_embedding_model

                await asyncio.to_thread(get_embedding_model, "local", None)
                logger.info("Local embedding warmup complete")
            except Exception:
                logger.exception("Local embedding warmup failed")

        asyncio.create_task(_warmup())

    yield
    # Shutdown: cleanup if needed


app = FastAPI(
    title="DocChat - Document Q&A Chatbot",
    description="Upload PDFs and ask questions about their content",
    version="1.0.0",
    lifespan=lifespan,
)

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        import time
        import uuid
        import logging

        req_logger = logging.getLogger("app.request")
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            dt_ms = int((time.perf_counter() - t0) * 1000)
            req_logger.exception(
                "HTTP FAIL method=%s path=%s request_id=%s duration_ms=%s",
                request.method,
                request.url.path,
                request_id,
                dt_ms,
            )
            raise
        dt_ms = int((time.perf_counter() - t0) * 1000)
        req_logger.info(
            "HTTP OK method=%s path=%s status=%s request_id=%s duration_ms=%s",
            request.method,
            request.url.path,
            response.status_code,
            request_id,
            dt_ms,
        )
        response.headers["X-Request-Id"] = request_id
        return response

app.add_middleware(RequestLoggingMiddleware)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(upload.router, prefix="/api", tags=["upload"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(documents.router, prefix="/api", tags=["documents"])


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "1.0.0"}
