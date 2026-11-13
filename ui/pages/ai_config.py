"""AI provider configuration panel - the real API/Integrations control surface.

Security rules implemented here:
  * the key input is a password field (EchoMode.Password) with an explicit
    Show/Hide toggle - the full key is never rendered anywhere else;
  * after a successful save the input is cleared, so the key only lives in
    Windows Credential Manager;
  * connection tests run in a background QThread against the real API and the
    displayed outcome always reflects the actual response;
  * no key value is ever placed into labels, tooltips, logs or audit events.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from core import ai_service as aisvc
from ui import theme
from ui.pages.common import GlassCard, StateLabel, make_button, make_label


class ConnectionTester(QObject):
    """Runs AIService.test_connection on a worker thread; emits the result."""

    finished = Signal(object)  # aisvc.ConnectionResult

    def __init__(self, ai_service: aisvc.AIService, timeout: float = 20.0,
                    api_key: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ai = ai_service
        self._timeout = timeout
        self._api_key = api_key

    @Slot()
    def run(self) -> None:
        try:
            result = self._ai.test_connection(timeout=self._timeout,
                                                api_key=self._api_key)
        except Exception as exc:  # defensive: still report honestly
            result = aisvc.ConnectionResult(
                ok=False, code=aisvc.PROVIDER_ERROR,
                message=f"Connection test crashed: {exc}")
        self.finished.emit(result)


def start_connection_test(ai_service: aisvc.AIService, owner: QObject,
                          on_finished, *, timeout: float = 20.0,
                            api_key: str | None = None) -> bool:
    """Start an async test; ``on_finished(result)`` runs on the GUI thread.

    Returns False when a test is already running (no API spam).
    """
    if getattr(owner, "_test_thread", None) is not None:
        return False
    thread = QThread(owner)
    worker = ConnectionTester(ai_service, timeout=timeout, api_key=api_key)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)

    def cleanup() -> None:
        worker.deleteLater()
        thread.deleteLater()
        owner._test_thread = None  # type: ignore[attr-defined]
        owner._test_worker = None  # type: ignore[attr-defined]

    worker.finished.connect(on_finished)
    worker.finished.connect(thread.quit)
    thread.finished.connect(cleanup)
    owner._test_thread = thread  # type: ignore[attr-defined]
    owner._test_worker = worker  # type: ignore[attr-defined]
    thread.start()
    return True


class AIProviderPanel(GlassCard):
    """Full AI provider setup: provider/model/key, status, test/save/remove."""

    config_changed = Signal()       # after save or key removal
    test_finished = Signal(object)  # aisvc.ConnectionResult

    def __init__(self, ai_service: aisvc.AIService,
                    parent: QWidget | None = None) -> None:
        super().__init__("AI PROVIDER - API CONFIGURATION", parent)
        self._ai = ai_service
        self._testing = False
        self._last_tested_key = ""
        self._build()
        self.refresh_status()

    # ---------------------------------------------------------------- ui --
    def _build(self) -> None:
        # ---- Provider routing mode: Local (Ollama) / Cloud (Groq) / Auto ----
        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        mode_row.addWidget(make_label("MODE", size=10,
                                        color=theme.TEXT_DIM, bold=True))
        self.mode_combo = QComboBox()
        self.mode_combo.setFixedHeight(36)
        self.mode_combo.addItem(aisvc.MODE_LABELS[aisvc.MODE_LOCAL], aisvc.MODE_LOCAL)
        self.mode_combo.addItem(aisvc.MODE_LABELS[aisvc.MODE_CLOUD], aisvc.MODE_CLOUD)
        self.mode_combo.addItem(aisvc.MODE_LABELS[aisvc.MODE_AUTO], aisvc.MODE_AUTO)
        self.mode_combo.setStyleSheet(self._combo_style())
        idx = self.mode_combo.findData(self._ai.mode)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self.mode_combo, 1)
        self.body.addLayout(mode_row)

        self.mode_hint = QLabel("")
        self.mode_hint.setStyleSheet(theme.label_style(theme.TEXT_DIM, 11))
        self.mode_hint.setWordWrap(True)
        self.body.addWidget(self.mode_hint)
        self._update_mode_hint()

        provider_row = QHBoxLayout()
        provider_row.setSpacing(10)
        provider_row.addWidget(make_label("PROVIDER", size=10,
                                            color=theme.TEXT_DIM, bold=True))
        self.provider_combo = QComboBox()
        self.provider_combo.setFixedHeight(36)
        for spec in aisvc.available_providers():
            self.provider_combo.addItem(spec.label, spec.id)
        self.provider_combo.setStyleSheet(self._combo_style())
        idx = self.provider_combo.findData(self._ai.provider_id)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_row.addWidget(self.provider_combo, 1)
        self.body.addLayout(provider_row)

        model_row = QHBoxLayout()
        model_row.setSpacing(10)
        model_row.addWidget(make_label("MODEL", size=10,
                                        color=theme.TEXT_DIM, bold=True))
        self.model_combo = QComboBox()
        self.model_combo.setFixedHeight(36)
        self.model_combo.setEditable(True)
        self.model_combo.setStyleSheet(self._combo_style())
        self._fill_models()
        model_row.addWidget(self.model_combo, 1)
        self.body.addLayout(model_row)

        # ---- Fallback provider + request policy (timeout/retry) ----
        fb_row = QHBoxLayout()
        fb_row.setSpacing(10)
        fb_row.addWidget(make_label("FALLBACK", size=10,
                                    color=theme.TEXT_DIM, bold=True))
        self.fallback_combo = QComboBox()
        self.fallback_combo.setFixedHeight(36)
        for spec in aisvc.available_providers():
            if spec.requires_api_key:
                self.fallback_combo.addItem(spec.label, spec.id)
        self.fallback_combo.setStyleSheet(self._combo_style())
        cur_fb = str(self._ai.settings.get("ai.fallback_provider", "groq") or "groq")
        idx = self.fallback_combo.findData(cur_fb)
        if idx >= 0:
            self.fallback_combo.setCurrentIndex(idx)
        fb_row.addWidget(self.fallback_combo, 1)
        self.body.addLayout(fb_row)

        policy_row = QHBoxLayout()
        policy_row.setSpacing(10)
        policy_row.addWidget(make_label("TIMEOUT", size=10,
                                        color=theme.TEXT_DIM, bold=True))
        self.timeout_input = QLineEdit(str(self._ai.settings.get("ai.timeout_s", 30.0)))
        self.timeout_input.setFixedHeight(36)
        self.timeout_input.setFixedWidth(90)
        self.timeout_input.setStyleSheet(theme.input_style())
        self.timeout_input.setPlaceholderText("30")
        policy_row.addWidget(self.timeout_input)
        policy_row.addWidget(make_label("RETRIES", size=10,
                                        color=theme.TEXT_DIM, bold=True))
        self.retries_input = QLineEdit(str(self._ai.settings.get("ai.retries", 1)))
        self.retries_input.setFixedHeight(36)
        self.retries_input.setFixedWidth(70)
        self.retries_input.setStyleSheet(theme.input_style())
        self.retries_input.setPlaceholderText("1")
        policy_row.addWidget(self.retries_input)
        self.local_refresh_btn = self._small_button("SYNC")
        self.local_refresh_btn.setFixedWidth(80)
        self.local_refresh_btn.setToolTip("List installed Ollama models")
        self.local_refresh_btn.clicked.connect(self.refresh_local_models)
        policy_row.addWidget(self.local_refresh_btn)
        policy_row.addStretch(1)
        self.body.addLayout(policy_row)

        self.key_label = make_label(f"{self._ai.spec.label.upper()} API KEY", size=10,
                        color=theme.TEXT_DIM, bold=True)
        self.body.addWidget(self.key_label)

        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        self.key_input = QLineEdit()
        self.key_input.setFixedHeight(38)
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setPlaceholderText("Paste the selected provider's API key")
        self.key_input.setStyleSheet(theme.input_style())
        self.key_input.setAccessibleName("Provider API key password field")
        key_row.addWidget(self.key_input, 1)

        self.show_btn = self._small_button("SHOW")
        self.show_btn.setObjectName("show_hide_key")
        self.show_btn.clicked.connect(self._toggle_key_visibility)
        key_row.addWidget(self.show_btn)

        self.paste_btn = self._small_button("PASTE")
        self.paste_btn.setObjectName("paste_key")
        self.paste_btn.clicked.connect(self._paste_key)
        key_row.addWidget(self.paste_btn)

        self.clear_btn = self._small_button("CLEAR")
        self.clear_btn.setObjectName("clear_key_field")
        self.clear_btn.clicked.connect(lambda: self.key_input.clear())
        key_row.addWidget(self.clear_btn)
        self.body.addLayout(key_row)

        self.stored_hint = QLabel("")
        self.stored_hint.setStyleSheet(theme.label_style(theme.TEXT_DIM, 11, mono=True))
        self.stored_hint.setWordWrap(True)
        self.body.addWidget(self.stored_hint)

        self.status_label = StateLabel("", "idle")
        self.status_label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        self.body.addWidget(self.status_label)

        self.detail_label = QLabel("")
        self.detail_label.setStyleSheet(theme.label_style(theme.TEXT_DIM, 11))
        self.detail_label.setWordWrap(True)
        self.body.addWidget(self.detail_label)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.test_btn = make_button("TEST CONNECTION", kind="primary")
        self.test_btn.setObjectName("test_connection")
        self.test_btn.clicked.connect(self.run_test)
        actions.addWidget(self.test_btn)

        self.save_btn = make_button("SAVE / APPLY")
        self.save_btn.setObjectName("save_config")
        self.save_btn.clicked.connect(self.save)
        actions.addWidget(self.save_btn)

        self.remove_btn = make_button("REMOVE API KEY", kind="danger")
        self.remove_btn.setObjectName("remove_key")
        self.remove_btn.clicked.connect(self.remove_key)
        actions.addWidget(self.remove_btn)
        actions.addStretch(1)
        self.body.addLayout(actions)

        note = make_label(
            "SECURITY: the key is stored in Windows Credential Manager - never "
            "in source code, logs, audit events or telemetry. It is only sent "
            "to the selected AI provider to authenticate your requests.",
            size=10, color="#5a6170", wrap=True)
        self.body.addWidget(note)
        self._update_key_controls(self._ai.spec)

    @staticmethod
    def _small_button(text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(38)
        btn.setFixedWidth(74)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(theme.button_style("rgba(15,20,30,180)",
                                                "rgba(0,191,255,25)",
                                                "rgba(0,191,255,60)",
                                                theme.ACCENT))
        return btn

    @staticmethod
    def _combo_style() -> str:
        return f"""
            QComboBox {{
                background-color: rgba(15, 20, 30, 150);
                border: 1px solid {theme.ACCENT_DIM};
                border-radius: 8px;
                color: {theme.TEXT};
                font-size: 13px;
                padding-left: 10px;
            }}
            QComboBox:hover {{ background-color: {theme.ACCENT_SOFT}; }}
            QComboBox QAbstractItemView {{
                background-color: #0d1219;
                color: {theme.TEXT};
                selection-background-color: rgba(0, 191, 255, 40);
                border: 1px solid rgba(0, 191, 255, 60);
            }}
        """

    def _fill_models(self) -> None:
        current = self.model_combo.currentText().strip() or self._ai.model
        self.model_combo.clear()
        self.model_combo.addItems(list(self._ai.spec.models))
        idx = self.model_combo.findText(current)
        self.model_combo.setCurrentIndex(max(idx, 0))
        if idx < 0:
            self.model_combo.setEditText(current)

    # ------------------------------------------------------------- actions --
    def _on_provider_changed(self, _index: int) -> None:
        # Provider switching only takes effect on SAVE; just refresh the model
        # choices for the newly selected provider spec.
        pid = self.provider_combo.currentData()
        spec = aisvc.PROVIDER_REGISTRY.get(pid)
        if spec:
            self._update_key_controls(spec)
            current = self.model_combo.currentText().strip()
            self.model_combo.clear()
            self.model_combo.addItems(list(spec.models))
            if current in spec.models:
                self.model_combo.setCurrentText(current)
            if spec.requires_api_key:
                self.detail_label.setText(
                    f"A key for {spec.label} is stored separately from other providers.")
            else:
                self.detail_label.setText(
                    "Ollama runs locally and does not require an API key.")

    def _current_mode(self) -> str:
        return str(self.mode_combo.currentData() or aisvc.MODE_AUTO)

    def _update_mode_hint(self) -> None:
        """Explain what the selected routing mode will do."""
        mode = self._current_mode()
        reachable = self._ai.ollama_reachable()
        if mode == aisvc.MODE_LOCAL:
            text = ("Local mode runs the Ollama model on this PC - no internet "
                    "and no API key are used. Start Ollama and install "
                    f"'{self._ai.ollama_model}' to use it.")
            if not reachable:
                text += " (Ollama was not detected on localhost:11434.)"
        elif mode == aisvc.MODE_CLOUD:
            text = ("Cloud mode always uses the configured cloud provider "
                    "(Groq) - it needs an API key and an internet connection.")
        else:  # automatic
            cloud_label = aisvc.PROVIDER_REGISTRY[
                self._ai.cloud_provider_id
            ].label
            text = (f"Automatic uses {cloud_label} when internet and its API "
                    "key are available; otherwise it uses local Ollama. A "
                    "cloud network failure also switches to Ollama when "
                    "the local model is reachable.")
            text += (" Ollama is currently detected."
                     if reachable else
                     " Ollama was not detected.")
        self.mode_hint.setText(text)

    def _on_mode_changed(self, _index: int) -> None:
        # Reflect the chosen mode in the hint and keep the PROVIDER/MODEL
        # selectors coherent with it. The mode itself is persisted on SAVE/TEST
        # alongside the provider.
        self._update_mode_hint()
        mode = self._current_mode()
        if mode == aisvc.MODE_LOCAL:
            # Local always means the local Ollama server and its models.
            idx = self.provider_combo.findData("ollama")
            if idx >= 0:
                self.provider_combo.setCurrentIndex(idx)
            self._on_provider_changed(0)
            self.detail_label.setText(
                "Local (Ollama) mode selected - no API key required.")
        elif mode == aisvc.MODE_CLOUD:
            # Cloud defaults to Groq unless another cloud provider is chosen.
            if self.provider_combo.currentData() == "ollama":
                idx = self.provider_combo.findData(aisvc.DEFAULT_CLOUD_PROVIDER)
                if idx >= 0:
                    self.provider_combo.setCurrentIndex(idx)
            self._on_provider_changed(0)
            self.detail_label.setText(
                "Cloud (Groq) mode selected - an API key and internet are required.")

    def _update_key_controls(self, spec: aisvc.ProviderSpec) -> None:
        needs_key = spec.requires_api_key
        self.key_label.setText(
            f"{spec.label.upper()} API KEY" if needs_key else "API KEY NOT REQUIRED")
        self.key_input.setEnabled(needs_key)
        self.key_input.setPlaceholderText(
            "Paste the selected provider's API key" if needs_key
            else "Ollama runs locally; no API key is needed")
        self.show_btn.setEnabled(needs_key)
        self.paste_btn.setEnabled(needs_key)
        self.clear_btn.setEnabled(needs_key)
        self.remove_btn.setEnabled(needs_key)
        if not needs_key:
            self.key_input.clear()
            self.key_input.setEchoMode(QLineEdit.Password)
            self.show_btn.setText("SHOW")

    def _toggle_key_visibility(self) -> None:
        if self.key_input.echoMode() == QLineEdit.Password:
            self.key_input.setEchoMode(QLineEdit.Normal)
            self.show_btn.setText("HIDE")
        else:
            self.key_input.setEchoMode(QLineEdit.Password)
            self.show_btn.setText("SHOW")

    def _paste_key(self) -> None:
        text = QApplication.clipboard().text().strip()
        if text:
            self.key_input.setText(text)
            # Stay masked: pasting must not reveal the key on screen.
            self.key_input.setEchoMode(QLineEdit.Password)
            self.show_btn.setText("SHOW")

    def refresh_local_models(self) -> None:
        """Replace the model list with actually-installed Ollama models."""
        installed = self._ai.list_ollama_models()
        if not installed:
            self.detail_label.setText(
                "Ollama is not reachable or has no models installed. "
                f"Start it with 'ollama serve', then 'ollama pull "
                f"{self._ai.ollama_model}'.")
            return
        self.model_combo.clear()
        self.model_combo.addItems(installed)
        current = self._ai.ollama_model
        idx = self.model_combo.findText(current)
        self.model_combo.setCurrentIndex(max(idx, 0))
        self.detail_label.setText(
            f"Found {len(installed)} installed local model(s).")

    def _persist_policy(self) -> None:
        try:
            timeout = float(self.timeout_input.text().strip() or 30.0)
        except ValueError:
            timeout = 30.0
        try:
            retries = int(self.retries_input.text().strip() or 1)
        except ValueError:
            retries = 1
        self._ai.settings.set("ai.fallback_provider",
                              str(self.fallback_combo.currentData() or "groq"))
        self._ai.settings.set("ai.timeout_s", min(max(timeout, 5.0), 300.0))
        self._ai.settings.set("ai.retries", min(max(retries, 0), 3))

    def refresh_status(self) -> None:
        """ repaint status area from the live service state (no API call)."""
        status = self._ai.status()
        state = status["state"]
        color = {
            aisvc.STATE_ONLINE: "ok",
            aisvc.STATE_NOT_CONFIGURED: "warn",
            aisvc.STATE_UNVERIFIED: "info",
            aisvc.STATE_ERROR: "error",
        }.get(state, "idle")
        self.status_label.set_state(color, status["label"])

        if status["key_hint"]:
            self.stored_hint.setText(
                f"Stored key: {status['key_hint']}  |  storage: "
                f"{status['key_storage']}  |  "
                f"{status['provider_label']} / {status['model']}")
        elif not self._ai.spec.requires_api_key:
            self.stored_hint.setText(
                f"No API key required  |  {status['provider_label']} / "
                f"{status['model']}")
        else:
            self.stored_hint.setText(
                f"No API key stored  |  {status['provider_label']} / "
                f"{status['model']}")

        last = status["last_result"]
        if last is not None:
            self.detail_label.setText(
                f"Last test: {last.label} - {last.message}"
                + (f" ({last.latency_ms} ms)" if last.latency_ms else "")
                + (f" | {last.detail}" if last.detail else ""))
        else:
            action = ("press TEST CONNECTION" if not self._ai.spec.requires_api_key
                      else "paste an API key and press TEST CONNECTION")
            self.detail_label.setText(
                f"No connection test run yet. {action} to verify "
                f"{status['provider_label']}.")

    def run_test(self) -> None:
        """Start a REAL API connection test in the background."""
        if self._testing:
            return
        typed = self.key_input.text().strip()
        provider = str(self.provider_combo.currentData() or "gemini")
        model = self.model_combo.currentText().strip()
        mode = self._current_mode()
        try:
            self._ai.configure(provider=provider, model=model, mode=mode)
        except (ValueError, RuntimeError, OSError) as exc:
            self.status_label.set_state("error", "CONFIGURATION FAILED")
            self.detail_label.setText(str(exc))
            return
        self._testing = True
        self.test_btn.setEnabled(False)
        self.test_btn.setText("TESTING...")
        self.status_label.set_state("info", "TESTING CONNECTION...")
        self.detail_label.setText(
            f"Sending a minimal real request to {self._ai.spec.label}...")

        def on_finished(result) -> None:
            self._testing = False
            self.test_btn.setEnabled(True)
            self.test_btn.setText("TEST CONNECTION")
            self._last_tested_key = typed or ""
            # Headline reflects the service state; the detail line carries the
            # exact test outcome (message + latency + provider excerpt).
            self.refresh_status()
            self.test_finished.emit(result)

        if not start_connection_test(self._ai, self, on_finished,
                                     api_key=typed or None):
            self._testing = False
            self.test_btn.setEnabled(True)
            self.test_btn.setText("TEST CONNECTION")

    def save(self) -> None:
        """Validate and persist mode/provider/model/secure key."""
        provider = self.provider_combo.currentData() or "gemini"
        model = self.model_combo.currentText().strip()
        mode = self._current_mode()
        typed_key = self.key_input.text().strip()
        try:
            self._ai.configure(
                api_key=typed_key or None,
                provider=str(provider),
                model=model,
                mode=mode,
            )
        except (ValueError, RuntimeError, OSError) as exc:
            self.status_label.set_state("error", "SAVE FAILED")
            self.detail_label.setText(str(exc))
            return
        tested_ok = (bool(typed_key) and typed_key == self._last_tested_key
                     and self._ai.last_result is not None
                     and self._ai.last_result.ok)
        self.key_input.clear()          # key only lives in the vault now
        self.key_input.setEchoMode(QLineEdit.Password)
        self.show_btn.setText("SHOW")
        self.refresh_status()
        self.config_changed.emit()
        if tested_ok:
            # The exact key just passed a real test - verify the stored copy
            # too, so the status can honestly reach "AI ONLINE".
            self.run_test()

    def remove_key(self) -> None:
        """Delete the stored credential and reset status honestly."""
        removed = self._ai.clear_key()
        self.key_input.clear()
        self.key_input.setEchoMode(QLineEdit.Password)
        self.show_btn.setText("SHOW")
        self._last_tested_key = ""
        self.refresh_status()
        if removed:
            self.detail_label.setText(
                "Stored API key removed from Windows Credential Manager. "
                "MAMBA will not call any AI provider until a new key is saved.")
        else:
            self.detail_label.setText(
                "No stored credential was present (an environment variable "
                "may still define GEMINI_API_KEY until the app restarts).")
        self.config_changed.emit()


class AIStatusCard(GlassCard):
    """Compact AI provider status for HOME with a configure shortcut."""

    configure_requested = Signal()

    def __init__(self, ai_service: aisvc.AIService,
                 parent: QWidget | None = None) -> None:
        super().__init__("AI PROVIDER", parent)
        self._ai = ai_service
        self.status_label = StateLabel("", "idle")
        self.body.addWidget(self.status_label)
        self.info_label = QLabel("")
        self.info_label.setStyleSheet(theme.label_style(theme.TEXT_DIM, 11, mono=True))
        self.info_label.setWordWrap(True)
        self.body.addWidget(self.info_label)
        self.action_btn = make_button("CONFIGURE AI", kind="ghost")
        self.action_btn.setObjectName("configure_ai")
        self.action_btn.clicked.connect(self.configure_requested.emit)
        self.body.addWidget(self.action_btn)
        self.refresh()

    def refresh(self) -> None:
        status = self._ai.status()
        chip = {
            aisvc.STATE_ONLINE: "ok",
            aisvc.STATE_NOT_CONFIGURED: "warn",
            aisvc.STATE_UNVERIFIED: "info",
            aisvc.STATE_ERROR: "error",
        }.get(status["state"], "idle")
        self.status_label.set_state(chip, status["label"])
        if status["state"] == aisvc.STATE_NOT_CONFIGURED:
            self.info_label.setText(
                "No API key found. Configure an AI provider to enable MAMBA's AI.")
            self.action_btn.setText("CONFIGURE AI")
            self.action_btn.show()
        elif status["state"] == aisvc.STATE_UNVERIFIED:
            self.info_label.setText(
                f"{status['provider_label']} / {status['model']}  "
                f"{status['key_hint']} - run TEST CONNECTION in INTEGRATIONS.")
            self.action_btn.setText("VERIFY CONNECTION")
            self.action_btn.show()
        elif status["state"] == aisvc.STATE_ONLINE:
            last = status["last_result"]
            detail = f" (last check {last.latency_ms} ms)" if last and last.latency_ms else ""
            self.info_label.setText(
                f"{status['provider_label']} / {status['model']}{detail}")
            self.action_btn.hide()
        else:  # error
            last = status["last_result"]
            self.info_label.setText(
                last.message if last else "Provider error - retest connection.")
            self.action_btn.setText("OPEN AI SETTINGS")
            self.action_btn.show()




