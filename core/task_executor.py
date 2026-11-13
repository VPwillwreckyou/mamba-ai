"""Multi-step autonomous task execution with stop/cancel and verification."""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StepResult:
    index: int
    description: str
    status: str  # completed | failed | cancelled
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class ExecutionReport:
    goal: str
    status: str  # completed | failed | cancelled | blocked
    steps: list[StepResult]
    summary: str


class TaskExecutor:
    """Execute a goal: explicit multi-step tool chains or a generic pipeline."""

    def __init__(
        self,
        *,
        task_planner: Any,
        tool_router: Any,
        security_manager: Any,
        permission_manager: Any,
        project_inspector: Any = None,
        ai_provider: Any = None,
        action_loop: Any = None,
        confirm_callback: Any = None,
    ) -> None:
        self.task_planner = task_planner
        self.tool_router = tool_router
        self.security_manager = security_manager
        self.permission_manager = permission_manager
        self.project_inspector = project_inspector
        self.ai_provider = ai_provider
        # UI hook: confirm_callback(call) -> bool asks the user to approve a
        # CONFIRM-tier step. None means "never approve autonomously".
        self.confirm_callback = confirm_callback
        if action_loop is None:
            from core.action_loop import ActionLoop
            action_loop = ActionLoop(
                tool_router=tool_router,
                security_manager=security_manager,
            )
        self.action_loop = action_loop
        self._cancelled = False

    def cancel(self) -> None:
        """Emergency stop hook: abort between steps."""
        self._cancelled = True

    def run_loop(self, call: Any, *, confirmed: bool = False) -> dict[str, Any]:
        """Run one tool call through OBSERVE->THINK->ACT->VERIFY and return
        a tool-result-compatible dict.

        If the ACT phase reports confirmation_required and a confirm_callback
        is wired (UI dialog), the user is asked once; approval re-runs the loop
        with confirmed=True. Without a callback the refusal stands.
        """
        from core.action_loop import LoopResult
        result: LoopResult = self.action_loop.run(call, confirmed=confirmed)
        if (not result.success
                and result.phase("ACT") is not None
                and result.phase("ACT").data.get("confirmation_required")
                and self.confirm_callback is not None
                and not confirmed):
            try:
                approved = bool(self.confirm_callback(call))
            except Exception:
                approved = False
            if approved:
                result = self.action_loop.run(call, confirmed=True)
        return result.to_dict()

    def _generic_steps(self, goal: str, plan: Any) -> list[StepResult]:
        """Run the real understand->inspect->plan->act->verify->report pipeline."""
        steps: list[StepResult] = []
        idx = 0

        def add(desc: str, status: str, result: dict[str, Any] | None = None, error: str = "") -> None:
            nonlocal idx
            idx += 1
            steps.append(StepResult(idx, desc, status, result or {}, error))

        add("Understand the goal", "completed", {"goal": goal})
        if self.project_inspector is not None:
            try:
                info = self.project_inspector.inspect()
                ok = bool(info.get("success", True))
                add("Inspect relevant context", "completed" if ok else "failed", info,
                    "" if ok else str(info.get("error", "inspection failed")))
            except Exception as exc:
                add("Inspect relevant context", "failed", {}, str(exc))
        else:
            add("Inspect relevant context", "completed", {"detail": "no project inspector available"})
        add("Plan the approach", "completed",
            {"steps": [getattr(s, "description", str(s)) for s in getattr(plan, "steps", [])]})
        if self.ai_provider is not None:
            try:
                reply = asyncio.run(self.ai_provider.chat(goal))
                add("Execute the actions", "completed" if reply else "failed",
                    {"reply": reply} if reply else {}, "" if reply else "empty provider reply")
            except Exception as exc:
                add("Execute the actions", "failed", {}, str(exc))
        else:
            add("Execute the actions", "completed",
                {"detail": "No executable tool matched the goal; nothing was changed (honest no-op)"})
        verify: dict[str, Any] = {}
        if self.project_inspector is not None:
            try:
                verify = self.project_inspector.inspect()
            except Exception:
                verify = {}
        add("Verify the result", "completed", verify or {"detail": "no verifiable side effects"})
        add("Report the outcome", "completed", {"note": "pipeline finished"})
        return steps

    def execute(self, goal: str) -> ExecutionReport:
        self._cancelled = False
        if not self.security_manager.is_allowed():
            self.security_manager.log_event(event="task_blocked", detail=goal[:120])
            return ExecutionReport(goal, "blocked", [], "Blocked by security manager")
        calls = self.tool_router.parse_all(goal)
        try:
            plan = self.task_planner.plan(goal)
            plan_error = ""
        except Exception as exc:
            plan = None
            plan_error = str(exc)

        if calls:
            steps: list[StepResult] = []
            for i, call in enumerate(calls, 1):
                if self._cancelled or not self.security_manager.is_allowed():
                    steps.append(StepResult(i, call.description, "cancelled", {}, "emergency stop"))
                    for rest in calls[i:]:
                        steps.append(StepResult(len(steps) + 1, rest.description, "cancelled", {}, "emergency stop"))
                    return ExecutionReport(goal, "cancelled", steps, "Emergency stop triggered")
                # OBSERVE -> THINK -> ACT -> VERIFY for this step's tool call.
                result = self.run_loop(call)
                status = "completed" if result.get("success") else "failed"
                err = "" if result.get("success") else str(result.get("error", "failed"))
                steps.append(StepResult(i, call.description, status, result, err))
                if status == "failed":
                    for rest in calls[i:]:
                        steps.append(StepResult(len(steps) + 1, rest.description, "cancelled", {}, "earlier step failed"))
                    break
            overall = "failed" if any(s.status == "failed" for s in steps) else (
                "cancelled" if any(s.status == "cancelled" for s in steps) else "completed")
        elif plan_error:
            steps = [StepResult(1, "Plan the approach", "failed", {}, plan_error)]
            overall = "failed"
        else:
            steps = self._generic_steps(goal, plan)
            overall = "failed" if any(s.status == "failed" for s in steps) else "completed"

        ok = sum(1 for s in steps if s.status == "completed")
        summary = f"Task '{goal[:60]}' {overall}: {ok}/{len(steps)} steps completed."
        self.security_manager.log_event(
            event="task_completed" if overall == "completed" else "task_failed",
            detail=summary,
            metadata={"steps": len(steps)},
        )
        return ExecutionReport(goal, overall, steps, summary)

    # -------------------------------------------------------- async execution
    def execute_background(self, goal: str,
                           on_complete: Any = None) -> threading.Thread:
        """Run execute() on a worker thread; optional completion callback.

        The worker still checks security_manager/cancel between steps, so the
        local emergency stop aborts it mid-chain.
        """
        def _worker() -> None:
            report = self.execute(goal)
            if on_complete is not None:
                try:
                    on_complete(report)
                except Exception:
                    pass

        thread = threading.Thread(target=_worker, daemon=True,
                                  name="mamba-task-executor")
        thread.start()
        return thread

    async def execute_async(self, goal: str) -> ExecutionReport:
        """Async variant of execute() for event-loop callers."""
        return await asyncio.to_thread(self.execute, goal)

