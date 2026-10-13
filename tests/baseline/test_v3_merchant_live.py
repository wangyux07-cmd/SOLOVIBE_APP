import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from services.actions import revalidate
from domain.errors import Conflict
from services.application import Application
from services.merchant_live import MerchantLiveService, live_snapshot_current


PLACE = {'poi_id': 'B001', 'name': '授权试点店', 'city': '上海',
         'address': '测试路 1 号', 'coordinate': '121.4,31.2'}


def iso(offset):
    return (datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat()


def payload(**overrides):
    return {'branch_id': 'shop-1', 'amap_poi_id': 'B001', 'observed_at': iso(-2),
            'valid_until': iso(90), 'open_now': True, 'availability': 'available',
            **overrides}


def service(handler, **overrides):
    options = {'endpoint': 'https://merchant.example/v1/status', 'token': 'private-test-token',
               'poi_id': 'B001', 'branch_id': 'shop-1',
               'authorization_ref': 'signed-pilot-agreement',
               'grant_expires_at': iso(3600),
               'source_url': 'https://merchant.example/shop-1',
               'fields': 'open_now,availability'}
    options.update(overrides)
    return MerchantLiveService(**options, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
async def test_no_grant_never_calls_network():
    calls = 0
    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=payload())
    source = service(handler, authorization_ref='')
    assert await source.read(PLACE) is None
    assert calls == 0
    await source.close()


@pytest.mark.asyncio
async def test_branch_scoped_success_and_field_permissions():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload())
    source = service(handler, fields='open_now')
    result = await source.read(PLACE)
    assert result['info']['open_now'] is True
    assert 'availability' not in result['info']
    assert result['info']['source_url'] == 'https://merchant.example/shop-1'
    assert [claim['field'] for claim in result['evidence']['claims']] == ['open_now']
    assert calls[0].headers['Authorization'] == 'Bearer private-test-token'
    assert await source.read({**PLACE, 'poi_id': 'other'}) is None
    assert len(calls) == 1
    await source.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [
    payload(branch_id='other'), payload(amap_poi_id='other'),
    payload(observed_at=iso(-180)), payload(valid_until=iso(-1)),
    payload(open_now='yes'), payload(unexpected='schema-change'),
])
async def test_wrong_branch_stale_or_changed_contract_is_unknown(body):
    source = service(lambda _: httpx.Response(200, json=body))
    assert await source.read(PLACE) is None
    await source.close()


@pytest.mark.asyncio
async def test_expired_grant_forbidden_and_timeout_fail_closed():
    source = service(lambda _: httpx.Response(200, json=payload()), grant_expires_at=iso(-1))
    assert await source.read(PLACE) is None
    await source.close()
    source = service(lambda _: httpx.Response(403))
    assert await source.read(PLACE) is None
    await source.close()
    def timeout(_):
        raise httpx.ReadTimeout('test timeout')
    source = service(timeout)
    assert await source.read(PLACE) is None
    await source.close()


@pytest.mark.asyncio
async def test_concurrent_reads_do_not_reuse_old_available_state():
    count = 0
    def handler(_):
        nonlocal count
        count += 1
        return httpx.Response(200, json=payload(availability=(
            'available' if count == 1 else 'unavailable')))
    source = service(handler)
    first, second = await asyncio.gather(source.read(PLACE), source.read(PLACE))
    assert count == 2
    assert {first['info']['availability'], second['info']['availability']} == {
        'available', 'unavailable'}
    assert not live_snapshot_current(first['info'], second['info'])
    assert not live_snapshot_current(first['info'], None)
    assert not live_snapshot_current(first['info'], first['info'],
                                     datetime.now(timezone.utc) + timedelta(minutes=3))
    await source.close()


@pytest.mark.asyncio
async def test_confirmed_action_rechecks_merchant_before_save():
    source = service(lambda _: httpx.Response(200, json=payload(availability='unavailable')))
    advertised = payload()
    advertised.update({'status': 'verified', 'source_url': 'https://merchant.example/shop-1'})
    action = {'expires_at': datetime.now(timezone.utc) + timedelta(minutes=5),
              'kind': 'save', 'plan_snapshot': {'place': PLACE, 'live_info': advertised},
              'context_snapshot': {'constraints': {}}}
    result = await revalidate(action, maps=None, merchant_live=source)
    assert result == {'valid': False, 'reason': 'merchant_state_changed'}
    await source.close()


@pytest.mark.asyncio
async def test_cached_plan_read_hides_failed_merchant_status():
    class Repository:
        async def read(self, _owner, _thread):
            return {'plan_set': {'plans': [{
                'plan_id': 'amap:B001', 'place': PLACE,
                'live_info': {'status': 'verified', 'valid_until': iso(60),
                              'availability': 'available'}, 'unknowns': []}]}}
    class FailedMerchant:
        async def read(self, _place):
            return None
    app = Application()
    app.repo = Repository()
    app.planner = SimpleNamespace(merchant_live=FailedMerchant())
    result = await app.read_conversation('owner', 'thread')
    plan = result['plan_set']['plans'][0]
    assert plan['live_info'] is None
    assert plan['live_recheck_required'] is True
    assert '到店可用性' in plan['unknowns']


@pytest.mark.asyncio
async def test_prepare_refuses_changed_merchant_state_before_creating_action():
    advertised = {'status': 'verified', 'valid_until': iso(60),
                  'branch_id': 'shop-1', 'amap_poi_id': 'B001',
                  'source_url': 'https://merchant.example/shop-1',
                  'availability': 'available'}
    class Actions:
        created = False
        async def latest(self, *_):
            return None
        async def by_request(self, *_):
            return None
        async def plan_for_prepare(self, *_):
            return {'place': PLACE, 'live_info': advertised}
        async def prepare(self, *_):
            self.created = True
    class Repository:
        actions = Actions()
        @asynccontextmanager
        async def guard(self, *_):
            yield
    class ChangedMerchant:
        async def read(self, _place):
            return {'info': {**advertised, 'availability': 'unavailable'}}
    app = Application()
    app.repo = Repository()
    app.planner = SimpleNamespace(merchant_live=ChangedMerchant())
    with pytest.raises(Conflict) as caught:
        await app.prepare_action('owner', 'thread', 'request', 'plan-set', 'amap:B001',
                                 'save', 1)
    assert caught.value.code == 'MERCHANT_STATE_CHANGED'
    assert app.repo.actions.created is False
