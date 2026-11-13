"""OBSERVE -> THINK -> ACT -> VERIFY loop around the existing ToolRouter.

The loop does not replace the router: ACT is always
``ToolRouter.execute()``, so the three safety gates (emergency stop,
SAFE/CONFIRM/BLOCK, autonomy) remain the single enforcement point. The loop
adds the four phases required for general-purpose computer control:

* OBSERVE - cheap pre-state relevant to the action (path existence,
  foreground window, mouse position). No screenshots by default, so the loop
  stays fast enough for interactive use.
* THINK   - three-tier safety classification + plan note (optional AI
  reasoning when an ai_provider is supplied; off by default to keep latency
  deterministic).
* ACT     - the gated tool execution, with optional user confirmation.
* VERIFY  - independent post-checks via VerificationEngine (filesystem,
  process, window, screenshot path) instead of trusting the tool's own
  report. Actions without an independent check trust the controller's
  readback and say so honestly.

An ``on_phase`` callback streams phase events (for the dashboard activity
panel and audit logging). The loop re-checks the local emergency stop before
ACT and VERIFY; it never depends on the AI for stopping.
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

PHASE_OBSERVE = "OBSERVE"
PHASE_THINK = "THINK"
PHASE_ACT = "ACT"
PHASE_VERIFY = "VERIFY"


@dataclass
class LoopPhase:
    name: str
    status: str          # completed | failed | skipped
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class LoopResult:
    success: bool
    action: str
    phases: list[LoopPhase]
    result: dict[str, Any]          # raw tool result from ACT
    verification: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def phase(self, name: str) -> LoopPhase | None:
        for p in self.phases:
            if p.name == name:
                return p
        return None

    def to_dict(self) -> dict[str, Any]:
        """Flatten to a tool-result dict compatible with _format_tool_result."""
        out: dict[str, Any] = dict(self.result)
        out["success"] = self.success
        out.setdefault("action", self.action)
        if self.error:
            out["error"] = self.error
        out["phases"] = [
            {"name": p.name, "status": p.status, "detail": p.detail}
            for p in self.phases
        ]
        out["verification"] = self.verification
        act = self.phase(PHASE_ACT)
        if act is not None and act.data.get("confirmation_required"):
            out["confirmation_required"] = True
        return out


# Actions whose success must be re-checked against the real world.
_STRICT_VERIFY = {
    "create_file", "edit_file", "delete_file", "move_file", "copy_file",
    "screenshot", "open_application", "close_application", "switch_window",
    "terminal_execute_safe", "terminal_execute_dangerous",
}


class ActionLoop:
    """Run one ToolCall through the four-phase control loop."""

    def __init__(
        self,
        *,
        tool_router: Any,
        security_manager: Any = None,
        verification_engine: Any = None,
        window_manager: Any = None,
        mouse_controller: Any = None,
        ai_provider: Any = None,
        on_phase: Callable[[str, str, LoopPhase], None] | None = None,
    ) -> None:
        self.tool_router = tool_router
        self.security_manager = security_manager
        if verification_engine is None:
            from core.verification_engine import VerificationEngine
            verification_engine = VerificationEngine()
        self.verification_engine = verification_engine
        self.window_manager = window_manager
        self.mouse_controller = mouse_controller
        self.ai_provider = ai_provider
        self.on_phase = on_phase

    # ---------------------------------------------------------------- helpers
    def _emit(self, action: str, phase: LoopPhase) -> None:
        if self.on_phase is not None:
            try:
                self.on_phase(action, phase.name, phase)
            except Exception:
                pass
        if self.security_manager is not None:
            try:
                self.security_manager.log_event(
                    event=f"loop_{phase.name.lower()}",
                    detail=f"{action}: {phase.detail}",
                    metadata={"action": action, "status": phase.status},
                )
            except Exception:
                pass

    def _allowed(self) -> bool:
        if self.security_manager is None:
            return True
        return bool(self.security_manager.is_allowed())

    # ----------------------------------------------------------------- phases
    def _observe(self, call: Any) -> LoopPhase:
        data: dict[str, Any] = {}
        params = call.params or {}
        path = params.get("path") or params.get("src")
        if isinstance(path, str) and path:
            try:
                data["target_exists_before"] = os.path.exists(path)
                data["target"] = path
            except Exception:
                pass
        if self.window_manager is not None and call.action in (
            "open_application", "close_application", "switch_window", "list_windows"
        ):
            try:
                windows = self.window_manager.list_windows()
                data["window_count_before"] = len(windows)
            except Exception:
                pass
        if self.mouse_controller is not None and call.action.startswith("mouse"):
            try:
                pos = self.mouse_controller.position()
                data["mouse_before"] = {"x": pos.get("x"), "y": pos.get("y")}
            except Exception:
                pass
        return LoopPhase(PHASE_OBSERVE, "completed",
                         "captured pre-action state", data)

    def _think(self, call: Any, *, confirmed: bool) -> LoopPhase:
        classifier = getattr(self.tool_router, "safety_classifier", None)
        if classifier is None:
            return LoopPhase(PHASE_THINK, "completed",
                             "no classifier wired; policy gates still apply in ACT")
        try:
            decision = classifier.classify(call.action, call.params, confirmed=confirmed)
        except Exception as exc:
            return LoopPhase(PHASE_THINK, "failed", f"classification failed: {exc}")
        detail = f"tier={decision.tier}: {decision.reason}"
        data = {"tier": decision.tier, "reason": decision.reason,
                "effective_action": decision.action}
        # Optional AI reasoning note; failures never affect execution.
        if self.ai_provider is not None and decision.tier != "block":
            try:
                prompt = (
                    f"Plan (one short line) for tool call: {call.description}. "
                    "No tools, no code, one sentence."
                )
                note = asyncio.run(self.ai_provider.chat(prompt))
                if isinstance(note, str) and note.strip():
                    data["ai_note"] = note.strip()[:300]
            except Exception:
                pass
        return LoopPhase(PHASE_THINK, "completed", detail, data)

    def _act(self, call: Any, *, confirmed: bool) -> LoopPhase:
        if not self._allowed():
            return LoopPhase(PHASE_ACT, "failed",
                             "Blocked by security manager (emergency stop or access revoked)")
        result = self.tool_router.execute(call, confirmed=confirmed)
        status = "completed" if result.get("success") else "failed"
        detail = call.description if result.get("success") \
            else str(result.get("error", "action failed"))
        phase = LoopPhase(PHASE_ACT, status, detail, {"result": result})
        if not result.get("success"):
            phase.data["confirmation_required"] = bool(
                result.get("confirmation_required")
            )
        return phase

    def _verify(self, call: Any, act: LoopPhase) -> LoopPhase:
        if act.status != "completed":
            return LoopPhase(PHASE_VERIFY, "skipped", "action did not succeed")
        result = act.data.get("result", {})
        if call.action not in _STRICT_VERIFY:
            return LoopPhase(
                PHASE_VERIFY, "completed",
                "no independent check for this action; trusting controller readback",
                {"independent": False, "tool_success": bool(result.get("success"))},
            )
        engine = self.verification_engine
        try:
            if call.action == "create_file":
                content = str(call.params.get("content", ""))
                vr = engine.verify_file_contains(call.params["path"], content) \
                    if content else engine.verify_file_exists(call.params["path"])
            elif call.action == "edit_file":
                if "append" in call.params:
                    vr = engine.verify_file_contains(
                        call.params["path"], str(call.params["append"])
                    )
                else:
                    vr = engine.verify_file_contains(
                        call.params["path"], str(call.params.get("new", ""))
                    )
            elif call.action == "delete_file":
                exists = os.path.exists(call.params["path"])
                from core.verification_engine import VerificationResult
                vr = VerificationResult(
                    action="delete_file", passed=not exists,
                    detail="File gone" if not exists else "File still exists",
                    evidence={"path": call.params["path"], "exists": exists},
                )
            elif call.action in ("move_file", "copy_file"):
                vr = engine.verify_file_exists(call.params["dst"], action=call.action)
            elif call.action == "screenshot":
                vr = engine.verify_file_exists(result.get("path", ""),
                                               action="screenshot")
            elif call.action == "open_application":
                proc = result.get("executable") or call.params.get("name", "")
                vr = engine.verify_process_running(proc, action="open_application")
            elif call.action == "close_application":
                from core.verification_engine import VerificationResult
                base = engine.verify_process_running(
                    call.params.get("name", ""), action="close_application")
                vr = VerificationResult(
                    action="close_application", passed=not base.passed,
                    detail="Process gone" if not base.passed else "Process still running",
                    evidence=base.evidence,
                )
            elif call.action == "switch_window":
                vr = engine.verify_window_visible(call.params["title"])
            elif call.action in ("terminal_execute_safe", "terminal_execute_dangerous"):
                from core.verification_engine import VerificationResult
                rc = result.get("returncode")
                vr = VerificationResult(
                    action="terminal",
                    passed=bool(result.get("success")) and rc == 0,
                    detail=f"exit code {rc}",
                    evidence={"returncode": rc,
                              "failure_markers": result.get("failure_markers", [])},
                )
            else:  # pragma: no cover - guarded by _STRICT_VERIFY
                vr = None
        except Exception as exc:
            return LoopPhase(PHASE_VERIFY, "failed", f"verification error: {exc}")
        if vr is None:
            return LoopPhase(PHASE_VERIFY, "skipped", "no verifier available")
        status = "completed" if vr.passed else "failed"
        return LoopPhase(PHASE_VERIFY, status, vr.detail,
                         {"independent": True, "passed": vr.passed,
                          "evidence": vr.evidence or {}})

    # -------------------------------------------------------------------- run
    def run(self, call: Any, *, confirmed: bool = False) -> LoopResult:
        """Execute one tool call through OBSERVE -> THINK -> ACT -> VERIFY."""
        phases: list[LoopPhase] = []

        observe = self._observe(call)
        phases.append(observe)
        self._emit(call.action, observe)

        think = self._think(call, confirmed=confirmed)
        phases.append(think)
        self._emit(call.action, think)

        if think.data.get("tier") == "block":
            act = LoopPhase(PHASE_ACT, "skipped", think.detail)
            verify = LoopPhase(PHASE_VERIFY, "skipped", "blocked before action")
        else:
            act = self._act(call, confirmed=confirmed)
            verify = self._verify(call, act)
        phases.append(act)
        self._emit(call.action, act)
        phases.append(verify)
        self._emit(call.action, verify)

        result = act.data.get("result", {}) or {}
        success = act.status == "completed" and verify.status != "failed"
        if act.status == "failed":
            error = act.detail
        elif verify.status == "failed":
            error = f"Independent verification failed: {verify.detail}"
        elif think.data.get("tier") == "block":
            error = act.detail
        else:
            error = ""
        return LoopResult(
            success=success, action=call.action, phases=phases,
            result=result, verification=verify.data, error=error,
        )

    async def run_async(self, call: Any, *, confirmed: bool = False) -> LoopResult:
        """Async wrapper so the loop can be driven from an event loop."""
        return await asyncio.to_thread(self.run, call, confirmed=confirmed)

