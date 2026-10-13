"""Release boundary checks independent of external services."""
import pytest
from fastapi.testclient import TestClient

from config import allowed_hosts, cookie_secure, cors_origins
from main import create_app


def test_production_requires_https_explicit_host_and_secure_cookie(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('CORS_ORIGINS', 'http://example.com')
    with pytest.raises(ValueError, match='HTTPS'):
        cors_origins()
    monkeypatch.setenv('CORS_ORIGINS', 'https://example.com')
    monkeypatch.setenv('PUBLIC_HOSTS', '*')
    with pytest.raises(ValueError, match='PUBLIC_HOSTS'):
        allowed_hosts()
    monkeypatch.setenv('PUBLIC_HOSTS', 'example.com')
    monkeypatch.setenv('SESSION_COOKIE_SECURE', 'false')
    with pytest.raises(ValueError, match='SESSION_COOKIE_SECURE'):
        cookie_secure('https')
    monkeypatch.setenv('SESSION_COOKIE_SECURE', 'true')
    assert cors_origins() == ['https://example.com']
    assert allowed_hosts() == ['example.com']
    assert cookie_secure('http') is True


def test_unready_release_endpoints_return_structured_error():
    client = TestClient(create_app())
    thread = '00000000-0000-4000-8000-000000000001'
    for method, path in (('GET', f'/api/conversations/{thread}/timeline'),
                         ('GET', f'/api/conversations/{thread}/requests/{thread}'),
                         ('DELETE', f'/api/conversations/{thread}')):
        response = client.request(method, path)
        assert response.status_code == 503
        assert response.json()['error']['code'] == 'STARTING'
