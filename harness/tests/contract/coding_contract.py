"""Shared behavioural contract for `CodingAgentAdapter` (T-130). Subclass
`CodingAgentContract` in an adapter-specific test module and implement
`make_adapter()` / `make_failing_adapter()`."""

from pathlib import Path

import pytest

from harness.adapters.coding import AgentResult, CodingAgentAdapter
from harness.core.errors import AdapterError
from harness.sandbox import Sandbox


def assert_valid_agent_result(result: AgentResult) -> None:
    assert isinstance(result.success, bool)
    assert isinstance(result.summary, str)
    assert result.usage.input_tokens >= 0
    assert result.usage.output_tokens >= 0
    assert result.cost_usd >= 0


class CodingAgentContract:
    def make_adapter(self) -> CodingAgentAdapter:
        raise NotImplementedError

    def make_failing_adapter(self) -> CodingAgentAdapter:
        raise NotImplementedError

    def test_run_returns_outcome_and_usage(self, tmp_path: Path) -> None:
        adapter = self.make_adapter()
        sandbox = Sandbox(root=tmp_path)
        result = adapter.run(tmp_path, "implement T-010", sandbox)
        assert_valid_agent_result(result)

    def test_run_wraps_provider_failures_as_adapter_error(self, tmp_path: Path) -> None:
        adapter = self.make_failing_adapter()
        sandbox = Sandbox(root=tmp_path)
        with pytest.raises(AdapterError):
            adapter.run(tmp_path, "trigger-failure", sandbox)
