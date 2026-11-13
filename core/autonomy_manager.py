from __future__ import annotations

from enum import Enum


class AutonomyLevel(str, Enum):
    MINIMUM = "minimum"
    NORMAL = "normal"
    ADVANCED = "advanced"
    MAXIMUM = "maximum"


class AutonomyManager:
    """Manages which classes of action may be executed autonomously.

    Autonomy is configured by the user and respected by the action execution
    layer. The AI cannot change autonomy settings itself.
    """

    def __init__(self, *, mode: AutonomyLevel = AutonomyLevel.MAXIMUM) -> None:
        self.mode = mode
        self.trusted_actions: set[str] = self._default_trusted_actions()
        self.protected_actions: set[str] = self._default_protected_actions()
        self.active = True

    def _default_trusted_actions(self) -> set[str]:
        return {
            "read_file",
            "list_files",
            "screenshot",
            "open_application",
            "close_application",
            "switch_window",
            "move_window",
            "resize_window",
            "mouse_move",
            "mouse_click",
            "mouse_scroll",
            "keyboard_type",
            "keyboard_press",
            "list_windows",
            "search_files",
            "web_navigation",
            "web_search",
            "terminal_execute_safe",
            "initiate_build",
            "run_tests",
            "project_inspect",
            "move_file",
            "copy_file",
            "rename_file",
            "create_file",
            "edit_file",
            "spotify_play",
            "spotify_pause",
            "spotify_skip",
            "spotify_search",
            "google_search",
            "browser_navigate",
            "browser_search",
            "browser_click",
            "browser_type",
            "browser_scroll",
            "browser_read_content",
        }

    def _default_protected_actions(self) -> set[str]:
        return {
            "delete_file",
            "delete_directory",
            "send_email",
            "send_message",
            "post_discord",
            "modify_discord_settings",
            "git_push",
            "git_delete_branch",
            "terminal_execute_dangerous",
            "security_setting_change",
        }

    def set_mode(self, mode: AutonomyLevel) -> None:
        self.mode = mode

    def can_automate(self, action: str) -> bool:
        if not self.active:
            return False
        if action in self.protected_actions:
            return False
        if action in self.trusted_actions:
            return True
        return self.mode in (AutonomyLevel.MAXIMUM, AutonomyLevel.ADVANCED)

    def supports_autonomous_execution(self) -> bool:
        return self.active and self.mode in (AutonomyLevel.MAXIMUM, AutonomyLevel.ADVANCED, AutonomyLevel.NORMAL)

    def pause(self) -> None:
        self.active = False

    def resume(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False
