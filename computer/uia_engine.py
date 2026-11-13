"""UI Automation helper using pywinauto for structured element inspection."""
from __future__ import annotations

import logging
from typing import Any

from pywinauto import Application

logger = logging.getLogger(__name__)

class UIAutomationEngine:
    """
    Provides structured access to Windows UI elements.
    This complements coordinate-based control by allowing search by control type,
    text, or accessibility labels.
    """

    def __init__(self, security_manager: Any | None = None) -> None:
        self._security_manager = security_manager

    def _allowed(self) -> bool:
        if self._security_manager is None:
            return True
        return bool(self._security_manager.is_allowed())

    def get_window_elements(self, title_substring: str) -> list[dict[str, Any]]:
        """
        Inspect a window and return a list of interactable elements.
        Returns a list of elements with their text, type, and center coordinates.
        """
        if not self._allowed():
            return []

        try:
            # Connect to the window
            app = Application(backend="uia").connect(title_re=f".*{title_substring}.*", timeout=2)
            window = app.top_window()

            elements = []
            # Descendants get all children. We filter for things that are likely interactable.
            for desc in window.descendants():
                try:
                    # Extract basic info
                    info = {
                        "text": desc.texts()[0] if desc.texts() else "",
                        "control_type": desc.element_info.control_type,
                        "rect": desc.rectangle(),
                        "center": (
                            int((desc.rectangle().left + desc.rectangle().right) / 2),
                            int((desc.rectangle().top + desc.rectangle().bottom) / 2)
                        ),
                        "id": desc.element_info.name
                    }
                    if info["text"] or info["control_type"] in ("Button", "Edit", "MenuItem", "ListItem"):
                        elements.append(info)
                except Exception:
                    continue

            return elements
        except Exception as e:
            logger.error(f"UIA inspection failed for {title_substring}: {e}")
            return []

    def find_element_coords(self, title_substring: str, text_target: str) -> tuple[int, int] | None:
        """Find the center coordinates of an element with specific text."""
        elements = self.get_window_elements(title_substring)
        for el in elements:
            if text_target.lower() in el["text"].lower():
                return el["center"]
        return None
