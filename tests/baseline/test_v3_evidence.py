"""V3 field evidence must fail closed at the consumer boundary."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from domain.evidence import (
    ClaimStatus, EvidenceScope, SourceKind, SourceObservation, ToolOutcome,
    ToolResult, VenueClaim, VenueIdentity, check_branch_claim,
)


NOW = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)


def sample(field="price", value=38, scope=EvidenceScope.branch):
    venue = VenueIdentity(amap_poi_id="B001", name="示例门店", city="上海市",
                          address="徐汇区示例路1号", amap_coordinate="121.436440,31.194160")
    observation = SourceObservation(observation_id=uuid4(), kind=SourceKind.official_site,
                                    outcome=ToolOutcome.success, scope=scope,
                                    amap_poi_id="B001" if scope == EvidenceScope.branch else None,
                                    url="https://example.org/menu", observed_at=NOW)
    claim = VenueClaim(claim_id=uuid4(), observation_id=observation.observation_id,
                       field=field, value=value, unit="CNY", scope=scope,
                       amap_poi_id="B001" if scope == EvidenceScope.branch else None,
                       status=ClaimStatus.verified, observed_at=NOW,
                       valid_until=NOW + timedelta(hours=1) if field == "offer" else None)
    return venue, observation, claim


def test_matching_fresh_branch_fact_may_be_consumed():
    venue, observation, claim = sample()
    result = check_branch_claim(venue, observation, claim, NOW + timedelta(minutes=1))
    assert result.outcome == "pass"
    assert result.claim_id == claim.claim_id


def test_wrong_branch_and_wrong_source_never_become_facts():
    venue, observation, claim = sample()
    wrong_branch = claim.model_copy(update={"amap_poi_id": "B002"})
    assert check_branch_claim(venue, observation, wrong_branch, NOW).reason == "identity_conflict"
    wrong_source = claim.model_copy(update={"observation_id": uuid4()})
    assert check_branch_claim(venue, observation, wrong_source, NOW).reason == "source_mismatch"


def test_brand_menu_is_not_branch_menu_and_search_lead_is_not_evidence():
    venue, observation, claim = sample("menu_item", "早餐三明治", EvidenceScope.brand)
    assert check_branch_claim(venue, observation, claim, NOW).reason == "not_branch_scoped"
    with pytest.raises(ValidationError):
        SourceObservation(observation_id=uuid4(), kind=SourceKind.search_lead,
                          outcome=ToolOutcome.success, scope=EvidenceScope.branch,
                          amap_poi_id="B001", url="https://example.org", observed_at=NOW)


def test_missing_price_and_expired_offer_fail_closed():
    venue, observation, _ = sample()
    with pytest.raises(ValidationError):
        sample(value=None)
    with pytest.raises(ValidationError):
        sample(value="about 38")
    _, offer_observation, offer = sample("offer", {"price_cny": 28, "description": "早餐套餐",
                                                     "terms": "仅工作日", "applies_to": "B001"})
    assert check_branch_claim(venue, offer_observation, offer, NOW + timedelta(hours=2)).reason == "stale"
    with pytest.raises(ValidationError):
        VenueClaim.model_validate(offer.model_dump() | {"valid_until": None})


def test_tool_failures_cannot_carry_success_data():
    with pytest.raises(ValidationError):
        ToolResult(outcome=ToolOutcome.timeout, data={"price": 38}, observed_at=NOW, source="merchant")
    with pytest.raises(ValidationError):
        ToolResult(outcome=ToolOutcome.success, observed_at=NOW, source="merchant")


def test_map_recorded_hours_cannot_claim_realtime_open_status():
    venue, observation, _ = sample()
    observation = observation.model_copy(update={"kind": SourceKind.map_api})
    claim = VenueClaim(claim_id=uuid4(), observation_id=observation.observation_id,
                       field="open_now", value=True, scope=EvidenceScope.branch,
                       amap_poi_id="B001", status=ClaimStatus.verified,
                       observed_at=NOW, valid_until=NOW + timedelta(minutes=5))
    assert check_branch_claim(venue, observation, claim, NOW).reason == "source_not_realtime"


def test_map_average_cost_cannot_be_promoted_to_item_price():
    venue, observation, claim = sample()
    observation = observation.model_copy(update={"kind": SourceKind.map_api})
    assert check_branch_claim(venue, observation, claim, NOW).reason == "source_scope_insufficient"


def test_offer_without_terms_is_not_verified():
    with pytest.raises(ValidationError):
        sample("offer", {"price_cny": 28})


def test_fixed_pilot_cohort_keeps_all_four_categories():
    path = Path(__file__).resolve().parents[2] / "eval/v3_pilot_shanghai.json"
    cohort = json.loads(path.read_text(encoding="utf-8"))
    assert len(cohort["venues"]) == 12
    assert len({item["id"] for item in cohort["venues"]}) == 12
    assert {category: sum(row["category"] == category for row in cohort["venues"])
            for category in {row["category"] for row in cohort["venues"]}} == {
                "cafe": 3, "dining": 3, "attraction": 3, "park": 3}
