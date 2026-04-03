from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT_DIR / ".env"

load_dotenv(ENV_PATH)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AppConfig:
    host: str = os.getenv("CSG_HOST", "0.0.0.0")
    port: int = int(os.getenv("CSG_PORT", "18080"))
    admin_username: str = os.getenv("CSG_ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("CSG_ADMIN_PASSWORD", "change-me-now")
    session_secret: str = os.getenv("CSG_SESSION_SECRET", "change-me-session-secret")
    app_name: str = os.getenv("CSG_APP_NAME", "Clash Socks Server UI")
    base_url: str = os.getenv("CSG_BASE_URL", "")
    enable_docs: bool = env_bool("CSG_ENABLE_DOCS", False)
    test_url: str = os.getenv("CSG_TEST_URL", "https://www.gstatic.com/generate_204")
    test_timeout_ms: int = int(os.getenv("CSG_TEST_TIMEOUT_MS", "5000"))


CONFIG = AppConfig()
