from importlib import import_module

from fastapi import Request
from fastapi.responses import JSONResponse


async def analyze_legacy(request: Request):
    """Explicit opt-in boundary. Importing health never imports legacy packages."""
    try:
        legacy = import_module("src.legacy_fastapi")
        return await legacy.analyze_recipe_endpoint(request)
    except Exception:
        # Do not expose provider messages, source content or credentials.
        return JSONResponse(
            status_code=503,
            content={"success": False, "error": "legacy_import_unavailable"},
        )
