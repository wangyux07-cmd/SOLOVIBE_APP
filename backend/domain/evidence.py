"""Typed, source-bound observations for V3 external information.

These records describe evidence, not permission to claim that a shop currently
has a product, seat, or offer. Consumer-specific suitability is checked below.
"""

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, model_validator


class ToolOutcome(str, Enum):
    success = "success"
    empty = "empty"
    forbidden = "forbidden"
    timeout = "timeout"
    invalid_response = "invalid_response"
    identity_conflict = "identity_conflict"
    stale = "stale"


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: ToolOutcome
    data: dict[str, Any] | None = None
    observed_at: AwareDatetime
    source: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def require_success_data(self):
        if (self.outcome == ToolOutcome.success) != (self.data is not None):
            raise ValueError("only successful tool results may carry data")
        return self


class EvidenceScope(str, Enum):
    branch = "branch"
    brand = "brand"
    area = "area"


class SourceKind(str, Enum):
    map_api = "map_api"
    official_site = "official_site"
    authorized_api = "authorized_api"
    merchant_direct = "merchant_direct"
    search_lead = "search_lead"


class ClaimStatus(str, Enum):
    verified = "verified"
    indicative = "indicative"
    unknown = "unknown"
    stale = "stale"
    conflict = "conflict"


class VenueIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amap_poi_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=80)
    address: str = Field(min_length=1, max_length=500)
    amap_coordinate: str = Field(pattern=r"^-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?$")


class SourceObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observation_id: UUID
    kind: SourceKind
    outcome: ToolOutcome
    scope: EvidenceScope
    amap_poi_id: str | None = None
    url: HttpUrl
    observed_at: AwareDatetime
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evidence_excerpt: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def branch_requires_identity(self):
        if self.url.scheme != "https":
            raise ValueError("source URL must use HTTPS")
        if self.scope == EvidenceScope.branch and not self.amap_poi_id:
            raise ValueError("branch evidence requires a matched POI identity")
        if self.kind == SourceKind.search_lead and self.scope == EvidenceScope.branch:
            raise ValueError("search leads cannot establish branch identity")
        return self


class VenueClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: UUID
    observation_id: UUID
    field: str = Field(min_length=1, max_length=80)
    value: Any
    unit: str | None = Field(default=None, max_length=40)
    scope: EvidenceScope
    amap_poi_id: str | None = None
    status: ClaimStatus
    observed_at: AwareDatetime
    valid_until: AwareDatetime | None = None

    @model_validator(mode="after")
    def check_claim_shape(self):
        if self.scope == EvidenceScope.branch and not self.amap_poi_id:
            raise ValueError("branch claim requires a POI identity")
        if self.field in {"offer", "open_now", "availability"} and self.status == ClaimStatus.verified:
            if self.valid_until is None:
                raise ValueError("current claims require an expiration")
        if self.field == "price" and self.status == ClaimStatus.verified:
            if (isinstance(self.value, bool) or not isinstance(self.value, (int, float))
                    or not math.isfinite(self.value) or self.value < 0 or self.unit != "CNY"):
                raise ValueError("verified price requires a nonnegative CNY amount")
        if self.field == "offer" and self.status == ClaimStatus.verified:
            offer = self.value
            if (not isinstance(offer, dict)
                    or isinstance(offer.get("price_cny"), bool)
                    or not isinstance(offer.get("price_cny"), (int, float))
                    or not math.isfinite(offer["price_cny"])
                    or offer["price_cny"] < 0
                    or not all(isinstance(offer.get(key), str) and offer[key].strip()
                               for key in ("description", "terms", "applies_to"))):
                raise ValueError("verified offer requires price, description, terms and applicability")
        return self


class FeasibilityCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: str = Field(pattern=r"^(pass|fail|unknown)$")
    reason: str = Field(min_length=1, max_length=120)
    claim_id: UUID | None = None


def check_branch_claim(
    venue: VenueIdentity,
    observation: SourceObservation,
    claim: VenueClaim,
    now: datetime | None = None,
) -> FeasibilityCheck:
    """Fail closed before a claim can affect a branch-level decision."""
    now = now or datetime.now(timezone.utc)
    if claim.observation_id != observation.observation_id:
        return FeasibilityCheck(outcome="unknown", reason="source_mismatch")
    if observation.outcome != ToolOutcome.success:
        return FeasibilityCheck(outcome="unknown", reason=observation.outcome.value)
    if observation.kind == SourceKind.search_lead:
        return FeasibilityCheck(outcome="unknown", reason="search_lead_only")
    if claim.field in {"price", "offer", "menu_item"} and observation.kind == SourceKind.map_api:
        return FeasibilityCheck(outcome="unknown", reason="source_scope_insufficient")
    if claim.field in {"open_now", "availability"} and observation.kind not in {
        SourceKind.authorized_api, SourceKind.merchant_direct,
    }:
        return FeasibilityCheck(outcome="unknown", reason="source_not_realtime")
    if claim.scope != EvidenceScope.branch or observation.scope != EvidenceScope.branch:
        return FeasibilityCheck(outcome="unknown", reason="not_branch_scoped")
    if claim.amap_poi_id != venue.amap_poi_id or observation.amap_poi_id != venue.amap_poi_id:
        return FeasibilityCheck(outcome="unknown", reason="identity_conflict")
    if claim.status != ClaimStatus.verified:
        return FeasibilityCheck(outcome="unknown", reason=claim.status.value)
    if claim.observed_at > now or observation.observed_at > now:
        return FeasibilityCheck(outcome="unknown", reason="future_observation")
    if claim.valid_until is not None and claim.valid_until <= now:
        return FeasibilityCheck(outcome="unknown", reason="stale")
    if claim.field in {"price", "offer"} and (claim.value is None or claim.value == ""):
        return FeasibilityCheck(outcome="unknown", reason="missing_value")
    return FeasibilityCheck(outcome="pass", reason="source_and_branch_verified", claim_id=claim.claim_id)
