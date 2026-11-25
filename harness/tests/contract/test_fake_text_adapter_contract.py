"""FakeTextAdapter must pass the shared TextStageAdapter contract (T-100)."""

from harness.adapters.text import GenerationResult, TextStageAdapter, TokenUsage
from tests.contract.text_contract import TextAdapterContract
from tests.fakes.fake_text import FakeTextAdapter


class TestFakeTextAdapterContract(TextAdapterContract):
    def make_adapter(self) -> TextStageAdapter:
        return FakeTextAdapter(
            script=[
                GenerationResult(text="scripted output", usage=TokenUsage(10, 20)),
                GenerationResult(text="scripted output 2", usage=TokenUsage(5, 5)),
            ]
        )

    def make_failing_adapter(self) -> TextStageAdapter:
        return FakeTextAdapter(script=[RuntimeError("provider exploded")])


def test_fake_text_adapter_records_calls_in_order() -> None:
    fake = FakeTextAdapter(
        script=[GenerationResult(text="a", usage=TokenUsage(1, 1))],
    )
    fake.generate("prompt-one", {"requirements.md": "reqs"})
    assert fake.calls == [("prompt-one", {"requirements.md": "reqs"})]


def test_fake_text_adapter_returns_scripted_results_in_sequence() -> None:
    fake = FakeTextAdapter(
        script=[
            GenerationResult(text="first", usage=TokenUsage(1, 1)),
            GenerationResult(text="second", usage=TokenUsage(2, 2)),
        ]
    )
    assert fake.generate("p1", {}).text == "first"
    assert fake.generate("p2", {}).text == "second"


def test_fake_text_adapter_raises_when_script_exhausted() -> None:
    from harness.core.errors import AdapterError

    fake = FakeTextAdapter(script=[])
    try:
        fake.generate("p", {})
    except AdapterError:
        pass
    else:
        raise AssertionError("expected AdapterError on exhausted script")
