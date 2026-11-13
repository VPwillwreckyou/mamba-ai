"""Unit tests for the OBSERVE->THINK->ACT->VERIFY loop and its UI contract.

These exercise the real ActionLoop/TaskExecutor against a fake ToolRouter so
the four-phase contract, the CONFIRM-tier re-run and the on_phase/confirm
callback signatures used by the dashboard are validated without touching the
real filesystem, screen or processes.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import get_type_hints

from core.action_loop import ActionLoop, LoopPhase
from core.task_executor import TaskExecutor
from core.tool_router import ToolCall


class FakeClassifier:
    """Minimal stand-in for the router's safety classifier."""

    def __init__(self, tier: str, reason: str = "policy") -> None:
        self._tier = tier
        self._reason = reason

    def classify(self, action, params=None, *, confirmed: bool = False):
        tier = self._tier
        if tier == "confirm" and confirmed:
            # A user-approved CONFIRM action behaves like SAFE once confirmed.
            tier = "safe"
        return SimpleNamespace(tier=tier, action=action, reason=self._reason)


class FakeVerifier:
    """Trusts the ACT readback; keeps strict-verify actions hermetic.

    The real VerificationEngine re-checks the filesystem/screen, which a fake
    router never touches. For control-flow tests we only need the VERIFY phase
    to mirror the ACT success/failure, not re-open real files.
    """

    def __getattr__(self, name):
        def _verify(*args, **kwargs):
            return SimpleNamespace(passed=True, detail="fake", evidence={})

        return _verify


class FakeRouter:
    """Records calls and returns scripted results, gated like the real router."""

    def __init__(self, classifier: FakeClassifier) -> None:
        self.safety_classifier = classifier
        self.executed: list[tuple[str, bool]] = []

    def execute(self, call: ToolCall, *, confirmed: bool = False) -> dict:
        decision = self.safety_classifier.classify(
            call.action, call.params, confirmed=confirmed
        )
        if decision.tier == "block":
            return {"success": False, "action": call.action, "error": decision.reason}
        if decision.tier == "confirm" and not confirmed:
            return {
                "success": False,
                "action": call.action,
                "error": "requires confirmation",
                "confirmation_required": True,
            }
        self.executed.append((call.action, confirmed))
        return {"success": True, "action": call.action, "detail": "done"}


class FakeSecurity:
    def __init__(self, allowed: bool = True) -> None:
        self._allowed = allowed

    def is_allowed(self) -> bool:
        return self._allowed

    def log_event(self, *a, **k) -> None:
        return None


def _call(action: str = "read_file") -> ToolCall:
    return ToolCall(action=action, description=f"do {action}", params={})


def test_task_executor_background_thread_annotation_resolves():
    hints = get_type_hints(TaskExecutor.execute_background)

    assert hints["return"] is threading.Thread


def test_loop_runs_all_four_phases_and_emits_them():
    classifier = FakeClassifier("safe")
    router = FakeRouter(classifier)
    seen: list[tuple[str, str, LoopPhase]] = []
    loop = ActionLoop(
        tool_router=router,
        security_manager=FakeSecurity(),
        verification_engine=None,
        on_phase=lambda action, name, phase: seen.append((action, name, phase)),
    )
    result = loop.run(_call("search"))
    names = [p.name for p in result.phases]
    assert names == ["OBSERVE", "THINK", "ACT", "VERIFY"]
    # on_phase fires once per phase with the same (action, name, phase) shape.
    assert [n for _, n, _ in seen] == names
    assert all(a == "search" for a, _, _ in seen)
    assert result.success is True


def test_loop_confirms_action_only_after_approval():
    classifier = FakeClassifier("confirm", reason="needs a human")
    router = FakeRouter(classifier)
    asks: list[ToolCall] = []

    def confirm_cb(call: ToolCall) -> bool:
        asks.append(call)
        return True

    executor = TaskExecutor(
        task_planner=None,
        tool_router=router,
        security_manager=FakeSecurity(),
        permission_manager=None,
        action_loop=ActionLoop(
            tool_router=router, security_manager=FakeSecurity(),
            verification_engine=FakeVerifier(),
        ),
        confirm_callback=confirm_cb,
    )

    call = _call("delete_file")
    # delete_file is strict-verify: the loop reads call.params["path"], so give
    # it one (the fake verifier trusts the ACT readback regardless).
    call.params["path"] = "tests/__tmp_delete_me.txt"
    out = executor.run_loop(call)

    # First attempt refused (confirmation_required), then user approved once,
    # and the action finally executed with confirmed=True. The final result is
    # a success, so it no longer advertises confirmation_required.
    assert len(asks) == 1
    assert out.get("success") is True
    assert ("delete_file", True) in router.executed
    assert out.get("confirmation_required") is None


def test_loop_without_confirm_callback_never_executes_confirm_tier():
    classifier = FakeClassifier("confirm", reason="needs a human")
    router = FakeRouter(classifier)
    executor = TaskExecutor(
        task_planner=None,
        tool_router=router,
        security_manager=FakeSecurity(),
        permission_manager=None,
        action_loop=ActionLoop(
            tool_router=router, security_manager=FakeSecurity(),
            verification_engine=FakeVerifier(),
        ),
        confirm_callback=None,
    )
    out = executor.run_loop(_call("delete_file"))
    assert out.get("success") is False
    assert router.executed == []


def test_loop_blocks_when_security_disallows():
    classifier = FakeClassifier("safe")
    router = FakeRouter(classifier)
    loop = ActionLoop(
        tool_router=router, security_manager=FakeSecurity(allowed=False)
    )
    result = loop.run(_call("read_file"))
    assert result.success is False
    assert result.phase("ACT").status == "failed"
    assert router.executed == []
