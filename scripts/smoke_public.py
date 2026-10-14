"""Read-only smoke check of the public frontend and API proxy."""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


def check(client: httpx.Client, name: str, url: str, expected: str) -> dict:
    started = time.monotonic()
    try:
        response = client.get(url)
        body = response.text
        if expected == "html":
            passed = (response.status_code == 200
                      and "<title>SoloVibe · 城市独行助手</title>" in body)
            detail = ("current SoloVibe page" if passed
                      else f"HTTP {response.status_code}; release marker absent")
        else:
            payload = response.json()
            passed = response.status_code == 200 and payload.get("ready") is True
            detail = {
                "http_status": response.status_code,
                "ready": payload.get("ready"),
                "stage": payload.get("stage"),
            }
    except (httpx.HTTPError, ValueError) as exc:
        passed = False
        detail = type(exc).__name__
    return {
        "name": name,
        "passed": passed,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "detail": detail,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", default="https://solovibe-app-vcdl.vercel.app")
    parser.add_argument("--backend", default="https://solovibe-oxne.onrender.com")
    parser.add_argument("--output", type=Path,
                        default=Path("docs/evidence/formal-2026-10-14-public-smoke.json"))
    args = parser.parse_args()
    with httpx.Client(timeout=httpx.Timeout(90, connect=15), follow_redirects=True) as client:
        results = [
            check(client, "frontend", args.frontend.rstrip("/") + "/", "html"),
            check(client, "frontend_api_proxy",
                  args.frontend.rstrip("/") + "/api/v1/readiness", "readiness"),
            check(client, "backend_readiness",
                  args.backend.rstrip("/") + "/api/v1/readiness", "readiness"),
        ]
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "mode": "public_read_only",
        "passed": sum(item["passed"] for item in results),
        "total": len(results),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"public_smoke={report['passed']}/{report['total']}")
    for item in results:
        print(f"{item['name']}: {'pass' if item['passed'] else 'fail'} "
              f"latency_ms={item['latency_ms']} detail={item['detail']}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
