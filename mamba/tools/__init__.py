"""Computer control tool layer.

Exports a clean interface to the planning/LLM layer so the AI can call
atomic, verifiable Windows actions. These functions are designed to be
threadsafe, exception-safe, and compatible with async bridges.
"""

from __future__ import annotations

from mamba.tools.computer_keyboard import (
    ensure_key,
    keyboard_hotkey,
    keyboard_paste,
    keyboard_press,
    keyboard_type,
)

from mamba.tools.task_engine import (
    TaskState,
    _execute_tool_chain,
    is_stop_requested,
    request_stop,
    reset_stop_flag,
)

__all__ = [
    "TaskState",
    "_execute_tool_chain",
    "ensure_key",
    "is_stop_requested",
    "keyboard_hotkey",
    "keyboard_paste",
    "keyboard_press",
    "keyboard_type",
    "request_stop",
    "reset_stop_flag",
]

from mamba.tools.application_resolver_part1 import (
    discover_applications,
    get_app_paths,
    get_known_app,
    resolve_app_identifier,
)
from mamba.tools.application_resolver_part2 import (
    _APPLICATION_CACHE,
    _EXECUTABLE_ALIASES,
    _KNOWN_DIRS,
    _MANIFEST_KEYS,
    _REGISTRY_KEYS,
    _START_MENU_PATHS,
    _merge_dict,
    _read_registry_string,
    _read_user_alias_file,
    _scan_executable_dirs,
    _scan_registration,
    _scan_start_menu,
)
from mamba.tools.computer_mouse import (
    mouse_click,
    mouse_double_click,
    mouse_drag,
    mouse_move,
    mouse_position,
    mouse_right_click,
    mouse_scroll,
)
from mamba.tools.computer_mouse import (
    mouse_position as get_mouse_position,
)
from mamba.tools.computer_screen import (
    capture_for_llm,
    get_active_window_title,
    screenshot,
)
from mamba.tools.filesystem import known_folder
from mamba.tools.filesystem import resolve as resolve_path
