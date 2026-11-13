"""MAMBA futuristic sidebar: collapsible navigation with badges and keyboard nav."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui import theme

# section id -> (display name, icon, tooltip description)
SECTIONS: list[tuple[str, str, str, str]] = [
    ("HOME", "\u2302", "HOME", "Command center: status, core visual, quick commands"),
    ("CHAT", "\u2726", "CHAT", "Conversation interface with MAMBA"),
    ("VOICE", "\u266B", "VOICE", "Push-to-talk input and spoken replies"),
    ("TASKS", "\u2611", "TASKS", "Active task and execution history"),
    ("MEMORY", "\u2B21", "MEMORY", "Long-term memory entries and statistics"),
    ("AUTONOMY", "\u26A1", "AUTONOMY", "Autonomy level and action trust policy"),
    ("TOOLS", "\u2692", "TOOLS", "Capability controllers and their availability"),
    ("FILES", "\u25EB", "FILES", "Sandboxed file browser and viewer"),
    ("TERMINAL", "\u25BA", "TERMINAL", "Security-gated command execution"),
    ("BROWSER", "\u25C9", "BROWSER", "Web navigation and live search"),
    ("CODING", "\u2328", "CODING", "Project inspection, build and test runs"),
    ("INTEGRATIONS", "\u2B22", "INTEGRATIONS", "External providers and their status"),
    ("PHONE", "\u260E", "PHONE", "Phone integration, default number, caller ID"),
    ("SPOTIFY", "\u25B6", "SPOTIFY", "Spotify control (status page)"),
    ("DISCORD", "\u2664", "DISCORD", "Discord integration (status page)"),
    ("SYSTEM", "\u2318", "SYSTEM", "Live system telemetry"),
    ("SECURITY", "\u26A0", "SECURITY", "Emergency stop, access revocation, audit log"),
    ("DIAGNOSTICS", "\u263C", "DIAGNOSTICS", "Health checks and test entry points"),
    ("SETTINGS", "\u2699", "SETTINGS", "MAMBA preferences"),
]

_BADGE_COLORS = {
    "active": theme.SUCCESS,
    "warn": theme.WARN,
    "crit": "#ff4d4d",
}


class NavButton(QPushButton):
    """A single futuristic navigation item with icon, label and status badge."""

    def __init__(self, section_id: str, name: str, icon: str, desc: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.section_id = section_id
        self._name = name
        self._icon = icon
        self._desc = desc
        self._active = False
        self._badge: str = "none"
        self._collapsed = False
        self.setFixedHeight(40)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip(f"{name}\n{desc}")
        self.setAccessibleName(name)
        self._apply_text()
        self._apply_style()

    def set_active(self, active: bool) -> None:
        self._active = active
        self._apply_style()

    def set_badge(self, kind: str) -> None:
        kind = kind if kind in _BADGE_COLORS else "none"
        if kind != self._badge:
            self._badge = kind
            self._apply_style()
            self.update()

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._apply_text()

    def _apply_text(self) -> None:
        if self._collapsed:
            self.setText(self._icon)
        else:
            self.setText(f"  {self._icon}   {self._name}")
        self.setToolTip(f"{self._name}\n{self._desc}")

    def _apply_style(self) -> None:
        if self._active:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 rgba(0, 191, 255, 45), stop:1 rgba(0, 191, 255, 5));
                    border: 1px solid rgba(0, 191, 255, 120);
                    border-left: 3px solid {theme.ACCENT};
                    border-radius: 8px;
                    color: #eaf7ff;
                    font-size: 12px;
                    font-weight: 700;
                    letter-spacing: 1px;
                    text-align: left;
                    padding-left: 8px;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 rgba(0, 191, 255, 60), stop:1 rgba(0, 191, 255, 10));
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    border: 1px solid transparent;
                    border-radius: 8px;
                    color: {theme.TEXT_DIM};
                    font-size: 12px;
                    font-weight: 500;
                    text-align: left;
                    padding-left: 8px;
                }}
                QPushButton:hover {{
                    background-color: rgba(0, 191, 255, 22);
                    border: 1px solid rgba(0, 191, 255, 60);
                    color: {theme.ACCENT};
                }}
                QPushButton:focus {{
                    border: 1px dashed rgba(0, 191, 255, 140);
                    color: {theme.ACCENT};
                }}
            """)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._badge == "none":
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(_BADGE_COLORS[self._badge])
        cx = self.width() - 14
        cy = self.height() // 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 60)))
        painter.drawEllipse(cx - 8, cy - 8, 16, 16)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(cx - 4, cy - 4, 8, 8)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right):
            node = self.parent()
            while node is not None and not isinstance(node, SidebarWidget):
                node = node.parent()
            if node is not None:
                node.focus_neighbor(
                    self,
                    1 if event.key() in (Qt.Key_Down, Qt.Key_Right) else -1,
                )
                return
        super().keyPressEvent(event)


class SidebarWidget(QFrame):
    """Collapsible navigation sidebar; keeps the active section highlighted."""

    section_activated = Signal(str)

    EXPANDED_WIDTH = 232
    COLLAPSED_WIDTH = 68

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SidebarWidget")
        self._collapsed = False
        self._active_id = "HOME"
        self._buttons: dict[str, NavButton] = {}
        self.setMinimumWidth(self.EXPANDED_WIDTH)
        self.setMaximumWidth(self.EXPANDED_WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setStyleSheet(f"""
            SidebarWidget {{
                background-color: {theme.BG_PANEL_LIGHT};
                border-right: 1px solid rgba(0, 191, 255, 30);
            }}
        """)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 14)
        layout.setSpacing(4)

        header = QWidget()
        header.setFixedHeight(44)
        hbox = QHBoxLayout(header)
        hbox.setContentsMargins(4, 0, 0, 0)
        hbox.setSpacing(6)

        self._logo = QLabel("\u25C9 MAMBA")
        self._logo.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self._logo.setStyleSheet(
            f"color: {theme.ACCENT}; letter-spacing: 2px; border: none;")
        hbox.addWidget(self._logo, 1)

        self._toggle = QPushButton("\u00AB")
        self._toggle.setFixedSize(30, 30)
        self._toggle.setToolTip("Collapse / expand sidebar")
        self._toggle.setCursor(Qt.PointingHandCursor)
        self._toggle.setFocusPolicy(Qt.StrongFocus)
        self._toggle.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(0, 191, 255, 15);
                border: 1px solid rgba(0, 191, 255, 50);
                border-radius: 6px;
                color: {theme.ACCENT};
                font-size: 14px;
                font-weight: 700;
            }}
            QPushButton:hover {{ background-color: rgba(0, 191, 255, 40); }}
        """)
        self._toggle.clicked.connect(self.toggle_collapsed)
        hbox.addWidget(self._toggle)
        layout.addWidget(header)
        layout.addSpacing(10)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._scroll.viewport().setStyleSheet("background: transparent;")

        nav_host = QWidget()
        nav_host.setStyleSheet("background: transparent;")
        self._nav_layout = QVBoxLayout(nav_host)
        self._nav_layout.setContentsMargins(0, 0, 4, 0)
        self._nav_layout.setSpacing(4)

        for sid, name, icon, desc in SECTIONS:
            btn = NavButton(sid, name, icon, desc)
            btn.clicked.connect(lambda _=False, s=sid: self.section_activated.emit(s))
            self._buttons[sid] = btn
            self._nav_layout.addWidget(btn)
        self._nav_layout.addStretch(1)

        self._scroll.setWidget(nav_host)
        layout.addWidget(self._scroll, 1)

        # Footer hint
        self._footer = QLabel("MVP BUILD")
        self._footer.setAlignment(Qt.AlignCenter)
        self._footer.setStyleSheet(
            "color: #5a6170; font-size: 9px; letter-spacing: 2px; border: none;")
        self._footer.setToolTip("MAMBA local build status")
        layout.addWidget(self._footer)

        # Start with HOME highlighted so the active state is never ambiguous.
        self.set_active(self._active_id)

    # ------------------------------------------------------------- public --
    def section_ids(self) -> list[str]:
        return [sid for sid, *_ in SECTIONS]

    def active_id(self) -> str:
        return self._active_id

    def section_button(self, section_id: str) -> NavButton | None:
        return self._buttons.get(section_id)

    def set_active(self, section_id: str) -> None:
        """Highlight the given section; clears highlights from the others."""
        if section_id not in self._buttons:
            return
        self._active_id = section_id
        for sid, btn in self._buttons.items():
            btn.set_active(sid == section_id)

    def set_badge(self, section_id: str, kind: str) -> None:
        btn = self._buttons.get(section_id)
        if btn is not None:
            btn.set_badge(kind)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        """Collapse/expand with a smooth width animation.

        The collapsed rail keeps every button clickable (icon-only, with the
        name+description tooltip) and re-expands through the same toggle.
        """
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        target = self.COLLAPSED_WIDTH if collapsed else self.EXPANDED_WIDTH

        for btn in self._buttons.values():
            btn.set_collapsed(collapsed)
        self._toggle.setText("\u00BB" if collapsed else "\u00AB")
        self._toggle.setToolTip(
            "Expand sidebar" if collapsed else "Collapse sidebar")
        self._logo.setVisible(not collapsed)
        self._footer.setVisible(not collapsed)

        # Allow shrinking first, animate maximumWidth, then pin both bounds.
        self.setMinimumWidth(min(self.width(), target))
        anim = QPropertyAnimation(self, b"maximumWidth", self)
        anim.setDuration(180)
        anim.setStartValue(self.width())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.finished.connect(lambda t=target: self.setMinimumWidth(t))
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    def focus_neighbor(self, current: QWidget, delta: int) -> None:
        """Move keyboard focus to the next/previous navigation button."""
        buttons = [self._buttons[sid] for sid in self.section_ids()
                   if sid in self._buttons]
        try:
            idx = buttons.index(current)
        except ValueError:
            return
        buttons[(idx + delta) % len(buttons)].setFocus()

