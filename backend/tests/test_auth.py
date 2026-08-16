from fastapi.testclient import TestClient
import pytest

import backend.auth as auth
import backend.main as main
from backend.main import app, room_analysis_locks, rooms
from backend.models import AuthUser


TEST_SECRET = "test-session-secret-that-is-at-least-32-characters"


@pytest.fixture(autouse=True)
def clear_auth_environment(monkeypatch: pytest.MonkeyPatch):
    rooms.clear()
    room_analysis_locks.clear()
    for name in (
        "GOOGLE_CLIENT_ID",
        "SESSION_SECRET",
        "SESSION_COOKIE_SECURE",
        "SESSION_TTL_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
    rooms.clear()
    room_analysis_locks.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def verified_user() -> AuthUser:
    return AuthUser(
        google_sub="google-user-123",
        email="member@example.com",
        name="테스트 멤버",
        picture="https://example.com/avatar.png",
    )


def test_auth_config_is_disabled_until_both_server_values_exist(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    assert client.get("/api/auth/config").json() == {
        "enabled": False,
        "client_id": None,
    }

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "web-client.apps.googleusercontent.com")
    assert client.get("/api/auth/config").json() == {
        "enabled": False,
        "client_id": "web-client.apps.googleusercontent.com",
    }

    monkeypatch.setenv("SESSION_SECRET", TEST_SECRET)
    assert client.get("/api/auth/config").json()["enabled"] is True


def test_google_login_sets_signed_httponly_session_and_me_reads_it(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "web-client.apps.googleusercontent.com")
    monkeypatch.setenv("SESSION_SECRET", TEST_SECRET)
    monkeypatch.setattr(main, "verify_google_credential", lambda _token: verified_user())

    response = client.post("/api/auth/google", json={"credential": "signed-google-token"})

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["user"]["google_sub"] == "google-user-123"
    set_cookie = response.headers["set-cookie"].lower()
    assert "consensus_session=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie

    current = client.get("/api/auth/me")
    assert current.status_code == 200
    assert current.json()["user"]["email"] == "member@example.com"


def test_logout_removes_the_session_cookie(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "web-client.apps.googleusercontent.com")
    monkeypatch.setenv("SESSION_SECRET", TEST_SECRET)
    monkeypatch.setattr(main, "verify_google_credential", lambda _token: verified_user())
    client.post("/api/auth/google", json={"credential": "signed-google-token"})

    response = client.post("/api/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert client.get("/api/auth/me").json() == {
        "authenticated": False,
        "user": None,
    }


def test_named_room_creation_requires_an_authenticated_session(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    payload = {
        "question": "어떤 안을 선택할까요?",
        "options": ["A", "B"],
        "criteria": ["가치"],
        "submission_mode": "named",
    }

    unauthenticated = client.post("/api/rooms", json=payload)

    monkeypatch.setenv("SESSION_SECRET", TEST_SECRET)
    client.cookies.set(
        auth.SESSION_COOKIE_NAME,
        auth.create_session_token(verified_user()),
    )
    authenticated = client.post("/api/rooms", json=payload)

    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["detail"] == (
        "authentication is required to create named rooms"
    )
    assert authenticated.status_code == 201
    assert authenticated.json()["submission_mode"] == "named"


def test_invalid_google_token_is_rejected_without_a_cookie(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "web-client.apps.googleusercontent.com")
    monkeypatch.setenv("SESSION_SECRET", TEST_SECRET)

    def reject(_token: str):
        raise main.InvalidGoogleCredential("invalid Google ID token")

    monkeypatch.setattr(main, "verify_google_credential", reject)

    response = client.post("/api/auth/google", json={"credential": "invalid"})

    assert response.status_code == 401
    assert "consensus_session" not in response.cookies


def test_login_reports_incomplete_server_configuration(client: TestClient):
    response = client.post("/api/auth/google", json={"credential": "anything"})

    assert response.status_code == 503
    assert response.json()["detail"] == "GOOGLE_CLIENT_ID is not configured"


def test_tampered_and_expired_session_tokens_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SESSION_SECRET", TEST_SECRET)
    token = auth.create_session_token(verified_user(), now=1_000)

    assert auth.read_session_token(token, now=1_001) == verified_user()
    assert auth.read_session_token(f"{token}x", now=1_001) is None
    assert auth.read_session_token(token, now=1_000 + auth.DEFAULT_SESSION_TTL_SECONDS) is None


def test_google_verifier_uses_configured_audience_and_verified_claims(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "web-client.apps.googleusercontent.com")
    captured: dict[str, str] = {}

    def fake_verify(token, _request, audience):
        captured.update(token=token, audience=audience)
        return {
            "sub": "stable-google-id",
            "email": "verified@gmail.com",
            "email_verified": True,
            "name": "Verified User",
        }

    monkeypatch.setattr(auth.id_token, "verify_oauth2_token", fake_verify)

    user = auth.verify_google_credential("google-jwt")

    assert captured == {
        "token": "google-jwt",
        "audience": "web-client.apps.googleusercontent.com",
    }
    assert user.google_sub == "stable-google-id"


def test_google_verifier_rejects_unverified_email(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "web-client.apps.googleusercontent.com")
    monkeypatch.setattr(
        auth.id_token,
        "verify_oauth2_token",
        lambda *_args: {
            "sub": "stable-google-id",
            "email": "unverified@example.com",
            "email_verified": False,
        },
    )

    with pytest.raises(auth.InvalidGoogleCredential, match="not verified"):
        auth.verify_google_credential("google-jwt")
