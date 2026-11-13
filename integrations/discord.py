"""Secure Discord bot status and channel messaging."""
from __future__ import annotations

import re
from typing import Any

import httpx


class DiscordController:
    """Use a stored Discord bot token for identity checks and message posting."""

    TOKEN_NAME = "DISCORD_BOT_TOKEN"
    API_BASE = "https://discord.com/api/v10"

    def __init__(self, secret_store: Any,
                 security_manager: Any | None = None,
                 permission_manager: Any | None = None) -> None:
        self._secret_store = secret_store
        self._security_manager = security_manager
        self._permission_manager = permission_manager

    def configured(self) -> bool:
        return self._secret_store.exists(self.TOKEN_NAME)

    def configure(self, token: str) -> None:
        cleaned = token.strip()
        if len(cleaned) < 20:
            raise ValueError("Discord bot token is too short")
        self._secret_store.store(self.TOKEN_NAME, cleaned)

    def remove_token(self) -> bool:
        return self._secret_store.delete(self.TOKEN_NAME)

    def test_connection(self) -> dict[str, Any]:
        token = self._secret_store.retrieve(self.TOKEN_NAME)
        if not token:
            return {"success": False, "error": "No Discord bot token is configured"}
        try:
            response = httpx.get(
                f"{self.API_BASE}/users/@me",
                headers={"Authorization": f"Bot {token}"},
                timeout=12.0,
                follow_redirects=False,
            )
            if response.status_code == 401:
                return {"success": False, "error": "Discord rejected the bot token"}
            response.raise_for_status()
            user = response.json()
            return {
                "success": True,
                "username": user.get("username", "Discord bot"),
                "bot_id": user.get("id", ""),
            }
        except httpx.HTTPError as exc:
            return {"success": False, "error": f"Discord connection failed: {exc}"}

    def send_message(self, channel_id: str, content: str,
                     *, confirmed: bool = False) -> dict[str, Any]:
        if self._security_manager is not None and not self._security_manager.is_allowed():
            return {"success": False, "error": "Blocked by security manager"}
        if self._permission_manager is not None:
            permission = self._permission_manager.authorize("post_discord")
            if permission == "forbidden":
                return {"success": False, "error": "Discord posting is forbidden by policy"}
            if permission == "confirmation_required" and not confirmed:
                return {"success": False, "error": "Discord posting requires explicit confirmation"}
        token = self._secret_store.retrieve(self.TOKEN_NAME)
        if not token:
            return {"success": False, "error": "No Discord bot token is configured"}
        channel = channel_id.strip()
        message = content.strip()
        if not re.fullmatch(r"\d{17,20}", channel):
            return {"success": False, "error": "Enter a valid Discord channel ID"}
        if not message or len(message) > 2000:
            return {"success": False, "error": "Message must contain 1 to 2000 characters"}
        try:
            response = httpx.post(
                f"{self.API_BASE}/channels/{channel}/messages",
                headers={"Authorization": f"Bot {token}"},
                json={"content": message, "allowed_mentions": {"parse": []}},
                timeout=12.0,
            )
            if response.status_code == 401:
                return {"success": False, "error": "Discord rejected the bot token"}
            if response.status_code == 403:
                return {"success": False, "error": "The bot cannot post in that channel"}
            response.raise_for_status()
            posted = response.json()
            return {
                "success": True,
                "channel_id": channel,
                "message_id": posted.get("id", ""),
                "detail": "Message posted to Discord",
            }
        except httpx.HTTPError as exc:
            return {"success": False, "error": f"Discord message failed: {exc}"}
