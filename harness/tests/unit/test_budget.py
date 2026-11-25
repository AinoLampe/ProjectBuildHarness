"""Behavioural tests for the budget guard (T-060, T-370)."""

import pytest

from harness.budget import (
    RATE_TABLE,
    BudgetGuard,
    ModelRate,
    estimate_cost_usd,
    estimate_tokens_from_text,
)
from harness.core.errors import BudgetExceeded, ConfigError


def test_estimate_cost_uses_rate_table() -> None:
    rate = RATE_TABLE["claude-opus-4-8"]
    expected = (1_000_000 / 1_000_000) * rate.input_per_mtok_usd + (
        500_000 / 1_000_000
    ) * rate.output_per_mtok_usd
    assert estimate_cost_usd("claude-opus-4-8", input_tokens=1_000_000, output_tokens=500_000) == (
        pytest.approx(expected)
    )


def test_estimate_cost_unknown_model_raises_config_error() -> None:
    with pytest.raises(ConfigError):
        estimate_cost_usd("not-a-real-model", input_tokens=1, output_tokens=1)


def test_guard_accumulates_spend_across_multiple_calls() -> None:
    guard = BudgetGuard(max_usd_per_run=100.0, warn_at_usd=1000.0)
    guard.record_usage("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0)
    first_total = guard.total_spent_usd
    guard.record_usage("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0)
    assert guard.total_spent_usd == pytest.approx(first_total * 2)
    assert guard.total_spent_usd > 0


def test_warn_signal_fires_exactly_once_when_crossing_threshold() -> None:
    rate = RATE_TABLE["claude-sonnet-4-6"]
    per_call_cost = rate.input_per_mtok_usd  # cost of 1_000_000 input tokens, 0 output
    guard = BudgetGuard(max_usd_per_run=1000.0, warn_at_usd=per_call_cost * 1.5)

    first = guard.record_usage("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0)
    assert first.warned is False

    second = guard.record_usage("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0)
    assert second.warned is True  # crosses warn_at_usd on this call

    third = guard.record_usage("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0)
    assert third.warned is False  # already warned once; does not fire again


def test_budget_exceeded_raised_preemptively_before_overspending() -> None:
    rate = RATE_TABLE["claude-sonnet-4-6"]
    per_call_cost = rate.input_per_mtok_usd
    guard = BudgetGuard(max_usd_per_run=per_call_cost * 1.5, warn_at_usd=per_call_cost * 1.5)

    guard.record_usage("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0)
    spent_before = guard.total_spent_usd

    with pytest.raises(BudgetExceeded):
        guard.record_usage("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0)

    # the rejected call must not have been accumulated (raised *before* the cap)
    assert guard.total_spent_usd == spent_before


def test_model_rate_is_a_plain_value_object() -> None:
    rate = ModelRate(input_per_mtok_usd=1.0, output_per_mtok_usd=2.0)
    assert rate.input_per_mtok_usd == 1.0
    assert rate.output_per_mtok_usd == 2.0


def test_check_headroom_blocks_a_call_that_would_breach_the_cap() -> None:
    rate = RATE_TABLE["claude-opus-4-8"]
    guard = BudgetGuard(max_usd_per_run=rate.output_per_mtok_usd / 2, warn_at_usd=0.0)

    with pytest.raises(BudgetExceeded):
        guard.check_headroom("claude-opus-4-8", est_input_tokens=1, max_output_tokens=1_000_000)

    assert guard.total_spent_usd == 0.0  # rejected before any accounting happened


def test_check_headroom_allows_a_call_within_the_cap() -> None:
    guard = BudgetGuard(max_usd_per_run=1000.0, warn_at_usd=900.0)
    guard.check_headroom("claude-sonnet-4-6", est_input_tokens=100, max_output_tokens=4096)
    # no exception; headroom exists


def test_estimate_cost_honours_a_custom_rate_table() -> None:
    custom_rates = {"my-custom-model": ModelRate(input_per_mtok_usd=1.0, output_per_mtok_usd=1.0)}
    cost = estimate_cost_usd(
        "my-custom-model", input_tokens=1_000_000, output_tokens=0, rate_table=custom_rates
    )
    assert cost == pytest.approx(1.0)

    with pytest.raises(ConfigError):
        estimate_cost_usd("my-custom-model", input_tokens=1, output_tokens=1)  # not in RATE_TABLE


def test_budget_guard_uses_its_injected_rate_table_for_both_headroom_and_recording() -> None:
    custom_rates = {"my-model": ModelRate(input_per_mtok_usd=10.0, output_per_mtok_usd=10.0)}
    guard = BudgetGuard(max_usd_per_run=1000.0, warn_at_usd=900.0, rate_table=custom_rates)

    guard.check_headroom("my-model", est_input_tokens=100, max_output_tokens=100)
    result = guard.record_usage("my-model", input_tokens=1_000_000, output_tokens=0)
    assert result.cost_usd == pytest.approx(10.0)


def test_estimate_tokens_from_text_is_conservative_and_never_zero() -> None:
    assert estimate_tokens_from_text("") == 1
    assert estimate_tokens_from_text("x" * 400) == 100


def test_record_direct_cost_accumulates_on_the_same_ledger_as_record_usage() -> None:
    guard = BudgetGuard(max_usd_per_run=100.0, warn_at_usd=1000.0)
    guard.record_usage("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0)
    after_text_call = guard.total_spent_usd

    guard.record_direct_cost("implement:T-010", 5.0)

    assert guard.total_spent_usd == pytest.approx(after_text_call + 5.0)


def test_record_direct_cost_halts_before_exceeding_the_cap() -> None:
    guard = BudgetGuard(max_usd_per_run=10.0, warn_at_usd=1000.0)
    guard.record_direct_cost("implement:T-010", 8.0)

    with pytest.raises(BudgetExceeded):
        guard.record_direct_cost("implement:T-020", 5.0)

    # the second (rejected) call was never accumulated
    assert guard.total_spent_usd == pytest.approx(8.0)


def test_record_direct_cost_warns_once_when_crossing_the_threshold() -> None:
    guard = BudgetGuard(max_usd_per_run=100.0, warn_at_usd=10.0)
    first = guard.record_direct_cost("implement:T-010", 5.0)
    assert first.warned is False

    second = guard.record_direct_cost("implement:T-020", 6.0)
    assert second.warned is True

    third = guard.record_direct_cost("implement:T-030", 1.0)
    assert third.warned is False


def test_max_usd_per_run_is_publicly_readable() -> None:
    guard = BudgetGuard(max_usd_per_run=42.0, warn_at_usd=10.0)
    assert guard.max_usd_per_run == 42.0
