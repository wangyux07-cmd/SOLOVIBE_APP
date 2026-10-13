"""Bounded extraction of public official pages; page text is never agent instructions."""
import hashlib
import ipaddress
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

from domain.evidence import (ClaimStatus, EvidenceScope, SourceKind,
                             SourceObservation, ToolOutcome, VenueClaim)


class MenuItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=2, max_length=100)
    category: str = Field(min_length=1, max_length=40)
    price_cny: float | None = Field(default=None, ge=0)


class AdmissionPrice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    description: str = Field(min_length=2, max_length=100)
    price_cny: float = Field(ge=0)


OFFICIAL_CATALOG = ({
    'brand': '星巴克', 'hosts': ('www.starbucks.com.cn',),
    'urls': ('https://www.starbucks.com.cn/menu/food/great-breakfast/',),
    'field_scope': 'menu_item', 'category': 'food',
},)


def approved_url(url, hosts):
    if not isinstance(url, str) or len(url) > 2048:
        return False
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower().rstrip('.')
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            pass
        port = parsed.port
    except ValueError:
        return False
    except (TypeError, AttributeError):
        return False
    return (parsed.scheme == 'https' and not parsed.username and not parsed.password
            and port in (None, 443) and host in hosts)


def clean_line(value, limit=400):
    if not isinstance(value, str):
        return ''
    return re.sub(r'[\x00-\x1f\x7f]+', ' ', value).strip()[:limit]


def evidence_line(content, field_scope):
    if not content:
        return None
    if field_scope == 'menu_item':
        match = next((line for line in content.splitlines() if line.startswith('### ')), '')
    else:
        match = next((line for line in content.splitlines()
                      if any(word in line for word in ('门票', '票价', '入场券'))
                      and re.search(r'[¥￥]|人民币', line)), '')
    return clean_line(match, 400) or None


def branch_identity_in_text(place, content):
    """Require both the full POI name and a distinctive street number, not a brand hit."""
    name = re.sub(r'\s+', '', place['name'])
    address = re.sub(r'\s+', '', place['address'])
    street = re.search(r'[\u4e00-\u9fff]{2,12}(?:路|街|道|弄)\d+号', address)
    compact = re.sub(r'\s+', '', content)
    return bool(street and name in compact and street.group() in compact)


def parse_menu(content, category, city=''):
    """Only explicit Markdown product headings, never prose or search snippets."""
    items = []
    headings = list(re.finditer(r'^### (.+)$', content, re.MULTILINE))
    for index, match in enumerate(headings):
        section = content[match.end():headings[index + 1].start() if index + 1 < len(headings) else len(content)]
        if city.startswith('上海') and (
            re.search(r'(?:上海|江浙沪).{0,20}不售卖', section)
            or re.search(r'仅在(?:北京|广州|深圳).{0,30}售卖', section)
        ):
            continue
        heading = clean_line(match.group(1), 180)
        name = re.split(r'\s+[A-Za-z][A-Za-z /&()\-]*$', heading)[0].strip()
        if len(name) < 2 or not re.search(r'[\u4e00-\u9fff]', name):
            continue
        price = re.search(r'(?:¥|￥)\s*(\d{1,4}(?:\.\d{1,2})?)\s*元?', name)
        if price:
            name = name[:price.start()].strip()
        item = MenuItem(name=name[:100], category=category,
                        price_cny=float(price.group(1)) if price else None)
        if item.name not in {existing.name for existing in items}:
            items.append(item)
    return items[:8]


def parse_admission(content):
    prices = []
    for line in content.splitlines():
        normalized = clean_line(line, 180)
        if not any(word in normalized for word in ('门票', '票价', '入场券')):
            continue
        found = re.search(r'(?:¥|￥|人民币)\s*(\d{1,4}(?:\.\d{1,2})?)\s*元?', normalized)
        if found:
            prices.append(AdmissionPrice(description=normalized[:100], price_cny=float(found.group(1))))
    return prices[:3]


class OfficialEvidenceService:
    URL = 'https://api.tavily.com/extract'

    def __init__(self, key, client=None, catalog=OFFICIAL_CATALOG):
        self.key = key
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(15, connect=3))
        self.owns_client = client is None
        self.catalog = catalog

    async def close(self):
        if self.owns_client:
            await self.client.aclose()

    def discover(self, place):
        return [source for source in self.catalog if source['brand'] in place['name']
                and (not source.get('requires_branch')
                     or source.get('branch_poi_id') == place['poi_id'])]

    async def extract(self, url, hosts):
        if not approved_url(url, hosts):
            return {'status': 'forbidden', 'content': None}
        if not self.key:
            return {'status': 'not_configured', 'content': None}
        try:
            response = await self.client.post(self.URL,
                headers={'Authorization': f'Bearer {self.key}'},
                json={'urls': [url], 'extract_depth': 'basic', 'format': 'markdown',
                      'include_images': False})
            if response.status_code in (401, 403, 432, 433):
                return {'status': 'forbidden', 'content': None}
            if response.status_code == 429 or response.status_code >= 500:
                return {'status': 'temporary', 'content': None}
            if response.status_code >= 400:
                return {'status': 'invalid_response', 'content': None}
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get('results'), list) or not isinstance(data.get('failed_results'), list):
                return {'status': 'invalid_response', 'content': None}
            matches = [row for row in data['results'] if isinstance(row, dict) and row.get('url') == url]
            failed = any(isinstance(row, dict) and row.get('url') == url for row in data['failed_results'])
            if matches and failed:
                return {'status': 'invalid_response', 'content': None}
            if len(matches) != 1:
                return {'status': 'extract_failed' if failed else 'empty', 'content': None}
            content = matches[0].get('raw_content')
            if not isinstance(content, str) or not content.strip() or len(content) > 20000:
                return {'status': 'invalid_response', 'content': None}
            return {'status': 'success', 'content': content}
        except httpx.TimeoutException:
            return {'status': 'timeout', 'content': None}
        except httpx.TransportError:
            return {'status': 'network', 'content': None}
        except (ValueError, TypeError):
            return {'status': 'invalid_response', 'content': None}

    async def collect(self, place, extraction_cache=None):
        sources = self.discover(place)
        result = {'status': 'no_official_source', 'observations': [], 'claims': [],
                  'brand_menu_items': [], 'branch_menu_items': [], 'admission_prices': []}
        if not sources:
            return result
        for source in sources[:2]:
            for url in source['urls'][:2]:
                if len(result['observations']) >= 2:
                    break
                if extraction_cache is not None and url in extraction_cache:
                    checked = extraction_cache[url]
                else:
                    checked = await self.extract(url, source['hosts'])
                    if extraction_cache is not None:
                        extraction_cache[url] = checked
                now = datetime.now(timezone.utc)
                content = checked['content']
                if content and source.get('requires_branch') and not branch_identity_in_text(place, content):
                    checked = {'status': 'identity_conflict', 'content': None}
                    content = None
                scope = (EvidenceScope.branch if source.get('requires_branch') and content
                         and branch_identity_in_text(place, content)
                         else EvidenceScope.brand)
                outcome = (ToolOutcome.success if checked['status'] == 'success' else
                           ToolOutcome.forbidden if checked['status'] == 'forbidden' else
                           ToolOutcome.timeout if checked['status'] == 'timeout' else
                           ToolOutcome.identity_conflict if checked['status'] == 'identity_conflict' else
                           ToolOutcome.empty if checked['status'] in ('empty', 'extract_failed', 'not_configured') else
                           ToolOutcome.invalid_response)
                observation = SourceObservation(observation_id=uuid4(), kind=SourceKind.official_site,
                    outcome=outcome, scope=scope, amap_poi_id=place['poi_id'], url=url,
                    observed_at=now, content_sha256=hashlib.sha256(content.encode()).hexdigest() if content else None,
                    evidence_excerpt=evidence_line(content, source['field_scope']))
                record = {**observation.model_dump(mode='json'), 'source_domain': urlsplit(url).hostname,
                          'extract_status': checked['status'], 'field_scope': source['field_scope'],
                          'content_length': len(content) if content else 0}
                result['observations'].append(record)
                if not content:
                    result['status'] = checked['status']
                    continue
                result['status'] = 'success'
                items = parse_menu(content, source['category'], place['city']) if source['field_scope'] == 'menu_item' else []
                admissions = parse_admission(content) if source['field_scope'] == 'ticket_price' else []
                for item in items:
                    claim = VenueClaim(claim_id=uuid4(), observation_id=observation.observation_id,
                        field='menu_item', value=item.model_dump(), unit=None, scope=scope,
                        amap_poi_id=place['poi_id'], status=ClaimStatus.verified, observed_at=now)
                    result['claims'].append(claim.model_dump(mode='json'))
                    visible = {'claim_id': str(claim.claim_id), 'observation_id': str(observation.observation_id),
                               'name': item.name, 'category': item.category, 'price_cny': item.price_cny,
                               'source_url': url, 'observed_at': now.isoformat(), 'scope': scope.value}
                    result['branch_menu_items' if scope == EvidenceScope.branch else 'brand_menu_items'].append(visible)
                for admission in admissions:
                    claim = VenueClaim(claim_id=uuid4(), observation_id=observation.observation_id,
                        field='ticket_price', value=admission.model_dump(), unit='CNY', scope=scope,
                        amap_poi_id=place['poi_id'], status=ClaimStatus.verified, observed_at=now)
                    result['claims'].append(claim.model_dump(mode='json'))
                    result['admission_prices'].append({'claim_id': str(claim.claim_id),
                        'observation_id': str(observation.observation_id), 'description': admission.description,
                        'price_cny': admission.price_cny, 'source_url': url,
                        'observed_at': now.isoformat(), 'scope': scope.value})
        for field in ('brand_menu_items', 'branch_menu_items'):
            by_name = {}
            for item in result[field]:
                if item['price_cny'] is not None:
                    by_name.setdefault(item['name'], set()).add(item['price_cny'])
            conflicts = {name for name, prices in by_name.items() if len(prices) > 1}
            if conflicts:
                result['status'] = 'conflict'
                for item in result[field]:
                    if item['name'] in conflicts:
                        item['price_cny'] = None
                for claim in result['claims']:
                    if claim['field'] == 'menu_item' and claim['value']['name'] in conflicts:
                        claim['status'] = ClaimStatus.conflict.value
        return result
