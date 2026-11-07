"""Developer-local settings cannot change test behavior or activate AWS providers."""

import os
import socket
import subprocess
import sys
from pathlib import Path

import boto3
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_default_sdk_session_has_no_external_credentials():
    assert boto3.session.Session().get_credentials() is None


@pytest.mark.parametrize("method", ["connect", "connect_ex"])
def test_raw_socket_connections_are_blocked(method):
    with socket.socket() as connection:
        with pytest.raises(pytest.fail.Exception, match="Tests must not make network calls"):
            getattr(connection, method)(("127.0.0.1", 9))


def test_disposable_git_commits_ignore_external_signing(tmp_path):
    root = tmp_path / "git-fixture"
    root.mkdir()
    for args in (
        ["init", "--quiet"],
        ["config", "user.name", "Synthetic Test"],
        ["config", "user.email", "test@example.invalid"],
        ["commit", "--quiet", "--allow-empty", "-m", "Synthetic fixture"],
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, timeout=30)


@pytest.mark.parametrize(
    "credential_mode", ["environment", "missing_profile", "credential_process"]
)
def test_host_configuration_cannot_break_stubs_or_activate_providers(tmp_path, credential_mode):
    marker = tmp_path / "credential-process-ran"
    provider = tmp_path / "provider.py"
    provider.write_text(
        "from pathlib import Path\n" + f"Path({str(marker)!r}).write_text('unexpected')\n",
        encoding="utf-8",
    )
    config = tmp_path / "host-config"
    config.write_text(
        f'[default]\ncredential_process = "{sys.executable}" "{provider}"\n',
        encoding="utf-8",
    )
    credentials = tmp_path / "host-credentials"
    credentials.write_text(
        "[default]\naws_access_key_id = inherited-fake-key\n"
        "aws_secret_access_key = inherited-fake-secret\n",
        encoding="utf-8",
    )
    gitconfig = tmp_path / "host-gitconfig"
    gitconfig.write_text(
        "[commit]\ngpgsign = true\n[gpg]\nprogram = synthetic-missing-signing-program\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        AWS_CONFIG_FILE=str(config),
        AWS_SHARED_CREDENTIALS_FILE=str(credentials),
        AWS_ACCESS_KEY_ID="inherited-fake-key",
        AWS_SECRET_ACCESS_KEY="inherited-fake-secret",
        AWS_CONTAINER_CREDENTIALS_FULL_URI="http://127.0.0.1:9/credentials",
        AWS_EC2_METADATA_DISABLED="false",
        GIT_CONFIG_GLOBAL=str(gitconfig),
        GIT_CONFIG_COUNT="1",
        GIT_CONFIG_KEY_0="commit.gpgsign",
        GIT_CONFIG_VALUE_0="true",
    )
    if credential_mode == "missing_profile":
        environment["AWS_PROFILE"] = "synthetic-absent-profile"
        environment["AWS_DEFAULT_PROFILE"] = "synthetic-absent-profile"
    elif credential_mode == "credential_process":
        credentials.write_text("", encoding="utf-8")
        for name in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_CONTAINER_CREDENTIALS_FULL_URI",
        ):
            environment.pop(name)
    probes = [
        "tests/test_inventory.py::test_wrong_account_blocks_amplify_clients",
        "tests/test_inventory.py::test_sts_failure_blocks_inventory_without_leaking_service_message",
        "tests/test_test_isolation.py::test_default_sdk_session_has_no_external_credentials",
        "tests/test_test_isolation.py::test_disposable_git_commits_ignore_external_signing",
    ]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            *probes,
            "--basetemp",
            str(tmp_path / "nested-pytest"),
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "4 passed" in result.stdout
    assert not marker.exists(), "The developer's credential_process must never run"
