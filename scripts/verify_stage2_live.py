"""Opt-in real model/database compaction check against a low-budget backend."""
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import config  # noqa: F401 - loads ignored local configuration
from services.application import database_dsn, make_pool


def accepted(response, status=200):
    data = response.json()
    if response.status_code != status:
        raise AssertionError(f'HTTP {response.status_code}: {data.get("error", {}).get("code", "unknown")}')
    return data


async def main():
    base = os.getenv('SOLOVIBE_BASE_URL', 'http://127.0.0.1:8001')
    async with httpx.AsyncClient(base_url=base, timeout=75) as client:
        assert accepted(await client.get('/api/v1/readiness'))['ready']
        accepted(await client.post('/api/session'))
        thread = accepted(await client.post('/api/conversations'))['thread_id']
        revision = 0
        retries = 0
        for index in range(8):
            if index == 0:
                message = '预算50元。我想独自出去散步，慢慢找一个安静的地方。'
            elif index == 1:
                message = '预算改成80元。希望这次出行仍然轻松，没有拥挤的人群。'
            else:
                message = f'第{index}次补充：' + '我想慢慢考虑这次独自出行的氛围，安静地走走并看看城市里的细节。' * 3
            response = await client.post('/api/chat', json={
                'thread_id': thread, 'request_id': str(uuid4()),
                'expected_revision': revision, 'message': message,
            })
            if response.status_code != 200:
                for _ in range(2):
                    pending = accepted(await client.get(f'/api/conversations/{thread}'))['pending_run']
                    if not pending:
                        break
                    retries += 1
                    response = await client.post(
                        f"/api/conversations/{thread}/runs/{pending['run_id']}/retry")
                    if response.status_code == 200:
                        break
            if response.status_code != 200:
                raise AssertionError(f'turn {index}: HTTP {response.status_code}, {response.json().get("error", {}).get("code")}')
            result = response.json()
            assert result['model']['actual_call'] is True
            revision = result['snapshot']['revision']
        conversation = accepted(await client.get(f'/api/conversations/{thread}'))
        assert conversation['snapshot']['constraints']['budget_cny'] == 80
        assert len(conversation['messages']) == 16
        assert conversation['pending_run'] is None
        assert conversation['context_memory']['summary_revision'] >= 1

        # A separate process reads the persisted summary, then a new explicit
        # correction must win over both the old narrative and prior snapshot.
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8000',
                                     cookies=client.cookies, timeout=75) as replica:
            recovered = accepted(await replica.get(f'/api/conversations/{thread}'))
            assert recovered['context_memory']['summary_revision'] >= 1
            updated = accepted(await replica.post('/api/chat', json={
                'thread_id': thread, 'request_id': str(uuid4()),
                'expected_revision': revision, 'message': '预算现在改成90元。',
            }))
            assert updated['snapshot']['constraints']['budget_cny'] == 90
            conversation = accepted(await client.get(f'/api/conversations/{thread}'))
            assert conversation['snapshot']['constraints']['budget_cny'] == 90
            assert len(conversation['messages']) == 18

    pool = make_pool(database_dsn())
    async with pool:
        async with pool.connection() as conn:
            summary = await (await conn.execute('''
                SELECT revision,covered_until_sequence,source_digest,content,
                       based_on_context_revision FROM solovibe_v1.rolling_summaries
                WHERE thread_id=%s
            ''', (thread,))).fetchone()
    assert summary is not None, 'Soft budget did not trigger compaction'
    assert summary['revision'] >= 1
    assert 0 < summary['covered_until_sequence'] <= 8
    assert len(summary['source_digest']) == 64
    print(json.dumps({'live_compaction': True, 'model_turns': 9, 'run_retries': retries,
                      'summary_revision': summary['revision'],
                      'covered_until_sequence': summary['covered_until_sequence'],
                      'retained_raw_messages': len(conversation['messages']),
                      'authoritative_budget_cny': conversation['snapshot']['constraints']['budget_cny'],
                      'cross_process_summary_recovery': True,
                      'thread_id': thread}, ensure_ascii=False))


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
