from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server settings; health never requires credentials or legacy extras."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    APP_ENV: Literal["local", "staging", "production"] = "local"
    API_TITLE: str = "Foodiefy API"
    API_VERSION: str = "0.1.0"
    ENABLE_LEGACY_IMPORT: bool = False
    LEGACY_BUDGET_USD: float = Field(default=0, ge=0, allow_inf_nan=False)
    GEMINI_API_KEY: SecretStr | None = None
    OPENAI_API_KEY: SecretStr | None = None
    STT_MODEL: str = "gpt-transcribe"
    RECIPE_EXTRACTOR_MODEL: str = "gpt-5-nano"
    ENABLE_VISUAL_FALLBACK: bool = False
    VISUAL_MODEL: str = "gemini-2.5-flash"
    AI_TIMEOUT_SECONDS: float = Field(default=60, gt=0, le=180)
    AI_MAX_OUTPUT_TOKENS: int = Field(default=6000, ge=512, le=16000)
    AI_MAX_INPUT_BYTES: int = Field(default=80000, ge=1024, le=200000)
    AI_TRANSIENT_RETRIES: int = Field(default=0, ge=0, le=1)
    IMPORT_DATABASE_URL: SecretStr | None = None
    SUPABASE_URL: str | None = None
    SUPABASE_JWT_AUDIENCE: str = "authenticated"
    SUPABASE_JWT_SECRET: SecretStr | None = None  # Local legacy JWT verification only.
    IMPORT_ALLOW_PAID: bool = False
    IMPORT_ALLOW_LOCAL_SOCIAL: bool = False
    IMPORT_MAX_DURATION_SECONDS: int = Field(default=300, ge=1, le=300)
    IMPORT_MAX_MEDIA_BYTES: int = Field(default=50 * 1024**2, ge=1024, le=50 * 1024**2)


# Compatibility for the isolated legacy module. No dotenv file is loaded implicitly.
settings = Settings()
