from __future__ import annotations

from core.autonomy_manager import AutonomyManager
from core.permission_manager import PermissionLevel, PermissionManager
from core.security_manager import SecurityManager
from core.tool_router import ToolRouter
from integrations.discord import DiscordController


class FakeSecretStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def store(self, name: str, value: str) -> None:
        self.values[name] = value

    def retrieve(self, name: str, *, env_fallback: str | None = None) -> str | None:
        return self.values.get(name)

    def exists(self, name: str, *, env_fallback: str | None = None) -> bool:
        return name in self.values

    def delete(self, name: str) -> bool:
        return self.values.pop(name, None) is not None


class FakeSpotifyController:
    def control(self, action: str) -> dict[str, object]:
        return {"success": True, "action": action}

    def search(self, query: str) -> dict[str, object]:
        return {"success": True, "query": query}


def make_router(spotify: FakeSpotifyController) -> ToolRouter:
    return ToolRouter(
        security_manager=SecurityManager(),
        permission_manager=PermissionManager(),
        autonomy_manager=AutonomyManager(),
        spotify_controller=spotify,
    )


def test_spotify_voice_commands_use_guarded_router() -> None:
    router = make_router(FakeSpotifyController())

    pause = router.parse("pause Spotify")
    next_track = router.parse("next track")
    volume = router.parse("volume up")

    assert pause is not None
    assert pause.action == "spotify_pause"
    assert router.execute(pause)["success"] is True
    assert next_track is not None
    assert next_track.params["control"] == "next"
    assert router.execute(next_track)["success"] is True
    assert volume is not None
    assert volume.params["control"] == "volume_up"
    assert router.execute(volume)["success"] is True


def test_browser_commands_still_parse() -> None:
    router = make_router(FakeSpotifyController())

    assert router.parse("open https://example.com").action == "browser_navigate"
    assert router.parse("search the web for weather").action == "web_search"


def test_discord_post_requires_confirmation_and_policy_allows_it() -> None:
    secrets = FakeSecretStore()
    permissions = PermissionManager()
    controller = DiscordController(
        secrets, SecurityManager(), permission_manager=permissions
    )
    controller.configure("test-discord-token-long-enough")

    denied = controller.send_message("12345678901234567", "hello")
    assert denied["success"] is False
    assert "confirmation" in denied["error"]

    permissions.set_override("post_discord", PermissionLevel.RESTRICTED)
    forbidden = controller.send_message(
        "12345678901234567", "hello", confirmed=True
    )
    assert forbidden["success"] is False
    assert "forbidden" in forbidden["error"]
