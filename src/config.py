from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server settings; health never requires credentials or legacy extras."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore", hide_input_in_errors=True)

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
    ENABLE_MOCKS: bool = False
    BYPASS_AUTH: bool = False
    ALLOW_INSECURE_HTTP: bool = False
    IMPORT_ENABLED: bool = True
    OPS_TOKEN: SecretStr | None = None
    WORKER_POLL_SECONDS: int = Field(default=2, ge=1, le=60)
    WORKER_HEARTBEAT_MAX_AGE_SECONDS: int = Field(default=90, ge=30, le=300)
    IMPORT_MIN_FREE_DISK_BYTES: int = Field(default=256 * 1024**2, ge=64*1024**2)
    IMPORT_TEMP_TTL_SECONDS: int = Field(default=3600, ge=600, le=86400)
    IMPORT_ALLOW_PAID: bool = False
    IMPORT_ALLOW_LOCAL_SOCIAL: bool = False
    IMPORT_MAX_DURATION_SECONDS: int = Field(default=300, ge=1, le=300)
    IMPORT_MAX_MEDIA_BYTES: int = Field(default=50 * 1024**2, ge=1024, le=50 * 1024**2)

    @model_validator(mode="after")
    def secure_runtime(self):
        if self.ENABLE_MOCKS or self.BYPASS_AUTH or self.ALLOW_INSECURE_HTTP:
            raise ValueError("unsafe_runtime_flags_forbidden")
        if self.APP_ENV != "local":
            if self.ENABLE_LEGACY_IMPORT or self.IMPORT_ALLOW_LOCAL_SOCIAL or self.SUPABASE_JWT_SECRET:
                raise ValueError("local_only_features_forbidden")
            if self.SUPABASE_URL:
                url = urlsplit(self.SUPABASE_URL)
                if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise ValueError("supabase_https_required")
        return self


# Compatibility for the isolated legacy module. No dotenv file is loaded implicitly.
settings = Settings()
