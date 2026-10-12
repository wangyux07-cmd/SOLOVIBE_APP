"""The baseline must start without keys and never claim provider success."""

import socket

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from config import configuration_status
from data_types import SoloIndexDimensions, ThreadState, ThreadStatus
from main import create_app

PROVIDER_VARS = (
    "DEEPSEEK_API_KEY", "AMAP_API_KEY", "TAVILY_API_KEY", "SERPER_API_KEY",
    "SUPABASE_URL", "SUPABASE_KEY", "DATABASE_URL",
)


@pytest.fixture
def client(monkeypatch):
    for name in PROVIDER_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    with TestClient(create_app()) as client:
        yield client


def test_liveness_does_not_claim_application_or_provider_readiness(client, monkeypatch):
    def fail_network(*args, **kwargs):
        raise AssertionError("Baseline checks must not call external services")

    monkeypatch.setattr(socket.socket, "connect", fail_network)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["ready"] is False
    assert all(not item["configured"] for item in response.json()["services"].values())
    assert client.get("/api/v1/readiness").status_code == 503


def test_configured_key_is_neither_verified_nor_exposed(client, monkeypatch):
    marker = "test-only-secret-never-a-real-credential"
    monkeypatch.setenv("DEEPSEEK_API_KEY", marker)
    response = client.get("/api/v1/config-status")
    assert marker not in response.text
    assert response.json()["services"]["model"] == {
        "configured": True, "verification": "not_checked",
    }
    assert client.get("/api/v1/health").json()["ready"] is False


@pytest.mark.parametrize("path", ["/api/v1/stream_chat", "/api/v1/threads/test/resume"])
def test_unimplemented_actions_do_not_produce_mock_success(client, path):
    response = client.post(path, json={"message": "附近有没有单人套餐？"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "FEATURE_NOT_IMPLEMENTED"
    assert "response" not in response.json()
    assert "plans" not in response.json()


@pytest.mark.parametrize("message", ["", "   ", "a" * 8001])
def test_invalid_input_rejected(client, message):
    assert client.post("/api/chat", json={"message": message}).status_code == 422


def test_chat_has_a_strict_contract_and_fails_closed_without_database(client):
    body = {
        "message": "预算 50 元", "thread_id": "a2a390be-9b6b-49e6-ab59-1a95e0e463f3",
        "request_id": "388d47bc-0db6-4ee5-8c25-2196a64003be", "expected_revision": 0,
    }
    assert client.post('/api/chat', json={**body,'owner_id':'forged'}).status_code == 422
    response = client.post('/api/chat',json=body)
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'DATABASE_NOT_CONFIGURED'
    assert 'response' not in response.json()


def test_legacy_plan_endpoint_cannot_return_synthetic_shops(client):
    response = client.get("/api/v2/wander-plans")
    assert response.status_code == 503
    assert "data" not in response.json()


def test_cors_only_allows_declared_frontend(client):
    headers = {"Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "POST"}
    response = client.options("/api/chat", headers=headers)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == headers["Origin"]
    headers["Origin"] = "https://unrelated.example"
    response = client.options("/api/chat", headers=headers)
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_database_requires_checkpoint_connection_and_unknown_dimensions_stay_unknown(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_KEY", "test-only")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert configuration_status()["database"]["configured"] is False
    assert all(value is None for value in SoloIndexDimensions().model_dump().values())
    with pytest.raises(ValidationError):
        SoloIndexDimensions(safety_rating=8)
    first = ThreadState(thread_id="a", status=ThreadStatus.ACTIVE)
    second = ThreadState(thread_id="b", status=ThreadStatus.ACTIVE)
    first.messages.append({"content": "private"})
    assert second.messages == []
