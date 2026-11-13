from __future__ import annotations

from email.message import EmailMessage

from integrations.email import EmailController


class FakeSettings:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get(self, key: str, default=None):
        return self.values.get(key, default)

    def set(self, key: str, value, *, save: bool = True) -> None:
        self.values[key] = value

    def save(self) -> None:
        pass


class FakeSecrets:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def store(self, name: str, value: str) -> None:
        self.values[name] = value

    def retrieve(self, name: str, *, env_fallback=None) -> str | None:
        return self.values.get(name)

    def exists(self, name: str, *, env_fallback=None) -> bool:
        return name in self.values

    def delete(self, name: str) -> bool:
        return self.values.pop(name, None) is not None


def test_configured_email_uses_tls_and_sends_message(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeSMTP:
        def __init__(self, host, port, *, timeout, context):
            captured.update(host=host, port=port, timeout=timeout, context=context)

        def login(self, username, password) -> None:
            captured.update(username=username, password=password)

        def send_message(self, message: EmailMessage) -> dict:
            captured["message"] = message
            return {}

        def quit(self) -> None:
            captured["quit"] = True

    monkeypatch.setattr("integrations.email.smtplib.SMTP_SSL", FakeSMTP)
    settings = FakeSettings()
    secrets = FakeSecrets()
    email = EmailController(secrets, settings)
    email.configure(
        smtp_host="smtp.example.com",
        smtp_port=465,
        username="sender@example.com",
        password="private-app-password",
        default_recipient="me@example.com",
    )

    result = email.send_email(
        "me@example.com", "Hello", "Test message", confirmed=True
    )

    assert result["success"] is True
    assert captured["host"] == "smtp.example.com"
    assert captured["port"] == 465
    assert captured["username"] == "sender@example.com"
    assert captured["password"] == "private-app-password"
    assert captured["message"]["To"] == "me@example.com"
    assert captured["message"]["Subject"] == "Hello"
    assert "private-app-password" not in repr(settings.values)


def test_email_rejects_invalid_recipient_before_connecting() -> None:
    settings = FakeSettings()
    secrets = FakeSecrets()
    email = EmailController(secrets, settings)
    email.configure(
        smtp_host="smtp.example.com",
        smtp_port=465,
        username="sender@example.com",
        password="private-app-password",
        default_recipient="me@example.com",
    )

    result = email.send_email(
        "not-an-email", "Hello", "Test message", confirmed=True
    )

    assert result["success"] is False
    assert result["error"] == "Enter a valid recipient email address"


def test_chat_email_request_uses_configured_default_recipient() -> None:
    settings = FakeSettings()
    email = EmailController(FakeSecrets(), settings)
    email.configure(
        smtp_host="smtp.example.com",
        smtp_port=465,
        username="sender@example.com",
        password="private-app-password",
        default_recipient="me@example.com",
    )

    draft = email.parse_request(
        "email me subject: A note body: Here is the message"
    )

    assert draft is not None
    assert draft.recipient == "me@example.com"
    assert draft.subject == "A note"
    assert draft.body == "Here is the message"


def test_email_send_requires_confirmation(monkeypatch) -> None:
    class ConfirmationRequired:
        def authorize(self, action: str) -> str:
            assert action == "send_email"
            return "confirmation_required"

    settings = FakeSettings()
    email = EmailController(
        FakeSecrets(), settings, permission_manager=ConfirmationRequired()
    )
    email.configure(
        smtp_host="smtp.example.com",
        smtp_port=465,
        username="sender@example.com",
        password="private-app-password",
        default_recipient="me@example.com",
    )
    monkeypatch.setattr(
        email, "_connect", lambda: (_ for _ in ()).throw(AssertionError("sent"))
    )

    result = email.send_email("me@example.com", "Hello", "Test")

    assert result["success"] is False
    assert result["error"] == "Sending email requires explicit confirmation"