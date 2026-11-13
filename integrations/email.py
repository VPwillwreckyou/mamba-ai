"""Secure SMTP email integration for MAMBA."""
from __future__ import annotations

import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any


@dataclass(frozen=True)
class EmailDraft:
    recipient: str
    subject: str
    body: str


class EmailController:
    """Configure SMTP credentials securely, test them, and send email."""

    PASSWORD_NAME = "SMTP_EMAIL_PASSWORD"

    def __init__(
        self,
        secret_store: Any,
        settings: Any,
        *,
        security_manager: Any | None = None,
        permission_manager: Any | None = None,
    ) -> None:
        self._secrets = secret_store
        self._settings = settings
        self._security = security_manager
        self._permissions = permission_manager

    def configuration(self) -> dict[str, Any]:
        """Return saved non-secret SMTP settings for the configuration UI."""
        return {
            "smtp_host": self._settings.get("integrations.email.smtp_host", ""),
            "smtp_port": self._settings.get("integrations.email.smtp_port", 465),
            "username": self._settings.get("integrations.email.username", ""),
            "default_recipient": self._settings.get(
                "integrations.email.default_recipient", ""
            ),
            "security": self._settings.get("integrations.email.security", "ssl"),
        }

    def parse_request(self, text: str) -> EmailDraft | None:
        pattern = re.compile(
            r"^(?:please\s+)?(?:send\s+)?(?:an?\s+)?email\s+(?:to\s+)?"
            r"(?P<recipient>me|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})"
            r"\s*[,;]?\s*subject:\s*(?P<subject>.*?)\s*[,;]?\s*"
            r"(?:body|message):\s*(?P<body>.+)$",
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.fullmatch(text.strip())
        if not match:
            return None
        recipient = match.group("recipient")
        if recipient.lower() == "me":
            recipient = str(self.configuration()["default_recipient"] or "")
        return EmailDraft(
            recipient=recipient,
            subject=match.group("subject").strip(),
            body=match.group("body").strip(),
        )

    def configured(self) -> bool:
        return bool(
            self._settings.get("integrations.email.smtp_host", "")
            and self._settings.get("integrations.email.username", "")
            and self._secrets.exists(self.PASSWORD_NAME)
        )

    def configure(
        self,
        *,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        default_recipient: str,
        security: str = "ssl",
    ) -> None:
        host = smtp_host.strip()
        account = username.strip()
        recipient = default_recipient.strip()
        secret = password.strip() or self._secrets.retrieve(self.PASSWORD_NAME) or ""
        try:
            port = int(smtp_port)
        except (TypeError, ValueError):
            raise ValueError("SMTP port must be a number") from None
        if not host or any(char in host for char in "\r\n"):
            raise ValueError("Enter a valid SMTP server")
        if not 1 <= port <= 65535:
            raise ValueError("SMTP port must be between 1 and 65535")
        if not self._valid_email(account):
            raise ValueError("Enter a valid sending email address")
        if recipient and not self._valid_email(recipient):
            raise ValueError("Enter a valid default recipient email address")
        if security not in {"ssl", "starttls"}:
            raise ValueError("Choose SSL or STARTTLS security")
        if not secret:
            raise ValueError("Enter the account's app password")

        if password.strip():
            self._secrets.store(self.PASSWORD_NAME, secret)
        values = {
            "integrations.email.smtp_host": host,
            "integrations.email.smtp_port": port,
            "integrations.email.username": account,
            "integrations.email.default_recipient": recipient,
            "integrations.email.security": security,
        }
        for key, value in values.items():
            self._settings.set(key, value, save=False)
        self._settings.save()

    def remove_credentials(self) -> bool:
        removed = self._secrets.delete(self.PASSWORD_NAME)
        for key in (
            "integrations.email.smtp_host",
            "integrations.email.smtp_port",
            "integrations.email.username",
            "integrations.email.default_recipient",
            "integrations.email.security",
        ):
            self._settings.set(key, "", save=False)
        self._settings.save()
        return removed

    def test_connection(self) -> dict[str, Any]:
        password = self._secrets.retrieve(self.PASSWORD_NAME)
        if not password or not self.configured():
            return {"success": False, "error": "Configure an email account first"}
        client = None
        try:
            client = self._connect()
            client.login(self._settings.get("integrations.email.username"), password)
            return {"success": True, "detail": "SMTP connection verified"}
        except Exception as exc:
            return {"success": False, "error": self._safe_error(exc, password)}
        finally:
            if client is not None:
                try:
                    client.quit()
                except Exception:
                    pass

    def send_email(
        self,
        recipient: str,
        subject: str,
        body: str,
        *,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        if self._security is not None and not self._security.is_allowed():
            return {"success": False, "error": "Blocked by security manager"}
        if self._permissions is not None:
            outcome = self._permissions.authorize("send_email")
            if outcome == "forbidden":
                return {"success": False, "error": "Email sending is forbidden by policy"}
        if not confirmed:
            return {"success": False, "error": "Sending email requires explicit confirmation"}
        password = self._secrets.retrieve(self.PASSWORD_NAME)
        if not password or not self.configured():
            return {"success": False, "error": "Configure an email account first"}
        to_address = recipient.strip()
        if not self._valid_email(to_address):
            return {"success": False, "error": "Enter a valid recipient email address"}
        if not body.strip():
            return {"success": False, "error": "Email body cannot be empty"}
        if "\r" in subject or "\n" in subject:
            return {"success": False, "error": "Email subject contains invalid characters"}

        message = EmailMessage()
        message["From"] = self._settings.get("integrations.email.username")
        message["To"] = to_address
        message["Subject"] = subject.strip() or "Message from MAMBA"
        message.set_content(body.strip())

        client = None
        try:
            client = self._connect()
            client.login(message["From"], password)
            refused = client.send_message(message)
            if refused:
                return {"success": False, "error": "The mail server refused the recipient"}
            return {"success": True, "detail": "Email sent", "recipient": to_address}
        except Exception as exc:
            return {"success": False, "error": self._safe_error(exc, password)}
        finally:
            if client is not None:
                try:
                    client.quit()
                except Exception:
                    pass

    def _connect(self):
        host = self._settings.get("integrations.email.smtp_host")
        port = int(self._settings.get("integrations.email.smtp_port", 465))
        context = ssl.create_default_context()
        if self._settings.get("integrations.email.security", "ssl") == "ssl":
            return smtplib.SMTP_SSL(host, port, timeout=15, context=context)
        client = smtplib.SMTP(host, port, timeout=15)
        client.ehlo()
        client.starttls(context=context)
        client.ehlo()
        return client

    @staticmethod
    def _valid_email(address: str) -> bool:
        parsed = parseaddr(address)
        return parsed[1] == address and "@" in address and not any(
            char in address for char in "\r\n"
        )

    @staticmethod
    def _safe_error(error: Exception, password: str) -> str:
        detail = str(error).replace(password, "***")
        return f"Email operation failed: {detail[:240]}"