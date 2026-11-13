"""Global hotkey manager for MAMBA AI."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import keyboard

logger = logging.getLogger(__name__)

class HotkeyManager:
    """
    Listens for a global hotkey (default: Ctrl+Space) and triggers a callback.
    Runs in a background thread to avoid blocking the UI.
    """

    def __init__(self, hotkey: str = "ctrl+space", callback: Callable[[], None] | None = None) -> None:
        self.hotkey = hotkey
        self.callback = callback
        self._listener_thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        """Register the hotkey and start the listener thread."""
        if self._running:
            return

        self._running = True
        self._listener_thread = threading.Thread(target=self._listen, daemon=True)
        self._listener_thread.start()
        logger.info(f"Global hotkey listener started for {self.hotkey}")

    def stop(self) -> None:
        """Stop listening for the hotkey."""
        self._running = False
        try:
            keyboard.remove_hotkey(self.hotkey)
        except Exception:
            pass
        logger.info("Global hotkey listener stopped")

    def _listen(self) -> None:
        """The loop that waits for the hotkey to be pressed."""
        try:
            # Use keyboard.add_hotkey for an event-driven approach
            keyboard.add_hotkey(self.hotkey, self._on_triggered)
            # Keep the thread alive
            while self._running:
                import time
                time.sleep(1)
        except Exception as e:
            logger.error(f"Hotkey listener thread error: {e}")
            self._running = False

    def _on_triggered(self) -> None:
        """Callback when the hotkey is pressed."""
        if self.callback:
            logger.info(f"Hotkey {self.hotkey} triggered")
            self.callback()
        else:
            logger.warning("Hotkey triggered but no callback provided")
