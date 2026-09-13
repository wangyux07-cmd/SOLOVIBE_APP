"""Read-only checks against the configured Postgres and the fixed DeepSeek API.

Print categories only, never DSNs, passwords, keys, or raw exception messages.
"""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit, unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import os
import config
import psycopg
from services.model_client import DeepSeekClient


async def main():
    report = {}
    dsn = os.getenv("DATABASE_URL", "")
    parsed = urlsplit(dsn)
    password = unquote(parsed.password or "").lower()
    placeholder = not password or password in {"password", "your-db-password", "your_password", "your-password", "[your-password]"}
    if placeholder:
        report["database"] = {"connected": False, "reason": "password_placeholder"}
    elif not ((parsed.hostname or "").endswith((".supabase.co", ".pooler.supabase.com"))):
        report["database"] = {"connected": False, "reason": "unexpected_host_needs_review"}
    else:
        try:
            async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=10, autocommit=True) as connection:
                cursor = await connection.execute("SELECT 1")
                report["database"] = {"connected": (await cursor.fetchone())[0] == 1}
        except Exception as exc:
            report["database"] = {"connected": False, "reason": type(exc).__name__, "sqlstate": getattr(exc, "sqlstate", None)}
    if os.getenv("DEEPSEEK_API_KEY"):
        client = DeepSeekClient(os.environ["DEEPSEEK_API_KEY"], os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))
        try:
            report["model"] = await client.probe()
        except Exception as exc:
            report["model"] = {"authenticated": False, "reason": getattr(exc, "code", type(exc).__name__)}
        finally:
            await client.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
