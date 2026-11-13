"""Shared MAMBA theme: palette, style-sheet factories, glow helpers.

Everything here mirrors the established futuristic look: deep blue-black
gradients, cyan (#00bfff) accents, Consolas telemetry text, thin glowing
borders and soft panel radii.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont

# ---------------------------------------------------------------- palette ---
BG_DARK = "#0a0e14"
BG_PANEL = "rgba(15, 20, 30, 180)"
BG_PANEL_LIGHT = "rgba(10, 14, 20, 200)"
ACCENT = "#00bfff"
ACCENT_DIM = "rgba(0, 191, 255, 40)"
ACCENT_SOFT = "rgba(0, 191, 255, 15)"
ACCENT_LINE = "rgba(0, 191, 255, 60)"
TEXT = "#dfe7f3"
TEXT_DIM = "#9fb6d8"
SUCCESS = "#00ff7f"
WARN = "#ffd700"
DANGER = "#ff8a8a"
DANGER_DEEP = "#b32a2a"
GOLD = "#ffd700"
MONO = "Consolas, 'Cascadia Mono', monospace"

SECTION_ORDER = [
    "HOME", "CHAT", "VOICE", "TASKS", "MEMORY", "AUTONOMY", "TOOLS", "FILES",
    "TERMINAL", "BROWSER", "CODING", "INTEGRATIONS", "PHONE", "SPOTIFY",
    "DISCORD", "SYSTEM", "SECURITY", "DIAGNOSTICS", "SETTINGS",
]


def mono_font(size: int = 12, bold: bool = False) -> QFont:
    f = QFont(MONO.split(",")[0].strip("' "), size)
    f.setBold(bold)
    return f


def _q(cls: str) -> str:
    """Wrap a declaration body in a selector (or bare block if cls empty)."""
    return f"{cls} {{ %s }}" if cls else "{ %s }"


def panel_style(object_name: str = "GlassPanel", radius: int = 12) -> str:
    return _q(object_name, ) % (
        f"background-color: {BG_PANEL};"
        f"border: 1px solid rgba(0, 191, 255, 60);"
        f"border-radius: {radius}px;"
    )


def label_style(color: str = TEXT, size: int = 12, *, bold: bool = False,
                mono: bool = False, pad: int = 0, bg: str | None = None,
                border: str | None = None, radius: int = 6) -> str:
    body = (
        f"color: {color}; font-size: {size}px; font-weight: {700 if bold else 500};"
        + (f" font-family: {MONO};" if mono else "")
        + (f" padding: {pad}px;" if pad else "")
        + (f" background-color: {bg};" if bg else "")
        + (f" border: {border};" if border else " border: none;")
        + (f" border-radius: {radius}px;" if border else "")
    )
    return f"QLabel {{ {body} }}"


def section_header_style(color: str = TEXT_DIM) -> str:
    return (
        f"QLabel {{ color: {color}; font-size: 10px; font-weight: 600;"
        f" letter-spacing: 1px; border: none; background: transparent; }}"
    )


def chip_style(color: str, alpha_bg: int = 10, alpha_border: int = 30) -> str:
    r, g, b = QColor(color).red(), QColor(color).green(), QColor(color).blue()
    return ( 
        "QLabel { "
        f"color: {color}; font-size: 13px; font-weight: 700; font-family: {MONO};"
        f"padding: 8px; background-color: rgba({r}, {g}, {b}, {alpha_bg});"
        f"border: 1px solid rgba({r}, {g}, {b}, {alpha_border}); border-radius: 6px; }}"
    )


def input_style() -> str:
    return f"""
        QLineEdit {{
            background-color: rgba(15, 20, 30, 150);
            border: 1px solid {ACCENT_DIM};
            border-radius: 8px;
            color: {TEXT};
            font-size: 13px;
            padding-left: 12px;
            selection-background-color: rgba(0, 191, 255, 60);
        }}
        QLineEdit:hover {{ background-color: {ACCENT_SOFT}; border-color: {ACCENT_LINE}; }}
        QLineEdit:focus {{ border-color: rgba(0, 191, 255, 120); color: {ACCENT}; }}
    """


def textview_style(size: int = 13) -> str:
    return f"""
        QTextEdit {{
            background-color: rgba(10, 14, 20, 180);
            border: 1px solid rgba(0, 191, 255, 30);
            border-radius: 8px;
            color: {TEXT};
            font-size: {size}px;
            font-family: {MONO};
            padding: 8px;
        }}
        QTextEdit:focus {{ border-color: rgba(0, 191, 255, 80); }}
    """


def button_style(primary: str = "#2b6fdb", primary_hover: str = "#3a7fe6",
                    border: str = "#4285e2", text: str = "#ffffff",
                    radius: int = 8, font_size: int = 12) -> str:
    return f"""
        QPushButton {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {primary}, stop:1 {primary});
            border: 1px solid {border};
            border-radius: {radius}px;
            color: {text};
            font-size: {font_size}px;
            font-weight: 700;
            letter-spacing: 1px;
            padding: 6px 14px;
        }}
        QPushButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {primary_hover}, stop:1 {primary});
        }}
        QPushButton:pressed {{ opacity: 0.8; }}
        QPushButton:disabled {{ color: #5a6170; border-color: #3a3f4b; }}
    """
