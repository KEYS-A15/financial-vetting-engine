from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    app_name: str = "Financial Vetting Engine"
    app_version: str = "0.1.0"
    debug: bool = False

    max_file_size_mb: int = 20
    allowed_extensions: list[str] = [".pdf"]

    temp_dir: Path = Path("/tmp/fve")


settings = Settings()
