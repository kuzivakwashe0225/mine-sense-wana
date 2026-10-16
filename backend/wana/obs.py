"""Observability: request ids, structured logs, Prometheus metrics and one error vocabulary.

Every failure is one of three kinds, so dashboards and alerts can tell them apart:
  * user      - the request itself is wrong (bad input, not signed in, no permission). Not our bug.
  * business  - the request is well formed but a rule says no (record locked, nothing to retrain, duplicate).
  * platform  - something on our side failed (dependency down, unhandled exception). Page someone.
"""
from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
import traceback
import uuid

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from .settings import settings

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
user_id: contextvars.ContextVar[str] = contextvars.ContextVar("user_id", default="-")

# ---------- metrics ----------
HTTP_REQUESTS = Counter("wana_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram("wana_http_request_duration_seconds", "HTTP request latency", ["method", "route"],
                         buckets=(.01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10, 30))
ERRORS = Counter("wana_errors_total", "Errors by kind and code", ["kind", "code"])
CLIENT_ERRORS = Counter("wana_client_errors_total", "Errors reported by browsers and phones", ["kind"])
EVENTS = Counter("wana_events_total", "Business events", ["event", "outcome"])
RETRAIN_SECONDS = Histogram("wana_retrain_duration_seconds", "Model retraining time", buckets=(1, 2, 5, 10, 20, 40, 80, 160))
DEPENDENCY_UP = Gauge("wana_dependency_up", "1 if a dependency answered its last health check", ["dependency"])
MODEL_VERSION = Gauge("wana_model_version", "Latest model version served")


# ---------- errors ----------
class AppError(Exception):
    kind = "platform"
    status = 500

    def __init__(self, message: str, code: str = "error", status: int | None = None, headers: dict | None = None):
        super().__init__(message)
        self.message, self.code = message, code
        self.headers = headers
        if status:
            self.status = status


class UserError(AppError):
    kind, status = "user", 400


class BusinessError(AppError):
    kind, status = "business", 409


class PlatformError(AppError):
    kind, status = "platform", 503


def _body(kind, code, message, status):
    # `detail` keeps the shape FastAPI clients already read; `error` carries the classification.
    return {"detail": message, "error": {"kind": kind, "code": code, "status": status, "request_id": request_id.get()}}


def _respond(kind, code, message, status, headers=None):
    ERRORS.labels(kind, code).inc()
    return JSONResponse(_body(kind, code, message, status), status_code=status, headers=headers)


async def app_error_handler(_: Request, exc: AppError):
    log = logging.getLogger("wana.errors")
    (log.error if exc.kind == "platform" else log.info)("%s error %s: %s", exc.kind, exc.code, exc.message)
    return _respond(exc.kind, exc.code, exc.message, exc.status, exc.headers)


_HTTP_CODES = {400: "bad_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
               409: "conflict", 413: "too_large", 415: "unsupported_media", 429: "rate_limited"}


async def http_error_handler(_: Request, exc: StarletteHTTPException):
    kind = "user" if exc.status_code < 500 else "platform"
    code = _HTTP_CODES.get(exc.status_code, f"http_{exc.status_code}")
    return _respond(kind, code, str(exc.detail), exc.status_code, getattr(exc, "headers", None))


async def validation_error_handler(_: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(x) for x in first.get("loc", []) if x not in ("body", "query", "form"))
    msg = f"{where}: {first.get('msg', 'invalid value')}" if where else first.get("msg", "Invalid request")
    return _respond("user", "validation", msg, 422)


async def unhandled_error_handler(_: Request, exc: Exception):
    logging.getLogger("wana.errors").error("platform error: unhandled %s", type(exc).__name__,
                                           exc_info=(type(exc), exc, exc.__traceback__))
    return _respond("platform", "internal", "Something went wrong on our side. It has been logged.", 500)


def install(app):
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    @app.middleware("http")
    async def observe(request: Request, call_next):
        rid = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex[:16]
        request_id.set(rid)
        user_id.set("-")
        t = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
        finally:
            route = request.scope.get("route")
            path = getattr(route, "path", None) or ("/static" if not request.url.path.startswith("/api") else "unmatched")
            dt = time.perf_counter() - t
            HTTP_REQUESTS.labels(request.method, path, str(status)).inc()
            HTTP_LATENCY.labels(request.method, path).observe(dt)
            if path != "/static" and path != "/metrics":
                logging.getLogger("wana.http").info("%s %s %s %.0fms", request.method, path, status, dt * 1000,
                                                    extra={"status": status, "duration_ms": round(dt * 1000, 1)})
        response.headers["X-Request-ID"] = rid
        return response

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        # served only inside the container network: the web proxy refuses /metrics from outside
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ---------- logging ----------
class JsonFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        out = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(r.created)) + f".{int(r.msecs):03d}Z",
               "level": r.levelname, "logger": r.name, "msg": r.getMessage(),
               "request_id": request_id.get(), "user": user_id.get()}
        for k in ("status", "duration_ms", "kind", "event"):
            if hasattr(r, k):
                out[k] = getattr(r, k)
        if r.exc_info:
            out["exc"] = "".join(traceback.format_exception(*r.exc_info))[-4000:]
        return json.dumps(out)


def setup_logging():
    root = logging.getLogger()
    if getattr(root, "_wana", False):
        return
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter() if settings.log_json else logging.Formatter("%(levelname)s %(name)s %(message)s"))
    root.handlers[:] = [h]
    root.setLevel(logging.INFO)
    root._wana = True
    logging.getLogger("uvicorn.access").disabled = True   # our middleware logs each request once, with its id
    logging.getLogger("httpx").setLevel(logging.WARNING)  # calls to Keycloak; failures are logged by accounts.py
