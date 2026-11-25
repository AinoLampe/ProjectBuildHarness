"""The v0 `TextStageAdapter` implementation: the Anthropic Messages API
(concept §13, §19 — single provider). Declared input files are injected into
the request as labelled blocks ahead of the prompt; SDK failures are wrapped
as `AdapterError`.

Authentication is via a per-provider API key (or the Claude subscription's
non-interactive Agent SDK credit) — **verify current pricing at run time**,
the autonomous-usage billing model changed mid-2026 (concept §1).
"""

import time
from collections.abc import Callable, Sequence
from typing import Protocol, cast

import anthropic

from harness.adapters.text import GenerationResult, TokenUsage
from harness.core.errors import AdapterError

DEFAULT_MAX_TOKENS = 4096

# Transient/retriable failure classes (T-420): rate limits, transient
# server-side errors, and connectivity issues are the most common failure
# mode in a long multi-call pipeline and are worth a bounded retry rather
# than aborting the whole run. Anything else (bad request, auth, etc.) is a
# client/config error and is wrapped immediately, never retried.
_RETRYABLE_EXCEPTIONS = (
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.OverloadedError,
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
)
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 1.0


class _ContentBlockLike(Protocol):
    @property
    def text(self) -> str: ...


class _UsageLike(Protocol):
    @property
    def input_tokens(self) -> int: ...

    @property
    def output_tokens(self) -> int: ...


class _MessageLike(Protocol):
    @property
    def content(self) -> Sequence[_ContentBlockLike]: ...

    @property
    def usage(self) -> _UsageLike: ...

    @property
    def stop_reason(self) -> str | None: ...


class _MessagesApiLike(Protocol):
    def create(
        self, *, model: str, max_tokens: int, messages: list[dict[str, str]]
    ) -> _MessageLike: ...


class _AnthropicClientLike(Protocol):
    @property
    def messages(self) -> _MessagesApiLike: ...


class AnthropicTextAdapter:
    """Wraps an Anthropic-Messages-API-shaped client. The client is injected
    so contract tests can substitute a double without any network access."""

    def __init__(
        self,
        client: _AnthropicClientLike,
        model: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._sleep = sleep

    @classmethod
    def from_api_key(
        cls, model: str, max_tokens: int = DEFAULT_MAX_TOKENS
    ) -> "AnthropicTextAdapter":
        """Build a real adapter authenticated via `ANTHROPIC_API_KEY` (or
        whatever credential the installed SDK resolves by default)."""
        # The real SDK client is structurally close to _AnthropicClientLike but its
        # content-block union type isn't a literal match (some blocks lack `.text`,
        # handled defensively in `generate()`); cast at this one true boundary.
        client = cast(_AnthropicClientLike, anthropic.Anthropic())
        return cls(client, model, max_tokens)

    def generate(
        self,
        prompt: str,
        files: dict[str, str],
        *,
        template_name: str = "",
        template_version: str = "",
    ) -> GenerationResult:
        content = self._compose_message(prompt, files)
        message = self._create_with_retry(content)

        if message.stop_reason == "max_tokens":
            raise AdapterError(
                f"response truncated at max_tokens={self._max_tokens} output tokens "
                "(stop_reason='max_tokens'); the harness never treats truncated text as "
                "complete — raise models.<stage>.max_tokens or shorten the expected output"
            )

        text = "".join(
            block.text for block in message.content if getattr(block, "text", None) is not None
        )
        usage = TokenUsage(
            input_tokens=message.usage.input_tokens, output_tokens=message.usage.output_tokens
        )
        return GenerationResult(text=text, usage=usage)

    def _create_with_retry(self, content: str) -> _MessageLike:
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    messages=[{"role": "user", "content": content}],
                )
            except _RETRYABLE_EXCEPTIONS as exc:
                if attempt == _MAX_ATTEMPTS - 1:
                    raise AdapterError(
                        f"Anthropic API call failed after {_MAX_ATTEMPTS} attempts "
                        f"(transient): {exc}"
                    ) from exc
                self._sleep(_BACKOFF_BASE_SECONDS * (2**attempt))
            except Exception as exc:  # noqa: BLE001 -- adapter boundary: translate any other
                # SDK failure into the harness's typed AdapterError (guidelines §3).
                raise AdapterError(f"Anthropic API call failed: {exc}") from exc
        raise AdapterError(f"Anthropic API call failed after {_MAX_ATTEMPTS} attempts")

    @staticmethod
    def _compose_message(prompt: str, files: dict[str, str]) -> str:
        if not files:
            return prompt
        file_blocks = "\n\n".join(f"--- {name} ---\n{text}" for name, text in files.items())
        return f"{file_blocks}\n\n{prompt}"
