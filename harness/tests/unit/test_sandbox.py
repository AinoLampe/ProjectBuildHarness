"""Behavioural tests for the sandbox (T-120, T-380). Container execution is
smoke-tested separately behind a Docker-availability skip; this module
unit-tests file confinement and Docker command construction without
running Docker."""

import shutil
import subprocess
from pathlib import Path

import pytest

from harness.core.errors import SandboxError
from harness.sandbox import Sandbox

DOCKER_AVAILABLE = shutil.which("docker") is not None


def test_confine_accepts_a_path_inside_the_root(tmp_path: Path) -> None:
    sandbox = Sandbox(root=tmp_path)
    inside = tmp_path / "src" / "main.py"
    assert sandbox.confine(inside) == inside.resolve()


def test_confine_rejects_a_path_outside_the_root(tmp_path: Path) -> None:
    sandbox = Sandbox(root=tmp_path)
    outside = tmp_path.parent / "elsewhere.txt"
    with pytest.raises(SandboxError):
        sandbox.confine(outside)


def test_confine_rejects_traversal_outside_the_root(tmp_path: Path) -> None:
    sandbox = Sandbox(root=tmp_path)
    traversal = tmp_path / "src" / ".." / ".." / "escape.txt"
    with pytest.raises(SandboxError):
        sandbox.confine(traversal)


def test_build_docker_command_defaults_to_network_none(tmp_path: Path) -> None:
    sandbox = Sandbox(root=tmp_path, network=[])
    command = sandbox.build_docker_command(["pytest"])
    assert "--network" in command
    assert command[command.index("--network") + 1] == "none"


def test_build_docker_command_with_allowlist_does_not_disable_network(tmp_path: Path) -> None:
    sandbox = Sandbox(root=tmp_path, network=["pypi.org"])
    command = sandbox.build_docker_command(["pip", "install", "foo"])
    if "--network" in command:
        assert command[command.index("--network") + 1] != "none"


def test_build_docker_command_mounts_project_root(tmp_path: Path) -> None:
    sandbox = Sandbox(root=tmp_path)
    command = sandbox.build_docker_command(["pytest"])
    assert "-v" in command
    mount_arg = command[command.index("-v") + 1]
    assert str(tmp_path) in mount_arg


def test_build_docker_command_uses_configured_image(tmp_path: Path) -> None:
    sandbox = Sandbox(root=tmp_path, container_image="harness/devcontainer:latest")
    command = sandbox.build_docker_command(["pytest"])
    assert "harness/devcontainer:latest" in command


def test_build_docker_command_ephemeral_includes_rm_flag(tmp_path: Path) -> None:
    sandbox = Sandbox(root=tmp_path, ephemeral=True)
    command = sandbox.build_docker_command(["pytest"])
    assert "--rm" in command


def test_build_docker_command_non_ephemeral_omits_rm_flag(tmp_path: Path) -> None:
    sandbox = Sandbox(root=tmp_path, ephemeral=False)
    command = sandbox.build_docker_command(["pytest"])
    assert "--rm" not in command


def test_build_docker_command_includes_the_caller_command(tmp_path: Path) -> None:
    sandbox = Sandbox(root=tmp_path)
    command = sandbox.build_docker_command(["pytest", "-q"])
    assert command[-2:] == ["pytest", "-q"]


@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="requires a local Docker daemon")
def test_run_executes_inside_a_container_and_returns_exit_code(tmp_path: Path) -> None:
    sandbox = Sandbox(root=tmp_path, container_image="alpine:latest")
    result = sandbox.run(["echo", "hello-from-sandbox"])
    assert result.exit_code == 0
    assert "hello-from-sandbox" in result.stdout


def test_run_wraps_a_missing_docker_binary_as_sandbox_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox = Sandbox(root=tmp_path)

    def _raise_missing(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("docker not found")

    monkeypatch.setattr("harness.sandbox.subprocess.run", _raise_missing)
    with pytest.raises(SandboxError):
        sandbox.run(["echo", "hi"])


def test_run_raises_sandbox_error_on_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox = Sandbox(root=tmp_path, default_timeout_s=5.0)

    def _raise_timeout(*_args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="docker run ...", timeout=kwargs["timeout"])  # type: ignore[arg-type]

    monkeypatch.setattr("harness.sandbox.subprocess.run", _raise_timeout)
    with pytest.raises(SandboxError, match="timed out"):
        sandbox.run(["sleep", "9999"])


def test_run_passes_the_configured_timeout_to_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def _capture(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr("harness.sandbox.subprocess.run", _capture)
    sandbox = Sandbox(root=tmp_path, default_timeout_s=42.0)
    sandbox.run(["echo", "hi"])
    assert captured["timeout"] == 42.0

    sandbox.run(["echo", "hi"], timeout_s=7.0)
    assert captured["timeout"] == 7.0
