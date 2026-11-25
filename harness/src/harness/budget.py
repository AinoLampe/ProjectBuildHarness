"""Pure cost accounting and budget guard (concept §14). No IO, no clock, no
logging — the orchestrator routes warn/halt events to the journal.

**Pricing must be verified at run time.** The autonomous-usage billing model
changed mid-2026 (concept §1); `RATE_TABLE` below is a placeholder snapshot,
not a guarantee of current pricing.
"""

from dataclasses import dataclass

from harness.core.errors import BudgetExceeded, ConfigError


@dataclass(frozen=True)
class ModelRate:
    """USD cost per million input/output tokens."""

    input_per_mtok_usd: float
    output_per_mtok_usd: float


RATE_TABLE: dict[str, ModelRate] = {
    "claude-opus-4-8": ModelRate(input_per_mtok_usd=15.0, output_per_mtok_usd=75.0),
    "claude-sonnet-4-6": ModelRate(input_per_mtok_usd=3.0, output_per_mtok_usd=15.0),
    "claude-haiku-4-5": ModelRate(input_per_mtok_usd=0.8, output_per_mtok_usd=4.0),
}


def estimate_cost_usd(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    rate_table: dict[str, ModelRate] | None = None,
) -> float:
    table = rate_table if rate_table is not None else RATE_TABLE
    rate = table.get(model)
    if rate is None:
        raise ConfigError(f"no rate-table entry for model {model!r}; cannot estimate cost")
    return (input_tokens / 1_000_000) * rate.input_per_mtok_usd + (
        output_tokens / 1_000_000
    ) * rate.output_per_mtok_usd


def estimate_tokens_from_text(text: str) -> int:
    """A conservative, documented placeholder token-count estimate (~4
    characters per token) used only for the *pre-call* headroom check
    (T-370) — never for post-call accounting, which always uses the
    provider's actual reported usage."""
    return max(1, len(text) // 4)


@dataclass(frozen=True)
class UsageResult:
    """Outcome of recording one call's usage against the guard."""

    cost_usd: float
    total_spent_usd: float
    warned: bool


class BudgetGuard:
    """Tracks cumulative spend across a run; warns once at `warn_at_usd`;
    raises `BudgetExceeded` pre-emptively when the *next* call would breach
    `max_usd_per_run` (never after overspending).

    `rate_table` overrides/extends the module-default `RATE_TABLE` — a
    project can configure rates for models not shipped by default, or
    override the placeholder defaults (concept §1: verify pricing at run
    time)."""

    def __init__(
        self,
        *,
        max_usd_per_run: float,
        warn_at_usd: float,
        rate_table: dict[str, ModelRate] | None = None,
    ) -> None:
        self._max_usd_per_run = max_usd_per_run
        self._warn_at_usd = warn_at_usd
        self._rate_table = rate_table if rate_table is not None else RATE_TABLE
        self._total_spent_usd = 0.0
        self._has_warned = False

    @property
    def total_spent_usd(self) -> float:
        return self._total_spent_usd

    @property
    def max_usd_per_run(self) -> float:
        return self._max_usd_per_run

    def check_headroom(self, model: str, *, est_input_tokens: int, max_output_tokens: int) -> None:
        """Raise `BudgetExceeded` *before* a call is made if its worst-case
        cost — the estimated input plus the call's `max_tokens` output
        ceiling — would breach the cap (T-370). This is stricter than
        `record_usage`'s post-call check: it can reject a call the provider
        was never even asked to make."""
        worst_case_cost = estimate_cost_usd(
            model,
            input_tokens=est_input_tokens,
            output_tokens=max_output_tokens,
            rate_table=self._rate_table,
        )
        projected = self._total_spent_usd + worst_case_cost
        if projected > self._max_usd_per_run:
            raise BudgetExceeded(
                f"worst-case cost ${worst_case_cost:.4f} for the next {model} call would "
                f"bring projected spend to ${projected:.4f}, exceeding "
                f"max_usd_per_run=${self._max_usd_per_run:.4f} — call not made"
            )

    def record_usage(self, model: str, *, input_tokens: int, output_tokens: int) -> UsageResult:
        cost = estimate_cost_usd(
            model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            rate_table=self._rate_table,
        )
        projected = self._total_spent_usd + cost
        if projected > self._max_usd_per_run:
            raise BudgetExceeded(
                f"projected spend ${projected:.4f} would exceed "
                f"max_usd_per_run=${self._max_usd_per_run:.4f}"
            )

        self._total_spent_usd = projected
        warned_this_call = False
        if not self._has_warned and self._total_spent_usd >= self._warn_at_usd:
            self._has_warned = True
            warned_this_call = True

        return UsageResult(
            cost_usd=cost, total_spent_usd=self._total_spent_usd, warned=warned_this_call
        )

    def record_direct_cost(self, source: str, cost_usd: float) -> UsageResult:
        """Add an already-known, self-reported dollar cost to the same
        ledger `record_usage` uses (T-510) — for Stage 3's agent/reviewer
        calls, whose cost is reported by the agent itself rather than
        estimated from a rate table (see DECISIONS.md T-220/T-510: the two
        accounting models must never both apply to the same spend).
        `source` names the caller for the error message only. Same
        pre-emptive-halt-before-the-cap and warn-once semantics as
        `record_usage`, except the cost of *this* call is already realised
        (the agent has already run) — what this halts is the *next* one."""
        projected = self._total_spent_usd + cost_usd
        if projected > self._max_usd_per_run:
            raise BudgetExceeded(
                f"direct cost ${cost_usd:.4f} from {source} brings total spend to "
                f"${projected:.4f}, exceeding max_usd_per_run=${self._max_usd_per_run:.4f}"
            )

        self._total_spent_usd = projected
        warned_this_call = False
        if not self._has_warned and self._total_spent_usd >= self._warn_at_usd:
            self._has_warned = True
            warned_this_call = True

        return UsageResult(
            cost_usd=cost_usd, total_spent_usd=self._total_spent_usd, warned=warned_this_call
        )
