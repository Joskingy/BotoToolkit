"""Bounded local diagnostics without creating AWS sessions or resolving credentials."""

import configparser
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from importlib import metadata
from pathlib import Path

from amplify_ops.models import DoctorCheck

MAX_CONFIG_BYTES = 256 * 1024
UV_TIMEOUT_SECONDS = 30
DISTRIBUTIONS = ("amplify-ops", "boto3", "typer", "rich")


def collect_checks(
    profile: str | None,
    expected_account: str | None,
    regions: list[str],
    project: Path | None = None,
) -> list[DoctorCheck]:
    """Check local prerequisites; AWS identity and permissions remain unverified."""
    checks = [_check_python()]
    checks.extend(_check_distribution(name) for name in DISTRIBUTIONS)
    checks.append(_check_profile(profile))
    checks.extend(_check_selections(expected_account, regions))
    checks.extend(_check_project(project))
    return checks


def _check_python() -> DoctorCheck:
    if sys.version_info < (3, 15):  # noqa: UP036 - diagnose unsupported interpreters
        return DoctorCheck(
            "python",
            "fail",
            "The running interpreter is older than Python 3.15.",
            "Install Python 3.15 or newer and recreate the toolkit environment.",
        )
    return DoctorCheck("python", "pass", "The running interpreter meets Python 3.15+.", "")


def _check_distribution(name: str) -> DoctorCheck:
    check_name = "package_" + name.replace("-", "_")
    try:
        version = metadata.version(name)
        if not isinstance(version, str) or not version.strip():
            raise ValueError("Unavailable version metadata")
    except metadata.PackageNotFoundError, OSError, ValueError, KeyError, TypeError:
        return DoctorCheck(
            check_name,
            "fail",
            "Required package metadata is missing or unreadable.",
            "Reinstall the toolkit, or run uv sync --locked in a source clone.",
        )
    return DoctorCheck(
        check_name,
        "pass",
        "Required package metadata is available; compatibility is not inferred.",
        "",
    )


def _read_sections(path: Path, explicit: bool) -> list[str]:
    """Read only section names, never evaluate profile options or credential providers."""
    try:
        details = path.stat()
    except FileNotFoundError:
        if explicit:
            raise
        return []
    if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_CONFIG_BYTES:
        raise ValueError("Unsupported configuration file")
    with path.open("rb") as handle:
        contents = handle.read(MAX_CONFIG_BYTES + 1)
    if len(contents) > MAX_CONFIG_BYTES:
        raise ValueError("Configuration is too large")
    parser = configparser.RawConfigParser()
    parser.read_string(contents.decode("utf-8"))
    return parser.sections()


def _config_path(variable: str, filename: str) -> tuple[Path, bool]:
    if variable in os.environ:
        value = os.environ[variable]
        if not value:
            raise ValueError("Empty configuration path")
        return Path(os.path.expandvars(os.path.expanduser(value))), True
    return Path.home() / ".aws" / filename, False


def _config_profile_present(sections: list[str], profile: str) -> bool:
    for section in sections:
        if section == "default" and profile == "default":
            return True
        if section.startswith("profile "):
            parts = shlex.split(section)
            if len(parts) == 2 and parts[0] == "profile" and parts[1] == profile:
                return True
    return False


def _check_profile(profile: str | None) -> DoctorCheck:
    if not profile:
        return DoctorCheck(
            "aws_profile",
            "warn",
            "No explicit AWS profile was selected.",
            "Supply the intended local profile with --profile before the doctor command.",
        )
    try:
        config_path, config_explicit = _config_path("AWS_CONFIG_FILE", "config")
        credentials_path, credentials_explicit = _config_path(
            "AWS_SHARED_CREDENTIALS_FILE", "credentials"
        )
        config_sections = _read_sections(config_path, config_explicit)
        credential_sections = _read_sections(credentials_path, credentials_explicit)
        present = (
            _config_profile_present(config_sections, profile) or profile in credential_sections
        )
    except OSError, ValueError, UnicodeError, configparser.Error, RuntimeError:
        return DoctorCheck(
            "aws_profile",
            "fail",
            "Local AWS configuration could not be safely read.",
            "Check local AWS configuration paths, permissions, INI syntax, and file size.",
        )
    if not present:
        return DoctorCheck(
            "aws_profile",
            "fail",
            "The selected AWS profile is absent from local configuration.",
            "Configure the selected local profile, then rerun doctor with --profile.",
        )
    return DoctorCheck(
        "aws_profile",
        "pass",
        "The selected local profile exists; credentials were not resolved.",
        "",
    )


def _check_selections(account: str | None, regions: list[str]) -> list[DoctorCheck]:
    checks = []
    if not account:
        checks.append(
            DoctorCheck(
                "expected_account",
                "warn",
                "No expected AWS account was selected.",
                "Before doctor --online, supply an independently confirmed --expected-account.",
            )
        )
    elif not re.fullmatch(r"[0-9]{12}", account):
        checks.append(
            DoctorCheck(
                "expected_account",
                "fail",
                "The expected account format is invalid.",
                "Supply an independently confirmed 12-digit account with --expected-account.",
            )
        )
    else:
        checks.append(
            DoctorCheck(
                "expected_account",
                "pass",
                "An expected account is selected; identity is unverified.",
                "",
            )
        )
    if not regions:
        checks.append(
            DoctorCheck(
                "regions",
                "warn",
                "No AWS region was selected.",
                "Supply an explicit --region before doctor --online.",
            )
        )
    elif any(not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-[0-9]+", region) for region in regions):
        checks.append(
            DoctorCheck(
                "regions",
                "fail",
                "A selected region has an invalid format.",
                "Supply resolved AWS region names using --region.",
            )
        )
    else:
        checks.append(
            DoctorCheck(
                "regions",
                "pass",
                "Explicit regions are selected; service availability is unverified.",
                "",
            )
        )
    return checks


def _skip_project_checks(message: str, next_step: str) -> list[DoctorCheck]:
    return [
        DoctorCheck(name, "skip", message, next_step) for name in ("uv", "uv_lock", "dependencies")
    ]


def _check_project(project: Path | None) -> list[DoctorCheck]:
    if project is None:
        hint = "For a source clone, rerun doctor --project with the repository directory."
        return [
            DoctorCheck("project_files", "skip", "No repository check was requested.", hint),
            *_skip_project_checks("No repository check was requested.", hint),
        ]
    try:
        valid = project.is_dir() and all(
            (project / filename).is_file() for filename in ("pyproject.toml", "uv.lock")
        )
    except OSError, ValueError:
        valid = False
    if not valid:
        return [
            DoctorCheck(
                "project_files",
                "fail",
                "The repository directory or required project files are unavailable.",
                "Use --project with a readable source clone containing pyproject.toml and uv.lock.",
            ),
            *_skip_project_checks(
                "Required repository files are unavailable.", "Fix project_files first."
            ),
        ]
    checks = [DoctorCheck("project_files", "pass", "Required repository files are present.", "")]
    executable = shutil.which("uv")
    if executable is None:
        checks.append(
            DoctorCheck(
                "uv",
                "fail",
                "The uv executable is unavailable.",
                "Install uv and make it available on PATH.",
            )
        )
        checks.extend(
            DoctorCheck(name, "skip", "uv is unavailable.", "Fix uv first.")
            for name in ("uv_lock", "dependencies")
        )
        return checks
    checks.append(DoctorCheck("uv", "pass", "The uv executable is available.", ""))
    shared = ["--offline", "--no-python-downloads", "--no-cache", "--no-progress"]
    checks.append(
        _run_uv(
            "uv_lock",
            [
                executable,
                "lock",
                "--check",
                "--no-build",
                "--keyring-provider",
                "disabled",
                "--python",
                sys.executable,
                *shared,
            ],
            project,
            "The repository lockfile is current under offline validation.",
            "Review lockfile consistency and offline availability; refresh the lockfile if needed.",
        )
    )
    checks.append(
        _run_uv(
            "dependencies",
            [executable, "pip", "check", "--python", sys.executable, "--no-config", *shared],
            project,
            "Installed dependencies are consistent for the running interpreter.",
            "Run uv pip check with the toolkit interpreter locally, then repair its environment.",
        )
    )
    return checks


def _run_uv(name: str, command: list[str], project: Path, success: str, hint: str) -> DoctorCheck:
    # Inherited uv flags must not weaken validation (for example UV_FROZEN or UV_PYTHON).
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("UV_") and key.upper() not in {"VIRTUAL_ENV"}
    }
    try:
        result = subprocess.run(
            command,
            cwd=project,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=UV_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return DoctorCheck(name, "fail", "Offline validation exceeded its time limit.", hint)
    except OSError, ValueError, subprocess.SubprocessError:
        return DoctorCheck(name, "fail", "Offline validation could not run.", hint)
    if result.returncode != 0:
        return DoctorCheck(name, "fail", "Offline validation did not pass.", hint)
    return DoctorCheck(name, "pass", success, "")
