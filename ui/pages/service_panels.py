"""Interactive panels for Spotify, Discord, and browser services."""
from __future__ import annotations

import html
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QTextBrowser,
    QTextEdit,
    QWidget,
)

from integrations.discord import DiscordController
from integrations.email import EmailController
from integrations.spotify import SpotifyController
from ui import theme
from ui.pages.common import GlassCard, StateLabel, make_button, make_label
from web.browser import BrowserController
from web.search import WebSearch


class ServiceWorker(QThread):
    completed = Signal(object)

    def __init__(self, operation: Callable[[], dict[str, Any]]) -> None:
        super().__init__()
        self._operation = operation

    def run(self) -> None:
        try:
            result = self._operation()
        except Exception as exc:
            result = {"success": False, "error": str(exc)}
        self.completed.emit(result)


class SpotifyPanel(GlassCard):
    def __init__(self, controller: SpotifyController,
                 parent: QWidget | None = None) -> None:
        super().__init__("SPOTIFY CONTROLS", parent)
        self._controller = controller
        self.status = StateLabel("READY", "idle")
        self.body.addWidget(self.status)
        row = QHBoxLayout()
        for text, action in (("PREVIOUS", "previous"), ("PLAY / PAUSE", "play_pause"),
                             ("NEXT", "next"), ("VOL -", "volume_down"),
                             ("VOL +", "volume_up")):
            button = make_button(text, kind="ghost")
            button.clicked.connect(lambda _checked=False, value=action: self._control(value))
            row.addWidget(button)
        self.body.addLayout(row)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Track, artist, or album")
        self.search_input.setStyleSheet(theme.input_style())
        search_row.addWidget(self.search_input, 1)
        search_button = make_button("SEARCH SPOTIFY")
        search_button.clicked.connect(self._search)
        search_row.addWidget(search_button)
        self.body.addLayout(search_row)
        self.body.addWidget(make_label(
            "Playback buttons control the active Windows media session. "
            "Spotify must be open; search opens Spotify in your browser.",
            size=10, color=theme.TEXT_DIM, wrap=True,
        ))

    def _control(self, action: str) -> None:
        result = self._controller.control(action)
        self.status.set_state("ok" if result["success"] else "error",
                              result.get("action", result.get("error", "Failed")).upper())

    def _search(self) -> None:
        result = self._controller.search(self.search_input.text())
        self.status.set_state("ok" if result["success"] else "error",
                              result.get("detail", result.get("error", "Failed")).upper())


class DiscordPanel(GlassCard):
    def __init__(self, controller: DiscordController,
                 settings: Any | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__("DISCORD BOT", parent)
        self._controller = controller
        self._settings = settings
        self._worker: ServiceWorker | None = None
        self.status = StateLabel("NOT CONNECTED", "warn")
        self.body.addWidget(self.status)

        self.token_input = QLineEdit()
        self.token_input.setEchoMode(QLineEdit.Password)
        self.token_input.setPlaceholderText("Discord bot token")
        self.token_input.setAccessibleName("Discord bot token")
        self.token_input.setStyleSheet(theme.input_style())
        self.body.addWidget(self.token_input)

        channel_row = QHBoxLayout()
        self.channel_input = QLineEdit()
        if settings is not None:
            self.channel_input.setText(
                str(settings.get("integrations.discord.channel_id", ""))
            )
        self.channel_input.setPlaceholderText("Target channel ID")
        self.channel_input.setStyleSheet(theme.input_style())
        if settings is not None:
            self.channel_input.editingFinished.connect(
                lambda: settings.set(
                    "integrations.discord.channel_id",
                    self.channel_input.text().strip(),
                )
            )
        channel_row.addWidget(self.channel_input, 1)
        save_button = make_button("SAVE TOKEN", kind="ghost")
        save_button.clicked.connect(self._save_token)
        channel_row.addWidget(save_button)
        test_button = make_button("TEST BOT")
        test_button.clicked.connect(self._test)
        channel_row.addWidget(test_button)
        self.body.addLayout(channel_row)

        self.message_input = QTextEdit()
        self.message_input.setPlaceholderText("Message to post")
        self.message_input.setMaximumHeight(110)
        self.message_input.setStyleSheet(theme.textview_style())
        self.body.addWidget(self.message_input)
        send_button = make_button("SEND DISCORD MESSAGE", kind="danger")
        send_button.clicked.connect(self._confirm_send)
        self.body.addWidget(send_button)
        self.body.addWidget(make_label(
            "The bot must be invited to the server with permission to view the "
            "target channel and send messages. Posting requires your confirmation.",
            size=10, color=theme.TEXT_DIM, wrap=True,
        ))
        if controller.configured():
            self.status.set_state("info", "TOKEN STORED - TEST CONNECTION")

    def _save_token(self) -> None:
        token = self.token_input.text().strip()
        if not token:
            self.status.set_state("warn", "ENTER A BOT TOKEN")
            return
        try:
            self._controller.configure(token)
        except (ValueError, RuntimeError, OSError) as exc:
            self.status.set_state("error", str(exc).upper())
            return
        self.token_input.clear()
        self.status.set_state("info", "TOKEN SAVED SECURELY")

    def _test(self) -> None:
        if self.token_input.text().strip():
            self._save_token()
        self.status.set_state("info", "CHECKING DISCORD...")
        self._run(self._controller.test_connection, self._show_test_result)

    def _confirm_send(self) -> None:
        channel = self.channel_input.text().strip()
        message = self.message_input.toPlainText().strip()
        if not self._controller.configured() and self.token_input.text().strip():
            self._save_token()
        if not self._controller.configured():
            self.status.set_state("warn", "SAVE A BOT TOKEN FIRST")
            return
        if not channel or not message:
            self.status.set_state("warn", "CHANNEL AND MESSAGE REQUIRED")
            return
        preview = message if len(message) <= 240 else message[:237] + "..."
        answer = QMessageBox.question(
            self, "Confirm Discord post",
            f"Post this message to channel {channel}?\n\n{preview}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.status.set_state("info", "POSTING MESSAGE...")
        self._run(lambda: self._controller.send_message(
            channel, message, confirmed=True
        ),
                  self._show_send_result)

    def _run(self, operation: Callable[[], dict[str, Any]], callback) -> None:
        if self._worker is not None:
            return
        worker = ServiceWorker(operation)
        self._worker = worker
        worker.completed.connect(callback)
        worker.finished.connect(self._worker_finished)
        worker.start()

    def _worker_finished(self) -> None:
        self._worker = None

    def _show_test_result(self, result: dict[str, Any]) -> None:
        if result.get("success"):
            self.status.set_state("ok", f"CONNECTED: {result.get('username', 'BOT')}")
        else:
            self.status.set_state("error", result.get("error", "Connection failed").upper())

    def _show_send_result(self, result: dict[str, Any]) -> None:
        if result.get("success"):
            self.message_input.clear()
            self.status.set_state("ok", "MESSAGE POSTED")
        else:
            self.status.set_state("error", result.get("error", "Send failed").upper())


class EmailPanel(GlassCard):
    def __init__(self, controller: EmailController,
                 parent: QWidget | None = None) -> None:
        super().__init__("EMAIL", parent)
        self._controller = controller
        self._worker: ServiceWorker | None = None
        config = controller.configuration()

        self.status = StateLabel(
            "ACCOUNT CONFIGURED" if controller.configured() else "NOT CONFIGURED",
            "info" if controller.configured() else "warn",
        )
        self.body.addWidget(self.status)

        server_row = QHBoxLayout()
        self.host_input = QLineEdit(str(config["smtp_host"]))
        self.host_input.setPlaceholderText("SMTP server, e.g. smtp.gmail.com")
        self.host_input.setStyleSheet(theme.input_style())
        server_row.addWidget(self.host_input, 1)
        self.port_input = QLineEdit(str(config["smtp_port"]))
        self.port_input.setPlaceholderText("Port")
        self.port_input.setMaximumWidth(90)
        self.port_input.setStyleSheet(theme.input_style())
        server_row.addWidget(self.port_input)
        self.security_combo = QComboBox()
        self.security_combo.addItem("SSL", "ssl")
        self.security_combo.addItem("STARTTLS", "starttls")
        self.security_combo.setCurrentIndex(
            max(0, self.security_combo.findData(config["security"]))
        )
        self.security_combo.setStyleSheet(theme.input_style())
        server_row.addWidget(self.security_combo)
        self.body.addLayout(server_row)

        account_row = QHBoxLayout()
        self.username_input = QLineEdit(str(config["username"]))
        self.username_input.setPlaceholderText("Sending email address")
        self.username_input.setStyleSheet(theme.input_style())
        account_row.addWidget(self.username_input, 1)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("Email app password")
        self.password_input.setAccessibleName("Email account app password")
        self.password_input.setStyleSheet(theme.input_style())
        account_row.addWidget(self.password_input, 1)
        self.body.addLayout(account_row)

        recipient_row = QHBoxLayout()
        self.default_recipient_input = QLineEdit(str(config["default_recipient"]))
        self.default_recipient_input.setPlaceholderText("Your email address for 'email me'")
        self.default_recipient_input.setStyleSheet(theme.input_style())
        recipient_row.addWidget(self.default_recipient_input, 1)
        save_button = make_button("SAVE ACCOUNT", kind="ghost")
        save_button.clicked.connect(self._save)
        recipient_row.addWidget(save_button)
        test_button = make_button("TEST CONNECTION")
        test_button.clicked.connect(self._test)
        recipient_row.addWidget(test_button)
        self.body.addLayout(recipient_row)

        self.to_input = QLineEdit(str(config["default_recipient"]))
        self.to_input.setPlaceholderText("To email address")
        self.to_input.setStyleSheet(theme.input_style())
        self.body.addWidget(self.to_input)
        self.subject_input = QLineEdit()
        self.subject_input.setPlaceholderText("Subject")
        self.subject_input.setStyleSheet(theme.input_style())
        self.body.addWidget(self.subject_input)
        self.message_input = QTextEdit()
        self.message_input.setPlaceholderText("Email message")
        self.message_input.setMaximumHeight(120)
        self.message_input.setStyleSheet(theme.textview_style())
        self.body.addWidget(self.message_input)
        send_button = make_button("REVIEW AND SEND EMAIL", kind="primary")
        send_button.clicked.connect(self._confirm_send)
        self.body.addWidget(send_button)
        self.body.addWidget(make_label(
            "Email passwords are stored in Windows Credential Manager. "
            "Every message requires your confirmation before it is sent.",
            size=10, color=theme.TEXT_DIM, wrap=True,
        ))

    def _save_configuration(self) -> bool:
        try:
            self._controller.configure(
                smtp_host=self.host_input.text(),
                smtp_port=self.port_input.text(),
                username=self.username_input.text(),
                password=self.password_input.text(),
                default_recipient=self.default_recipient_input.text(),
                security=self.security_combo.currentData(),
            )
        except (ValueError, RuntimeError, OSError) as exc:
            self.status.set_state("error", str(exc).upper())
            return False
        self.password_input.clear()
        self.status.set_state("info", "EMAIL ACCOUNT SAVED SECURELY")
        return True

    def _save(self) -> None:
        self._save_configuration()

    def _test(self) -> None:
        if not self._save_configuration():
            return
        if not self._controller.configured():
            self.status.set_state("warn", "SAVE AN EMAIL ACCOUNT FIRST")
            return
        self.status.set_state("info", "TESTING EMAIL CONNECTION...")
        self._run(self._controller.test_connection, self._show_test_result)

    def _confirm_send(self) -> None:
        if not self._controller.configured():
            self.status.set_state("warn", "CONFIGURE AN EMAIL ACCOUNT FIRST")
            return
        recipient = self.to_input.text().strip()
        subject = self.subject_input.text().strip() or "Message from MAMBA"
        body = self.message_input.toPlainText().strip()
        if not recipient or not body:
            self.status.set_state("warn", "RECIPIENT AND MESSAGE REQUIRED")
            return
        preview = body if len(body) <= 240 else body[:237] + "..."
        answer = QMessageBox.question(
            self, "Confirm email",
            f"Send this email to {recipient}?\n\nSubject: {subject}\n\n{preview}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.status.set_state("info", "SENDING EMAIL...")
        self._run(
            lambda: self._controller.send_email(
                recipient, subject, body, confirmed=True
            ),
            self._show_send_result,
        )

    def _run(self, operation: Callable[[], dict[str, Any]], callback) -> None:
        if self._worker is not None:
            return
        worker = ServiceWorker(operation)
        self._worker = worker
        worker.completed.connect(callback)
        worker.finished.connect(self._worker_finished)
        worker.start()

    def _worker_finished(self) -> None:
        self._worker = None

    def _show_test_result(self, result: dict[str, Any]) -> None:
        self.status.set_state(
            "ok" if result.get("success") else "error",
            result.get("detail", result.get("error", "Email test failed")).upper(),
        )

    def _show_send_result(self, result: dict[str, Any]) -> None:
        if result.get("success"):
            self.message_input.clear()
            self.subject_input.clear()
            self.status.set_state("ok", "EMAIL SENT")
        else:
            self.status.set_state("error", result.get("error", "Send failed").upper())


class BrowserPanel(GlassCard):
    def __init__(self, browser: BrowserController, search: WebSearch,
                 parent: QWidget | None = None) -> None:
        super().__init__("BROWSER AND WEB SEARCH", parent)
        self._browser = browser
        self._search = search
        self._worker: ServiceWorker | None = None
        self.status = StateLabel("READY", "idle")
        self.body.addWidget(self.status)

        url_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://example.com")
        self.url_input.setStyleSheet(theme.input_style())
        url_row.addWidget(self.url_input, 1)
        open_button = make_button("OPEN PAGE")
        open_button.clicked.connect(self._open_url)
        url_row.addWidget(open_button)
        self.body.addLayout(url_row)

        search_row = QHBoxLayout()
        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("Search the web")
        self.query_input.setStyleSheet(theme.input_style())
        self.query_input.returnPressed.connect(self._search_web)
        search_row.addWidget(self.query_input, 1)
        search_button = make_button("SEARCH WEB", kind="ghost")
        search_button.clicked.connect(self._search_web)
        search_row.addWidget(search_button)
        self.body.addLayout(search_row)

        self.results = QTextBrowser()
        self.results.setOpenExternalLinks(True)
        self.results.setMinimumHeight(240)
        self.results.setStyleSheet(theme.textview_style())
        self.body.addWidget(self.results)

    def _open_url(self) -> None:
        result = self._browser.open(self.url_input.text())
        self.status.set_state("ok" if result["success"] else "error",
                              result.get("url", result.get("error", "Failed")).upper())

    def _search_web(self) -> None:
        query = self.query_input.text().strip()
        if not query or self._worker is not None:
            return
        self.status.set_state("info", "SEARCHING THE WEB...")
        worker = ServiceWorker(lambda: self._search.search(query))
        self._worker = worker
        worker.completed.connect(self._show_results)
        worker.finished.connect(self._worker_finished)
        worker.start()

    def _show_results(self, result: dict[str, Any]) -> None:
        if not result.get("success"):
            self.status.set_state("error", result.get("error", "Search failed").upper())
            self.results.setPlainText(result.get("error", "Search failed"))
            return
        blocks = []
        for item in result.get("results", []):
            raw_url = str(item.get("url", ""))
            if not raw_url.startswith(("https://", "http://")):
                continue
            title = html.escape(str(item.get("title", "")))
            url = html.escape(raw_url, quote=True)
            snippet = html.escape(str(item.get("snippet", "")))
            blocks.append(
                f'<p><a href="{url}"><b>{title}</b></a><br>{snippet}</p>'
            )
        self.results.setHtml("".join(blocks) or "No results found.")
        self.status.set_state("ok", f"{result.get('count', 0)} RESULTS")

    def _worker_finished(self) -> None:
        self._worker = None
