"""Centralized navigation for MAMBA's sidebar-driven UI.

The sidebar never talks to pages directly: every click goes through
``NavigationManager``, which switches the stacked view, keeps the sidebar's
active highlight in sync, and emits ``section_changed`` so other widgets can
react. Adding a page means registering it once - no per-button handlers.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QStackedWidget, QWidget

from ui import theme
from ui.sidebar import SidebarWidget


class NavigationManager(QObject):
    """Maps sidebar section ids to pages in a QStackedWidget."""

    section_changed = Signal(str)

    def __init__(self, sidebar: SidebarWidget, stack: QStackedWidget,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sidebar = sidebar
        self._stack = stack
        self._pages: dict[str, QWidget] = {}
        self._order: list[str] = []
        sidebar.section_activated.connect(self.navigate)

    # ------------------------------------------------------------ registry --
    def register(self, section_id: str, page: QWidget) -> None:
        """Attach a page widget to a section id (idempotent replace)."""
        if section_id not in theme.SECTION_ORDER:
            raise ValueError(f"Unknown sidebar section: {section_id}")
        if section_id in self._pages:
            old = self._pages[section_id]
            idx = self._stack.indexOf(old)
            if idx >= 0:
                self._stack.removeWidget(old)
                old.deleteLater()
        self._pages[section_id] = page
        self._stack.addWidget(page)
        if section_id not in self._order:
            self._order.append(section_id)

    def has(self, section_id: str) -> bool:
        return section_id in self._pages

    def page(self, section_id: str) -> QWidget | None:
        return self._pages.get(section_id)

    def registered_ids(self) -> list[str]:
        return list(self._order)

    def missing_sections(self) -> list[str]:
        return [s for s in theme.SECTION_ORDER if s not in self._pages]

    # ------------------------------------------------------------- routing --
    def navigate(self, section_id: str) -> bool:
        """Show the page for section_id; returns False when unknown."""
        page = self._pages.get(section_id)
        if page is None:
            return False
        if self._stack.currentWidget() is page:
            # Still refresh the highlight so state can never drift.
            self._sidebar.set_active(section_id)
            return True
        self._stack.setCurrentWidget(page)
        self._sidebar.set_active(section_id)
        self.section_changed.emit(section_id)
        return True

    def current_section(self) -> str | None:
        widget = self._stack.currentWidget()
        for sid, page in self._pages.items():
            if page is widget:
                return sid
        return None

    @property
    def sidebar(self) -> SidebarWidget:
        return self._sidebar

    @property
    def stack(self) -> QStackedWidget:
        return self._stack
