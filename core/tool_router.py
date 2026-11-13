"""Natural-language tool routing: parse a command, gate it, execute it.

The router is the single enforcement choke point for non-phone actions:
1. SecurityManager.is_allowed()          -> emergency stop / access revocation
2. PermissionManager.authorize(action)   -> SAFE / CONFIRM / RESTRICTED
3. AutonomyManager.can_automate(action)  -> trusted vs protected actions

Only after all three gates pass does the underlying controller run.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """A parsed, not-yet-authorized tool invocation."""

    action: str
    description: str
    params: dict[str, Any] = field(default_factory=dict)
    raw: str = ""


class ToolRouter:
    """Parse natural language into ToolCalls and execute them safely."""

    def __init__(
        self,
        *,
        security_manager: Any,
        permission_manager: Any,
        autonomy_manager: Any,
        app_controller: Any = None,
        window_manager: Any = None,
        keyboard_controller: Any = None,
        mouse_controller: Any = None,
        screen_capture: Any = None,
        vision_engine: Any = None,
        file_manager: Any = None,
        terminal: Any = None,
        project_inspector: Any = None,
        web_search: Any = None,
        browser_controller: Any = None,
        spotify_controller: Any = None,
        safety_classifier: Any = None,
        alias_config: Any = None,
        tool_selector: Any = None,
    ) -> None:
        self.security_manager = security_manager
        self.permission_manager = permission_manager
        self.autonomy_manager = autonomy_manager
        self.app_controller = app_controller
        self.window_manager = window_manager
        self.keyboard_controller = keyboard_controller
        self.mouse_controller = mouse_controller
        self.screen_capture = screen_capture
        self.vision_engine = vision_engine
        self.file_manager = file_manager
        self.terminal = terminal
        self.project_inspector = project_inspector
        self.web_search = web_search
        self.browser_controller = browser_controller
        self.spotify_controller = spotify_controller
        # Computer-control layer (three-tier safety, aliases, AI selection).
        if safety_classifier is None:
            from core.computer_tools import SafetyClassifier
            safety_classifier = SafetyClassifier(
                security_manager=security_manager,
                permission_manager=permission_manager,
            )
        self.safety_classifier = safety_classifier
        self.alias_config = alias_config
        self.tool_selector = tool_selector

    # ---------------------------------------------------------------- parsing

    def _patterns(self) -> list[tuple[str, re.Pattern, Callable[[re.Match], ToolCall]]]:
        """Ordered pattern list; first match wins (order encodes priority)."""

        def app_call(m: re.Match) -> ToolCall:
            return ToolCall("open_application", f"Open application {m.group('name')}", {"name": m.group("name")}, m.group(0))

        def close_call(m: re.Match) -> ToolCall:
            return ToolCall("close_application", f"Close application {m.group('name')}", {"name": m.group("name")}, m.group(0))

        def run_call(m: re.Match) -> ToolCall:
            cmd = m.group("cmd").strip().strip("'\"")
            return ToolCall("terminal_execute_safe", f"Run command: {cmd}", {"command": cmd}, m.group(0))

        def url_call(m: re.Match) -> ToolCall:
            return ToolCall("browser_navigate", f"Open URL {m.group('url')}", {"url": m.group("url")}, m.group(0))

        def create_file_call(m: re.Match) -> ToolCall:
            content = m.group("content").strip()
            if len(content) >= 2 and content[0] == content[-1] and content[0] in "\"'":
                content = content[1:-1]
            return ToolCall("create_file", f"Create file {m.group('path')}", {"path": m.group("path"), "content": content.replace("\\n", "\n")}, m.group(0))

        def read_file_call(m: re.Match) -> ToolCall:
            return ToolCall("read_file", f"Read file {m.group('path')}", {"path": m.group("path")}, m.group(0))

        def edit_file_call(m: re.Match) -> ToolCall:
            return ToolCall(
                "edit_file",
                f"Edit file {m.group('path')}",
                {"path": m.group("path"), "old": m.group("old"), "new": m.group("new")},
                m.group(0),
            )

        def append_call(m: re.Match) -> ToolCall:
            content = m.group("content").strip()
            if len(content) >= 2 and content[0] == content[-1] and content[0] in "\"'":
                content = content[1:-1]
            return ToolCall("edit_file", f"Append to {m.group('path')}", {"path": m.group("path"), "append": content}, m.group(0))

        def list_files_call(m: re.Match) -> ToolCall:
            path = m.group("path") or "."
            return ToolCall("list_files", f"List files in {path.strip()}", {"path": path.strip()}, m.group(0))

        def screenshot_call(m: re.Match) -> ToolCall:
            return ToolCall("screenshot", "Take a screenshot", {}, m.group(0))

        def read_screen_call(m: re.Match) -> ToolCall:
            return ToolCall("screenshot", "Capture and understand the screen", {"analyze": True}, m.group(0))

        def search_call(m: re.Match) -> ToolCall:
            return ToolCall("web_search", f"Web search: {m.group('query')}", {"query": m.group("query").strip().strip("'\"")}, m.group(0))

        def spotify_control_call(m: re.Match) -> ToolCall:
            command = (m.group("action") or "volume " + m.group("volume")).lower()
            controls = {
                "play": ("spotify_play", "play_pause"),
                "pause": ("spotify_pause", "play_pause"),
                "resume": ("spotify_play", "play_pause"),
                "skip": ("spotify_skip", "next"),
                "next": ("spotify_skip", "next"),
                "previous": ("spotify_skip", "previous"),
                "volume up": ("spotify_play", "volume_up"),
                "volume down": ("spotify_play", "volume_down"),
            }
            action, control = controls[command]
            return ToolCall(action, f"Spotify {command}", {"control": control}, m.group(0))

        def spotify_search_call(m: re.Match) -> ToolCall:
            query = m.group("query").strip().strip("'\"")
            return ToolCall("spotify_search", f"Search Spotify: {query}",
                            {"query": query}, m.group(0))

        def type_call(m: re.Match) -> ToolCall:
            text = m.group("text").strip()
            if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
                text = text[1:-1]
            return ToolCall("keyboard_type", "Type text", {"text": text}, m.group(0))

        def mouse_move_call(m: re.Match) -> ToolCall:
            return ToolCall("mouse_move", f"Move mouse to ({m.group('x')},{m.group('y')})", {"x": int(m.group("x")), "y": int(m.group("y"))}, m.group(0))

        def mouse_click_call(m: re.Match) -> ToolCall:
            return ToolCall("mouse_click", f"Click at ({m.group('x')},{m.group('y')})", {"x": int(m.group("x")), "y": int(m.group("y"))}, m.group(0))

        def focus_call(m: re.Match) -> ToolCall:
            return ToolCall("switch_window", f"Focus window {m.group('title')}", {"title": m.group("title").strip()}, m.group(0))

        def press_call(m: re.Match) -> ToolCall:
            keys = [k.strip() for k in re.split(r"\s*\+\s*", m.group("keys")) if k.strip()]
            return ToolCall("keyboard_press", f"Press {'+'.join(keys)}", {"keys": keys}, m.group(0))

        def scroll_call(m: re.Match) -> ToolCall:
            amount = int(m.group("amount") or 3)
            direction = m.group("dir").lower()
            return ToolCall("mouse_scroll", f"Scroll {direction} {amount}",
                            {"direction": direction, "amount": amount}, m.group(0))

        def delete_file_call(m: re.Match) -> ToolCall:
            return ToolCall("delete_file", f"Delete file {m.group('path')}",
                            {"path": m.group("path")}, m.group(0))

        def move_file_call(m: re.Match) -> ToolCall:
            return ToolCall("move_file", f"Move file {m.group('src')} to {m.group('dst')}",
                            {"src": m.group("src"), "dst": m.group("dst")}, m.group(0))

        def copy_file_call(m: re.Match) -> ToolCall:
            return ToolCall("copy_file", f"Copy file {m.group('src')} to {m.group('dst')}",
                            {"src": m.group("src"), "dst": m.group("dst")}, m.group(0))

        def search_files_call(m: re.Match) -> ToolCall:
            path = m.group("path") or "."
            return ToolCall("search_files",
                            f"Find files matching {m.group('pattern')} in {path.strip()}",
                            {"pattern": m.group("pattern"), "path": path.strip()}, m.group(0))

        def list_windows_call(m: re.Match) -> ToolCall:
            return ToolCall("list_windows", "List open windows", {}, m.group(0))

        def button_click_call(button: str, clicks: int):
            def builder(m: re.Match) -> ToolCall:
                label = f"{button} click" if clicks == 1 else "double click"
                return ToolCall("mouse_click", f"{label} at ({m.group('x')},{m.group('y')})",
                                {"x": int(m.group("x")), "y": int(m.group("y")),
                                 "button": button, "clicks": clicks}, m.group(0))
            return builder

        right_click_call = button_click_call("right", 1)
        middle_click_call = button_click_call("middle", 1)
        double_click_call = button_click_call("left", 2)

        return [
            ("close_application", re.compile(r"^(?:please\s+)?(?:close|kill)\s+(?:the\s+)?(?:app(?:location)?\s+)?(?P<name>.+?)\.?$", re.IGNORECASE), close_call),
            ("create_file", re.compile(r"^(?:please\s+)?(?:create|make|write)\s+(?:a\s+)?(?:new\s+)?file\s+(?P<path>\S+)\s+(?:with|containing|that\s+contains)\s*(?P<content>.+)$", re.IGNORECASE), create_file_call),
            ("edit_file", re.compile(r"^(?:please\s+)?(?:edit|replace)\s+(?:the\s+)?file\s+(?P<path>\S+)\s+(?:replacing\s+|replace\s+|changing\s+)?[\"']?(?P<old>.+?)[\"']?\s+with\s+[\"']?(?P<new>.+?)[\"']?$", re.IGNORECASE), edit_file_call),
            ("append", re.compile(r"^(?:please\s+)?append\s+(?P<content>.+?)\s+to\s+(?:file\s+)?(?P<path>\S+)$", re.IGNORECASE), append_call),
            ("read_file", re.compile(r"^(?:please\s+)?(?:read|show|cat)\s+(?:the\s+)?(?:file\s+)?(?P<path>\S+\.\w+)$", re.IGNORECASE), read_file_call),
            ("list_files", re.compile(r"^(?:please\s+)?(?:list|show)\s+(?:the\s+)?files(?:\s+(?:in|of)\s+(?P<path>.+))?$", re.IGNORECASE), list_files_call),
            ("screenshot_read", re.compile(r"^(?:please\s+)?(?:read|analyze|describe|understand|check)\s+(?:the\s+)?(?:current\s+)?(?:screen|display)$", re.IGNORECASE), read_screen_call),
            ("screenshot", re.compile(r"^(?:please\s+)?(?:take\s+a?\s*)?(?:screenshot|capture\s+(?:the\s+)?screen)(?:\s+(?:of\s+the\s+screen))?$", re.IGNORECASE), screenshot_call),
            ("web_search", re.compile(r"^(?:please\s+)?(?:search\s+(?:the\s+)?web(?:\s+for)?|web\s+search(?:\s+for)?|search\s+for|google)\s+(?P<query>.+)$", re.IGNORECASE), search_call),
            ("spotify_search", re.compile(r"^(?:please\s+)?(?:search\s+spotify\s+for|find\s+(?:a\s+)?(?:song|track)\s+on\s+spotify)\s+(?P<query>.+)$", re.IGNORECASE), spotify_search_call),
            ("spotify_control", re.compile(r"^(?:please\s+)?(?:(?P<action>play|pause|resume|skip|next|previous)(?:\s+(?:on\s+)?spotify|\s+(?:music|track|song))|volume\s+(?P<volume>up|down))$", re.IGNORECASE), spotify_control_call),
            ("browser", re.compile(r"^(?:please\s+)?(?:open|visit|go\s+to|navigate\s+to)\s+(?P<url>(?:https?://\S+)|(?:[\w-]+(?:\.[\w-]+)+(?:/\S*)?))$", re.IGNORECASE), url_call),
            ("open_app", re.compile(r"^(?:please\s+)?(?:open|launch|start)\s+(?:the\s+)?(?:app(?:location)?\s+)?(?P<name>.+?)\.?$", re.IGNORECASE), app_call),
            ("type", re.compile(r"^(?:please\s+)?(?:type|write)\s+[\"']?(?P<text>.+?)[\"']?$", re.IGNORECASE), type_call),
            ("mouse_move", re.compile(r"^(?:please\s+)?move\s+(?:the\s+)?mouse\s+to\s+(?P<x>\d+)\s*,?\s*(?P<y>\d+)$", re.IGNORECASE), mouse_move_call),
            ("mouse_click", re.compile(r"^(?:please\s+)?click(?:\s+at)?\s+(?P<x>\d+)\s*,?\s*(?P<y>\d+)$", re.IGNORECASE), mouse_click_call),
            ("right_click", re.compile(r"^(?:please\s+)?right[\s-]?click(?:\s+at)?\s+(?P<x>\d+)\s*,?\s*(?P<y>\d+)$", re.IGNORECASE), right_click_call),
            ("middle_click", re.compile(r"^(?:please\s+)?middle[\s-]?click(?:\s+at)?\s+(?P<x>\d+)\s*,?\s*(?P<y>\d+)$", re.IGNORECASE), middle_click_call),
            ("double_click", re.compile(r"^(?:please\s+)?double[\s-]?click(?:\s+at)?\s+(?P<x>\d+)\s*,?\s*(?P<y>\d+)$", re.IGNORECASE), double_click_call),
            ("press", re.compile(r"^(?:please\s+)?(?:press|hit)\s+(?P<keys>[\w#+]+(?:\s*\+\s*[\w#+]+)*)$", re.IGNORECASE), press_call),
            ("scroll", re.compile(r"^(?:please\s+)?scroll\s+(?P<dir>up|down)(?:\s+(?P<amount>\d+))?(?:\s+(?:notches|clicks|steps))?$", re.IGNORECASE), scroll_call),
            ("delete_file", re.compile(r"^(?:please\s+)?(?:delete|remove)\s+(?:the\s+)?file\s+(?P<path>\S+)$", re.IGNORECASE), delete_file_call),
            ("move_file", re.compile(r"^(?:please\s+)?move\s+(?:the\s+)?file\s+(?P<src>\S+)\s+to\s+(?P<dst>\S+)$", re.IGNORECASE), move_file_call),
            ("copy_file", re.compile(r"^(?:please\s+)?copy\s+(?:the\s+)?file\s+(?P<src>\S+)\s+to\s+(?P<dst>\S+)$", re.IGNORECASE), copy_file_call),
            ("search_files", re.compile(r"^(?:please\s+)?(?:find|search)(?:\s+for)?\s+(?:the\s+)?files?\s+(?:named\s+|called\s+|matching\s+)?(?P<pattern>\S+)(?:\s+(?:in|under)\s+(?P<path>.+))?$", re.IGNORECASE), search_files_call),
            ("list_windows", re.compile(r"^(?:please\s+)?(?:list|show)\s+(?:the\s+)?(?:open\s+)?windows$", re.IGNORECASE), list_windows_call),
            ("focus", re.compile(r"^(?:please\s+)?(?:focus|switch\s+to)\s+(?P<title>.+)$", re.IGNORECASE), focus_call),
            ("run", re.compile(r"^(?:please\s+)?(?:run|execute)\s+(?:the\s+)?(?:command\s+)?[:>]?\s*(?P<cmd>.+)$", re.IGNORECASE), run_call),
        ]

    def parse(self, message: str) -> ToolCall | None:
        """Parse a single tool command; returns None when no tool matches."""
        text = message.strip()
        text = re.sub(r"^(?:then|and|also)\s+", "", text, flags=re.IGNORECASE)
        if self.alias_config is not None:
            # User aliases + Windows known-folder tokens expand first.
            text = self.alias_config.expand(text)
        if not text:
            return None
        for _name, pattern, builder in self._patterns():
            match = pattern.match(text)
            if match:
                return builder(match)
        return None

    @staticmethod
    def _split_multi(message: str) -> list[str]:
        """Split multi-step commands on ';', ' then ', and ' and <verb>'."""
        parts = [message]
        for sep in (";", " then "):
            next_parts: list[str] = []
            for part in parts:
                next_parts.extend(re.split(rf"\s*{re.escape(sep)}\s*", part, flags=re.IGNORECASE))
            parts = next_parts
        verb = (r"(?:open|run|create|read|edit|append|take|search|list|type|close|move|"
                r"click|focus|press|hit|scroll|delete|remove|copy|find)")
        next_parts = []
        for part in parts:
            next_parts.extend(re.split(rf"\s+and\s+(?={verb}\b)", part, flags=re.IGNORECASE))
        parts = next_parts
        return [p.strip() for p in parts if p.strip()]

    def parse_all(self, message: str, *, ai_fallback: bool = False) -> list[ToolCall]:
        """Parse every tool command found in the message, in order.

        Deterministic regex patterns always run first. With ``ai_fallback``
        (chat path), segments the patterns cannot match are offered to the AI
        tool selector (if configured) so free-form requests still map to
        registered tools. AI output is validated by the selector itself and
        re-gated by execute().
        """
        calls: list[ToolCall] = []
        for segment in self._split_multi(message):
            call = self.parse(segment)
            if call is None and ai_fallback and self.tool_selector is not None:
                try:
                    picked = self.tool_selector.select(segment)
                except Exception:
                    picked = []
                call = picked[0] if picked else None
            if call is not None:
                calls.append(call)
        return calls

    # -------------------------------------------------------------- execution

    def _dispatch(self, call: ToolCall) -> dict[str, Any]:
        action = call.action
        p = call.params
        if action == "open_application":
            return self.app_controller.open_application(p["name"])
        if action == "close_application":
            return self.app_controller.close_application(p["name"])
        if action == "switch_window":
            return self.window_manager.focus_window(p["title"])
        if action == "terminal_execute_safe":
            return self.terminal.run(
                p["command"], allow_dangerous=bool(p.get("allow_dangerous", False))
            )
        if action == "terminal_execute_dangerous":
            # Only reachable after SafetyClassifier saw confirmed=True.
            return self.terminal.run(p["command"], allow_dangerous=True)
        if action == "create_file":
            return self.file_manager.create(p["path"], p.get("content", ""))
        if action == "edit_file":
            if "append" in p:
                return self.file_manager.append(p["path"], p["append"])
            return self.file_manager.edit(p["path"], p["old"], p["new"])
        if action == "read_file":
            return self.file_manager.read(p["path"])
        if action == "list_files":
            return self.file_manager.list_files(p.get("path", "."))
        if action == "screenshot":
            shot = self.screen_capture.capture_full()
            if shot.get("success") and p.get("analyze"):
                shot["analysis"] = self.vision_engine.analyze(shot["path"])
            return shot
        if action == "web_search":
            return self.web_search.search(p["query"])
        if action == "browser_navigate":
            return self.browser_controller.open(p["url"])
        if action in {"spotify_play", "spotify_pause", "spotify_skip"}:
            return self.spotify_controller.control(p["control"])
        if action == "spotify_search":
            return self.spotify_controller.search(p["query"])
        if action == "keyboard_type":
            return self.keyboard_controller.type_text(p["text"])
        if action == "mouse_move":
            return self.mouse_controller.move_to(p["x"], p["y"])
        if action == "mouse_click":
            return self.mouse_controller.click(
                p["x"], p["y"],
                button=p.get("button", "left"),
                clicks=int(p.get("clicks", 1)),
            )
        if action == "mouse_scroll":
            return self.mouse_controller.scroll(
                p.get("direction", "down"), int(p.get("amount", 3))
            )
        if action == "keyboard_press":
            keys = p.get("keys") or []
            if isinstance(keys, str):
                keys = [keys]
            return self.keyboard_controller.press(*keys)
        if action == "delete_file":
            return self.file_manager.delete(p["path"])
        if action == "move_file":
            return self.file_manager.move(p["src"], p["dst"])
        if action == "copy_file":
            return self.file_manager.copy(p["src"], p["dst"])
        if action == "search_files":
            return self.file_manager.search(p.get("pattern", "*"), p.get("path", "."))
        if action == "list_windows":
            windows = self.window_manager.list_windows()
            return {"success": True, "windows": windows, "count": len(windows)}
        return {"success": False, "error": f"No handler for action {action}"}

    def execute(self, call: ToolCall, *, confirmed: bool = False) -> dict[str, Any]:
        """Gate a tool call through security, three-tier safety, and autonomy.

        confirmed=True marks an explicit user approval (confirmation dialog);
        it unlocks CONFIRM-tier actions but never BLOCK-tier ones.
        """
        # Gate 1: emergency stop / access revocation always wins (local, non-AI).
        if not self.security_manager.is_allowed():
            self.security_manager.log_event(
                event="action_blocked_security",
                detail=f"{call.action} blocked",
                metadata={"action": call.action},
            )
            return {
                "success": False,
                "action": call.action,
                "error": "Blocked by security manager (emergency stop or access revoked)",
            }

        # Gate 2: three-tier safety classification (SAFE / CONFIRM / BLOCK).
        decision = self.safety_classifier.classify(call.action, call.params, confirmed=confirmed)
        if decision.tier == "block":
            self.security_manager.log_event(
                event="action_blocked_policy",
                detail=f"{call.action} blocked: {decision.reason}",
                metadata={"action": call.action, "reason": decision.reason},
            )
            return {"success": False, "action": call.action, "error": decision.reason}
        if decision.tier == "confirm" and not confirmed:
            self.security_manager.log_event(
                event="action_needs_confirmation",
                detail=f"{call.action} requires confirmation",
                metadata={"action": call.action},
            )
            return {
                "success": False,
                "action": call.action,
                "error": "Action requires explicit user confirmation (CONFIRM level); not executed autonomously",
                "confirmation_required": True,
            }
        if confirmed and decision.tier == "confirm":
            self.security_manager.log_event(
                event="action_confirmed",
                detail=f"{call.action} approved by user",
                metadata={"action": call.action},
            )
            # A user-confirmed dangerous shell command may proceed: thread the
            # confirmation through to the terminal dispatch layer.
            if decision.action == "terminal_execute_dangerous":
                call.params["allow_dangerous"] = True

        # Gate 3: autonomy policy (user-confirmed actions skip it - the user
        # decided; autonomy governs *unattended* execution only).
        if not confirmed and not self.autonomy_manager.can_automate(call.action):
            self.security_manager.log_event(
                event="action_refused_autonomy",
                detail=f"{call.action} refused by autonomy policy",
                metadata={"action": call.action},
            )
            return {"success": False, "action": call.action, "error": "Autonomy policy refused this action"}

        # All gates passed: execute for real.
        try:
            result = self._dispatch(call)
        except Exception as exc:
            result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        result.setdefault("success", False)
        result["action"] = call.action
        result["description"] = call.description
        self.security_manager.log_event(
            event="action_executed" if result.get("success") else "action_failed",
            detail=f"{call.action}: {'ok' if result.get('success') else result.get('error', 'failed')}",
            metadata={"action": call.action, "confirmed": confirmed},
        )
        return result




