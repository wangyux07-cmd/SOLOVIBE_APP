"""Opt-in, read-only bridge for a merchant that has granted branch-level access.

The configured endpoint is a merchant-owned integration contract, not an
undocumented Meituan/Dianping API. No configuration means no network call.
"""
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, model_validator

from domain.evidence import (ClaimStatus, EvidenceScope, SourceKind, SourceObservation,
                             ToolOutcome, VenueClaim, VenueIdentity, check_branch_claim)


class MerchantPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    branch_id: str = Field(min_length=1, max_length=100)
    amap_poi_id: str = Field(min_length=1, max_length=80)
    observed_at: AwareDatetime
    valid_until: AwareDatetime
    open_now: StrictBool | None = None
    availability: str | None = Field(default=None, pattern='^(available|limited|unavailable|unknown)$')

    @model_validator(mode='after')
    def has_information(self):
        if self.open_now is None and self.availability in (None, 'unknown'):
            raise ValueError('no authorized live field')
        return self


class MerchantLiveService:
    def __init__(self, endpoint='', token='', poi_id='', branch_id='', authorization_ref='',
                 grant_expires_at='', source_url='', fields='', client=None):
        self.endpoint, self.token = endpoint.strip(), token.strip()
        self.poi_id, self.branch_id = poi_id.strip(), branch_id.strip()
        self.authorization_ref = authorization_ref.strip()
        self.source_url = source_url.strip()
        self.fields = {value.strip() for value in fields.split(',') if value.strip()}
        try:
            self.grant_expires_at = datetime.fromisoformat(grant_expires_at.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            self.grant_expires_at = None
        endpoint_url, public_url = urlsplit(self.endpoint), urlsplit(self.source_url)
        self.configured = bool(
            all((self.endpoint, self.token, self.poi_id, self.branch_id,
                 self.authorization_ref, self.grant_expires_at, self.source_url))
            and self.grant_expires_at.tzinfo is not None
            and endpoint_url.scheme == public_url.scheme == 'https'
            and endpoint_url.hostname and public_url.hostname
            and not any((endpoint_url.username, endpoint_url.password, endpoint_url.query,
                         endpoint_url.fragment, public_url.username, public_url.password,
                         public_url.query, public_url.fragment))
            and self.fields and self.fields <= {'open_now', 'availability'}
        )
        self.client = client or httpx.AsyncClient(timeout=4, follow_redirects=False)

    @classmethod
    def from_environment(cls):
        return cls(endpoint=os.getenv('MERCHANT_LIVE_ENDPOINT', ''),
                   token=os.getenv('MERCHANT_LIVE_TOKEN', ''),
                   poi_id=os.getenv('MERCHANT_LIVE_AMAP_POI_ID', ''),
                   branch_id=os.getenv('MERCHANT_LIVE_BRANCH_ID', ''),
                   authorization_ref=os.getenv('MERCHANT_LIVE_AUTHORIZATION_REF', ''),
                   grant_expires_at=os.getenv('MERCHANT_LIVE_GRANT_EXPIRES_AT', ''),
                   source_url=os.getenv('MERCHANT_LIVE_SOURCE_URL', ''),
                   fields=os.getenv('MERCHANT_LIVE_FIELDS', ''))

    async def close(self):
        await self.client.aclose()

    async def read(self, place):
        """Return verified, expiring branch facts or None; never return stale cache."""
        now = datetime.now(timezone.utc)
        if not self.configured or place.get('poi_id') != self.poi_id:
            return None
        if self.grant_expires_at <= now:
            return None
        try:
            response = await self.client.get(
                self.endpoint, headers={'Authorization': f'Bearer {self.token}',
                                        'Accept': 'application/json'})
            response.raise_for_status()
            if len(response.content) > 65536:
                return None
            payload = MerchantPayload.model_validate(response.json())
        except (httpx.HTTPError, ValueError, TypeError):
            return None
        now = datetime.now(timezone.utc)
        if self.grant_expires_at <= now:
            return None
        if payload.branch_id != self.branch_id or payload.amap_poi_id != self.poi_id:
            return None
        if (payload.observed_at > now + timedelta(seconds=5)
                or now - payload.observed_at > timedelta(minutes=2)
                or payload.valid_until <= now
                or payload.valid_until > payload.observed_at + timedelta(minutes=2)):
            return None
        valid_until = min(payload.valid_until, self.grant_expires_at)
        if valid_until <= now:
            return None
        values = {'open_now': payload.open_now, 'availability': payload.availability}
        values = {key: value for key, value in values.items()
                  if key in self.fields and value is not None and value != 'unknown'}
        if not values:
            return None
        try:
            venue = VenueIdentity(amap_poi_id=place['poi_id'], name=place['name'],
                                  city=place['city'], address=place['address'],
                                  amap_coordinate=place['coordinate'])
            observation = SourceObservation(observation_id=uuid4(), kind=SourceKind.merchant_direct,
                                            outcome=ToolOutcome.success, scope=EvidenceScope.branch,
                                            amap_poi_id=self.poi_id, url=self.source_url,
                                            observed_at=payload.observed_at)
            claims = [VenueClaim(claim_id=uuid4(), observation_id=observation.observation_id,
                                 field=key, value=value, scope=EvidenceScope.branch,
                                 amap_poi_id=self.poi_id, status=ClaimStatus.verified,
                                 observed_at=payload.observed_at, valid_until=valid_until)
                      for key, value in values.items()]
            if any(check_branch_claim(venue, observation, claim, now).outcome != 'pass'
                   for claim in claims):
                return None
        except (ValueError, KeyError, TypeError):
            return None
        info = {'status': 'verified', 'source_kind': 'merchant_direct',
                'source_url': self.source_url, 'branch_id': self.branch_id,
                'amap_poi_id': self.poi_id, 'observed_at': payload.observed_at.isoformat(),
                'valid_until': valid_until.isoformat(), **values}
        evidence = {'observations': [{**observation.model_dump(mode='json'),
                    'source_domain': urlsplit(self.source_url).hostname,
                    'extract_status': 'authorized_read', 'field_scope': 'branch_live',
                    'content_length': 0}],
                    'claims': [claim.model_dump(mode='json') for claim in claims]}
        return {'info': info, 'evidence': evidence}


def live_snapshot_current(advertised, current, now=None):
    """A changed/expired grant or branch fact requires a new user proposal."""
    now = now or datetime.now(timezone.utc)
    if not advertised:
        return True
    if not current or advertised.get('status') != 'verified':
        return False
    try:
        expiry = datetime.fromisoformat(advertised['valid_until'])
        current_expiry = datetime.fromisoformat(current['valid_until'])
        if (expiry.tzinfo is None or expiry <= now or current_expiry.tzinfo is None
                or current_expiry <= now):
            return False
    except (KeyError, TypeError, ValueError):
        return False
    keys = ('branch_id', 'amap_poi_id', 'source_url', 'open_now', 'availability')
    return all(advertised.get(key) == current.get(key) for key in keys)
