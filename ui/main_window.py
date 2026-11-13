import time
from typing import Any

import psutil
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.navigation import NavigationManager
from ui.pages.common import GlassCard, PageShell, make_label
from ui.pages.voice import VoiceControlPanel
from ui.sidebar import SidebarWidget


class MambaCoreWidget(QWidget):
    """Central MAMBA status visualization with animated core."""

    status_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._status = "IDLE"
        self._animation_phase = 0.0
        self._pulse_intensity = 0.5
        self.setMinimumSize(200, 200)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(30)

    def set_status(self, status: str) -> None:
        self._status = status.upper()
        self.status_changed.emit(self._status)
        self.update()

    def _animate(self) -> None:
        self._animation_phase = (self._animation_phase + 0.05) % (2 * 3.14159)
        if self._status == "THINKING":
            self._pulse_intensity = 0.5 + 0.3 * abs(self._animation_phase)
        elif self._status == "EXECUTING":
            self._pulse_intensity = 0.6 + 0.4 * abs(self._animation_phase)
        elif self._status == "LISTENING":
            self._pulse_intensity = 0.4 + 0.4 * abs(self._animation_phase)
        elif self._status == "SPEAKING":
            self._pulse_intensity = 0.5 + 0.5 * abs(self._animation_phase)
        elif self._status == "ERROR":
            self._pulse_intensity = 0.8 + 0.2 * abs(self._animation_phase)
        else:
            self._pulse_intensity = 0.3 + 0.1 * abs(self._animation_phase)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        center_x = rect.width() // 2
        center_y = rect.height() // 2
        max_radius = min(rect.width(), rect.height()) // 2 - 20

        # Status colors
        status_colors = {
            "IDLE": QColor(100, 149, 237),
            "LISTENING": QColor(0, 255, 127),
            "THINKING": QColor(138, 43, 226),
            "EXECUTING": QColor(255, 165, 0),
            "SPEAKING": QColor(0, 191, 255),
            "ERROR": QColor(255, 69, 0)
        }
        base_color = status_colors.get(self._status, QColor(100, 149, 237))

        # Outer glow
        gradient = QRadialGradient(center_x, center_y, max_radius)
        gradient.setColorAt(0, QColor(base_color.red(), base_color.green(), base_color.blue(), int(100 * self._pulse_intensity)))
        gradient.setColorAt(0.5, QColor(base_color.red(), base_color.green(), base_color.blue(), int(50 * self._pulse_intensity)))
        gradient.setColorAt(1, QColor(base_color.red(), base_color.green(), base_color.blue(), 0))
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(center_x - max_radius, center_y - max_radius, max_radius * 2, max_radius * 2)

        # Core circle
        core_radius = int(max_radius * 0.4 * self._pulse_intensity)
        core_gradient = QRadialGradient(center_x, center_y, core_radius)
        core_gradient.setColorAt(0, QColor(255, 255, 255, 200))
        core_gradient.setColorAt(0.7, base_color)
        core_gradient.setColorAt(1, QColor(base_color.red() // 2, base_color.green() // 2, base_color.blue() // 2))
        painter.setBrush(QBrush(core_gradient))
        painter.drawEllipse(center_x - core_radius, center_y - core_radius, core_radius * 2, core_radius * 2)

        # Inner ring
        ring_radius = int(max_radius * 0.6)
        pen = QPen(base_color)
        pen.setWidth(2)
        pen.setColor(QColor(base_color.red(), base_color.green(), base_color.blue(), int(150 * self._pulse_intensity)))
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(center_x - ring_radius, center_y - ring_radius, ring_radius * 2, ring_radius * 2)

        # Status text
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Segoe UI", 12, QFont.Bold))
        painter.drawText(rect, Qt.AlignCenter, self._status)


class SystemTelemetryWidget(QWidget):
    """Real-time system health monitoring."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_telemetry)
        self._timer.start(1000)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # CPU
        self._cpu_label = QLabel("CPU: --%")
        self._cpu_label.setStyleSheet("color: #00ff7f; font-size: 11px; font-family: 'Consolas', monospace;")
        layout.addWidget(self._cpu_label)

        # RAM
        self._ram_label = QLabel("RAM: --%")
        self._ram_label.setStyleSheet("color: #00bfff; font-size: 11px; font-family: 'Consolas', monospace;")
        layout.addWidget(self._ram_label)

        # Network
        self._net_label = QLabel("NET: ACTIVE")
        self._net_label.setStyleSheet("color: #ffd700; font-size: 11px; font-family: 'Consolas', monospace;")
        layout.addWidget(self._net_label)

        # Uptime
        self._uptime_label = QLabel("UPTIME: --:--:--")
        self._uptime_label.setStyleSheet("color: #9fb6d8; font-size: 11px; font-family: 'Consolas', monospace;")
        layout.addWidget(self._uptime_label)

        self._start_time = time.time()

    def _update_telemetry(self) -> None:
        cpu_percent = psutil.cpu_percent()
        ram_percent = psutil.virtual_memory().percent

        self._cpu_label.setText(f"CPU: {cpu_percent:5.1f}%")
        self._ram_label.setText(f"RAM: {ram_percent:5.1f}%")

        uptime = int(time.time() - self._start_time)
        hours = uptime // 3600
        minutes = (uptime % 3600) // 60
        seconds = uptime % 60
        self._uptime_label.setText(f"UPTIME: {hours:02d}:{minutes:02d}:{seconds:02d}")


class VoiceWaveformWidget(QWidget):
    """Audio waveform visualization for voice interaction."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._amplitude = 0.0
        self._wave_data = [0.0] * 32
        self._is_active = False
        self.setMinimumHeight(60)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(30)

    def set_active(self, active: bool) -> None:
        self._is_active = active

    def _animate(self) -> None:
        import random
        if self._is_active:
            self._amplitude = random.uniform(0.3, 0.8)
            self._wave_data = [random.uniform(-self._amplitude, self._amplitude) for _ in range(32)]
        else:
            self._amplitude = max(0.0, self._amplitude - 0.05)
            self._wave_data = [random.uniform(-self._amplitude * 0.3, self._amplitude * 0.3) for _ in range(32)]
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        center_y = rect.height() // 2
        width = rect.width()
        bar_width = width / len(self._wave_data)

        # Draw waveform bars
        for i, amplitude in enumerate(self._wave_data):
            x = i * bar_width
            bar_height = abs(amplitude) * (rect.height() * 0.4)
            
            gradient = QLinearGradient(x, center_y - bar_height, x, center_y + bar_height)
            if self._is_active:
                gradient.setColorAt(0, QColor(0, 255, 127, 200))
                gradient.setColorAt(0.5, QColor(0, 191, 255, 255))
                gradient.setColorAt(1, QColor(0, 255, 127, 200))
            else:
                gradient.setColorAt(0, QColor(100, 149, 237, 100))
                gradient.setColorAt(0.5, QColor(100, 149, 237, 150))
                gradient.setColorAt(1, QColor(100, 149, 237, 100))
            
            painter.setBrush(QBrush(gradient))
            painter.setPen(Qt.NoPen)
            painter.drawRect(int(x), int(center_y - bar_height), int(bar_width - 1), int(bar_height * 2))


class GlassPanel(QWidget):
    """Futuristic glass panel with glow effects."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("""
            GlassPanel {
                background-color: rgba(15, 20, 30, 180);
                border: 1px solid rgba(0, 191, 255, 60);
                border-radius: 12px;
            }
        """)


class SidebarButton(QPushButton):
    """Futuristic sidebar navigation button."""

    def __init__(self, text: str, icon: str = "◆", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon = icon
        self.setText(f"{icon} {text}")
        self.setFixedHeight(40)
        self.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                color: #9fb6d8;
                font-size: 12px;
                font-weight: 500;
                text-align: left;
                padding-left: 16px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: rgba(0, 191, 255, 20);
                color: #00bfff;
            }
            QPushButton:pressed {
                background-color: rgba(0, 191, 255, 40);
            }
        """)


class DashboardWidget(QWidget):
    """Main futuristic dashboard UI for MAMBA."""

    chat_requested = Signal(str)
    ai_config_changed = Signal()
    emergency_stop_requested = Signal()
    access_revoke_requested = Signal()

    def __init__(self, parent: QWidget | None = None,
                 ai_service: Any | None = None,
                 discord_controller: Any | None = None,
                 spotify_controller: Any | None = None,
                 browser_controller: Any | None = None,
                 web_search: Any | None = None,
                 email_controller: Any | None = None,
                 settings: Any | None = None) -> None:
        super().__init__(parent)
        self._ai_service = ai_service
        self._discord_controller = discord_controller
        self._spotify_controller = spotify_controller
        self._browser_controller = browser_controller
        self._web_search = web_search
        self._email_controller = email_controller
        self._settings = settings or getattr(ai_service, "settings", None)
        self.voice_panel: VoiceControlPanel | None = None
        self.setFocusPolicy(Qt.StrongFocus)
        self._build_ui()

    def _build_ui(self) -> None:
        # Main container with dark background
        self.setStyleSheet("""
            DashboardWidget {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0a0e14,
                    stop:0.5 #0d1219,
                    stop:1 #0a0e14
                );
            }
        """)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.sidebar = SidebarWidget()
        main_layout.addWidget(self.sidebar)

        # Main content area
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(16)

        # Top bar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(16)

        # MAMBA Core visualization
        core_container = GlassPanel()
        core_layout = QVBoxLayout(core_container)
        core_layout.setContentsMargins(16, 16, 16, 16)

        core_title = QLabel("MAMBA CORE")
        core_title.setStyleSheet("color: #00bfff; font-size: 10px; font-weight: 600; letter-spacing: 1px;")
        core_title.setAlignment(Qt.AlignCenter)
        core_layout.addWidget(core_title)

        self._mamba_core = MambaCoreWidget()
        core_layout.addWidget(self._mamba_core, 1, Qt.AlignCenter)

        top_bar.addWidget(core_container, 1)

        # System telemetry
        telemetry_panel = GlassPanel()
        telemetry_layout = QVBoxLayout(telemetry_panel)
        telemetry_layout.setContentsMargins(16, 16, 16, 16)

        telemetry_title = QLabel("SYSTEM TELEMETRY")
        telemetry_title.setStyleSheet("color: #ffd700; font-size: 10px; font-weight: 600; letter-spacing: 1px;")
        telemetry_layout.addWidget(telemetry_title)

        self._telemetry = SystemTelemetryWidget()
        telemetry_layout.addWidget(self._telemetry)

        top_bar.addWidget(telemetry_panel)

        content_layout.addLayout(top_bar)

        # Middle section
        middle_section = QHBoxLayout()
        middle_section.setSpacing(16)

        # Left panel - Task & Action
        left_panel = GlassPanel()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(12)

        # Status
        status_header = QLabel("SYSTEM STATUS")
        status_header.setStyleSheet("color: #9fb6d8; font-size: 10px; font-weight: 600; letter-spacing: 1px;")
        left_layout.addWidget(status_header)

        self._status_label = QLabel("READY")
        self._status_label.setStyleSheet("""
            QLabel {
                color: #00ff7f;
                font-size: 14px;
                font-weight: 700;
                font-family: 'Consolas', monospace;
                padding: 8px;
                background-color: rgba(0, 255, 127, 10);
                border: 1px solid rgba(0, 255, 127, 30);
                border-radius: 6px;
            }
        """)
        left_layout.addWidget(self._status_label)

        # Mode
        mode_header = QLabel("AUTONOMY MODE")
        mode_header.setStyleSheet("color: #9fb6d8; font-size: 10px; font-weight: 600; letter-spacing: 1px;")
        left_layout.addWidget(mode_header)

        self._mode_label = QLabel("MAXIMUM")
        self._mode_label.setStyleSheet("""
            QLabel {
                color: #00bfff;
                font-size: 14px;
                font-weight: 700;
                font-family: 'Consolas', monospace;
                padding: 8px;
                background-color: rgba(0, 191, 255, 10);
                border: 1px solid rgba(0, 191, 255, 30);
                border-radius: 6px;
            }
        """)
        left_layout.addWidget(self._mode_label)

        # Current Task
        task_header = QLabel("CURRENT TASK")
        task_header.setStyleSheet("color: #9fb6d8; font-size: 10px; font-weight: 600; letter-spacing: 1px;")
        left_layout.addWidget(task_header)

        self._task_label = QLabel("No active task")
        self._task_label.setStyleSheet("""
            QLabel {
                color: #dfe7f3;
                font-size: 13px;
                padding: 10px;
                background-color: rgba(255, 255, 255, 5);
                border: 1px solid rgba(159, 182, 216, 20);
                border-radius: 6px;
            }
        """)
        self._task_label.setWordWrap(True)
        left_layout.addWidget(self._task_label)

        # Current Action
        action_header = QLabel("CURRENT ACTION")
        action_header.setStyleSheet("color: #9fb6d8; font-size: 10px; font-weight: 600; letter-spacing: 1px;")
        left_layout.addWidget(action_header)

        self._action_label = QLabel("IDLE")
        self._action_label.setStyleSheet("""
            QLabel {
                color: #ffd700;
                font-size: 13px;
                font-weight: 600;
                padding: 10px;
                background-color: rgba(255, 215, 0, 10);
                border: 1px solid rgba(255, 215, 0, 30);
                border-radius: 6px;
            }
        """)
        self._action_label.setWordWrap(True)
        left_layout.addWidget(self._action_label)

        # Activity feed for the OBSERVE->THINK->ACT->VERIFY loop
        activity_header = QLabel("ACTIVITY")
        activity_header.setStyleSheet(
            "color: #9fb6d8; font-size: 10px; font-weight: 600; letter-spacing: 1px;")
        left_layout.addWidget(activity_header)

        self._activity_log = QTextEdit()
        self._activity_log.setReadOnly(True)
        self._activity_log.setPlaceholderText("Loop activity will appear here...")
        self._activity_log.setStyleSheet("""
            QTextEdit {
                color: #b9c9e4;
                font-size: 11px;
                font-family: 'Consolas', monospace;
                background-color: rgba(255, 255, 255, 4);
                border: 1px solid rgba(159, 182, 216, 20);
                border-radius: 6px;
                padding: 6px;
            }
        """)
        self._activity_log.setMinimumHeight(120)
        left_layout.addWidget(self._activity_log, 1)

        middle_section.addWidget(left_panel, 1)

        # Right panel - Security & Permissions
        right_panel = GlassPanel()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(12)

        # Security Status
        security_header = QLabel("SECURITY STATUS")
        security_header.setStyleSheet("color: #9fb6d8; font-size: 10px; font-weight: 600; letter-spacing: 1px;")
        right_layout.addWidget(security_header)

        self._security_label = QLabel("SECURE")
        self._security_label.setStyleSheet("""
            QLabel {
                color: #00ff7f;
                font-size: 14px;
                font-weight: 700;
                font-family: 'Consolas', monospace;
                padding: 8px;
                background-color: rgba(0, 255, 127, 10);
                border: 1px solid rgba(0, 255, 127, 30);
                border-radius: 6px;
            }
        """)
        right_layout.addWidget(self._security_label)

        # Voice Waveform
        voice_header = QLabel("VOICE ACTIVITY")
        voice_header.setStyleSheet("color: #9fb6d8; font-size: 10px; font-weight: 600; letter-spacing: 1px;")
        right_layout.addWidget(voice_header)

        self._voice_waveform = VoiceWaveformWidget()
        right_layout.addWidget(self._voice_waveform)

        # Trusted Actions
        trust_header = QLabel("TRUSTED ACTIONS")
        trust_header.setStyleSheet("color: #9fb6d8; font-size: 10px; font-weight: 600; letter-spacing: 1px;")
        right_layout.addWidget(trust_header)

        self._trusted_label = QLabel("None")
        self._trusted_label.setStyleSheet("""
            QLabel {
                color: #9fd6c4;
                font-size: 12px;
                padding: 10px;
                background-color: rgba(159, 214, 196, 10);
                border: 1px solid rgba(159, 214, 196, 20);
                border-radius: 6px;
            }
        """)
        self._trusted_label.setWordWrap(True)
        right_layout.addWidget(self._trusted_label)

        # Protected Actions
        protected_header = QLabel("PROTECTED ACTIONS")
        protected_header.setStyleSheet("color: #9fb6d8; font-size: 10px; font-weight: 600; letter-spacing: 1px;")
        right_layout.addWidget(protected_header)

        self._protected_label = QLabel("System modifications, File deletions, Network access")
        self._protected_label.setStyleSheet("""
            QLabel {
                color: #ff8a8a;
                font-size: 12px;
                padding: 10px;
                background-color: rgba(255, 138, 138, 10);
                border: 1px solid rgba(255, 138, 138, 20);
                border-radius: 6px;
            }
        """)
        self._protected_label.setWordWrap(True)
        right_layout.addWidget(self._protected_label)

        middle_section.addWidget(right_panel, 1)

        content_layout.addLayout(middle_section)

        # Input section
        input_panel = GlassPanel()
        input_layout = QVBoxLayout(input_panel)
        input_layout.setContentsMargins(16, 16, 16, 16)
        input_layout.setSpacing(12)

        input_header = QLabel("COMMAND INPUT")
        input_header.setStyleSheet("color: #9fb6d8; font-size: 10px; font-weight: 600; letter-spacing: 1px;")
        input_layout.addWidget(input_header)

        input_row = QHBoxLayout()
        input_row.setSpacing(12)

        self._input_field = QLineEdit()
        self._input_field.setPlaceholderText("Enter command...")
        self._input_field.setFixedHeight(48)
        self._input_field.setStyleSheet("""
            QLineEdit {
                background-color: rgba(15, 20, 30, 150);
                border: 1px solid rgba(0, 191, 255, 40);
                border-radius: 8px;
                color: #dfe7f3;
                font-size: 14px;
                padding-left: 16px;
                selection-background-color: rgba(0, 191, 255, 60);
            }
            QLineEdit:hover {
                background-color: rgba(0, 191, 255, 15);
                border-color: rgba(0, 191, 255, 60);
            }
            QLineEdit:focus {
                border-color: rgba(0, 191, 255, 120);
                color: #00bfff;
            }
        """)
        input_row.addWidget(self._input_field, 1)

        send_button = QPushButton("EXECUTE")
        send_button.setFixedHeight(48)
        send_button.setMinimumWidth(100)
        send_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2b6fdb,
                    stop:1 #1f5bb8
                );
                border: 1px solid #4285e2;
                border-radius: 8px;
                color: #ffffff;
                font-size: 13px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QPushButton:hover {
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3a7fe6,
                    stop:1 #2b6fdb
                );
                border-color: #6aa0f0;
            }
            QPushButton:pressed {
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f5bb8,
                    stop:1 #163d8a
                );
            }
        """)
        input_row.addWidget(send_button)

        input_layout.addLayout(input_row)
        content_layout.addWidget(input_panel)

        # Response / conversation log
        resp_panel = GlassPanel()
        resp_layout = QVBoxLayout(resp_panel)
        resp_layout.setContentsMargins(16, 16, 16, 16)
        resp_layout.setSpacing(12)

        resp_header = QLabel("MAMBA RESPONSE")
        resp_header.setStyleSheet("color: #9fb6d8; font-size: 10px; font-weight: 600; letter-spacing: 1px;")
        resp_layout.addWidget(resp_header)

        self._response_view = QTextEdit()
        self._response_view.setReadOnly(True)
        self._response_view.setMinimumHeight(90)
        self._response_view.setAcceptRichText(True)
        self._response_view.setStyleSheet("""
            QTextEdit {
                background-color: rgba(10, 14, 20, 180);
                border: 1px solid rgba(0, 191, 255, 30);
                border-radius: 8px;
                color: #dfe7f3;
                font-size: 13px;
                font-family: 'Consolas', monospace;
                padding: 10px;
            }
        """)
        resp_layout.addWidget(self._response_view)
        content_layout.addWidget(resp_panel, 1)

        # Control buttons
        control_row = QHBoxLayout()
        control_row.setSpacing(12)

        self._emergency_stop_button = QPushButton("⚠ EMERGENCY STOP")
        self._emergency_stop_button.setFixedHeight(44)
        self._emergency_stop_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #b32a2a,
                    stop:1 #8a1d1d
                );
                border: 1px solid #d94a4a;
                border-radius: 8px;
                color: #ffffff;
                font-size: 13px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QPushButton:hover {
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #d94a4a,
                    stop:1 #b32a2a
                );
                border-color: #f06f6f;
            }
            QPushButton:pressed {
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #8a1d1d,
                    stop:1 #5a1212
                );
            }
        """)
        control_row.addWidget(self._emergency_stop_button)

        revoke_button = QPushButton("🔒 REVOKE ACCESS")
        revoke_button.setFixedHeight(44)
        revoke_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3a3f4b,
                    stop:1 #2a2e37
                );
                border: 1px solid #5a6170;
                border-radius: 8px;
                color: #ffffff;
                font-size: 13px;
                font-weight: 600;
                letter-spacing: 0.5px;
            }
            QPushButton:hover {
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4a515f,
                    stop:1 #3a3f4b
                );
                border-color: #737a8a;
            }
            QPushButton:pressed {
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2a2e37,
                    stop:1 #1a1e27
                );
            }
        """)
        control_row.addWidget(revoke_button)

        content_layout.addLayout(control_row)

        self.page_stack = QStackedWidget()
        self.navigation = NavigationManager(self.sidebar, self.page_stack, self)
        self.navigation.register("HOME", content)
        for section_id in self.sidebar.section_ids():
            if section_id != "HOME":
                self.navigation.register(
                    section_id, self._make_section_page(section_id)
                )
        main_layout.addWidget(self.page_stack, 1)
        initial_section = "HOME"
        if self._ai_service is not None and not self._ai_service.is_configured():
            initial_section = "INTEGRATIONS"
        self.navigation.navigate(initial_section)

        # Connect signals
        self._input_field.returnPressed.connect(self._submit_input)
        send_button.clicked.connect(self._submit_input)
        self._emergency_stop_button.clicked.connect(lambda: self.emergency_stop_requested.emit())
        revoke_button.clicked.connect(lambda: self.access_revoke_requested.emit())

    def _make_section_page(self, section_id: str) -> QWidget:
        descriptions = {
            "CHAT": "Submit a message from HOME to chat with MAMBA.",
            "TASKS": "Task execution and results appear in the HOME conversation.",
            "MEMORY": "MAMBA records conversation context while you use the assistant.",
            "AUTONOMY": "Automation remains subject to the app's permission checks.",
            "TOOLS": "Available computer and web tools are used through HOME commands.",
            "FILES": "File operations are available through the secured command workflow.",
            "TERMINAL": "Terminal commands are handled through the secured command workflow.",
            "BROWSER": "Browser and search actions are available through HOME commands.",
            "CODING": "Project inspection and coding commands are available through HOME.",
            "PHONE": "Phone actions require provider credentials and explicit user commands.",
            "SPOTIFY": "Control the active Windows media session or search Spotify.",
            "DISCORD": "Verify a bot, choose a channel, and confirm messages before posting.",
            "SYSTEM": "System status is available on the HOME dashboard.",
            "SECURITY": "Emergency stop and access revocation are available on HOME.",
            "DIAGNOSTICS": "Run the project test suite from the development environment.",
            "SETTINGS": "AI provider and voice settings are available in INTEGRATIONS and VOICE.",
        }
        if section_id == "INTEGRATIONS":
            page = PageShell(
                "INTEGRATIONS", "Configure MAMBA's connected services."
            )
            if self._ai_service is not None:
                from ui.pages.ai_config import AIProviderPanel

                panel = AIProviderPanel(self._ai_service)
                panel.config_changed.connect(self.ai_config_changed.emit)
                page.add_card(panel)
            else:
                card = GlassCard("AI PROVIDER")
                card.body.addWidget(make_label(
                    "AI settings are unavailable because the provider service "
                    "was not initialized.", wrap=True
                ))
                page.add_card(card)
            if self._email_controller is not None:
                from ui.pages.service_panels import EmailPanel

                page.add_card(EmailPanel(self._email_controller))
            page.add_stretch()
            return page

        if section_id == "VOICE":
            page = PageShell(
                "VOICE", "Push-to-talk input and spoken assistant replies."
            )
            self.voice_panel = VoiceControlPanel()
            self.voice_panel.text_recognized.connect(self.chat_requested.emit)
            self.voice_panel.activity_changed.connect(self.set_voice_active)
            page.add_card(self.voice_panel)
            page.add_stretch()
            return page

        if section_id == "SPOTIFY" and self._spotify_controller is not None:
            from ui.pages.service_panels import SpotifyPanel

            page = PageShell("SPOTIFY", descriptions[section_id])
            page.add_card(SpotifyPanel(self._spotify_controller))
            page.add_stretch()
            return page

        if section_id == "DISCORD" and self._discord_controller is not None:
            from ui.pages.service_panels import DiscordPanel

            page = PageShell("DISCORD", descriptions[section_id])
            page.add_card(DiscordPanel(
                self._discord_controller, settings=self._settings
            ))
            page.add_stretch()
            return page

        if section_id == "BROWSER" and self._browser_controller is not None and self._web_search is not None:
            from ui.pages.service_panels import BrowserPanel

            page = PageShell("BROWSER", descriptions[section_id])
            page.add_card(BrowserPanel(self._browser_controller, self._web_search))
            page.add_stretch()
            return page

        page = PageShell(section_id, descriptions.get(
            section_id, "This section is connected to MAMBA navigation."
        ))
        card = GlassCard(f"{section_id} STATUS")
        card.body.addWidget(make_label(
            descriptions.get(section_id, "This section is connected to MAMBA navigation."),
            wrap=True,
        ))
        page.add_card(card)
        page.add_stretch()
        return page

    def _submit_input(self) -> None:
        """Emit the actually typed command (empty input is ignored)."""
        text = self._input_field.text().strip()
        if not text:
            return
        self._input_field.clear()
        self.chat_requested.emit(text)

    def append_chat(self, role: str, text: str) -> None:
        """Append a message to the conversation log with light HTML escaping."""
        safe = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        color = "#00bfff" if role.lower() == "mamba" else "#9fb6d8"
        self._response_view.append(
            f'<span style="color:{color}; font-weight:700;">{role}:</span> {safe}'
        )
        if role.lower() == "mamba" and self.voice_panel is not None:
            self.voice_panel.speak(text)
        scrollbar = self._response_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def append_activity(self, action: str, phase_name: str, phase: Any) -> None:
        """Stream one OBSERVE->THINK->ACT->VERIFY phase into the activity feed.

        Matches the ``on_phase(action, phase_name, phase)`` callback contract of
        ``core.action_loop.ActionLoop``. ``phase`` is a ``LoopPhase`` with a
        ``status`` (completed | failed | skipped), a ``detail`` line and an
        optional ``data`` dict (e.g. the THINK tier). Colour-coding keeps a
        failed/skipped phase visually distinct without trusting the tool report.
        """
        status = getattr(phase, "status", "") or ""
        detail = getattr(phase, "detail", "") or ""
        data = getattr(phase, "data", None) or {}
        tier = data.get("tier") if isinstance(data, dict) else None
        status_color = {
            "completed": "#00ff7f",
            "failed": "#ff8a8a",
            "skipped": "#9fb6d8",
        }.get(status, "#b9c9e4")
        tier_tag = f" [{str(tier).upper()}]" if tier else ""
        safe_detail = (str(detail).replace("&", "&amp;")
                       .replace("<", "&lt;").replace(">", "&gt;"))
        self._activity_log.append(
            f'<span style="color:#6f86a8;">{phase_name}</span>'
            f'{tier_tag} '
            f'<span style="color:#00bfff; font-weight:700;">{action}</span> '
            f'<span style="color:{status_color};">({status})</span> '
            f'<span style="color:#b9c9e4;">{safe_detail}</span>'
        )
        # QTextEdit has no block cap; trim the oldest paragraphs ourselves so a
        # long autonomous session cannot grow the document without bound.
        document = self._activity_log.document()
        if document.blockCount() > 300:
            self._trim_activity(document.blockCount() - 300)
        scrollbar = self._activity_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _trim_activity(self, excess_blocks: int) -> None:
        """Drop the oldest activity paragraphs to keep the feed bounded."""
        if excess_blocks <= 0:
            return
        cursor = self._activity_log.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        for _ in range(excess_blocks):
            cursor.select(cursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            # Remove the leftover newline so blocks collapse cleanly.
            cursor.deleteChar()
        self._activity_log.setTextCursor(cursor)

    def confirm_action(self, call: Any) -> bool:
        """Ask the user to approve a CONFIRM-tier action (modal dialog).

        Matches the ``confirm_callback(call) -> bool`` contract of
        ``core.task_executor.TaskExecutor``. Defaults to deny so a dismissed
        dialog is always the safe choice; the caller only re-runs the action
        when this returns True.
        """
        action = getattr(call, "action", "this action")
        description = getattr(call, "description", "") or action
        params = getattr(call, "params", {}) or {}
        answer = QMessageBox.question(
            self,
            "Confirm action",
            f"MAMBA wants to perform a CONFIRM-level action:\n\n"
            f"{description}\n\nParameters: {params}\n\nProceed?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        approved = answer == QMessageBox.Yes
        self.append_chat(
            "MAMBA",
            f"Confirmation {'granted' if approved else 'denied'} for {action}.",
        )
        return approved

    def get_response_text(self) -> str:
        """Return the plain text of the conversation log (for verification)."""
        return self._response_view.toPlainText()

    def get_input_text(self) -> str:
        """Return the current text of the command input field."""
        return self._input_field.text()

    def set_status(self, text: str, *, warning: bool = False, error: bool = False) -> None:
        self._status_label.setText(text.upper())
        self._mamba_core.set_status(text)

        if error:
            self._status_label.setStyleSheet("""
                QLabel {
                    color: #ff8a8a;
                    font-size: 14px;
                    font-weight: 700;
                    font-family: 'Consolas', monospace;
                    padding: 8px;
                    background-color: rgba(255, 138, 138, 10);
                    border: 1px solid rgba(255, 138, 138, 30);
                    border-radius: 6px;
                }
            """)
        elif warning:
            self._status_label.setStyleSheet("""
                QLabel {
                    color: #ffd700;
                    font-size: 14px;
                    font-weight: 700;
                    font-family: 'Consolas', monospace;
                    padding: 8px;
                    background-color: rgba(255, 215, 0, 10);
                    border: 1px solid rgba(255, 215, 0, 30);
                    border-radius: 6px;
                }
            """)
        else:
            self._status_label.setStyleSheet("""
                QLabel {
                    color: #00ff7f;
                    font-size: 14px;
                    font-weight: 700;
                    font-family: 'Consolas', monospace;
                    padding: 8px;
                    background-color: rgba(0, 255, 127, 10);
                    border: 1px solid rgba(0, 255, 127, 30);
                    border-radius: 6px;
                }
            """)

    def set_mode(self, mode_text: str) -> None:
        self._mode_label.setText(mode_text.upper())

    def set_task(self, task_text: str) -> None:
        self._task_label.setText(task_text if task_text else 'No active task')

    def set_action(self, action_text: str) -> None:
        self._action_label.setText(action_text.upper() if action_text else 'IDLE')
        if action_text:
            self._mamba_core.set_status("EXECUTING")
        else:
            self._mamba_core.set_status("IDLE")

    def set_voice_active(self, active: bool) -> None:
        """Activate or deactivate voice waveform visualization."""
        self._voice_waveform.set_active(active)
        if active:
            self._mamba_core.set_status("LISTENING")
        else:
            self._mamba_core.set_status("IDLE")

    def set_thinking(self, thinking: bool) -> None:
        """Set MAMBA to thinking state."""
        if thinking:
            self._mamba_core.set_status("THINKING")
        else:
            self._mamba_core.set_status("IDLE")

    def set_speaking(self, speaking: bool) -> None:
        """Set MAMBA to speaking state."""
        if speaking:
            self._mamba_core.set_status("SPEAKING")
            self._voice_waveform.set_active(True)
        else:
            self._mamba_core.set_status("IDLE")
            self._voice_waveform.set_active(False)
