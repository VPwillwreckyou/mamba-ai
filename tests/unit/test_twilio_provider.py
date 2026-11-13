from __future__ import annotations

import asyncio
from types import SimpleNamespace

import core.twilio_provider as twilio_module
from core.twilio_provider import TwilioProvider


def test_twilio_call_uses_mamba_greeting(monkeypatch) -> None:
    captured: dict[str, str] = {}

    class FakeCalls:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(sid="CA123", status="queued")

    class FakeClient:
        def __init__(self, account_sid: str, auth_token: str) -> None:
            assert account_sid == "AC-test"
            assert auth_token == "test-token"
            self.calls = FakeCalls()

    class FakeTwilioRestException(Exception):
        pass

    monkeypatch.setattr(twilio_module, "TWILIO_AVAILABLE", True)
    monkeypatch.setattr(twilio_module, "Client", FakeClient)
    monkeypatch.setattr(twilio_module, "TwilioRestException", FakeTwilioRestException)
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC-test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+14155550123")

    result = asyncio.run(TwilioProvider().make_call("055190685"))

    assert result["success"] is True
    assert result["call_sid"] == "CA123"
    assert captured["to"] == "+37455190685"
    assert captured["from_"] == "+14155550123"
    assert "MAMBA AI" in captured["twiml"]
    assert "You asked me to call you" in captured["twiml"]