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

__all__ = [
    "DEFAULT_RUNNER_FACTORIES",
    "DispatchPlan",
    "DispatchRequest",
    "Dispatcher",
    "ParticipantsPool",
    "RegistryError",
    "RoleAssignment",
    "RunnerFactory",
    "TaskType",
    "build_participants_pool",
    "render_plan_summary",
]
