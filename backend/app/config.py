from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    gemini_api_key: str | None = None
    llm_model: str = "gemini/gemini-2.5-flash-lite"

    database_url: str = f"sqlite:///{DATA_DIR / 'incidents.db'}"
    chroma_dir: Path = DATA_DIR / "chroma"

    github_adapter: str = "mock"  # mock | real
    slack_adapter: str = "mock"  # mock | real

    ecommerce_repo_path: Path = REPO_ROOT / "ecommerce-app"
    runbooks_dir: Path = REPO_ROOT / "runbooks"

    slack_channel: str = "#incidents"

    cors_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)
