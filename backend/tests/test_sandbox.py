"""Docker sandbox isolation tests (skipped when Docker is unavailable)."""

import pytest

from app.core.config import get_settings
from app.core.errors import SandboxError
from app.services.execution_service import DockerSandbox
from tests.conftest import docker_available


@pytest.fixture
def sandbox():
    if not docker_available():
        pytest.skip("Docker daemon not available")
    settings = get_settings().model_copy(update={"sandbox_command_timeout_seconds": 5, "sandbox_memory": "256m"})
    return DockerSandbox(settings)


@pytest.mark.docker
def test_runs_commands_and_captures_output(sandbox, tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "hello.py").write_text("print('hello from sandbox')\n")
    run = sandbox.run(tmp_path, image=sandbox.settings.sandbox_python_image, workdir="pkg", setup_commands=[],
                      commands=["python hello.py", "python -c 'import sys; sys.exit(3)'", "pwd"])
    assert run.setup_succeeded
    out = [(c.exit_code, c.stdout.strip()) for c in run.commands]
    assert out == [(0, "hello from sandbox"), (3, ""), (0, "/workspace/pkg")]


@pytest.mark.docker
def test_isolation_network_host_files_and_socket(sandbox, tmp_path):
    (tmp_path / "f.txt").write_text("x")
    checks = [
        "python -c \"import socket; socket.create_connection(('1.1.1.1', 53), 2)\"",  # no network
        "test ! -e /var/run/docker.sock",                                             # no docker socket
        f"test ! -e {tmp_path}",                                                      # host path not mounted
        "cat /proc/self/status | grep -q 'CapEff:\\s*0000000000000000'",               # no capabilities
    ]
    run = sandbox.run(tmp_path, image=sandbox.settings.sandbox_python_image, workdir=".", setup_commands=[],
                      commands=checks)
    assert run.commands[0].exit_code != 0
    assert [c.exit_code for c in run.commands[1:]] == [0, 0, 0]


@pytest.mark.docker
def test_generated_code_cannot_modify_host_workspace(sandbox, tmp_path):
    (tmp_path / "data.txt").write_text("original")
    sandbox.run(tmp_path, image=sandbox.settings.sandbox_python_image, workdir=".", setup_commands=[],
                commands=["echo hacked > data.txt"])
    assert (tmp_path / "data.txt").read_text() == "original"


@pytest.mark.docker
def test_timeout_kills_command(sandbox, tmp_path):
    run = sandbox.run(tmp_path, image=sandbox.settings.sandbox_python_image, workdir=".", setup_commands=[],
                      commands=["sleep 30"])
    assert run.commands[0].timed_out and run.commands[0].exit_code is None


@pytest.mark.docker
def test_install_without_network_fails_with_hint(sandbox, tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.32.3\n")
    run = sandbox.run(tmp_path, image=sandbox.settings.sandbox_python_image, workdir=".",
                      setup_commands=["pip install --retries 0 --timeout 3 -r requirements.txt"], commands=["true"])
    assert not run.setup_succeeded and run.commands == []
    assert "Network access is disabled" in run.setup[0].stderr


def test_unavailable_docker_never_falls_back_to_host(tmp_path):
    sandbox = DockerSandbox(get_settings(), docker_bin="definitely-not-docker")
    with pytest.raises(SandboxError, match="never executed on the host"):
        sandbox.run(tmp_path, image="x", workdir=".", setup_commands=[], commands=["true"])


def test_unreachable_daemon_is_reported_unavailable(tmp_path, monkeypatch):
    """`docker info --format` may exit 0 with empty output when the socket is missing."""
    fake = tmp_path / "docker"
    fake.write_text("#!/bin/sh\necho 'Cannot connect to the Docker daemon' >&2\nexit 0\n")
    fake.chmod(0o755)
    sandbox = DockerSandbox(get_settings(), docker_bin=str(fake))
    ok, reason = sandbox.available()
    assert not ok and "unavailable" in reason
