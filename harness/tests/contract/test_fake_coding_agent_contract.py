"""FakeCodingAgent must pass the shared CodingAgentAdapter contract (T-130)."""

from pathlib import Path

from harness.adapters.coding import AgentResult, CodingAgentAdapter
from harness.adapters.text import TokenUsage
from harness.sandbox import Sandbox
from tests.contract.coding_contract import CodingAgentContract
from tests.fakes.fake_coding import FakeCodingAgent, ScriptedRun


class TestFakeCodingAgentContract(CodingAgentContract):
    def make_adapter(self) -> CodingAgentAdapter:
        return FakeCodingAgent(
            script=[
                ScriptedRun(
                    result=AgentResult(
                        success=True,
                        summary="did the thing",
                        usage=TokenUsage(10, 20),
                        cost_usd=0.01,
                    )
                )
            ]
        )

    def make_failing_adapter(self) -> CodingAgentAdapter:
        return FakeCodingAgent(script=[RuntimeError("agent crashed")])


def test_fake_coding_agent_writes_scripted_files(tmp_path: Path) -> None:
    fake = FakeCodingAgent(
        script=[
            ScriptedRun(
                result=AgentResult(
                    success=True, summary="wrote a module", usage=TokenUsage(1, 1), cost_usd=0.0
                ),
                writes={"src/harness/dag.py": "# generated content"},
            )
        ]
    )
    sandbox = Sandbox(root=tmp_path)
    result = fake.run(tmp_path, "implement T-080", sandbox)
    assert result.success is True
    written = tmp_path / "src" / "harness" / "dag.py"
    assert written.read_text(encoding="utf-8") == "# generated content"


def test_fake_coding_agent_records_calls(tmp_path: Path) -> None:
    fake = FakeCodingAgent(
        script=[
            ScriptedRun(
                result=AgentResult(success=True, summary="x", usage=TokenUsage(1, 1), cost_usd=0.0)
            )
        ]
    )
    sandbox = Sandbox(root=tmp_path)
    fake.run(tmp_path, "implement T-080", sandbox)
    assert fake.calls == [(tmp_path, "implement T-080")]
