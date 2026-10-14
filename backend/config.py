"""Environment configuration without network calls or credential disclosure."""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env", override=False)

DEPLOYED_FRONTEND_ORIGIN = 'https://solovibe-app-vcdl.vercel.app'


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
    if os.getenv('APP_ENV', 'development').lower() == 'production' and (
            not origins or any(not origin.startswith('https://') for origin in origins)):
        raise ValueError('Production CORS_ORIGINS must contain explicit HTTPS origins')
    # The deployed Vercel site is an exact, owned origin; custom domains still use CORS_ORIGINS.
    return list(dict.fromkeys([*origins, DEPLOYED_FRONTEND_ORIGIN]))


def cookie_secure(request_scheme: str) -> bool:
    """A TLS-terminating proxy can make the internal request scheme HTTP."""
    configured = os.getenv('SESSION_COOKIE_SECURE', '').strip().lower()
    if configured in ('true', '1'):
        return True
    if os.getenv('APP_ENV', 'development').lower() == 'production':
        raise ValueError('Production requires SESSION_COOKIE_SECURE=true')
    return request_scheme == 'https'


def allowed_hosts() -> list[str]:
    values = [item.strip() for item in os.getenv('PUBLIC_HOSTS', '').split(',') if item.strip()]
    if os.getenv('APP_ENV', 'development').lower() == 'production' and (
            not values or '*' in values or any('/' in value for value in values)):
        raise ValueError('Production requires explicit PUBLIC_HOSTS without wildcards or paths')
    return values or ['127.0.0.1', 'localhost', 'testserver']
