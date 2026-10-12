"""Provider contract tests with controlled HTTP responses, not live API claims."""
import httpx
import json
import pytest

from domain.errors import AppError
from services.model_client import DeepSeekClient


async def client_for(handler):
    adapter = DeepSeekClient('test-key')
    await adapter.close()
    adapter.client = httpx.AsyncClient(base_url='https://api.deepseek.com',transport=httpx.MockTransport(handler))
    return adapter


@pytest.mark.asyncio
async def test_payment_failure_is_explicit_and_does_not_claim_generation():
    adapter = await client_for(lambda request:httpx.Response(402,json={'error':'payment required'}))
    try:
        with pytest.raises(AppError) as caught:
            await adapter.understand({},[],'预算50元')
        assert caught.value.code == 'MODEL_PAYMENT_REQUIRED'
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_malformed_json_is_rejected_before_state_commit():
    def handler(request):
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'not json'}}]})
    adapter = await client_for(handler)
    try:
        with pytest.raises(AppError) as caught:
            await adapter.understand({},[],'预算50元')
        assert caught.value.code == 'MODEL_OUTPUT_INVALID'
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_timeout_has_a_stable_safe_error():
    def handler(request):
        raise httpx.ReadTimeout('test-only timeout')
    adapter = await client_for(handler)
    try:
        with pytest.raises(AppError) as caught:
            await adapter.understand({},[],'预算50元')
        assert caught.value.code == 'MODEL_UNAVAILABLE'
        assert 'test-only timeout' not in caught.value.message
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_summary_contract_uses_non_thinking_json_and_rejects_truncation():
    requests = []

    def success(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {
            'content': json.dumps({'topic': 'city walk', 'preference_reasons': [],
                                   'rejected_ideas': [], 'unresolved_questions': []})}}]})

    adapter = await client_for(success)
    try:
        content, meta = await adapter.summarize_history(None, [
            {'sequence': 1, 'role': 'user', 'content': '想散步'},
            {'sequence': 2, 'role': 'assistant', 'content': '好'},
        ], 6000)
        assert content['topic'] == 'city walk'
        assert meta['actual_call'] is True
        assert requests[0]['thinking'] == {'type': 'disabled'}
    finally:
        await adapter.close()

    adapter = await client_for(lambda request: httpx.Response(200, json={
        'choices': [{'finish_reason': 'length', 'message': {'content': ''}}],
    }))
    try:
        with pytest.raises(AppError) as caught:
            await adapter.summarize_history(None, [], 6000)
        assert caught.value.code == 'SUMMARY_INVALID'
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_summary_input_limit_blocks_provider_call():
    adapter = await client_for(lambda request: (_ for _ in ()).throw(
        AssertionError('provider call must not happen')))
    try:
        with pytest.raises(AppError) as caught:
            await adapter.summarize_history(None, [], 100)
        assert caught.value.code == 'SUMMARY_INPUT_OVERFLOW'
    finally:
        await adapter.close()
