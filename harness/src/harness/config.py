"""Pydantic v2 config model + YAML loader/validator for `harness.config.yaml`
(concept §4). v0 constrains text stages to the Anthropic provider and the
implement/review stages to the Claude Code agent; the `provider`/`agent` fields
exist for v1 pluggability but other values are rejected with a clear message.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator
from pydantic_core import ErrorDetails

from harness.budget import RATE_TABLE
from harness.core.errors import ConfigError

GatePolicy = Literal["interactive", "auto_approve"]

_TEXT_STAGES = ("concept", "guidelines", "tickets")
_AGENT_STAGES = ("implement", "review")


class _Strict(BaseModel):
    """Base model rejecting unknown fields, so a typo or stale key is a hard
    config error rather than a silently-ignored field."""

    model_config = ConfigDict(extra="forbid")


class ProjectConfig(_Strict):
    name: str
    root: Path
    requirements: Path
    instructions: Path | None = None


class ModelRoute(_Strict):
    provider: str | None = None
    agent: str | None = None
    model: str
    # Text-stage generation ceiling (T-420); `None` uses the adapter's own
    # default. Not meaningful for agent stages (implement/review).
    max_tokens: int | None = None


class ModelsConfig(_Strict):
    concept: ModelRoute
    guidelines: ModelRoute
    tickets: ModelRoute
    implement: ModelRoute
    review: ModelRoute

    @model_validator(mode="after")
    def _check_v0_provider_agent_constraints(self) -> "ModelsConfig":
        for stage_name in _TEXT_STAGES:
            route = getattr(self, stage_name)
            if route.provider != "anthropic":
                raise ValueError(
                    f"models.{stage_name}.provider must be 'anthropic' in v0, "
                    f"got {route.provider!r}"
                )
            if route.agent is not None:
                raise ValueError(f"models.{stage_name} must not set 'agent' (text stage)")
        for stage_name in _AGENT_STAGES:
            route = getattr(self, stage_name)
            if route.agent != "claude-code":
                raise ValueError(
                    f"models.{stage_name}.agent must be 'claude-code' in v0, got {route.agent!r}"
                )
            if route.provider is not None:
                raise ValueError(f"models.{stage_name} must not set 'provider' (agent stage)")
        return self


class GatesConfig(_Strict):
    concept: GatePolicy = "interactive"
    guidelines: GatePolicy = "interactive"
    tickets: GatePolicy = "interactive"
    phase_boundary: Literal["stop"] = "stop"


class BrainstormConfig(_Strict):
    max_rounds: int = 3
    on_exhaust: Literal["proceed_with_documented_assumptions"] = (
        "proceed_with_documented_assumptions"
    )


class ReviewPolicy(_Strict):
    require_tests_green: bool = True
    require_llm_review: bool = True


class ImplementationConfig(_Strict):
    order: Literal["dependency_graph"] = "dependency_graph"
    review: ReviewPolicy = ReviewPolicy()
    retry_budget: int = 2
    on_exhaust: Literal["escalate_to_user"] = "escalate_to_user"
    # Bounds a single `claude -p` implementer/reviewer invocation (T-380) so
    # a wedged agent process cannot block an unattended run forever.
    agent_timeout_s: float = 1800.0


class SandboxConfig(_Strict):
    file_confinement: Literal["project_root"] = "project_root"
    code_execution: Literal["container"] = "container"
    network: list[str] = []
    container_image: str = "harness/devcontainer:latest"
    # Fixed-in-v0: `file_confinement`/`code_execution` accept only the
    # literal values above; the two fields below are the tunable knobs.
    ephemeral: bool = True
    command_timeout_s: float = 1800.0


class ModelRateConfig(_Strict):
    """A project-supplied cost rate for one model (T-370), merged over
    `budget.RATE_TABLE`'s defaults so a project can price a model the
    harness doesn't ship a rate for, or override a stale default."""

    input_per_mtok_usd: float
    output_per_mtok_usd: float


class BudgetConfig(_Strict):
    max_usd_per_run: float = 25
    warn_at_usd: float = 15
    model_rates: dict[str, ModelRateConfig] = {}

    @model_validator(mode="after")
    def _check_warn_at_or_below_max(self) -> "BudgetConfig":
        if self.warn_at_usd > self.max_usd_per_run:
            raise ValueError(
                f"budget.warn_at_usd ({self.warn_at_usd}) must not exceed "
                f"budget.max_usd_per_run ({self.max_usd_per_run})"
            )
        return self


class PromptsConfig(_Strict):
    template_dir: Path = Path("./harness/prompts")
    version: str = "v1"


class HarnessConfig(_Strict):
    project: ProjectConfig
    models: ModelsConfig
    gates: GatesConfig = GatesConfig()
    brainstorm: BrainstormConfig = BrainstormConfig()
    implementation: ImplementationConfig = ImplementationConfig()
    sandbox: SandboxConfig = SandboxConfig()
    budget: BudgetConfig = BudgetConfig()
    prompts: PromptsConfig = PromptsConfig()

    @model_validator(mode="after")
    def _check_text_stage_models_have_budget_rates(self) -> "HarnessConfig":
        # only the text stages (concept/guidelines/tickets) route through
        # BudgetGuard today (T-370); Stage 3's agent/reviewer spend is
        # self-reported, not rate-table-estimated (DECISIONS.md T-220/T-510).
        known_models = set(RATE_TABLE) | set(self.budget.model_rates)
        for stage_name in _TEXT_STAGES:
            model = getattr(self.models, stage_name).model
            if model not in known_models:
                raise ValueError(
                    f"models.{stage_name}.model {model!r} has no budget rate — add it to "
                    "budget.model_rates or use a model already in the default rate table"
                )
        return self


def _field_path(error: ErrorDetails) -> str:
    return ".".join(str(part) for part in error["loc"])


def load_config(path: Path) -> HarnessConfig:
    """Load and validate `harness.config.yaml`, raising `ConfigError` naming
    the offending field on any failure."""
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"could not read config file {path}: {exc}") from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc

    try:
        config = HarnessConfig.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = _field_path(first)
        raise ConfigError(f"{field}: {first['msg']}") from exc

    if not config.prompts.template_dir.is_absolute():
        # Resolved against the config file's own directory (T-400), not the
        # process CWD — so a relative `prompts.template_dir` behaves
        # identically regardless of where `harness run` is invoked from.
        config.prompts.template_dir = (path.parent / config.prompts.template_dir).resolve()

    return config
