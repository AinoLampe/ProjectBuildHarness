"""File confinement + container code-execution (concept §12). Two distinct
guarantees: (1) the agent may only read/write inside the project root, and
(2) untrusted generated code runs inside a container, bind-mounted to the
project root, network disabled by default (or restricted to an allowlist).

The exact allowlist enforcement mechanism (DNS/proxy-level filtering) is a
concept §20 open item; v0 implements the binary case precisely (`network:
[]` → `--network none`, fully offline) and documents the allowlist case as a
best-effort placeholder (falls back to the default bridge network) pending
that follow-up.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from harness.core.errors import SandboxError


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str


class Sandbox:
    """Confines file access to `root` and runs commands for that root inside
    a container per `config.sandbox` (file_confinement/code_execution/
    network/container_image)."""

    def __init__(
        self,
        *,
        root: Path,
        network: list[str] | None = None,
        container_image: str = "harness/devcontainer:latest",
        ephemeral: bool = True,
        mount_path: str = "/workspace",
        default_timeout_s: float = 1800.0,
    ) -> None:
        self._root = root.resolve()
        self._network = list(network) if network is not None else []
        self._container_image = container_image
        self._ephemeral = ephemeral
        self._mount_path = mount_path
        self._default_timeout_s = default_timeout_s

    def confine(self, path: Path) -> Path:
        """Resolve `path` and reject it with `SandboxError` if it falls
        outside the project root (file confinement)."""
        resolved = path.resolve()
        if resolved != self._root and self._root not in resolved.parents:
            raise SandboxError(f"path {resolved} is outside the confined root {self._root}")
        return resolved

    def build_docker_command(self, command: list[str]) -> list[str]:
        """Construct (without executing) the `docker run` invocation for
        `command`, scoped to this sandbox's root, image, and network policy."""
        docker_command = ["docker", "run"]
        if self._ephemeral:
            docker_command.append("--rm")

        docker_command += ["-v", f"{self._root}:{self._mount_path}"]
        docker_command += ["-w", self._mount_path]

        if not self._network:
            docker_command += ["--network", "none"]
        # else: best-effort — falls back to the default bridge network; true
        # per-domain allowlisting is a concept §20 open item.

        docker_command.append(self._container_image)
        docker_command += command
        return docker_command

    def run(self, command: list[str], *, timeout_s: float | None = None) -> CommandResult:
        """Run `command` inside the configured container. `timeout_s`
        (default: `default_timeout_s`) bounds how long an unattended run can
        be blocked by one hung command (T-380); on expiry, raises
        `SandboxError` naming the command and the timeout rather than
        hanging forever."""
        docker_command = self.build_docker_command(command)
        effective_timeout = timeout_s if timeout_s is not None else self._default_timeout_s
        try:
            completed = subprocess.run(  # noqa: S603 -- docker_command is built, not user-shell input
                docker_command,
                capture_output=True,
                text=True,
                check=False,
                timeout=effective_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise SandboxError(
                f"sandboxed command {command} timed out after {effective_timeout}s"
            ) from exc
        except OSError as exc:
            raise SandboxError(f"failed to run sandboxed command via Docker: {exc}") from exc

        return CommandResult(
            exit_code=completed.returncode, stdout=completed.stdout, stderr=completed.stderr
        )
