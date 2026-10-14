"""Aggregate the frozen real-map cohort and deterministic fault matrix."""
import argparse
import json
import math
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def percentile(values: list[int], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[math.ceil(len(ordered) * fraction) - 1], 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("eval/formal_itinerary_scenarios.json"))
    parser.add_argument("--evidence-dir", type=Path, default=Path("docs/evidence"))
    parser.add_argument("--output", type=Path,
                        default=Path("docs/evidence/formal-2026-10-14-summary.json"))
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    expected = {item["id"]: item["expected"] for item in dataset["scenarios"]}
    if len(expected) != 30:
        raise SystemExit(f"Expected 30 frozen real scenarios, got {len(expected)}")

    rounds = []
    for index in range(1, 4):
        path = args.evidence_dir / f"formal-2026-10-14-real-round{index}.json"
        run = json.loads(path.read_text(encoding="utf-8"))
        results = run["results"]
        if len(results) != 30 or {item["id"] for item in results} != set(expected):
            raise SystemExit(f"Round {index} has an incomplete or changed scenario set")
        if any(item["expected"] != expected[item["id"]] for item in results):
            raise SystemExit(f"Round {index} changed a frozen expectation")
        rounds.append(run)

    fault = json.loads((args.evidence_dir / "formal-2026-10-14-faults.json")
                       .read_text(encoding="utf-8"))
    observations = [item for run in rounds for item in run["results"]]
    feasible = [item for item in observations if expected[item["id"]] == "passed"]
    boundary = [item for item in observations if expected[item["id"]] == "no_itinerary"]
    dinner = [item for item in feasible if item["id"].endswith("_dinner")]
    published = [item for item in observations if item.get("stop_count", 0) >= 2]
    failures = Counter()
    for item in observations:
        failures.update(item.get("provider_failures", {}))
    route_denominator = sum(item.get("leg_count", 0) for item in published)
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": dataset["version"],
        "mode": "real_amap_no_model_plus_mocked_faults",
        "real_scenarios": len(expected),
        "real_rounds": len(rounds),
        "real_observations": len(observations),
        "feasible_passed": sum(item["status"] == "passed" for item in feasible),
        "feasible_total": len(feasible),
        "boundary_rejected": sum(item["status"] == "no_itinerary" for item in boundary),
        "boundary_total": len(boundary),
        "expected_outcome_matches": sum(item["outcome_match"] for item in observations),
        "dinner_satisfied": sum(item.get("dinner_satisfied", False) for item in dinner),
        "dinner_total": len(dinner),
        "published_itineraries": len(published),
        "published_hard_constraint_violations": sum(
            not item.get("hard_constraints_pass", False) for item in published),
        "verified_route_legs": sum(item.get("route_leg_count", 0) for item in published),
        "geometry_route_legs": sum(item.get("geometry_leg_count", 0) for item in published),
        "published_route_legs": route_denominator,
        "p50_map_chain_ms": percentile([item["latency_ms"] for item in observations], 0.5),
        "p95_map_chain_ms": percentile([item["latency_ms"] for item in observations], 0.95),
        "mean_map_chain_ms": round(statistics.mean(item["latency_ms"] for item in observations), 1),
        "logical_map_calls": sum(item["map_calls"] for item in observations),
        "mean_map_calls_per_observation": round(
            statistics.mean(item["map_calls"] for item in observations), 1),
        "provider_failures": dict(failures),
        "outcome_counts": dict(Counter(item["status"] for item in observations)),
        "fault_injection_passed": fault["passed_count"],
        "fault_injection_total": fault["case_count"] * fault["round_count"],
        "rounds": [{
            "run_at": run["run_at"],
            "expected_match": run["expected_outcome_match_count"],
            "feasible_passed": sum(
                item["status"] == "passed" for item in run["results"]
                if expected[item["id"]] == "passed"),
            "boundary_rejected": sum(
                item["status"] == "no_itinerary" for item in run["results"]
                if expected[item["id"]] == "no_itinerary"),
            "p50_map_chain_ms": run["p50_latency_ms"],
            "p95_map_chain_ms": run["p95_latency_ms"],
            "logical_map_calls": run["logical_map_calls"],
            "provider_failures": run["provider_failures"],
        } for run in rounds],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"real_expected_match={report['expected_outcome_matches']}/{report['real_observations']} "
          f"feasible={report['feasible_passed']}/{report['feasible_total']} "
          f"boundary={report['boundary_rejected']}/{report['boundary_total']} "
          f"faults={report['fault_injection_passed']}/{report['fault_injection_total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
