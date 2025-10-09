from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración centralizada de la aplicación."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Configuración de la API
    API_TITLE: str = "Python API Railway"
    API_VERSION: str = "1.0.0"
    DATABASE_URL: str = "sqlite:///./test.db"  # Cambiar según la base de datos utilizada
    SECRET_KEY: str = "your_secret_key"  # Cambiar por una clave secreta segura

settings = Settings()