"""Offer contracts and confirmation gates, with external calls isolated."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from services.actions import revalidate
from services.offer_policy import SHANGHAI_TZ, parse_offers
from services.planning import schedule_evidence
from services.planning import Planner
from domain.context import Constraints, ContextSnapshot
from services.public_sources import OfficialEvidenceService


PLACE = {'poi_id': 'B001', 'name': '样例面馆(美罗城店)',
         'address': '肇嘉浜路1111号', 'city': '上海市',
         'coordinate': '121.436000,31.194000'}
URL = 'https://official.example/metrocity-offer'
CATALOG = ({'brand': '样例面馆', 'hosts': ('official.example',), 'urls': (URL,),
            'field_scope': 'offer', 'category': 'food', 'requires_branch': True,
            'branch_poi_id': 'B001'},)


def page(*, branch=PLACE['name'], price='￥38元', terms='仅堂食，不与其他优惠同享',
         dates=None, apply=None):
    today = datetime.now(SHANGHAI_TZ).date()
    dates = dates or f'{today - timedelta(days=1)} 至 {today + timedelta(days=2)}'
    return (f'{PLACE["name"]} {PLACE["address"]}\n### 午餐套餐\n'
            f'套餐价：{price}\n适用门店：{apply or branch}\n'
            f'使用条件：{terms}\n有效期：{dates}')


@pytest.mark.asyncio
async def test_valid_branch_offer_has_terms_expiry_and_known_option_budget():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={'results': [{'url': URL, 'raw_content': page()}], 'failed_results': []})))
    result = await OfficialEvidenceService('key', client, CATALOG).collect(PLACE)
    assert result['status'] == 'success'
    assert len(result['offers']) == len(result['claims']) == 1
    assert result['claims'][0]['field'] == 'offer'
    assert result['claims'][0]['scope'] == 'branch'
    assert result['claims'][0]['valid_until']
    assert result['offers'][0]['price_cny'] == 38
    assert result['offers'][0]['budget_option'] == 'unknown'
    await client.aclose()


def test_incomplete_wrong_branch_or_invalid_date_is_not_an_offer():
    assert not parse_offers(page(terms='').replace('使用条件：\n', ''), PLACE)
    assert not parse_offers(page(apply='样例面馆(南京路店)'), PLACE)
    assert not parse_offers(page(price='约38元'), PLACE)
    assert not parse_offers(page(dates='2026-12-31 至 2026-01-01'), PLACE)


@pytest.mark.asyncio
async def test_expired_offer_is_not_persisted_as_verified_claim():
    content = page(dates='2025-01-01 至 2025-01-02')
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={'results': [{'url': URL, 'raw_content': content}], 'failed_results': []})))
    result = await OfficialEvidenceService('key', client, CATALOG).collect(PLACE)
    assert result['status'] == 'success'
    assert result['offers'] == result['claims'] == []
    assert result['observations'][0]['outcome'] == 'success'
    await client.aclose()


@pytest.mark.asyncio
async def test_wrong_poi_catalog_does_not_discover_offer():
    result = await OfficialEvidenceService('key', catalog=CATALOG).collect({**PLACE, 'poi_id': 'B002'})
    assert result['status'] == 'no_official_source'


@pytest.mark.asyncio
async def test_offer_is_rechecked_before_confirmed_save_and_price_change_invalidates():
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    offer = {'description': '午餐套餐', 'price_cny': 38, 'terms': '仅堂食',
             'applies_to': PLACE['name'], 'valid_until': expires.isoformat(),
             'source_url': URL}
    action = {'expires_at': expires, 'kind': 'save', 'plan_snapshot': {
        'place': PLACE, 'public_info': {'offers': [offer]}}, 'context_snapshot': {'constraints': {}}}
    class Public:
        def __init__(self, offer_price):
            self.offer_price = offer_price
        async def collect(self, place):
            return {'status': 'success', 'offers': [{**offer, 'price_cny': self.offer_price}]}
    assert (await revalidate(action, None, Public(38)))['valid'] is True
    assert (await revalidate(action, None, Public(42)))['reason'] == 'offer_changed'
    assert (await revalidate(action, None, None))['reason'] == 'offer_source_unavailable'


def test_recorded_hours_only_produce_a_schedule_inference():
    now = datetime(2026, 10, 13, 4, tzinfo=timezone.utc)
    result = schedule_evidence({'recorded_today_hours': '09:00-18:00',
                                'observed_at': now.isoformat()}, now)
    assert result['kind'] == 'recorded_schedule'
    assert result['inference'] == 'possibly_within_recorded_hours'
    assert result['open_now'] == 'unknown'
    assert schedule_evidence({'recorded_today_hours': '以门店为准'}, now)['inference'] == 'unknown'


def test_budget_refers_to_one_verified_offer_never_the_whole_activity():
    expiry = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    offer = {'claim_id': 'C1', 'price_cny': 38, 'budget_option': 'within_limit',
             'valid_until': expiry}
    place = {**PLACE, 'provider': 'amap', 'category': '餐饮', 'source_url': URL,
             'observed_at': datetime.now(timezone.utc).isoformat(),
             'route': {'walking_minutes': 5, 'distance_meters': 300},
             'return_route': {'walking_minutes': 5, 'distance_meters': 300},
             'web_status': 'empty', 'web_sources': [], 'facts': {'average_cost_cny': 25},
             'public_info': {'offers': [offer]}}
    snapshot = ContextSnapshot(constraints=Constraints(city='上海市', location_text='徐家汇',
        budget_cny=50, available_minutes=90, desired_dwell_minutes=30))
    plan = Planner(None).publish(snapshot, [place], {'status': 'success', 'errors': []})['plans'][0]
    assert plan['budget_option'] == 'known_offer_within_limit'
    assert plan['feasibility_checks']['budget'] == 'unknown'
    place['public_info'] = {'offers': []}
    assert Planner(None).publish(snapshot, [place], {'status': 'success', 'errors': []})['plans'][0]['budget_option'] == 'unknown'
