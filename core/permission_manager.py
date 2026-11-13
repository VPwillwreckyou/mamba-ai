from __future__ import annotations

from enum import Enum


class PermissionLevel(str, Enum):
    SAFE = "safe"
    CONFIRM = "confirm"
    RESTRICTED = "restricted"


class PermissionManager:
    """Security authorization layer for actions.

    The permission manager classifies actions and decides whether a requested
    action may proceed, must be confirmed by the user, or is forbidden.

    Security policy is authoritative. The AI or memory must not be able to
    change these rules through normal operations.
    """

    def __init__(self) -> None:
        self._policy: dict[str, PermissionLevel] = self._default_policy()
        self._overrides: dict[str, PermissionLevel] = {}

    def _default_policy(self) -> dict[str, PermissionLevel]:
        return {
            "search": PermissionLevel.SAFE,
            "read_file": PermissionLevel.SAFE,
            "list_files": PermissionLevel.SAFE,
            "screenshot": PermissionLevel.SAFE,
            "open_application": PermissionLevel.SAFE,
            "close_application": PermissionLevel.SAFE,
            "switch_window": PermissionLevel.SAFE,
            "move_window": PermissionLevel.SAFE,
            "resize_window": PermissionLevel.SAFE,
            "mouse_move": PermissionLevel.SAFE,
            "mouse_click": PermissionLevel.SAFE,
            "mouse_scroll": PermissionLevel.SAFE,
            "keyboard_type": PermissionLevel.SAFE,
            "keyboard_press": PermissionLevel.SAFE,
            "list_windows": PermissionLevel.SAFE,
            "search_files": PermissionLevel.SAFE,
            "web_navigation": PermissionLevel.SAFE,
            "browser_navigate": PermissionLevel.SAFE,
            "web_search": PermissionLevel.SAFE,
            "terminal_read_output": PermissionLevel.SAFE,
            "terminal_execute_safe": PermissionLevel.SAFE,
            "initiate_build": PermissionLevel.SAFE,
            "run_tests": PermissionLevel.SAFE,
            "project_inspect": PermissionLevel.SAFE,
            "delete_file": PermissionLevel.CONFIRM,
            "delete_directory": PermissionLevel.CONFIRM,
            "move_file": PermissionLevel.SAFE,
            "copy_file": PermissionLevel.SAFE,
            "rename_file": PermissionLevel.SAFE,
            "create_file": PermissionLevel.SAFE,
            "edit_file": PermissionLevel.SAFE,
            "send_email": PermissionLevel.CONFIRM,
            "send_message": PermissionLevel.CONFIRM,
            "post_discord": PermissionLevel.CONFIRM,
            "modify_discord_settings": PermissionLevel.CONFIRM,
            "spotify_play": PermissionLevel.SAFE,
            "spotify_pause": PermissionLevel.SAFE,
            "spotify_skip": PermissionLevel.SAFE,
            "spotify_search": PermissionLevel.SAFE,
            "git_commit": PermissionLevel.SAFE,
            "git_push": PermissionLevel.CONFIRM,
            "git_force_push": PermissionLevel.RESTRICTED,
            "git_destructive_reset": PermissionLevel.RESTRICTED,
            "git_delete_branch": PermissionLevel.CONFIRM,
            "terminal_execute_dangerous": PermissionLevel.CONFIRM,
            "security_setting_change": PermissionLevel.CONFIRM,
            "disable_security": PermissionLevel.RESTRICTED,
            "credential_export": PermissionLevel.RESTRICTED,
            "account_bypass": PermissionLevel.RESTRICTED,
            "captcha_bypass": PermissionLevel.RESTRICTED,
            "bypass_permission": PermissionLevel.RESTRICTED,
        }

    def set_override(self, action: str, level: PermissionLevel) -> None:
        """Temporarily override the effective policy for a specific action.

        This is intentionally limited and must not be used by the AI to weaken
        the security posture.
        """
        self._overrides[action] = level

    def clear_override(self, action: str) -> None:
        self._overrides.pop(action, None)

    def level_for(self, action: str) -> PermissionLevel:
        """Return the effective permission level for an action."""
        if action in self._overrides:
            return self._overrides[action]
        return self._policy.get(action, PermissionLevel.CONFIRM)

    def may_execute(self, action: str) -> bool:
        return self.level_for(action) == PermissionLevel.SAFE

    def requires_confirmation(self, action: str) -> bool:
        return self.level_for(action) == PermissionLevel.CONFIRM

    def is_forbidden(self, action: str) -> bool:
        return self.level_for(action) == PermissionLevel.RESTRICTED

    def authorize(self, action: str) -> str:
        """Return the authorization outcome for an action as a string.

        Returns one of: allowed, confirmation_required, forbidden.
        """
        if self.is_forbidden(action):
            return "forbidden"
        if self.may_execute(action):
            return "allowed"
        return "confirmation_required"
