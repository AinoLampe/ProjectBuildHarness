"""Shared behavioural contract for `TextStageAdapter` (T-100). Any
implementation (real or fake) must pass this suite. Subclass
`TextAdapterContract` in an adapter-specific test module and implement
`make_adapter()` / `make_failing_adapter()`.
"""

import pytest

from harness.adapters.text import GenerationResult, TextStageAdapter
from harness.core.errors import AdapterError


def assert_valid_generation_result(result: GenerationResult) -> None:
    assert isinstance(result.text, str)
    assert result.usage.input_tokens >= 0
    assert result.usage.output_tokens >= 0


class TextAdapterContract:
    def make_adapter(self) -> TextStageAdapter:
        raise NotImplementedError

    def make_failing_adapter(self) -> TextStageAdapter:
        raise NotImplementedError

    def test_generate_returns_text_and_usage(self) -> None:
        adapter = self.make_adapter()
        result = adapter.generate("hello", {})
        assert_valid_generation_result(result)

    def test_generate_accepts_declared_input_files(self) -> None:
        adapter = self.make_adapter()
        result = adapter.generate("summarise", {"requirements.md": "build a thing"})
        assert_valid_generation_result(result)

    def test_generate_wraps_provider_failures_as_adapter_error(self) -> None:
        adapter = self.make_failing_adapter()
        with pytest.raises(AdapterError):
            adapter.generate("trigger-failure", {})
