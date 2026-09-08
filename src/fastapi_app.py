from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .contracts.recipe_v1 import recipe_draft_json_schema


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else Settings()
    app = FastAPI(title=config.API_TITLE, version=config.API_VERSION)
    from .imports.api import install
    install(app, config)

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/contracts/recipe-draft", response_model=None)
    def recipe_draft_contract() -> dict:
        return recipe_draft_json_schema()

    @app.post("/api/analyze-recipe")
    async def analyze(request: Request):
        if not config.ENABLE_LEGACY_IMPORT:
            return JSONResponse(
                status_code=503,
                content={"success": False, "error": "legacy_import_disabled"},
            )
        if (
            config.APP_ENV != "local"
            or config.LEGACY_BUDGET_USD <= 0
            or not config.GEMINI_API_KEY
        ):
            return JSONResponse(
                status_code=503,
                content={"success": False, "error": "legacy_import_not_configured"},
            )
        # Phase 06 retires the last active path to Flask/TextBlob/Whisper/Torch.
        # Imports remain a local pipeline until authenticated durable jobs in phase 08.
        return JSONResponse(status_code=503, content={"success": False, "error": "legacy_import_retired"})

    return app


app = create_app()
