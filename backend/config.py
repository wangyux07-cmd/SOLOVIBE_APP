"""Environment configuration without network calls or credential disclosure."""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env", override=False)


def is_configured(name: str) -> bool:
    value = os.getenv(name, "").strip()
    return bool(value) and not value.lower().startswith(
        ("your-", "your_", "replace", "sk-你的", "<")
    )


def database_configured() -> bool:
    from domain.errors import AppError
    from services.application import database_dsn
    try:
        database_dsn()
        return True
    except AppError:
        return False


def configuration_status() -> dict:
    """Configured means present, never authenticated or verified."""
    services = {
        "model": is_configured("DEEPSEEK_API_KEY"),
        "maps": is_configured("AMAP_API_KEY"),
        "search": is_configured("TAVILY_API_KEY"),
        "database": database_configured(),
    }
    return {
        name: {"configured": configured, "verification": "not_checked"}
        for name, configured in services.items()
    }


def cors_origins() -> list[str]:
    default = "http://127.0.0.1:5173,http://localhost:5173"
    origins = [item.strip().rstrip("/") for item in os.getenv("CORS_ORIGINS", default).split(",") if item.strip()]
    if "*" in origins:
        raise ValueError("CORS_ORIGINS must contain explicit origins, not '*'")
    return origins
