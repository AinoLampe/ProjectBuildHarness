"""Behavioural tests for the config model + loader (T-030)."""

from pathlib import Path

import pytest

from harness.config import HarnessConfig, load_config
from harness.core.errors import ConfigError

SAMPLE_YAML = """
project:
  name: my-project
  root: ./my-project
  requirements: ./my-project/requirements.md
  instructions: ./my-project/instructions.md

models:
  concept:    { provider: anthropic, model: claude-opus-4-8 }
  guidelines: { provider: anthropic, model: claude-sonnet-4-6 }
  tickets:    { provider: anthropic, model: claude-opus-4-8 }
  implement:  { agent: claude-code,  model: claude-sonnet-4-6 }
  review:     { agent: claude-code,  model: claude-opus-4-8 }

gates:
  concept:    interactive
  guidelines: interactive
  tickets:    interactive
  phase_boundary: stop

brainstorm:
  max_rounds: 3
  on_exhaust: proceed_with_documented_assumptions

implementation:
  order: dependency_graph
  review:
    require_tests_green: true
    require_llm_review: true
  retry_budget: 2
  on_exhaust: escalate_to_user

sandbox:
  file_confinement: project_root
  code_execution: container
  network: []
  container_image: harness/devcontainer:latest

budget:
  max_usd_per_run: 25
  warn_at_usd: 15

prompts:
  template_dir: ./harness/prompts
  version: v1
"""

MINIMAL_YAML = """
project:
  name: my-project
  root: ./my-project
  requirements: ./my-project/requirements.md

models:
  concept:    { provider: anthropic, model: claude-opus-4-8 }
  guidelines: { provider: anthropic, model: claude-sonnet-4-6 }
  tickets:    { provider: anthropic, model: claude-opus-4-8 }
  implement:  { agent: claude-code,  model: claude-sonnet-4-6 }
  review:     { agent: claude-code,  model: claude-opus-4-8 }
"""


def write(tmp_path: Path, text: str) -> Path:
    config_path = tmp_path / "harness.config.yaml"
    config_path.write_text(text, encoding="utf-8")
    return config_path


def test_sample_config_round_trips(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, SAMPLE_YAML))
    assert isinstance(config, HarnessConfig)
    assert config.project.name == "my-project"
    assert config.models.concept.provider == "anthropic"
    assert config.models.concept.model == "claude-opus-4-8"
    assert config.models.implement.agent == "claude-code"
    assert config.sandbox.network == []
    assert config.budget.max_usd_per_run == 25
    assert config.prompts.version == "v1"


def test_defaults_are_applied_when_sections_are_omitted(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, MINIMAL_YAML))
    assert config.gates.concept == "interactive"
    assert config.gates.phase_boundary == "stop"
    assert config.brainstorm.max_rounds == 3
    assert config.brainstorm.on_exhaust == "proceed_with_documented_assumptions"
    assert config.implementation.retry_budget == 2
    assert config.implementation.on_exhaust == "escalate_to_user"
    assert config.implementation.agent_timeout_s == 1800.0
    assert config.budget.max_usd_per_run == 25
    assert config.budget.warn_at_usd == 15
    assert config.sandbox.file_confinement == "project_root"
    assert config.sandbox.ephemeral is True
    assert config.sandbox.command_timeout_s == 1800.0


def test_sandbox_ephemeral_and_timeouts_are_configurable(tmp_path: Path) -> None:
    custom = (
        MINIMAL_YAML
        + "\nsandbox:\n  ephemeral: false\n  command_timeout_s: 60\n"
        + "\nimplementation:\n  agent_timeout_s: 120\n"
    )
    config = load_config(write(tmp_path, custom))
    assert config.sandbox.ephemeral is False
    assert config.sandbox.command_timeout_s == 60
    assert config.implementation.agent_timeout_s == 120


def test_per_stage_routing_is_accessible(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, SAMPLE_YAML))
    assert config.models.tickets.model == "claude-opus-4-8"
    assert config.models.review.agent == "claude-code"


def test_missing_required_field_raises_config_error_naming_field(tmp_path: Path) -> None:
    broken = MINIMAL_YAML.replace("name: my-project", "")
    with pytest.raises(ConfigError, match="project.name"):
        load_config(write(tmp_path, broken))


def test_unknown_top_level_stage_raises_config_error(tmp_path: Path) -> None:
    broken = MINIMAL_YAML + "\nbogus_section:\n  foo: bar\n"
    with pytest.raises(ConfigError, match="bogus_section"):
        load_config(write(tmp_path, broken))


def test_bad_type_raises_config_error_naming_field(tmp_path: Path) -> None:
    broken = MINIMAL_YAML + "\nbudget:\n  max_usd_per_run: not-a-number\n"
    with pytest.raises(ConfigError, match="budget.max_usd_per_run"):
        load_config(write(tmp_path, broken))


def test_text_stage_with_non_anthropic_provider_is_rejected(tmp_path: Path) -> None:
    broken = MINIMAL_YAML.replace(
        "concept:    { provider: anthropic, model: claude-opus-4-8 }",
        "concept:    { provider: openai, model: gpt-5 }",
    )
    with pytest.raises(ConfigError, match="anthropic"):
        load_config(write(tmp_path, broken))


def test_implement_stage_with_non_claude_code_agent_is_rejected(tmp_path: Path) -> None:
    broken = MINIMAL_YAML.replace(
        "implement:  { agent: claude-code,  model: claude-sonnet-4-6 }",
        "implement:  { agent: opencode,  model: claude-sonnet-4-6 }",
    )
    with pytest.raises(ConfigError, match="claude-code"):
        load_config(write(tmp_path, broken))


def test_missing_config_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "does-not-exist.yaml")


def test_warn_at_usd_above_max_usd_per_run_is_rejected(tmp_path: Path) -> None:
    broken = MINIMAL_YAML + "\nbudget:\n  max_usd_per_run: 10\n  warn_at_usd: 20\n"
    with pytest.raises(ConfigError, match="warn_at_usd"):
        load_config(write(tmp_path, broken))


def test_unrated_model_for_a_text_stage_is_rejected(tmp_path: Path) -> None:
    broken = MINIMAL_YAML.replace(
        "concept:    { provider: anthropic, model: claude-opus-4-8 }",
        "concept:    { provider: anthropic, model: claude-unreleased-9 }",
    )
    with pytest.raises(ConfigError, match="models.concept.model"):
        load_config(write(tmp_path, broken))


def test_max_tokens_is_optional_per_model_route(tmp_path: Path) -> None:
    with_max_tokens = MINIMAL_YAML.replace(
        "concept:    { provider: anthropic, model: claude-opus-4-8 }",
        "concept:    { provider: anthropic, model: claude-opus-4-8, max_tokens: 16384 }",
    )
    config = load_config(write(tmp_path, with_max_tokens))
    assert config.models.concept.max_tokens == 16384
    assert config.models.guidelines.max_tokens is None


def test_custom_model_rates_satisfy_the_rate_requirement(tmp_path: Path) -> None:
    custom = MINIMAL_YAML.replace(
        "concept:    { provider: anthropic, model: claude-opus-4-8 }",
        "concept:    { provider: anthropic, model: claude-unreleased-9 }",
    )
    custom += (
        "\nbudget:\n  model_rates:\n    claude-unreleased-9:\n"
        "      input_per_mtok_usd: 5.0\n      output_per_mtok_usd: 25.0\n"
    )
    config = load_config(write(tmp_path, custom))
    assert config.budget.model_rates["claude-unreleased-9"].input_per_mtok_usd == 5.0
