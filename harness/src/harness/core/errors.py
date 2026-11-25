"""Typed exception hierarchy. Every error the harness raises descends from
`HarnessError` so callers can catch the harness's own failures specifically,
never bare `Exception` (guidelines §3)."""


class HarnessError(Exception):
    """Base class for every error the harness raises deliberately."""


class ConfigError(HarnessError):
    """Raised when `harness.config.yaml` is missing, malformed, or invalid."""


class FolderError(HarnessError):
    """Raised on illegal or failed project-folder access."""


class StageError(HarnessError):
    """Raised when a stage fails to produce its declared outputs."""


class BudgetExceeded(HarnessError):
    """Raised pre-emptively when the next call would breach the run budget."""


class GateRejected(HarnessError):
    """Raised when a human gate rejects an artifact; carries feedback."""


class SandboxError(HarnessError):
    """Raised on a sandbox confinement or execution failure."""


class AdapterError(HarnessError):
    """Raised when a provider/agent adapter call fails."""


class DagCycleError(HarnessError):
    """Raised when the ticket dependency graph contains a cycle."""


class DagReferenceError(HarnessError):
    """Raised when a ticket's Connections reference a ticket id that does
    not exist in the dependency graph (T-360)."""


class PromptError(HarnessError):
    """Raised when a named prompt template is missing or rendering it is
    missing a required variable (T-090; see DECISIONS.md)."""


class EscalationRequired(HarnessError):
    """Raised when a run cannot proceed without human input — retry-budget
    exhaustion, unresolved ambiguity, or final-acceptance drift (T-530).
    Carries no attachment beyond its message; the caller is expected to
    have already recorded an `EscalationRecord` (journal.py) before
    raising, and the orchestrator turns this into a clean halt rather than
    letting it surface as a traceback."""
