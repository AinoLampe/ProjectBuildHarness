"""Gated smoke test: a real call to the Anthropic API. Skipped offline / when
no API key is configured (guidelines §4.2 — real adapters smoke-tested
separately from the contract suite)."""

import os

import pytest

from harness.adapters.anthropic_text import AnthropicTextAdapter

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="requires ANTHROPIC_API_KEY for a live smoke test",
)


def test_real_anthropic_call_returns_populated_text_and_usage() -> None:
    adapter = AnthropicTextAdapter.from_api_key(model="claude-haiku-4-5")
    result = adapter.generate("Reply with exactly the word: pong", {})
    assert result.text.strip() != ""
    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0
