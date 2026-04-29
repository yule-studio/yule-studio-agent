"""Engineering-agent department runtime: runners, registry, hooks."""

from .dispatcher import (
    DispatchPlan,
    DispatchRequest,
    Dispatcher,
    RoleAssignment,
    TaskType,
    render_plan_summary,
)
from .registry import (
    DEFAULT_RUNNER_FACTORIES,
    ParticipantsPool,
    RegistryError,
    RunnerFactory,
    build_participants_pool,
)
from .workflow import (
    CompletionResult,
    IntakeResult,
    ProgressResult,
    WorkflowError,
    WorkflowOrchestrator,
    extract_urls,
    format_completion_message,
    format_intake_message,
    format_progress_message,
)
from .workflow_state import WorkflowSession, WorkflowState

__all__ = [
    "CompletionResult",
    "DEFAULT_RUNNER_FACTORIES",
    "DispatchPlan",
    "DispatchRequest",
    "Dispatcher",
    "IntakeResult",
    "ParticipantsPool",
    "ProgressResult",
    "RegistryError",
    "RoleAssignment",
    "RunnerFactory",
    "TaskType",
    "WorkflowError",
    "WorkflowOrchestrator",
    "WorkflowSession",
    "WorkflowState",
    "build_participants_pool",
    "extract_urls",
    "format_completion_message",
    "format_intake_message",
    "format_progress_message",
    "render_plan_summary",
]
