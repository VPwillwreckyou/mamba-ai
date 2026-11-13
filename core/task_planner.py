from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.phone_manager import PhoneManager


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskStep:
    """A single step in a task plan."""

    index: int
    description: str
    action: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None


@dataclass
class TaskPlan:
    """A structured task plan produced from natural language intent."""

    goal: str
    steps: list[TaskStep] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    metadata: dict[str, Any] = field(default_factory=dict)


class TaskPlanner:
    """Turns natural-language intent into an executable task plan.

    The planner is an AI-assisted component. For the MVP, a structured planning
    routine can produce a baseline plan even when the AI provider is unavailable.
    Real planning output must still be validated before execution.
    """

    def __init__(self, *, ai_provider: Any | None = None, phone_manager: PhoneManager | None = None) -> None:
        self.ai_provider = ai_provider
        self.phone_manager = phone_manager or PhoneManager()

    def plan(self, intent: str, *, context: str | None = None) -> TaskPlan:
        """Create a task plan for the given intent.

        The MVP implementation produces a sensible default plan skeleton when the
        AI provider is unavailable, and augments it when possible.
        """
        if not intent.strip():
            raise ValueError("Intent cannot be empty")

        # Check if this is a phone command
        phone_command = self.phone_manager.parse_command(intent)
        if phone_command:
            plan = self._phone_command_plan(phone_command)
        else:
            plan = self._default_plan(intent)
        
        plan.metadata["intent"] = intent
        if context:
            plan.metadata["context"] = context
        return plan

    def _default_plan(self, intent: str) -> TaskPlan:
        """Create a baseline plan based on the intent's language."""
        lower = intent.lower()
        if "fix" in lower or "debug" in lower or "error" in lower:
            return TaskPlan(
                goal=intent,
                steps=[
                    TaskStep(index=1, description="Identify the project or target"),
                    TaskStep(index=2, description="Inspect relevant files and current state"),
                    TaskStep(index=3, description="Run the build or application"),
                    TaskStep(index=4, description="Inspect actual errors or output"),
                    TaskStep(index=5, description="Determine the likely cause"),
                    TaskStep(index=6, description="Modify relevant files where appropriate"),
                    TaskStep(index=7, description="Rebuild or rerun"),
                    TaskStep(index=8, description="Run tests if available"),
                    TaskStep(index=9, description="Verify the result"),
                    TaskStep(index=10, description="Report what happened"),
                ],
            )
        if "search" in lower or "research" in lower or "find" in lower:
            return TaskPlan(
                goal=intent,
                steps=[
                    TaskStep(index=1, description="Clarify the search goal"),
                    TaskStep(index=2, description="Run the web search"),
                    TaskStep(index=3, description="Collect sources"),
                    TaskStep(index=4, description="Compare and date results where relevant"),
                    TaskStep(index=5, description="Summarize and cite sources"),
                ],
            )
        return TaskPlan(
            goal=intent,
            steps=[
                TaskStep(index=1, description="Understand the goal"),
                TaskStep(index=2, description="Inspect relevant context"),
                TaskStep(index=3, description="Plan the actions"),
                TaskStep(index=4, description="Execute the actions"),
                TaskStep(index=5, description="Verify the result"),
                TaskStep(index=6, description="Report the outcome"),
            ],
        )

    def _phone_command_plan(self, phone_command) -> TaskPlan:
        """Create a task plan for phone communication commands."""
        action_desc = f"{phone_command.action.value.capitalize()} {phone_command.recipient}"
        if phone_command.message:
            action_desc += f" with message: {phone_command.message[:50]}..."
        
        steps = [
            TaskStep(index=1, description="Parse phone command"),
            TaskStep(index=2, description=f"Resolve recipient: {phone_command.recipient}"),
            TaskStep(index=3, description="Validate phone number"),
            TaskStep(index=4, description=f"Execute {phone_command.action.value}"),
            TaskStep(index=5, description="Verify operation success"),
            TaskStep(index=6, description="Report result"),
        ]
        
        return TaskPlan(
            goal=action_desc,
            steps=steps,
            metadata={
                "phone_action": phone_command.action.value,
                "recipient": phone_command.recipient,
                "is_default_number": phone_command.is_default_number,
                "message": phone_command.message,
            }
        )

    def refine_plan(self, plan: TaskPlan, *, feedback: str | None = None) -> TaskPlan:
        """Refine a plan based on feedback or AI assistance.

        This is a placeholder for future AI-assisted refinement. For now, it
        returns the existing plan unchanged.
        """
        return plan
