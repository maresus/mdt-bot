from __future__ import annotations

from app.services import sms_service


class _Resp:
    def __init__(self, status_code: int = 200, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_smsapi_send_success(monkeypatch):
    monkeypatch.setattr(sms_service, "SMS_MOCK_MODE", False)
    monkeypatch.setattr(sms_service, "SMS_PROVIDER", "smsapi")
    monkeypatch.setattr(sms_service, "SMSAPI_OAUTH_TOKEN", "token-123")
    monkeypatch.setattr(sms_service, "SMSAPI_BASE_URL", "https://api.smsapi.com")
    monkeypatch.setattr(sms_service, "SMSAPI_SENDER", "")

    captured = {}

    def _fake_post(url, data=None, headers=None, timeout=None):
        captured["url"] = url
        captured["data"] = data or {}
        captured["headers"] = headers or {}
        return _Resp(status_code=200, payload=[{"id": "abc123"}])

    monkeypatch.setattr(sms_service.requests, "post", _fake_post)

    result = sms_service.send_sms("040111222", "Test sporocilo")

    assert result.get("success") is True
    assert result.get("provider") == "smsapi"
    assert result.get("message_sid") == "abc123"
    assert captured["url"].endswith("/sms.do")
    assert captured["headers"].get("Authorization", "").startswith("Bearer ")
    assert captured["data"].get("to") == "38640111222"


def test_smsapi_send_http_error(monkeypatch):
    monkeypatch.setattr(sms_service, "SMS_MOCK_MODE", False)
    monkeypatch.setattr(sms_service, "SMS_PROVIDER", "smsapi")
    monkeypatch.setattr(sms_service, "SMSAPI_OAUTH_TOKEN", "token-123")

    def _fake_post(url, data=None, headers=None, timeout=None):
        return _Resp(status_code=400, text="ERROR: invalid")

    monkeypatch.setattr(sms_service.requests, "post", _fake_post)

    result = sms_service.send_sms("040111222", "Test sporocilo")

    assert result.get("success") is False
    assert "SMSAPI HTTP 400" in (result.get("error") or "")
