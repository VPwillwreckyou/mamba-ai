#!/usr/bin/env python
"""MAMBA - Personal AI Assistant

Main application entry point for the MAMBA desktop application.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from PySide6.QtWidgets import QApplication, QMessageBox

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load environment variables
load_dotenv(PROJECT_ROOT / ".env")

import importlib

from core.ai_service import AIService
from core.app_settings import SettingsManager
from core.autonomy_manager import AutonomyManager
from core.memory_manager import MemoryManager
from core.permission_manager import PermissionManager
from core.phone_manager import PhoneManager
from core.secret_store import SecretStore
from core.security_manager import SecurityManager
from core.task_executor import TaskExecutor
from core.task_planner import TaskPlanner
from core.tool_router import ToolRouter
from integrations.discord import DiscordController
from integrations.email import EmailController
from integrations.spotify import SpotifyController
from ui.main_window import DashboardWidget

# Try to import real phone providers
try:
    from core.twilio_provider import TwilioProvider
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
    TwilioProvider = None  # type: ignore


        # Controllers are imported dynamically at init time so a missing
        # optional dependency degrades gracefully instead of crashing startup.
_CONTROLLER_SPECS = {
    "window_manager": ("computer.window_manager", "WindowManager"),
    "app_controller": ("computer.app_controller", "AppController"),
    "keyboard_controller": ("computer.keyboard_controller", "KeyboardController"),
    "mouse_controller": ("computer.mouse_controller", "MouseController"),
    "screen_capture": ("computer.screen_capture", "ScreenCapture"),
    "vision_engine": ("computer.vision_engine", "VisionEngine"),
    "file_manager": ("coding.file_manager", "FileManager"),
    "terminal": ("coding.terminal", "Terminal"),
    "project_inspector": ("coding.project_inspector", "ProjectInspector"),
    "web_search": ("web.search", "WebSearch"),
    "browser_controller": ("web.browser", "BrowserController"),
    "uia_engine": ("computer.uia_engine", "UIAutomationEngine"),
}



class MambaApp:
    """Main application controller for MAMBA."""

    def __init__(self):
        self.qt_app = QApplication(sys.argv)

        # Initialize core components
        self.security_manager = SecurityManager()
        self.memory_manager = MemoryManager(str(PROJECT_ROOT / "data" / "memory.db"))
        
        # Initialize phone provider.
        # TwilioProvider() may raise at construction time (library missing or
        # credentials not configured), so the construction must happen inside
        # a guarded block, never in a bare conditional expression.
        phone_provider = None
        if TWILIO_AVAILABLE:
            try:
                candidate = TwilioProvider()
                if candidate.is_available():
                    phone_provider = candidate
                    self.security_manager.log_event(
                        event="phone_provider_initialized",
                        detail="Twilio provider initialized successfully"
                    )
                else:
                    self.security_manager.log_event(
                        event="phone_provider_mock",
                        detail="Twilio library present but not configured (missing credentials)"
                    )
            except Exception as e:
                phone_provider = None
                self.security_manager.log_event(
                    event="phone_provider_failed",
                    detail=f"Failed to initialize Twilio provider: {e}",
                    metadata={"error": str(e)}
                )
        else:
            self.security_manager.log_event(
                event="phone_provider_mock",
                detail="Using mock phone provider (Twilio library not installed)"
            )
        
        caller_id = os.getenv("CALLER_ID", "MAMBA AI")
        default_phone_number = os.getenv("DEFAULT_PHONE_NUMBER", "")
        self.phone_manager = PhoneManager(
            default_phone_number=default_phone_number,
            caller_id=caller_id,
            provider=phone_provider,
        )
        self.ai_settings = SettingsManager(PROJECT_ROOT / "data" / "settings.json")
        self.secret_store = SecretStore(self.security_manager)
        self.ai_service = AIService(
            self.ai_settings,
            self.secret_store,
            security_manager=self.security_manager,
        )
        self.ai_provider = self.ai_service.provider_or_none()
        self.task_planner = TaskPlanner(
            ai_provider=self.ai_provider, phone_manager=self.phone_manager
        )
        if self.ai_provider is None:
            self.security_manager.log_event(
                event="ai_provider_missing",
                detail="No API key configured for the selected AI provider",
            )
        else:
            self.security_manager.log_event(
                event="ai_provider_initialized",
                detail=f"{self.ai_service.spec.label} provider initialized",
            )

        # Build capability controllers; individual failures degrade to None
        # instead of crashing the whole application.
        constructor_kwargs: dict[str, dict] = {
            "window_manager": {"security_manager": self.security_manager},
            "app_controller": {"security_manager": self.security_manager},
            "keyboard_controller": {"security_manager": self.security_manager},
            "mouse_controller": {"security_manager": self.security_manager},
            "screen_capture": {
                "output_dir": str(PROJECT_ROOT / "data" / "screenshots"),
                "security_manager": self.security_manager,
            },
            "vision_engine": {"ai_provider": self.ai_provider},
            "file_manager": {"root": PROJECT_ROOT, "security_manager": self.security_manager},
            "terminal": {"cwd": PROJECT_ROOT, "security_manager": self.security_manager},
            "project_inspector": {"root": PROJECT_ROOT},
            "web_search": {},
            "browser_controller": {"security_manager": self.security_manager},
            "uia_engine": {"security_manager": self.security_manager},
        }
        self.controllers: dict[str, object] = {}
        for key, (module_name, class_name) in _CONTROLLER_SPECS.items():

            try:
                cls = getattr(importlib.import_module(module_name), class_name)
                self.controllers[key] = cls(**constructor_kwargs[key])
            except Exception as exc:
                self.controllers[key] = None
                self.security_manager.log_event(
                    event="controller_unavailable",
                    detail=f"{key} unavailable: {exc}",
                    metadata={"controller": key},
                )

        ctrl = self.controllers.get
        self.permission_manager = PermissionManager()
        self.autonomy_manager = AutonomyManager()
        self.discord_controller = DiscordController(
            self.secret_store,
            security_manager=self.security_manager,
            permission_manager=self.permission_manager,
        )
        self.spotify_controller = SpotifyController(self.security_manager)
        self.email_controller = EmailController(
            self.secret_store,
            self.ai_settings,
            security_manager=self.security_manager,
            permission_manager=self.permission_manager,
        )
        self.controllers["discord_controller"] = self.discord_controller
        self.controllers["spotify_controller"] = self.spotify_controller
        self.tool_router = ToolRouter(
            security_manager=self.security_manager,
            permission_manager=self.permission_manager,
            autonomy_manager=self.autonomy_manager,
            app_controller=ctrl("app_controller"),
            window_manager=ctrl("window_manager"),
            keyboard_controller=ctrl("keyboard_controller"),
            mouse_controller=ctrl("mouse_controller"),
            screen_capture=ctrl("screen_capture"),
            vision_engine=ctrl("vision_engine"),
            file_manager=ctrl("file_manager"),
            terminal=ctrl("terminal"),
            project_inspector=ctrl("project_inspector"),
            web_search=ctrl("web_search"),
            browser_controller=ctrl("browser_controller"),
            spotify_controller=self.spotify_controller,
        )
        self.task_executor = TaskExecutor(
            task_planner=self.task_planner,
            tool_router=self.tool_router,
            security_manager=self.security_manager,
            permission_manager=self.permission_manager,
            project_inspector=ctrl("project_inspector"),
            ai_provider=self.ai_provider,
        )

        # Initialize UI
        self.dashboard = DashboardWidget(
            ai_service=self.ai_service,
            discord_controller=self.discord_controller,
            spotify_controller=self.spotify_controller,
            browser_controller=ctrl("browser_controller"),
            web_search=ctrl("web_search"),
            email_controller=self.email_controller,
            settings=self.ai_settings,
        )
        self.dashboard.chat_requested.connect(self.handle_chat_request)
        self.dashboard.ai_config_changed.connect(self._refresh_ai_provider)
        self.dashboard.emergency_stop_requested.connect(self.handle_emergency_stop)
        self.dashboard.access_revoke_requested.connect(self.handle_access_revoke)

        # Stream the OBSERVE->THINK->ACT->VERIFY phases into the dashboard's
        # activity feed, and route CONFIRM-tier approvals through a modal
        # dialog. handle_chat_request runs execute() on the UI thread, so both
        # callbacks fire on the main thread and may touch widgets directly.
        if self.task_executor is not None:
            self.task_executor.action_loop.on_phase = self.dashboard.append_activity
            self.task_executor.confirm_callback = self.dashboard.confirm_action

        self.security_manager.log_event(
            event="application_started",
            detail="MAMBA application initialized"
        )

    def _refresh_ai_provider(self) -> None:
        """Apply provider changes from the Integrations page to live clients."""
        self.ai_provider = self.ai_service.provider_or_none()
        self.task_planner.ai_provider = self.ai_provider
        self.task_executor.ai_provider = self.ai_provider
        vision = self.controllers.get("vision_engine")
        if vision is not None:
            vision.ai_provider = self.ai_provider

    def handle_chat_request(self, message: str):
        """Handle a chat request from the UI."""
        self.security_manager.log_event(
            event="chat_requested",
            detail=f"User sent message: {message[:100]}..."
        )
        self.dashboard.set_status("Processing...")
        self.dashboard.set_task(message)
        self.dashboard.set_action("Planning task...")
        self.dashboard.append_chat("You", message)

        # Check if this is a phone command
        phone_command = self.phone_manager.parse_command(message)
        email_draft = self.email_controller.parse_request(message)
        
        if phone_command:
            # Execute phone command directly
            import asyncio
            try:
                result = asyncio.run(self.phone_manager.execute_command(phone_command))
                if result.get("success"):
                    self.dashboard.set_status(f"{phone_command.action.value.capitalize()} successful")
                    self.dashboard.append_chat(
                        "MAMBA",
                        f"Phone {phone_command.action.value} -> {result.get('phone_number', 'default number')} "
                        f"via {result.get('provider', 'unknown')} provider",
                    )
                    self.dashboard.set_action(f"Completed {phone_command.action.value} to {result.get('phone_number', 'unknown')}")
                    self.security_manager.log_event(
                        event="phone_command_executed",
                        detail=f"{phone_command.action.value} executed successfully",
                        metadata={
                            "action": phone_command.action.value,
                            "phone_number": result.get("phone_number"),
                            "is_default_number": phone_command.is_default_number
                        }
                    )
                else:
                    self.dashboard.set_status("Phone command failed", error=True)
                    self.dashboard.append_chat(
                        "MAMBA",
                        f"Phone {phone_command.action.value} failed: {result.get('error', 'Unknown error')}",
                    )
                    self.dashboard.set_action(f"Error: {result.get('error', 'Unknown error')}")
                    self.security_manager.log_event(
                        event="phone_command_failed",
                        detail=f"Phone command failed: {result.get('error')}",
                        metadata={
                            "action": phone_command.action.value,
                            "error": result.get("error")
                        }
                    )
            except Exception as e:
                self.dashboard.set_status("Phone command error", error=True)
                self.dashboard.set_action(f"Exception: {e!s}")
                self.security_manager.log_event(
                    event="phone_command_exception",
                    detail=f"Phone command exception: {e}",
                    metadata={"error": str(e)}
                )
        elif email_draft is not None:
            if not self.email_controller.configured():
                result = {
                    "success": False,
                    "error": "Configure email in INTEGRATIONS before sending.",
                }
            elif not email_draft.recipient:
                result = {
                    "success": False,
                    "error": "Set your default recipient email in INTEGRATIONS first.",
                }
            else:
                answer = QMessageBox.question(
                    self.dashboard,
                    "Confirm email",
                    f"Send this email to {email_draft.recipient}?\n\n"
                    f"Subject: {email_draft.subject or 'Message from MAMBA'}\n\n"
                    f"{email_draft.body[:240]}",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer == QMessageBox.Yes:
                    result = self.email_controller.send_email(
                        email_draft.recipient,
                        email_draft.subject,
                        email_draft.body,
                        confirmed=True,
                    )
                else:
                    result = {"success": False, "error": "Email cancelled."}

            if result.get("success"):
                self.dashboard.set_status("Email sent")
                self.dashboard.append_chat(
                    "MAMBA", f"Email sent to {email_draft.recipient}."
                )
                self.security_manager.log_event(
                    event="email_sent",
                    detail="User-confirmed email sent",
                )
            else:
                self.dashboard.set_status("Email not sent", error=True)
                self.dashboard.append_chat("MAMBA", result["error"])
            self.dashboard.set_action(result.get("error", "Email sent"))
        else:
            # Route to real tools, or fall back to conversational AI/memory.
            try:
                calls = self.tool_router.parse_all(message)
                if len(calls) > 1:
                    # Multi-step autonomous execution through the task executor.
                    self.dashboard.set_action(f"Executing {len(calls)} steps...")
                    report = self.task_executor.execute(message)
                    for step in report.steps:
                        self.dashboard.append_chat(
                            f"Step {step.index} ({step.status})", step.description
                        )
                        if step.error:
                            self.dashboard.append_chat(f"Step {step.index} error", step.error)
                    self.dashboard.append_chat("MAMBA", report.summary)
                    self.dashboard.set_status(
                        "Task completed" if report.status == "completed" else f"Task {report.status}",
                        error=report.status == "failed",
                        warning=report.status == "cancelled",
                    )
                    self.dashboard.set_action(
                        report.steps[-1].description if report.steps else "Done"
                    )
                    self.security_manager.log_event(
                        event="task_executed",
                        detail=report.summary,
                        metadata={"goal": message[:200], "status": report.status},
                    )
                elif len(calls) == 1:
                    call = calls[0]
                    result = self.tool_router.execute(call)
                    self.dashboard.append_chat("MAMBA", self._format_tool_result(result))
                    if result.get("success"):
                        self.dashboard.set_status(f"{call.action} completed")
                        self.dashboard.set_action(call.description)
                    else:
                        self.dashboard.set_status(f"{call.action} failed", error=True)
                        self.dashboard.set_action(str(result.get("error", "failed")))
                else:
                    reply = self._assistant_reply(message)
                    self.dashboard.append_chat("MAMBA", reply)
                    self.dashboard.set_status("Response ready")
                    self.dashboard.set_action("Conversational reply")
                    self.security_manager.log_event(
                        event="chat_replied", detail=reply[:150]
                    )
            except Exception as e:
                self.dashboard.set_status(f"Error: {e}", error=True)
                self.security_manager.log_event(
                    event="chat_handling_failed",
                    detail=f"Chat handling failed: {e}",
                    metadata={"error": str(e)}
                )

    @staticmethod
    def _format_tool_result(result: dict) -> str:
        """Render a tool result for the conversation panel."""
        action = result.get("action", "action")
        keys = ("path", "command", "stdout", "stderr", "output", "url", "results",
                "title", "name", "count", "detail", "analysis", "returncode",
                "failure_markers", "blocked", "content", "entries", "bytes")

        def fmt(val) -> str:
            if isinstance(val, (list, dict)):
                val = str(val)
            if isinstance(val, str) and len(val) > 400:
                val = val[:400] + "..."
            return str(val)

        if result.get("success"):
            extras = [f"{k}: {fmt(result[k])}" for k in keys
                      if k in result and result[k] not in (None, "", [])]
            body = "; ".join(extras) if extras else result.get("description", "done")
            return f"OK - {action}: {body}"
        parts = [f"FAILED - {action}: {result.get('error') or 'command failed'}"]
        parts += [f"{k}: {fmt(result[k])}" for k in keys
                  if k in result and result[k] not in (None, "", [])]
        return "; ".join(parts)

    def _assistant_reply(self, message: str) -> str:
        """Reply to conversational messages.

        Uses the AI provider when configured; otherwise falls back to an honest
        local memory-based assistant so context retention still works offline.
        """
        try:
            self.memory_manager.remember("conversation", "user message", message, tags=["chat"])
        except Exception:
            pass

        if self.ai_provider is not None:
            try:
                import asyncio
                recent = self.memory_manager.search(kind="conversation")
                context = "\n".join(f"- {e['content']}" for e in recent[-6:])
                prompt = f"Recent conversation:\n{context}\n\nUser: {message}\nAssistant:"
                # Build native conversation history for providers that support
                # multi-turn messages (Ollama). Other providers ignore this and
                # use the flattened prompt above, preserving existing behavior.
                history: list[dict] = []
                for e in recent[-6:-1]:
                    content = str(e.get("content", "")).strip()
                    if content:
                        history.append({"role": "user", "content": content})
                history.append({"role": "user", "content": message})
                system_prompt = (
                    "You are MAMBA, a concise, helpful personal AI assistant "
                    "running locally. Answer clearly and briefly."
                )
                return asyncio.run(
                    self.ai_service.chat(
                        prompt, system_prompt=system_prompt, messages=history
                    )
                )
            except Exception as exc:
                return f"(AI provider error: {exc}) I could not reach the AI provider; using local mode."

        import re as _re

        m = _re.search(r"my favorite (\w+) is ([\w\s]+?)[.!]?$", message, _re.IGNORECASE)
        if m:
            kind_val, val = m.group(1).lower(), m.group(2).strip()
            try:
                self.memory_manager.remember("preference", f"favorite {kind_val}", val, tags=["preference"])
            except Exception:
                pass
            return f"Noted - your favorite {kind_val} is {val}."
        m = _re.search(r"what(?:'s| is) my favorite (\w+)", message, _re.IGNORECASE)
        if m:
            kind_val = m.group(1).lower()
            hits = self.memory_manager.search(kind="preference", query=f"favorite {kind_val}")
            if hits:
                return f"You told me your favorite {kind_val} is {hits[-1]['content']}."
            return f"I don't have a stored favorite {kind_val} yet - tell me and I'll remember it."
        m = _re.search(r"remember (?:that )?(.+)", message, _re.IGNORECASE)
        if m:
            fact = m.group(1).strip()
            try:
                self.memory_manager.remember("fact", "user fact", fact, tags=["memory"])
            except Exception:
                pass
            return f"Remembered: {fact}"
        if _re.search(r"what did i (?:just )?say", message, _re.IGNORECASE):
            prior = [e for e in self.memory_manager.search(kind="conversation") if e["content"] != message]
            if prior:
                return f"Your previous message was: '{prior[-1]['content']}'"
            return "I don't have any earlier messages from you."
        history = self.memory_manager.search(kind="conversation")
        last = history[-1]["content"] if history else ""
        return (
            "(No AI provider configured - local mode.) "
            f"I recorded your message. I remember {len(history)} message(s) this session; "
            f"last: '{last[:80]}'. Configure an AI provider in INTEGRATIONS for full AI chat."
        )

    def handle_emergency_stop(self):
        """Handle emergency stop request."""
        self.security_manager.emergency_stop()
        if self.task_executor is not None:
            self.task_executor.cancel()
        self.dashboard.set_status("EMERGENCY STOP ACTIVATED", error=True)
        self.dashboard.set_action("All automation stopped")
        self.dashboard.append_chat("MAMBA", "EMERGENCY STOP: all automation halted immediately.")
        self.security_manager.log_event(
            event="emergency_stop_ui", detail="Emergency stop activated from UI"
        )

    def handle_access_revoke(self):
        """Handle access revocation request."""
        self.security_manager.revoke_access()
        if self.task_executor is not None:
            self.task_executor.cancel()
        self.dashboard.set_status("ACCESS REVOKED", warning=True)
        self.dashboard.set_action("MAMBA access revoked")
        self.dashboard.append_chat("MAMBA", "ACCESS REVOKED: computer control is disabled until re-granted.")
        self.security_manager.log_event(
            event="access_revoked_ui", detail="Access revoked from UI"
        )

    def run(self):
        """Run the application."""
        self.dashboard.show()
        self.dashboard.setWindowTitle("MAMBA - Personal AI Assistant")
        self.dashboard.resize(800, 600)
        return self.qt_app.exec()


def main() -> None:
    """Main entry point."""
    # DPI awareness is owned by Qt: when QApplication is constructed it sets
    # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2, which is the best mode for
    # accurate mouse/screen coordinate mapping on mixed-DPI displays. We must
    # NOT call SetProcessDpiAwareness() here first: Windows locks DPI awareness
    # after the first setter, so a manual call would force the inferior
    # system-DPI-aware level and make Qt's own (better) attempt fail with
    # "Access is denied". Letting Qt configure it avoids that conflict.

    # Ensure data directory exists
    data_dir = PROJECT_ROOT / "data"

    data_dir.mkdir(exist_ok=True)

    app = MambaApp()
    sys.exit(app.run())


if __name__ == "__main__":
    main()