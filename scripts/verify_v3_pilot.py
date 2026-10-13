"""Query the fixed V3 cohort against the real Amap key; never invent POI IDs."""
import asyncio
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import config  # noqa: F401 - loads ignored backend/.env
from services.planning import AmapProvider, ProviderFailure


async def main(output: Path | None):
    cohort = json.loads((ROOT / "docs/v3_pilot_shanghai.json").read_text(encoding="utf-8"))
    from os import getenv
    provider = AmapProvider(getenv("AMAP_API_KEY", "").strip())
    rows = []
    try:
        for venue in cohort["venues"]:
            try:
                candidates = await provider.search(cohort["city"], cohort["anchor_amap_coordinate"], venue["query"])
                rows.append({
                    "id": venue["id"], "query": venue["query"], "outcome": "success" if candidates else "empty",
                    "candidates": [{"poi_id": item["poi_id"], "name": item["name"], "address": item["address"],
                                    "coordinate": item["coordinate"], "source_url": item["source_url"]}
                                   for item in candidates[:3]],
                })
            except ProviderFailure as exc:
                rows.append({"id": venue["id"], "query": venue["query"], "outcome": exc.category, "candidates": []})
    finally:
        await provider.close()
    report = {"cohort_version": cohort["version"], "queried_at": datetime.now(timezone.utc).isoformat(),
              "provider": "amap", "rows": rows}
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if output:
        output.write_text(payload, encoding="utf-8")
        print(json.dumps({"rows": len(rows), "report": str(output)}, ensure_ascii=True))
    else:
        print(payload)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main(args.output))
