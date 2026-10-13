"""Conservative offer extraction and consumption for one verified Amap POI."""
import re
from datetime import date, datetime, time, timezone, timedelta

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from domain.evidence import (ClaimStatus, EvidenceScope, SourceObservation,
                             VenueClaim, VenueIdentity, check_branch_claim)


SHANGHAI_TZ = timezone(timedelta(hours=8))


class Offer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    description: str = Field(min_length=2, max_length=100)
    price_cny: float = Field(ge=0)
    terms: str = Field(min_length=2, max_length=200)
    applies_to: str = Field(min_length=2, max_length=200)
    starts_at: AwareDatetime
    ends_at: AwareDatetime


def _field(section, label):
    match = re.search(rf'^(?:[-*]\s*)?(?:{label})[：:]\s*(.+)$', section, re.MULTILINE)
    return match.group(1).strip() if match else None


def parse_offers(content, place):
    """Accept only a complete, explicit offer block naming the exact venue."""
    found = []
    headings = list(re.finditer(r'^### (.+)$', content, re.MULTILINE))
    for index, heading in enumerate(headings):
        section = content[heading.end():headings[index + 1].start() if index + 1 < len(headings) else len(content)]
        title = heading.group(1).strip()
        price_text = _field(section, '套餐价|优惠价|价格')
        terms = _field(section, '使用条件|活动条款')
        applies_to = _field(section, '适用门店')
        period = _field(section, '有效期')
        if not all((price_text, terms, applies_to, period)):
            continue
        if re.sub(r'\s+', '', applies_to) != re.sub(r'\s+', '', place['name']):
            continue
        price = re.fullmatch(r'[¥￥]\s*(\d{1,4}(?:\.\d{1,2})?)\s*元?', price_text)
        dates = re.fullmatch(r'(\d{4}-\d{2}-\d{2})\s*(?:至|~|—)\s*(\d{4}-\d{2}-\d{2})', period)
        if not price or not dates:
            continue
        try:
            start = date.fromisoformat(dates.group(1))
            end = date.fromisoformat(dates.group(2))
            if end < start:
                continue
            offer = Offer(description=title[:100], price_cny=float(price.group(1)),
                          terms=terms[:200], applies_to=applies_to[:200],
                          starts_at=datetime.combine(start, time.min, SHANGHAI_TZ),
                          ends_at=datetime.combine(end + timedelta(days=1), time.min, SHANGHAI_TZ))
        except (ValueError, OverflowError):
            continue
        found.append(offer)
    return found[:3]


def evaluate_offer(place, observation_record, claim_record, budget_cny, now=None):
    """Return a priced option only when source, scope, time and branch all pass."""
    now = now or datetime.now(timezone.utc)
    try:
        venue = VenueIdentity(amap_poi_id=place['poi_id'], name=place['name'],
                              city=place['city'], address=place['address'],
                              amap_coordinate=place['coordinate'])
        observation = SourceObservation.model_validate({
            'observation_id': observation_record['observation_id'],
            'kind': observation_record['kind'], 'outcome': observation_record['outcome'],
            'scope': observation_record['scope'], 'amap_poi_id': observation_record['amap_poi_id'],
            'url': observation_record['url'], 'observed_at': observation_record['observed_at'],
            'content_sha256': observation_record.get('content_sha256'),
            'evidence_excerpt': observation_record.get('evidence_excerpt')})
        claim = VenueClaim.model_validate(claim_record)
        check = check_branch_claim(venue, observation, claim, now)
        offer = Offer.model_validate(claim.value)
    except (KeyError, TypeError, ValueError):
        return None
    if (claim.field != 'offer' or check.outcome != 'pass'
            or not offer.starts_at <= now < offer.ends_at
            or claim.valid_until != offer.ends_at):
        return None
    return {'claim_id': str(claim.claim_id), 'observation_id': str(observation.observation_id),
            'description': offer.description, 'price_cny': offer.price_cny,
            'terms': offer.terms, 'applies_to': offer.applies_to,
            'valid_until': offer.ends_at.isoformat(), 'source_url': str(observation.url),
            'observed_at': observation.observed_at.isoformat(),
            'budget_option': ('within_limit' if budget_cny is not None and offer.price_cny <= budget_cny
                              else 'over_limit' if budget_cny is not None else 'unknown')}
