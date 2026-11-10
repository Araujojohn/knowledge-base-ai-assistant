from fastapi.testclient import TestClient
from api import app, limiter
import pytest


client = TestClient(app)


def test_apihealth():
    response = client.get("/health")
    assert response.status_code == 200, "Status code not 200"
    assert response.json() == {"message": "API Healthy and Working"}


@pytest.fixture
def secrets_set(monkeypatch):
    """Known secrets, and a clean rate-limit count before and after each test."""
    monkeypatch.setenv("CHAT_API_SECRET", "right-secret")
    monkeypatch.setenv("FRONTEND_PASSWORD", "right-password")
    limiter.reset()
    yield
    limiter.reset()


CHAT_BODY = {"message": "hi", "reply_to": "123"}


def test_wrong_chat_secret_counts_toward_the_rate_limit(secrets_set):
    answers = [
        client.post(
            "/chat", json=CHAT_BODY, headers={"X-Chat-Secret": "wrong"}
        ).status_code
        for _ in range(11)
    ]
    assert answers == [401] * 10 + [429]


def test_wrong_page_password_counts_toward_the_rate_limit(secrets_set):
    answers = [
        client.get("/mnemosyne", auth=("john", "wrong")).status_code for _ in range(11)
    ]
    assert answers == [401] * 10 + [429]


def test_each_route_has_its_own_limit(secrets_set):
    for _ in range(10):
        client.get("/mnemosyne", auth=("john", "wrong"))
    assert client.get("/mnemosyne/app.js", auth=("john", "wrong")).status_code == 401


def test_secret_with_non_ascii_character_is_refused_without_crashing(secrets_set):
    # HTTP headers travel as latin-1 bytes: b"\xe9" is "é"
    response = client.post(
        "/chat", json=CHAT_BODY, headers={"X-Chat-Secret": b"wr\xe9ng"}
    )
    assert response.status_code == 401
    assert client.get("/mnemosyne", auth=("john", "wréng")).status_code == 401


def test_right_page_password_still_opens_the_widget(secrets_set):
    response = client.get("/mnemosyne", auth=("john", "right-password"))
    assert response.status_code == 200
