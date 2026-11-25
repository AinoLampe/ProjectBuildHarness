"""AnthropicTextAdapter must pass the shared TextStageAdapter contract
(T-110), exercised against a fake Messages-API-shaped client — no network.

Truncation detection and transient-error retry (T-420) are Anthropic-
specific behaviours tied to the real Messages API's `stop_reason` field and
the `anthropic` SDK's exception hierarchy — neither concept exists in the
abstract `TextStageAdapter` protocol (`GenerationResult` carries only text +
usage), so these cases live here rather than in the shared contract suite.
"""

from dataclasses import dataclass

import httpx
import pytest
from anthropic import APIConnectionError, BadRequestError, RateLimitError

from harness.adapters.anthropic_text import AnthropicTextAdapter
from harness.adapters.text import TextStageAdapter
from harness.core.errors import AdapterError
from tests.contract.text_contract import TextAdapterContract


@dataclass
class _FakeBlock:
    text: str


@dataclass
class _FakeUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class _FakeMessage:
    content: list[_FakeBlock]
    usage: _FakeUsage
    stop_reason: str | None = "end_turn"


class _FakeMessagesApi:
    def __init__(self, *, fail: bool) -> None:
        self._fail = fail

    def create(
        self, *, model: str, max_tokens: int, messages: list[dict[str, str]]
    ) -> _FakeMessage:
        if self._fail:
            raise RuntimeError("simulated Anthropic SDK failure")
        return _FakeMessage(content=[_FakeBlock(text="fake response")], usage=_FakeUsage(7, 11))


class _FakeAnthropicClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.messages = _FakeMessagesApi(fail=fail)


class TestAnthropicTextAdapterContract(TextAdapterContract):
    def make_adapter(self) -> TextStageAdapter:
        return AnthropicTextAdapter(_FakeAnthropicClient(), model="claude-opus-4-8")

    def make_failing_adapter(self) -> TextStageAdapter:
        return AnthropicTextAdapter(_FakeAnthropicClient(fail=True), model="claude-opus-4-8")


def test_declared_files_are_injected_ahead_of_the_prompt() -> None:
    captured: dict[str, object] = {}

    class _CapturingMessagesApi:
        def create(
            self, *, model: str, max_tokens: int, messages: list[dict[str, str]]
        ) -> _FakeMessage:
            captured["messages"] = messages
            return _FakeMessage(content=[_FakeBlock(text="ok")], usage=_FakeUsage(1, 1))

    class _CapturingClient:
        def __init__(self) -> None:
            self.messages = _CapturingMessagesApi()

    adapter = AnthropicTextAdapter(_CapturingClient(), model="claude-opus-4-8")
    adapter.generate("write the concept", {"requirements.md": "build a thing"})

    sent_content = captured["messages"][0]["content"]  # type: ignore[index]
    assert "requirements.md" in sent_content
    assert "build a thing" in sent_content
    assert "write the concept" in sent_content


def _rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def _connection_error() -> APIConnectionError:
    return APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )


def test_truncated_response_raises_adapter_error_not_returned_as_complete() -> None:
    class _TruncatingMessagesApi:
        def create(
            self, *, model: str, max_tokens: int, messages: list[dict[str, str]]
        ) -> _FakeMessage:
            return _FakeMessage(
                content=[_FakeBlock(text="cut off mid-")],
                usage=_FakeUsage(10, max_tokens),
                stop_reason="max_tokens",
            )

    class _TruncatingClient:
        def __init__(self) -> None:
            self.messages = _TruncatingMessagesApi()

    adapter = AnthropicTextAdapter(_TruncatingClient(), model="claude-opus-4-8")
    with pytest.raises(AdapterError, match="truncated"):
        adapter.generate("write something long", {})


def test_normal_end_turn_response_is_unaffected_by_truncation_check() -> None:
    adapter = AnthropicTextAdapter(_FakeAnthropicClient(), model="claude-opus-4-8")
    result = adapter.generate("hello", {})
    assert result.text == "fake response"


def test_transient_error_is_retried_then_succeeds() -> None:
    calls = {"count": 0}

    class _FlakyMessagesApi:
        def create(
            self, *, model: str, max_tokens: int, messages: list[dict[str, str]]
        ) -> _FakeMessage:
            calls["count"] += 1
            if calls["count"] < 3:
                raise _rate_limit_error()
            return _FakeMessage(content=[_FakeBlock(text="ok")], usage=_FakeUsage(1, 1))

    class _FlakyClient:
        def __init__(self) -> None:
            self.messages = _FlakyMessagesApi()

    sleeps: list[float] = []
    adapter = AnthropicTextAdapter(_FlakyClient(), model="claude-opus-4-8", sleep=sleeps.append)

    result = adapter.generate("hello", {})

    assert result.text == "ok"
    assert calls["count"] == 3
    assert len(sleeps) == 2  # slept between attempts 1->2 and 2->3, not after success


def test_transient_error_exhausting_retries_raises_adapter_error() -> None:
    class _AlwaysFlakyMessagesApi:
        def create(
            self, *, model: str, max_tokens: int, messages: list[dict[str, str]]
        ) -> _FakeMessage:
            raise _connection_error()

    class _AlwaysFlakyClient:
        def __init__(self) -> None:
            self.messages = _AlwaysFlakyMessagesApi()

    adapter = AnthropicTextAdapter(
        _AlwaysFlakyClient(), model="claude-opus-4-8", sleep=lambda _seconds: None
    )
    with pytest.raises(AdapterError, match="3 attempts"):
        adapter.generate("hello", {})


def test_non_transient_error_is_not_retried() -> None:
    calls = {"count": 0}

    class _BadRequestMessagesApi:
        def create(
            self, *, model: str, max_tokens: int, messages: list[dict[str, str]]
        ) -> _FakeMessage:
            calls["count"] += 1
            request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            response = httpx.Response(400, request=request)
            raise BadRequestError("bad request", response=response, body=None)

    class _BadRequestClient:
        def __init__(self) -> None:
            self.messages = _BadRequestMessagesApi()

    adapter = AnthropicTextAdapter(
        _BadRequestClient(), model="claude-opus-4-8", sleep=lambda _seconds: None
    )
    with pytest.raises(AdapterError):
        adapter.generate("hello", {})
    assert calls["count"] == 1  # no retry for a non-transient error
