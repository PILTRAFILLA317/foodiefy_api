"""Operational metadata only. Never log request bodies, headers, URLs or exceptions."""
import json
import logging
import secrets
import time
from uuid import UUID, uuid4

from fastapi import Header
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

LOG = logging.getLogger("foodiefy.http")


def install(app, config):
    @app.middleware("http")
    async def correlation(request, call_next):
        try:
            request_id = str(UUID(request.headers.get("x-request-id", "")))
        except ValueError:
            request_id = str(uuid4())
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            response = JSONResponse(status_code=500, content={"error": {"code": "internal_error"}})
        response.headers["X-Request-ID"] = request_id
        route = request.scope.get("route")
        LOG.info(json.dumps({"event": "http_request", "request_id": request_id,
            "route": getattr(route, "path", "unmatched"), "status": response.status_code,
            "duration_ms": round((time.monotonic()-started)*1000, 2)}))
        return response

    @app.get("/ops/metrics", include_in_schema=False)
    def metrics(x_ops_token: str | None = Header(default=None)):
        if not config.OPS_TOKEN or not x_ops_token or not secrets.compare_digest(x_ops_token, config.OPS_TOKEN.get_secret_value()):
            return JSONResponse(status_code=404, content={"error": {"code": "not_found"}})
        try:
            result = app.state.import_store.metrics()
        except Exception:
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return JSONResponse(content=jsonable_encoder(result))
