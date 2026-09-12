"""Offline tests for the Slack credential, origin, and HTTP boundaries."""

import io
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from backend.slack_client import SlackAPIError, SlackClient, SlackConfig, _NoRedirect


TOKEN = "xoxb-offline-test-token"
SECRET = "offline-signing-secret-never-real-000000"
HOOK = "https://hooks.slack.com/commands/TTEST/opaque-response-secret"


@pytest.fixture
def configured_env(monkeypatch):
    values = {
        "SLACK_BOT_TOKEN": TOKEN,
        "SLACK_SIGNING_SECRET": SECRET,
        "SLACK_TEAM_ID": "TTEST123",
        "SLACK_APP_ID": "ATEST123",
        "SLACK_PUBLIC_BASE_URL": "https://consensus.test",
        "SLACK_HISTORY_RETENTION_DAYS": "90",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values


def test_config_loads_valid_settings_and_default_retention(configured_env, monkeypatch):
    monkeypatch.delenv("SLACK_HISTORY_RETENTION_DAYS")
    config = SlackConfig.from_env()
    assert config.bot_token == TOKEN
    assert config.signing_secret == SECRET
    assert config.team_id == "TTEST123"
    assert config.app_id == "ATEST123"
    assert config.public_base_url == "https://consensus.test"
    assert config.retention_days == 90


@pytest.mark.parametrize("key", ["BOT_TOKEN", "SIGNING_SECRET", "TEAM_ID", "APP_ID", "PUBLIC_BASE_URL"])
def test_missing_required_configuration_fails_without_exposing_credentials(configured_env, monkeypatch, key):
    monkeypatch.delenv(f"SLACK_{key}")
    with pytest.raises(ValueError) as exc:
        SlackConfig.from_env()
    assert TOKEN not in str(exc.value) and SECRET not in str(exc.value)


@pytest.mark.parametrize(("key", "value"), [
    ("BOT_TOKEN", "xoxp-user-token"),
    ("SIGNING_SECRET", "too-short"),
    ("TEAM_ID", "ATEST123"),
    ("TEAM_ID", "TTEST/other"),
    ("APP_ID", "TTEST123"),
    ("APP_ID", "ATEST?other"),
    ("HISTORY_RETENTION_DAYS", "6"),
    ("HISTORY_RETENTION_DAYS", "366"),
    ("HISTORY_RETENTION_DAYS", "forever"),
])
def test_invalid_config_values_fail(configured_env, monkeypatch, key, value):
    monkeypatch.setenv(f"SLACK_{key}", value)
    with pytest.raises(ValueError):
        SlackConfig.from_env()


@pytest.mark.parametrize("days", [7, 365])
def test_config_accepts_retention_boundaries(configured_env, monkeypatch, days):
    monkeypatch.setenv("SLACK_HISTORY_RETENTION_DAYS", str(days))
    assert SlackConfig.from_env().retention_days == days


@pytest.mark.parametrize(("origin", "normalized"), [
    (" https://consensus.test/ ", "https://consensus.test"),
    ("https://consensus.test:8443", "https://consensus.test:8443"),
    ("http://localhost:8080", "http://localhost:8080"),
    ("http://127.0.0.1:8080", "http://127.0.0.1:8080"),
    ("http://[::1]:8080", "http://[::1]:8080"),
])
def test_config_accepts_https_and_loopback_origins(configured_env, monkeypatch, origin, normalized):
    monkeypatch.setenv("SLACK_PUBLIC_BASE_URL", origin)
    assert SlackConfig.from_env().public_base_url == normalized


@pytest.mark.parametrize("origin", [
    "http://consensus.test", "ftp://consensus.test", "https:///",
    "http://localhost.evil.test", "https://consensus.test/app",
    "https://consensus.test?account=other", "https://consensus.test#section",
    "https://user:password@consensus.test", "https://consensus.test:bad",
    "https://consensus.test:99999",
])
def test_config_rejects_non_origin_or_invalid_public_urls(configured_env, monkeypatch, origin):
    monkeypatch.setenv("SLACK_PUBLIC_BASE_URL", origin)
    with pytest.raises(ValueError):
        SlackConfig.from_env()


class FakeResponse:
    def __init__(self, body):
        self.body = body
        self.read_limits = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def read(self, limit):
        self.read_limits.append(limit)
        return self.body[:limit]


class FakeOpener:
    def __init__(self, body=b'{"ok":true}', error=None):
        self.response = FakeResponse(body)
        self.error = error
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error is not None:
            raise self.error
        return self.response


def _client(body=b'{"ok":true}', error=None):
    client = SlackClient(TOKEN)
    opener = FakeOpener(body, error)
    client._opener = opener
    return client, opener


@pytest.mark.parametrize("method", ["views.open", "views.update", "chat.postMessage", "chat.postEphemeral"])
def test_allowed_api_calls_use_fixed_slack_url_and_bearer_header(method):
    client, opener = _client(b'{"ok":true,"view":{"id":"VTEST"}}')
    payload = {"text": "한글 질문 <!channel>", "view": {"type": "modal"}}
    result = client.call(method, payload)
    request, timeout = opener.requests[0]
    assert request.full_url == f"https://slack.com/api/{method}"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    assert request.get_header("Content-type") == "application/json; charset=utf-8"
    assert json.loads(request.data) == payload
    assert timeout == 2
    assert result == {"ok": True, "view": {"id": "VTEST"}}
    assert opener.response.closed


@pytest.mark.parametrize("method", [
    "users.list", "admin.users.remove", "https://other.test/api", "../views.open", "views.open?url=other",
])
def test_unapproved_api_methods_fail_before_http(method):
    client, opener = _client()
    with pytest.raises(ValueError, match="unsupported Slack API method"):
        client.call(method, {})
    assert opener.requests == []


@pytest.mark.parametrize("response_url", [HOOK, "https://hooks.slack.com:443/services/TTEST/BTEST/opaque"])
def test_response_url_is_ephemeral_and_never_receives_bot_authorization(response_url):
    client, opener = _client(b"ok\n")
    result = client.respond(response_url, {"text": "완료"})
    request, timeout = opener.requests[0]
    assert request.full_url == response_url
    assert request.get_header("Authorization") is None
    assert TOKEN.encode() not in request.data
    assert json.loads(request.data) == {"response_type": "ephemeral", "replace_original": False, "text": "완료"}
    assert timeout == 2
    assert result == {"ok": True}


@pytest.mark.parametrize("response_url", [
    "http://hooks.slack.com/commands/TTEST/secret",
    "https://hooks.slack.com.evil.test/commands/TTEST/secret",
    "https://evil.test/commands/TTEST/secret",
    "https://hooks.slack.com:8443/commands/TTEST/secret",
    "https://user:password@hooks.slack.com/commands/TTEST/secret",
    "https://hooks.slack.com/commands/TTEST/secret?query=extra",
    "https://hooks.slack.com/commands/TTEST/secret#extra",
    "https://hooks.slack.com/api/chat.postMessage",
    "https://hooks.slack.com:bad/commands/TTEST/secret",
])
def test_untrusted_response_urls_fail_closed_before_http(response_url):
    client, opener = _client()
    with pytest.raises(SlackAPIError, match="invalid_response_url") as exc:
        client.respond(response_url, {"text": "result"})
    assert "secret" not in str(exc.value)
    assert opener.requests == []


@pytest.mark.parametrize("body", [
    b'{"ok":false,"error":"private-response-detail"}',
    b'{"error":"private-response-detail"}', b"[]", b"null", b"42", b'"ok"',
])
def test_authenticated_api_rejects_failed_or_non_object_json_without_payload_leak(body):
    client, _ = _client(body)
    with pytest.raises(SlackAPIError, match="slack_rejected_request") as exc:
        client.call("views.open", {})
    assert "private-response-detail" not in str(exc.value)


def test_response_url_accepts_success_json():
    client, _ = _client(b'{"ok":true}')
    assert client.respond(HOOK, {"text": "result"}) == {"ok": True}


def test_response_url_rejects_explicit_slack_error():
    client, _ = _client(b'{"ok":false,"error":"private-response-detail"}')
    with pytest.raises(SlackAPIError, match="slack_rejected_request"):
        client.respond(HOOK, {"text": "result"})


@pytest.mark.parametrize("body", [b"not-json-private-response", b"\xff\xfe", b""])
def test_invalid_response_bytes_become_sanitized_errors(body):
    client, _ = _client(body)
    with pytest.raises(SlackAPIError) as exc:
        client.call("views.open", {})
    assert str(exc.value) in {"JSONDecodeError", "UnicodeDecodeError"}
    assert "private-response" not in str(exc.value)


def test_response_size_limit_does_not_read_unbounded_body():
    client, opener = _client(b"x" * 2_000_000)
    with pytest.raises(SlackAPIError, match="response_too_large"):
        client.call("views.open", {})
    assert opener.response.read_limits == [1_000_001]
    assert opener.response.closed


@pytest.mark.parametrize("error", [TimeoutError("private-timeout-detail"), URLError("private-network-detail"), OSError("private-os-detail")])
def test_network_failures_have_only_error_type(error):
    client, _ = _client(error=error)
    with pytest.raises(SlackAPIError) as exc:
        client.call("views.open", {})
    assert str(exc.value) == type(error).__name__
    assert "private" not in str(exc.value)


@pytest.mark.parametrize("status", [302, 403, 429, 500])
def test_http_errors_do_not_expose_url_body_or_credentials(status):
    error = HTTPError(HOOK, status, "private-error-message", {}, io.BytesIO(b"private-body"))
    client, _ = _client(error=error)
    with pytest.raises(SlackAPIError, match=f"^http_{status}$") as exc:
        client.respond(HOOK, {"text": "result"})
    assert "private" not in str(exc.value) and "opaque" not in str(exc.value)


def test_http_opener_redirect_policy_refuses_to_forward_credentials():
    client = SlackClient(TOKEN)
    handler = next(handler for handler in client._opener.handlers if isinstance(handler, _NoRedirect))
    request = Request("https://slack.com/api/views.open", data=b"{}", headers={"Authorization": f"Bearer {TOKEN}"})
    for destination in ["https://other.test/collect", "https://slack.com/another-path"]:
        assert handler.redirect_request(request, None, 302, "Found", {}, destination) is None
        with pytest.raises(HTTPError) as exc:
            client._opener.error("http", request, io.BytesIO(b"redirect"), 302, "Found", {"location": destination})
        assert exc.value.code == 302
