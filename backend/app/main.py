import asyncio
import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from app.api.routes import allowed_origin, router
from app.api.teaching import router as teaching_router
from app.api.body_limit import BodyLimitMiddleware
from app.errors import DomainError
from app.services.engine import Engine

ROOT = Path(__file__).resolve().parents[2]


def create_app(data_dir: Path | None = None, config_path: Path | None = None, model_root: Path | None = None):
    @asynccontextmanager
    async def lifespan(app):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        app.state.engine = Engine(
            data_dir or Path(os.getenv("PALLET_DATA_DIR", ROOT / "data")),
            config_path or Path(os.getenv("PALLET_CONFIG_PATH", ROOT / "config.json")),
            model_root or Path(os.getenv("PALLET_MODEL_DIR", ROOT / "models")),
        )
        app.state.mutation_lock = asyncio.Lock()
        yield
        await asyncio.to_thread(app.state.engine.close)

    app = FastAPI(title="Pallet Vision", version="0.1.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def safety(request: Request, call_next):
        request_id = uuid4().hex
        request.state.request_id = request_id
        if request.method not in ("GET", "HEAD", "OPTIONS") and not allowed_origin(
            request.headers.get("origin")
        ):
            return JSONResponse(
                {
                    "error": {
                        "code": "ORIGIN_REJECTED",
                        "message": "Only the local HMI may mutate this workstation",
                        "request_id": request_id,
                    }
                },
                status_code=403,
            )
        length = request.headers.get("content-length")
        if length and (not length.isdigit()):
            return JSONResponse(
                {"error": {"code": "INVALID_CONTENT_LENGTH", "message": "Invalid Content-Length"}},
                status_code=400,
            )
        if (
            length
            and int(length)
            > request.app.state.engine.config.get().runtime.max_upload_mb * 1024 * 1024 + 65536
        ):
            return JSONResponse(
                {
                    "error": {
                        "code": "UPLOAD_TOO_LARGE",
                        "message": "Request exceeds configured limit",
                        "request_id": request_id,
                    }
                },
                status_code=413,
            )
        # Serialize mutations to protect session/camera transitions and idempotency.
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            async with request.app.state.mutation_lock:
                key = (
                    request.headers.get("idempotency-key")
                    if request.method == "POST" and request.url.path != "/api/v1/assets"
                    else None
                )
                fingerprint = None
                if key:
                    if len(key) > 128:
                        return JSONResponse(
                            {"error": {"code": "INVALID_IDEMPOTENCY_KEY", "message": "Key too long"}},
                            status_code=422,
                        )
                    fingerprint = hashlib.sha256(request.url.path.encode() + await request.body()).hexdigest()
                    with request.app.state.engine.db.connect() as db:
                        prior = db.execute("SELECT * FROM idempotency WHERE key=?", (key,)).fetchone()
                    if prior:
                        if prior["fingerprint"] != fingerprint:
                            return JSONResponse(
                                {
                                    "error": {
                                        "code": "IDEMPOTENCY_CONFLICT",
                                        "message": "Key was used for a different request",
                                    }
                                },
                                status_code=409,
                            )
                        return JSONResponse(json.loads(prior["payload"]), status_code=prior["status"])
                response = await call_next(request)
                if key and response.status_code < 300:
                    body = b"".join([chunk async for chunk in response.body_iterator])
                    with request.app.state.engine.db.connect() as db:
                        db.execute(
                            "INSERT INTO idempotency(key,fingerprint,status,payload) VALUES (?,?,?,?)",
                            (key, fingerprint, response.status_code, body.decode()),
                        )
                    response = JSONResponse(json.loads(body), status_code=response.status_code)
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        headers = {"Retry-After": "2"} if exc.status == 503 else None
        return JSONResponse(
            {"error": {**exc.public(), "request_id": getattr(request.state, "request_id", None)}},
            status_code=exc.status,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [{"location": list(e["loc"]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(
            {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid request fields",
                    "details": details,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logging.getLogger("pallet.api").exception("request.failed", exc_info=exc)
        return JSONResponse(
            {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Unexpected server error; check local server logs",
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
            status_code=500,
        )

    # Outermost guard also bounds body reads performed by idempotency middleware.
    app.add_middleware(BodyLimitMiddleware)
    app.include_router(router)
    app.include_router(teaching_router)
    frontend = ROOT / "frontend" / "dist"
    if frontend.exists():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="hmi")
    return app


app = create_app()
