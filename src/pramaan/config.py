"""Runtime configuration for Pramaan.

All settings come from environment variables (optionally loaded from ``src/.env``)
so the same code runs on an investigator's laptop, inside Docker, or as the MCP
server that an MCP client (Claude Desktop, VS Code, ...) launches. Nothing here requires network access: with the
defaults, Pramaan runs fully offline (air-gapped FSLs are the norm, not the
exception).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
SRC_DIR = PACKAGE_DIR.parent
REPO_DIR = SRC_DIR.parent

ENGINE_VERSION = "1.0.0"
WEB_DIR = SRC_DIR / "web"
SCENARIOS_DIR = SRC_DIR / "scenarios"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines). Existing env vars always win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(SRC_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    home: Path = field(default_factory=lambda: Path(os.getenv("PRAMAAN_HOME", SRC_DIR / "runtime")))
    llm_provider: str = field(default_factory=lambda: os.getenv("PRAMAAN_LLM_PROVIDER", "none").lower())
    watsonx_api_key: str = field(default_factory=lambda: os.getenv("WATSONX_API_KEY", ""))
    watsonx_project_id: str = field(default_factory=lambda: os.getenv("WATSONX_PROJECT_ID", ""))
    watsonx_space_id: str = field(default_factory=lambda: os.getenv("WATSONX_SPACE_ID", ""))
    watsonx_url: str = field(default_factory=lambda: os.getenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com"))
    watsonx_model_id: str = field(default_factory=lambda: os.getenv("WATSONX_MODEL_ID", "ibm/granite-4-h-small"))
    api_host: str = field(default_factory=lambda: os.getenv("APP_HOST", "127.0.0.1"))
    api_port: int = field(default_factory=lambda: int(os.getenv("APP_PORT", "8000")))
    protected_terms_file: Path = field(
        default_factory=lambda: Path(os.getenv("PRAMAAN_PROTECTED_TERMS", SRC_DIR / "runtime" / "protected_terms.sha256"))
    )

    @property
    def db_path(self) -> Path:
        return Path(os.getenv("PRAMAAN_DB_PATH", self.home / "pramaan.sqlite3"))

    @property
    def cases_dir(self) -> Path:
        return self.home / "cases"

    def ensure_dirs(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.cases_dir.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    """Read settings fresh each call so tests can monkeypatch the environment."""
    return Settings()
