from contextlib import asynccontextmanager
import hmac
import logging
from base64 import b64decode
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.jobs import JobStore
from app.web.routes import router
from app.web.webhook import router as webhook_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)
# These authenticate themselves (or are public) and are called by machines, not browsers.
OPEN_PREFIXES = ("/health", "/webhooks/")


def _password_ok(request: Request, password: str) -> bool:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return False
    try:
        supplied = b64decode(header[6:]).decode().partition(":")[2]
    except ValueError:
        return False
    return hmac.compare_digest(supplied.encode(), password.encode())


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Sentinel PR Review", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.jobs = JobStore(settings.job_ttl_seconds)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if not request.url.path.startswith(OPEN_PREFIXES):
            password = settings.ui_password.get_secret_value()
            if password and not _password_ok(request, password):
                return PlainTextResponse(
                    "Authentication required", status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="Sentinel"'},
                )
            origin = request.headers.get("origin")
            allowed = {h.strip() for h in settings.allowed_origins.split(",") if h.strip()}
            allowed.add(request.headers.get("host", ""))
            allowed.add(request.headers.get("x-forwarded-host", ""))
            if request.method == "POST" and origin and urlparse(origin).netloc not in allowed:
                return PlainTextResponse("Cross-origin request blocked", status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static")
    app.include_router(router)
    app.include_router(webhook_router)
    return app


app = create_app()
