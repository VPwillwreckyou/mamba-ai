"""Computer-control tool layer: tool registry, safety classifier, aliases.

This module is the definition layer for MAMBA's general-purpose PC control
(keyboard, mouse, screen, filesystem, apps, windows, terminal, web). It does
NOT execute anything itself; the execution choke point stays
``core.tool_router.ToolRouter.execute``. What lives here:

* ``ToolSpec`` / ``COMPUTER_TOOLS`` - declarative registry of the control
  tools, used for AI-driven tool selection (schema prompt) and validation.
* ``SafetyClassifier`` - single source of truth for the three-tier safety
  decision (safe / confirm / block). It delegates policy to the existing
  ``PermissionManager`` and the local emergency stop to ``SecurityManager``,
  and adds a parameter-aware rule: dangerous shell commands are never executed
  autonomously (blocked), regardless of AI output.
* ``AliasConfig`` - user-configurable phrase aliases (``data/aliases.json``)
  plus Windows known-folder tokens (``{desktop}`` etc.) resolved through the
  ``SHGetKnownFolderPath`` API.
* ``ToolSelector`` - AI-driven tool selection: asks the configured AI provider
  to choose tool(s) from the registry for free-form text and returns validated
  ``ToolCall``s. Any failure (no provider, bad JSON, unknown tool) degrades to
  "no selection" so the deterministic regex patterns remain the fallback.
"""
from __future__ import annotations

import asyncio
import ctypes
import json
import os
import re
import uuid as uuid_mod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --------------------------------------------------------------- known folders
# Windows Known Folder GUIDs (KNOWNFOLDERID), used with SHGetKnownFolderPath.
_KNOWN_FOLDER_GUIDS: dict[str, str] = {
    "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "documents": "{FDD39AD0-238F-46AF-ADB2-0D55FB55A9E5}",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
    "videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
    "appdata": "{3EB685DB-65F9-4CF6-A03A-E7EF64AEBF39}",
    "localappdata": "{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}",
}


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _env_fallback(key: str) -> str | None:
    """Best-effort environment fallback when the Known Folder API is unavailable."""
    home = Path.home()
    candidates = {
        "desktop": home / "Desktop",
        "documents": home / "Documents",
        "downloads": home / "Downloads",
        "pictures": home / "Pictures",
        "music": home / "Music",
        "videos": home / "Videos",
        "appdata": Path(os.getenv("APPDATA", home / "AppData" / "Roaming")),
        "localappdata": Path(os.getenv("LOCALAPPDATA", home / "AppData" / "Local")),
    }
    target = candidates.get(key)
    if target is None:
        return None
    return str(target)


def known_folder(name: str) -> str | None:
    """Resolve a Windows known folder (``desktop``, ``downloads``, ...) by name.

    Uses the ``SHGetKnownFolderPath`` API; falls back to well-known environment
    locations when the API is unavailable (non-Windows, API failure). Returns
    None for unknown names.
    """
    key = name.strip().lower().strip("{}")
    guid_text = _KNOWN_FOLDER_GUIDS.get(key)
    if guid_text is None:
        return None
    if os.name != "nt":
        return _env_fallback(key)
    try:
        u = uuid_mod.UUID(guid_text)
        guid = _GUID(u.time_low, u.time_mid, u.time_hi_version,
                     (ctypes.c_ubyte * 8)(*u.bytes[8:]))
        path_ptr = ctypes.c_wchar_p()
        hr = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(path_ptr)
        )
        if hr != 0 or not path_ptr.value:
            return _env_fallback(key)
        result = path_ptr.value
        try:
            ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(path_ptr, ctypes.c_void_p))
        except Exception:
            pass
        return result
    except Exception:
        return _env_fallback(key)



# -------------------------------------------------------------- tool registry
@dataclass(frozen=True)
class ToolSpec:
    """Declarative definition of one computer-control tool."""

    name: str            # name the AI selector must return
    category: str        # keyboard | mouse | screen | filesystem | apps | windows | terminal | web
    description: str     # one-line description used in the selection prompt
    action: str          # ToolRouter action id the spec maps to
    params: dict[str, str] = field(default_factory=dict)      # param -> hint
    default_params: dict[str, Any] = field(default_factory=dict)

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "params": self.params,
        }


COMPUTER_TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec("type_text", "keyboard",
                 "Type a string of text at the current cursor position.",
                 "keyboard_type", {"text": "the exact text to type"}),
        ToolSpec("press_key", "keyboard",
                 "Press a key or hotkey combination (e.g. enter, ctrl+s, alt+tab).",
                 "keyboard_press", {"keys": "list of keys, e.g. ['ctrl','s']"}),
        ToolSpec("move_mouse", "mouse",
                 "Move the mouse cursor to screen coordinates.",
                 "mouse_move", {"x": "pixel x", "y": "pixel y"}),
        ToolSpec("click_mouse", "mouse",
                 "Click at coordinates; optionally right/middle button or double click.",
                 "mouse_click",
                 {"x": "pixel x", "y": "pixel y", "button": "left|right|middle",
                  "clicks": "1 or 2"}),
        ToolSpec("scroll_mouse", "mouse",
                 "Scroll the mouse wheel up or down.",
                 "mouse_scroll", {"direction": "up|down", "amount": "notches"}),
        ToolSpec("screenshot", "screen",
                 "Capture a screenshot of the full screen.",
                 "screenshot", {}),
        ToolSpec("read_screen", "screen",
                 "Capture the screen and analyze/OCR what is visible.",
                 "screenshot", {"ocr": "also run OCR when available"},
                 {"analyze": True}),
        ToolSpec("list_files", "filesystem",
                 "List entries of a directory inside the workspace.",
                 "list_files", {"path": "directory path"}),
        ToolSpec("read_file", "filesystem",
                 "Read a text file inside the workspace.",
                 "read_file", {"path": "file path"}),
        ToolSpec("create_file", "filesystem",
                 "Create a new file with content inside the workspace.",
                 "create_file", {"path": "file path", "content": "file content"}),
        ToolSpec("edit_file", "filesystem",
                 "Replace text inside an existing file.",
                 "edit_file", {"path": "file path", "old": "exact text to replace",
                               "new": "replacement text"}),
        ToolSpec("delete_file", "filesystem",
                 "Delete a file (requires user confirmation).",
                 "delete_file", {"path": "file path"}),
        ToolSpec("move_file", "filesystem",
                 "Move/rename a file inside the workspace.",
                 "move_file", {"src": "source path", "dst": "destination path"}),
        ToolSpec("copy_file", "filesystem",
                 "Copy a file inside the workspace.",
                 "copy_file", {"src": "source path", "dst": "destination path"}),
        ToolSpec("search_files", "filesystem",
                 "Find files by name pattern inside the workspace.",
                 "search_files", {"pattern": "name pattern, e.g. *.txt",
                                  "path": "directory to search"}),
        ToolSpec("open_application", "apps",
                 "Open/launch a desktop application.",
                 "open_application", {"name": "application name"}),
        ToolSpec("close_application", "apps",
                 "Close a running desktop application.",
                 "close_application", {"name": "application name"}),
        ToolSpec("switch_window", "windows",
                 "Focus a window by (partial) title.",
                 "switch_window", {"title": "window title substring"}),
        ToolSpec("list_windows", "windows",
                 "List currently visible windows.",
                 "list_windows", {}),
        ToolSpec("run_command", "terminal",
                 "Run a shell command and return real output "
                 "(dangerous commands are blocked).",
                 "terminal_execute_safe", {"command": "the shell command"}),
        ToolSpec("web_search", "web",
                 "Search the web and return results.",
                 "web_search", {"query": "search query"}),
        ToolSpec("browser_navigate", "web",
                 "Open a URL in the browser.",
                 "browser_navigate", {"url": "absolute URL"}),
    )
}


# ------------------------------------------------------------ safety classifier
TIER_SAFE = "safe"
TIER_CONFIRM = "confirm"
TIER_BLOCK = "block"


@dataclass(frozen=True)
class SafetyDecision:
    """Three-tier safety decision for one tool call."""

    tier: str            # safe | confirm | block
    reason: str
    action: str          # possibly escalated action id (e.g. dangerous terminal)


class SafetyClassifier:
    """Classify tool calls into SAFE / CONFIRM / BLOCK.

    Delegates the policy table to ``PermissionManager`` and the local
    emergency stop / access revocation to ``SecurityManager`` (independent of
    any AI). Adds one parameter-aware escalation: a shell command matching the
    terminal's dangerous-command detection is never executed autonomously
    (BLOCK for the autonomous path; a human must run it through a trusted
    channel). Unknown actions default to CONFIRM via PermissionManager.
    """

    def __init__(self, *, security_manager: Any, permission_manager: Any,
                 dangerous_check: Callable[[str], bool] | None = None) -> None:
        self.security_manager = security_manager
        self.permission_manager = permission_manager
        # Late-bound import avoids a hard cycle; default uses coding.terminal.
        self._dangerous_check = dangerous_check

    def _is_dangerous(self, command: str) -> bool:
        check = self._dangerous_check
        if check is None:
            try:
                from coding.terminal import Terminal
                check = Terminal.is_dangerous
            except Exception:
                return False
        try:
            return bool(check(command))
        except Exception:
            return False

    def classify(self, action: str, params: dict[str, Any] | None = None,
                 *, confirmed: bool = False) -> SafetyDecision:
        params = params or {}

        # Tier 0: local emergency stop / revocation always wins (non-AI).
        if self.security_manager is not None and not self.security_manager.is_allowed():
            return SafetyDecision(
                TIER_BLOCK,
                "Blocked by security manager (emergency stop or access revoked)",
                action,
            )

        # Parameter-aware escalation: dangerous shell commands never run
        # autonomously. They only pass when the caller marks the call as
        # explicitly user-confirmed through a trusted UI channel; AI output
        # alone can never set that flag.
        effective = action
        if action in ("terminal_execute_safe", "terminal_execute_dangerous"):
            command = str(params.get("command", ""))
            if self._is_dangerous(command):
                if not confirmed:
                    return SafetyDecision(
                        TIER_BLOCK,
                        "Dangerous command blocked for autonomous execution "
                        "(requires explicit user confirmation through a trusted channel)",
                        "terminal_execute_dangerous",
                    )
                effective = "terminal_execute_dangerous"
            else:
                effective = "terminal_execute_safe"

        outcome = self.permission_manager.authorize(effective)
        if outcome == "forbidden":
            return SafetyDecision(TIER_BLOCK, "Action is RESTRICTED and forbidden", effective)
        if outcome == "confirmation_required":
            return SafetyDecision(
                TIER_CONFIRM,
                "Action requires explicit user confirmation (CONFIRM level)",
                effective,
            )
        return SafetyDecision(TIER_SAFE, "Action is SAFE under current policy", effective)


# ------------------------------------------------------------ alias config
_KNOWN_TOKEN_RE = re.compile(r"\{([a-zA-Z_]+)\}")


class AliasConfig:
    """User-configurable phrase aliases + Windows known-folder tokens.

    Aliases map a phrase to an expansion string (e.g. ``"my notes dir"`` ->
    ``"data/notes"``). Known-folder tokens like ``{desktop}`` resolve through
    the ``SHGetKnownFolderPath`` API. Stored as JSON in ``data/aliases.json``;
    created with defaults on first use. Aliases are applied by the router
    before pattern matching so users can teach MAMBA their own vocabulary.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._aliases: dict[str, str] = {}
        self.load()

    @staticmethod
    def _defaults() -> dict[str, str]:
        return {
            "my notes": "data/notes",
            "screenshots folder": "data/screenshots",
        }

    def load(self) -> None:
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._aliases = {
                        str(k).strip().lower(): str(v)
                        for k, v in raw.items()
                        if str(k).strip()
                    }
                    return
            self._aliases = self._defaults()
            self.save()
        except Exception:
            self._aliases = self._defaults()

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._aliases, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass  # aliases stay usable in-memory even if persistence fails

    def set_alias(self, phrase: str, expansion: str) -> None:
        key = phrase.strip().lower()
        if not key:
            raise ValueError("Alias phrase cannot be empty")
        self._aliases[key] = expansion
        self.save()

    def remove_alias(self, phrase: str) -> bool:
        gone = self._aliases.pop(phrase.strip().lower(), None) is not None
        if gone:
            self.save()
        return gone

    def all(self) -> dict[str, str]:
        return dict(self._aliases)

    def resolve_token(self, token: str) -> str | None:
        """Resolve a ``{known_folder}`` token to an absolute path."""
        return known_folder(token)

    def expand_known_tokens(self, text: str) -> str:
        """Replace ``{desktop}``-style tokens with real paths (best effort)."""
        def repl(m: re.Match) -> str:
            resolved = self.resolve_token(m.group(1))
            return resolved if resolved else m.group(0)
        return _KNOWN_TOKEN_RE.sub(repl, text)

    def expand(self, text: str) -> str:
        """Apply known-folder tokens first, then alias phrases (longest first)."""
        result = self.expand_known_tokens(text)
        for phrase in sorted(self._aliases, key=len, reverse=True):
            if len(phrase) < 3:
                continue
            pattern = re.compile(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", re.IGNORECASE)
            result = pattern.sub(self._aliases[phrase], result)
        return result


# ----------------------------------------------------------- AI tool selection
_SELECT_SYSTEM_PROMPT = """You are a PC-control tool router.
Choose ZERO OR MORE tools from this registry that accomplish the user request.
Reply with ONLY a JSON array. Each element: {"tool": "<name>", "params": {...}}.
Rules:
- Use ONLY tool names and param keys from the registry.
- No prose, no markdown fences, no explanations.
- Empty array [] when no tool applies (e.g. casual conversation).
"""

_MAX_REPLY_CHARS = 2000


class ToolSelector:
    """AI-driven tool selection over the computer-tool registry.

    Deterministic regex patterns in ToolRouter stay the primary parser; this
    selector handles free-form requests the patterns do not cover. Every AI
    reply is strictly validated (tool must exist, params coerced) and any
    failure degrades to "no selection" - the AI can never bypass validation,
    and authorization still happens later in ToolRouter.execute().
    """

    def __init__(self, *, ai_provider: Any, tools: dict[str, ToolSpec] | None = None) -> None:
        self.ai_provider = ai_provider
        self.tools = tools if tools is not None else COMPUTER_TOOLS

    def _registry_prompt(self, message: str) -> str:
        schemas = json.dumps([s.schema() for s in self.tools.values()], indent=1)
        return (
            f"{_SELECT_SYSTEM_PROMPT}\nRegistry:\n{schemas}\n"
            f"User request: {message}\nJSON array:"
        )

    @staticmethod
    def _extract_json_array(reply: str) -> list[Any] | None:
        text = reply.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            return None
        try:
            parsed = json.loads(text[start:end + 1])
        except Exception:
            return None
        return parsed if isinstance(parsed, list) else None

    def _build_call(self, entry: Any):
        # Local import: computer_tools must not import tool_router at module
        # load time (tool_router imports this module).
        from core.tool_router import ToolCall

        if not isinstance(entry, dict):
            return None
        name = entry.get("tool") or entry.get("name")
        spec = self.tools.get(str(name)) if name else None
        if spec is None:
            return None
        raw_params = entry.get("params") or {}
        if not isinstance(raw_params, dict):
            return None
        # Only params declared by the spec may pass; defaults fill the rest.
        params = dict(spec.default_params)
        for key, value in raw_params.items():
            if key not in spec.params:
                continue
            if isinstance(value, (str, int, float, bool)):
                params[key] = value
        return ToolCall(
            spec.action,
            f"{spec.description} ({spec.name})",
            params,
            raw=json.dumps({"selector": spec.name, "params": params}),
        )

    def select(self, message: str) -> list[Any]:
        """Return validated ToolCalls for a free-form message (possibly empty)."""
        if self.ai_provider is None or not message.strip():
            return []
        try:
            prompt = self._registry_prompt(message)[:6000]
            reply = asyncio.run(self.ai_provider.chat(prompt))
        except Exception:
            return []
        if not isinstance(reply, str) or not reply.strip():
            return []
        entries = self._extract_json_array(reply[:_MAX_REPLY_CHARS])
        if not entries:
            return []
        calls = []
        for entry in entries[:4]:  # hard cap: no runaway multi-step chains
            call = self._build_call(entry)
            if call is not None:
                calls.append(call)
        return calls
