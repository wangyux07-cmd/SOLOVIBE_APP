"""Provider contract tests with controlled HTTP responses, not live API claims."""
import httpx
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
