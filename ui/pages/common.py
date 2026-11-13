"""Shared building blocks for MAMBA's section pages.

All pages use the same glass-panel aesthetic from ``ui.theme``: a header with
section title/subtitle, a scrollable body, and card widgets with neon accents.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui import theme

# state -> (text color, background rgba, border rgba)
STATE_COLORS = {
    "ok": ("#00ff7f", "rgba(0, 255, 127, 10)", "rgba(0, 255, 127, 45)"),
    "warn": ("#ffd700", "rgba(255, 215, 0, 10)", "rgba(255, 215, 0, 45)"),
    "error": ("#ff8a8a", "rgba(255, 138, 138, 10)", "rgba(255, 138, 138, 45)"),
    "info": ("#00bfff", "rgba(0, 191, 255, 10)", "rgba(0, 191, 255, 45)"),
    "idle": ("#9fb6d8", "rgba(159, 182, 216, 8)", "rgba(159, 182, 216, 30)"),
}


def state_color(state: str) -> tuple[str, str, str]:
    return STATE_COLORS.get(state, STATE_COLORS["idle"])


class GlassCard(QFrame):
    """Translucent glowing card used to group page content."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("GlassCard")
        self.setStyleSheet(
            "QFrame#GlassCard {"
            f"background-color: {theme.BG_PANEL};"
            "border: 1px solid rgba(0, 191, 255, 55);"
            "border-radius: 12px;"
            "}"
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 14)
        self._layout.setSpacing(10)
        if title:
            header = QLabel(title)
            header.setStyleSheet(theme.section_header_style(theme.ACCENT))
            header.setFont(QFont("Segoe UI", 10, QFont.Bold))
            self._layout.addWidget(header)

    @property
    def body(self) -> QVBoxLayout:
        return self._layout

    def add_row(self, *widgets: QWidget, stretch_last: bool = False) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        for w in widgets:
            row.addWidget(w)
        if stretch_last and widgets:
            row.addStretch(1)
        self._layout.addLayout(row)
        return row


class StateLabel(QLabel):
    """A neon status chip whose color reflects ok/warn/error/info/idle."""

    def __init__(self, text: str = "", state: str = "idle",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = "idle"
        self.set_state(state, text=text)

    def set_state(self, state: str, text: str | None = None) -> None:
        self._state = state if state in STATE_COLORS else "idle"
        if text is not None:
            self.setText(text)
        fg, bg, border = state_color(self._state)
        self.setStyleSheet(
            f"QLabel {{ color: {fg}; font-size: 13px; font-weight: 700;"
            f"font-family: {theme.MONO}; padding: 8px 12px;"
            f"background-color: {bg}; border: 1px solid {border};"
            "border-radius: 6px; }"
        )

    @property
    def state(self) -> str:
        return self._state


def make_button(text: str, *, kind: str = "primary",
                parent: QWidget | None = None) -> QPushButton:
    """Create a futuristic button: primary | danger | ghost."""
    btn = QPushButton(text, parent)
    btn.setFixedHeight(38)
    btn.setCursor(Qt.PointingHandCursor)
    if kind == "danger":
        btn.setStyleSheet(theme.button_style("#8a1d1d", "#b32a2a", "#d94a4a"))
    elif kind == "ghost":
        btn.setStyleSheet(theme.button_style("rgba(15,20,30,180)",
                                             "rgba(0,191,255,25)",
                                             "rgba(0,191,255,60)",
                                             theme.ACCENT))
    else:
        btn.setStyleSheet(theme.button_style())
    return btn


def make_label(text: str, *, size: int = 13, color: str = theme.TEXT,
               bold: bool = False, mono: bool = False,
               wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(theme.label_style(color, size, bold=bold, mono=mono, pad=6))
    if wrap:
        lbl.setWordWrap(True)
    return lbl


def kv_row(label: str, value: str) -> tuple[QLabel, QLabel]:
    """Key/value pair for status lists (value is selectable)."""
    key = QLabel(label)
    key.setStyleSheet(theme.section_header_style())
    val = QLabel(value)
    val.setStyleSheet(theme.label_style(theme.TEXT, 12, mono=True, pad=4))
    val.setTextInteractionFlags(Qt.TextSelectableByMouse)
    val.setWordWrap(True)
    return key, val


class PageShell(QWidget):
    """Standard page: title header + scrollable body column."""

    def __init__(self, title: str, subtitle: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)

        head = QVBoxLayout()
        head.setSpacing(2)
        self.title = QLabel(title)
        self.title.setFont(QFont("Segoe UI", 20, QFont.Bold))
        self.title.setStyleSheet(
            f"color: {theme.ACCENT}; letter-spacing: 2px; border: none;")
        head.addWidget(self.title)
        if subtitle:
            self.subtitle = QLabel(subtitle)
            self.subtitle.setStyleSheet(theme.label_style(theme.TEXT_DIM, 11))
            self.subtitle.setWordWrap(True)
            head.addWidget(self.subtitle)
        outer.addLayout(head)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(
            "background-color: rgba(0, 191, 255, 60); border: none;")
        outer.addWidget(line)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: rgba(10,14,20,120); width: 10px;"
            " border-radius: 4px; }"
            "QScrollBar::handle:vertical { background: rgba(0,191,255,80);"
            " border-radius: 4px; min-height: 24px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical"
            " { height: 0; }"
        )
        scroll.viewport().setStyleSheet("background: transparent;")

        self._body_host = QWidget()
        self._body_host.setStyleSheet("background: transparent;")
        self.body = QVBoxLayout(self._body_host)
        self.body.setContentsMargins(0, 4, 8, 8)
        self.body.setSpacing(14)
        scroll.setWidget(self._body_host)
        outer.addWidget(scroll, 1)

    def add_card(self, card: GlassCard, stretch: int = 0) -> None:
        self.body.addWidget(card, stretch)

    def add_stretch(self) -> None:
        self.body.addStretch(1)

