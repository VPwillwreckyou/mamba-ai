"""Push-to-talk speech input and optional local speech output."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QWidget

from ui import theme
from ui.pages.common import GlassCard, StateLabel, make_button, make_label


class VoiceWorker(QThread):
    text_ready = Signal(str)
    failed = Signal(str)

    def __init__(self, *, listen: bool, text: str = "") -> None:
        super().__init__()
        self._listen = listen
        self._text = text

    def run(self) -> None:
        try:
            if self._listen:
                import speech_recognition as sr

                recognizer = sr.Recognizer()
                with sr.Microphone() as source:
                    recognizer.adjust_for_ambient_noise(source, duration=0.4)
                    audio = recognizer.listen(
                        source, timeout=6, phrase_time_limit=20
                    )
                transcript = recognizer.recognize_google(audio)
                if not transcript.strip():
                    raise RuntimeError("No speech was recognized.")
                self.text_ready.emit(transcript.strip())
            else:
                import pyttsx3

                engine = pyttsx3.init()
                engine.say(self._text)
                engine.runAndWait()
                self.text_ready.emit("")
        except Exception as exc:
            self.failed.emit(str(exc))


class VoiceControlPanel(GlassCard):
    text_recognized = Signal(str)
    activity_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("VOICE CONTROLS", parent)
        self._worker: VoiceWorker | None = None
        self._build()

    def _build(self) -> None:
        self.status = StateLabel("VOICE READY", "idle")
        self.body.addWidget(self.status)

        row = QHBoxLayout()
        self.listen_button = make_button("START LISTENING", kind="primary")
        self.listen_button.setToolTip("Capture one spoken command")
        self.listen_button.clicked.connect(self.listen)
        row.addWidget(self.listen_button)

        self.speak_enabled = QCheckBox("Speak MAMBA replies")
        self.speak_enabled.setChecked(True)
        self.speak_enabled.setStyleSheet(
            f"QCheckBox {{ color: {theme.TEXT}; spacing: 8px; }}"
            f"QCheckBox::indicator {{ width: 16px; height: 16px; }}"
        )
        row.addWidget(self.speak_enabled)
        row.addStretch(1)
        self.body.addLayout(row)

        self.body.addWidget(make_label(
            "Speech input uses the system microphone and Google's online speech "
            "recognition. Spoken replies use the local Windows speech engine.",
            size=10, color=theme.TEXT_DIM, wrap=True,
        ))

    def listen(self) -> None:
        if self._worker is not None:
            return
        self.status.set_state("info", "LISTENING FOR ONE COMMAND...")
        self.listen_button.setEnabled(False)
        self.activity_changed.emit(True)
        self._start_worker(VoiceWorker(listen=True))

    def speak(self, text: str) -> None:
        if not self.speak_enabled.isChecked() or not text.strip():
            return
        if self._worker is not None:
            return
        self.status.set_state("info", "SPEAKING...")
        self._start_worker(VoiceWorker(listen=False, text=text))

    def _start_worker(self, worker: VoiceWorker) -> None:
        self._worker = worker
        worker.text_ready.connect(self._on_text_ready)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_finished)
        worker.start()

    def _on_text_ready(self, text: str) -> None:
        if text:
            self.status.set_state("ok", "VOICE INPUT RECEIVED")
            self.text_recognized.emit(text)
        else:
            self.status.set_state("ok", "SPEECH COMPLETE")

    def _on_failed(self, error: str) -> None:
        self.status.set_state("error", "VOICE UNAVAILABLE")
        self.status.setToolTip(error)

    def _on_finished(self) -> None:
        self.listen_button.setEnabled(True)
        self.activity_changed.emit(False)
        self._worker = None
