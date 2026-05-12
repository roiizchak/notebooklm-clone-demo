"""Inject an X-Request-ID into every request, expose it via a contextvar,
and stamp every stdlib LogRecord with the active request_id."""

from __future__ import annotations

import contextvars
import logging
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        return response


class RequestIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        return True


_ORIGINAL_RECORD_FACTORY: logging.LogRecord | None = None
_FACTORY_INSTALLED = False


def install_logging_filter() -> None:
    """Install a LogRecord factory + a root filter so every record carries
    `request_id`. Using setLogRecordFactory ensures the attribute is stamped
    at record construction, which catches records emitted from any logger
    regardless of propagation or handler-level filtering (incl. pytest's
    `caplog`)."""
    global _ORIGINAL_RECORD_FACTORY, _FACTORY_INSTALLED

    if not _FACTORY_INSTALLED:
        _ORIGINAL_RECORD_FACTORY = logging.getLogRecordFactory()

        def _factory(*args, **kwargs):  # type: ignore[no-untyped-def]
            record = _ORIGINAL_RECORD_FACTORY(*args, **kwargs)  # type: ignore[misc]
            record.request_id = request_id_var.get()
            return record

        logging.setLogRecordFactory(_factory)
        _FACTORY_INSTALLED = True

    root = logging.getLogger()
    if not any(isinstance(f, RequestIDFilter) for f in root.filters):
        root.addFilter(RequestIDFilter())
