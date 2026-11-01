"""Isolated Docker sandbox for executing generated code.

Generated code never runs on the host. For every QA run the sandbox:

1. creates a container from the component image with CPU, memory and PID
   limits, all capabilities dropped and ``no-new-privileges`` set;
2. copies the workspace into the container with ``docker cp`` (no bind mounts,
   so no host directory - and never the Docker socket - is visible inside);
3. runs dependency installation (network disabled unless explicitly allowed);
4. snapshots that container to a temporary image;
5. runs each test/lint/build command in a fresh container from the snapshot
   with ``--network none`` and a hard timeout;
6. captures stdout, stderr and exit code, then removes containers and images.
"""

from __future__ import annotations

import logging
import shlex
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.errors import SandboxError

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    command: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass
class SandboxRun:
    setup: list[CommandResult] = field(default_factory=list)
    commands: list[CommandResult] = field(default_factory=list)

    @property
    def setup_succeeded(self) -> bool:
        return all(r.succeeded for r in self.setup)


def _tail(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"... [{len(text) - limit} characters truncated]\n" + text[-limit:]


class DockerSandbox:
    def __init__(self, settings: Settings | None = None, *, docker_bin: str = "docker",
                 allow_network_for_install: bool | None = None) -> None:
        self.settings = settings or get_settings()
        self.docker = docker_bin
        self.allow_network_for_install = (
            self.settings.sandbox_allow_network_for_install
            if allow_network_for_install is None else allow_network_for_install
        )

    # -- helpers -------------------------------------------------------------------

    def available(self) -> tuple[bool, str]:
        if not self.settings.sandbox_enabled:
            return False, "Sandbox disabled by configuration (SANDBOX_ENABLED=false)"
        if shutil.which(self.docker) is None:
            return False, "Docker CLI not found"
        try:
            result = subprocess.run([self.docker, "info", "--format", "{{.ServerVersion}}"],
                                    capture_output=True, text=True, timeout=15, check=False)
        except subprocess.TimeoutExpired:
            return False, "Docker daemon did not respond"
        version = result.stdout.strip()
        # `docker info --format` can exit 0 with empty output when the daemon is unreachable.
        if result.returncode != 0 or not version or "error" in result.stderr.lower():
            return False, f"Docker daemon unavailable: {result.stderr.strip()[:300] or 'no server version reported'}"
        return True, version

    def _docker(self, *args: str, timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run([self.docker, *args], capture_output=True, text=True, timeout=timeout,
                                    check=False)
        except subprocess.TimeoutExpired as exc:
            raise SandboxError(f"docker {args[0]} timed out") from exc
        if check and result.returncode != 0:
            raise SandboxError(f"docker {args[0]} failed: {result.stderr.strip()[:1000]}")
        return result

    def _limits(self) -> list[str]:
        s = self.settings
        return [
            f"--cpus={s.sandbox_cpus}",
            f"--memory={s.sandbox_memory}",
            f"--memory-swap={s.sandbox_memory}",
            f"--pids-limit={s.sandbox_pids_limit}",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--env=CI=true",
            "--env=HOME=/tmp",
            "--env=PIP_DISABLE_PIP_VERSION_CHECK=1",
            "--env=npm_config_update_notifier=false",
        ]

    def ensure_image(self, image: str) -> None:
        if self._docker("image", "inspect", image, check=False).returncode == 0:
            return
        logger.info("Pulling sandbox image", extra={"image": image})
        self._docker("pull", image, timeout=900)

    def _run_attached(self, args: list[str], name: str, timeout: int) -> CommandResult:
        started = time.monotonic()
        command = args[-1] if args else ""
        try:
            proc = subprocess.run([self.docker, *args], capture_output=True, text=True, timeout=timeout,
                                  check=False)
            limit = self.settings.sandbox_output_limit_chars
            return CommandResult(command, proc.returncode, _tail(proc.stdout, limit), _tail(proc.stderr, limit),
                                 int((time.monotonic() - started) * 1000))
        except subprocess.TimeoutExpired as exc:
            self._docker("kill", name, check=False, timeout=30)
            out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            err = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            limit = self.settings.sandbox_output_limit_chars
            return CommandResult(command, None, _tail(out, limit),
                                 _tail(err + f"\n[sandbox] command timed out after {timeout}s", limit),
                                 int((time.monotonic() - started) * 1000), timed_out=True)

    # -- public API ----------------------------------------------------------------

    def run(self, workspace: Path, *, image: str, workdir: str, setup_commands: list[str],
            commands: list[str]) -> SandboxRun:
        ok, reason = self.available()
        if not ok:
            raise SandboxError(f"Sandbox unavailable: {reason}. Generated code is never executed on the host.")
        self.ensure_image(image)
        run_id = uuid.uuid4().hex[:12]
        setup_name = f"devflow-setup-{run_id}"
        snapshot = f"devflow-sandbox:{run_id}"
        container_dir = "/workspace/" + workdir.strip("/") if workdir not in ("", ".") else "/workspace"
        result = SandboxRun()
        network = "bridge" if self.allow_network_for_install else "none"
        setup_script = " && ".join(["set -e", f"cd {shlex.quote(container_dir)}", *setup_commands]) or "true"
        try:
            self._docker("create", "--name", setup_name, f"--network={network}", *self._limits(),
                         image, "sh", "-c", setup_script)
            self._docker("cp", f"{workspace}/.", f"{setup_name}:/workspace", timeout=600)
            started = time.monotonic()
            try:
                proc = subprocess.run([self.docker, "start", "-a", setup_name], capture_output=True, text=True,
                                      timeout=self.settings.sandbox_setup_timeout_seconds, check=False)
                limit = self.settings.sandbox_output_limit_chars
                exit_code = int(self._docker("inspect", "--format", "{{.State.ExitCode}}", setup_name).stdout.strip())
                result.setup.append(CommandResult(" && ".join(setup_commands) or "(copy workspace)", exit_code,
                                                  _tail(proc.stdout, limit), _tail(proc.stderr, limit),
                                                  int((time.monotonic() - started) * 1000)))
            except subprocess.TimeoutExpired:
                self._docker("kill", setup_name, check=False)
                result.setup.append(CommandResult(" && ".join(setup_commands), None, "",
                                                  "[sandbox] dependency installation timed out",
                                                  int((time.monotonic() - started) * 1000), timed_out=True))
            if not result.setup_succeeded:
                if not self.allow_network_for_install and setup_commands:
                    result.setup[-1].stderr += (
                        "\n[sandbox] Network access is disabled during installation. Enable "
                        "'Allow network for dependency install' in Settings if dependencies must be downloaded."
                    )
                return result
            self._docker("commit", setup_name, snapshot, timeout=600)
            for command in commands:
                name = f"devflow-run-{run_id}-{uuid.uuid4().hex[:6]}"
                args = ["run", "--rm", "--name", name, "--network=none", *self._limits(),
                        "-w", container_dir, snapshot, "sh", "-c", command]
                result.commands.append(
                    self._run_attached(args, name, self.settings.sandbox_command_timeout_seconds)
                )
            return result
        finally:
            self._docker("rm", "-f", setup_name, check=False)
            self._docker("rmi", "-f", snapshot, check=False)
