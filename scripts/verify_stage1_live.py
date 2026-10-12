"""Run explicit, real-service Stage 1 checks without printing credentials."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx


BASE = 'http://127.0.0.1:8000'


def require(response, status):
    try:
        body = response.json()
    except ValueError:
        raise AssertionError(f'HTTP {response.status_code}: non-JSON response') from None
    if response.status_code != status:
        code = body.get('error', {}).get('code', 'UNKNOWN')
        raise AssertionError(f'HTTP {response.status_code}, expected {status}: {code}')
    return body


def main():
    with httpx.Client(base_url=BASE, timeout=75) as client:
        assert require(client.get('/api/v1/readiness'), 200)['ready']
        require(client.post('/api/session'), 200)
        thread = require(client.post('/api/conversations'), 200)
        thread_id = thread['thread_id']
        assert thread['snapshot']['revision'] == 0

        message = '我在上海徐汇，今天有点累，预算80元，只有一小时。'
        request_id = str(uuid4())
        payload = {'thread_id': thread_id, 'request_id': request_id,
                   'expected_revision': 0, 'message': message}
        first = require(client.post('/api/chat', json=payload), 200)
        assert first['model']['actual_call'] is True
        assert first['snapshot']['revision'] == 1
        assert first['snapshot']['constraints']['budget_cny'] == 80
        assert first['snapshot']['constraints']['available_minutes'] == 60
        assert first['snapshot']['sources']['budget_cny']['quote'] in message
        assert first['snapshot']['sources']['available_minutes']['quote'] in message
        trace = require(client.get(f"/api/conversations/{thread_id}/runs/{first['run_id']}/trace"), 200)
        completed = [event['node'] for event in trace['events'] if event['status'] == 'completed']
        assert 'understand_context' in completed and 'persist_reply' in completed

        replay = require(client.post('/api/chat', json=payload), 200)
        assert replay['run_id'] == first['run_id']
        assert require(client.post('/api/chat', json={**payload, 'message': 'changed'}), 409)['error']['code'] == 'REQUEST_ID_REUSED'
        assert require(client.post('/api/chat', json={**payload, 'request_id': str(uuid4())}), 409)['error']['code'] == 'STALE_REVISION'

        second = require(client.post('/api/chat', json={
            'thread_id': thread_id, 'request_id': str(uuid4()),
            'expected_revision': 1, 'message': '预算改成100元。',
        }), 200)
        assert second['snapshot']['revision'] == 2
        assert second['snapshot']['constraints']['budget_cny'] == 100
        state = require(client.get(f'/api/conversations/{thread_id}'), 200)
        assert state['snapshot']['revision'] == 2
        assert len(state['messages']) == 4
        assert state['pending_run'] is None

        replica_url = os.getenv('SOLOVIBE_REPLICA_URL')
        if replica_url:
            with httpx.Client(base_url=replica_url, cookies=client.cookies, timeout=75) as replica:
                assert require(replica.get('/api/v1/readiness'), 200)['ready']
                recovered = require(replica.get(f'/api/conversations/{thread_id}'), 200)
                assert recovered['snapshot'] == state['snapshot']
                assert len(recovered['messages']) == 4
                third = require(replica.post('/api/chat', json={
                    'thread_id': thread_id, 'request_id': str(uuid4()),
                    'expected_revision': 2, 'message': '现在只有半小时。',
                }), 200)
                assert third['snapshot']['revision'] == 3
                assert third['snapshot']['constraints']['available_minutes'] == 30
                state = require(client.get(f'/api/conversations/{thread_id}'), 200)
                assert state['snapshot']['revision'] == 3
                assert len(state['messages']) == 6

        with httpx.Client(base_url=BASE, timeout=15) as stranger:
            require(stranger.post('/api/session'), 200)
            forbidden = require(stranger.get(f'/api/conversations/{thread_id}'), 404)
            assert forbidden['error']['code'] == 'NOT_FOUND'

        concurrent_thread = require(client.post('/api/conversations'), 200)['thread_id']
        def race(index):
            return client.post('/api/chat', json={
                'thread_id': concurrent_thread, 'request_id': str(uuid4()),
                'expected_revision': 0, 'message': f'预算{index * 10 + 20}元。',
            })
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(race, (1, 2)))
        assert sorted(result.status_code for result in results) == [200, 409]
        collision = next(result for result in results if result.status_code == 409)
        assert collision.json()['error']['code'] in {'THREAD_BUSY', 'STALE_REVISION'}
        concurrent_state = require(client.get(f'/api/conversations/{concurrent_thread}'), 200)
        assert concurrent_state['snapshot']['revision'] == 1
        assert len(concurrent_state['messages']) == 2

        print(json.dumps({
            'live': True, 'real_model_calls': 4 if replica_url else 3,
            'persisted_revision': state['snapshot']['revision'],
            'message_count': len(state['messages']), 'graph_nodes': completed,
            'idempotency': True, 'stale_revision': True, 'ownership_isolation': True,
            'same_thread_concurrency': True,
            'cross_process_recovery': bool(replica_url),
            'thread_id': thread_id,
        }, ensure_ascii=False))


if __name__ == '__main__':
    main()
