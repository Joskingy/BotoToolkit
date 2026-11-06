"""GitHub read evidence via the installed gh CLI and its existing authentication."""

import json
import os
import re
import subprocess
from dataclasses import dataclass
from threading import Event, Thread
from time import monotonic

MAX_STDOUT = 2 * 1024 * 1024
MAX_STDERR = 64 * 1024


class GitHubReadFailure(Exception):
    """A fixed error code only; do not expose gh stderr or credential diagnostics."""


def run_command(
    args: list[str], *, timeout: float, env: dict[str, str]
) -> subprocess.CompletedProcess:
    """Drain both pipes concurrently with fixed byte budgets and a shared deadline."""
    buffers = [bytearray(), bytearray()]
    exceeded, failed = Event(), Event()

    def read_pipe(pipe, buffer: bytearray, limit: int) -> None:
        try:
            with pipe:
                while chunk := pipe.read(min(65536, limit + 1 - len(buffer))):
                    if len(buffer) + len(chunk) > limit:
                        exceeded.set()
                        process.kill()
                        return
                    buffer.extend(chunk)
        except OSError:
            failed.set()

    deadline = monotonic() + timeout
    process = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, bufsize=0
    )
    readers = [
        Thread(target=read_pipe, args=(process.stdout, buffers[0], MAX_STDOUT), daemon=True),
        Thread(target=read_pipe, args=(process.stderr, buffers[1], MAX_STDERR), daemon=True),
    ]
    try:
        for reader in readers:
            reader.start()
        process.wait(timeout=max(0, deadline - monotonic()))
        for reader in readers:
            reader.join(timeout=max(0, deadline - monotonic()))
        if exceeded.is_set():
            raise GitHubReadFailure("GitHubResponseLimit")
        if any(reader.is_alive() for reader in readers):
            raise subprocess.TimeoutExpired(args, timeout)
        if failed.is_set():
            raise GitHubReadFailure("GitHubUnavailable")
        return subprocess.CompletedProcess(
            args,
            process.returncode,
            buffers[0].decode("utf-8", errors="replace"),
            buffers[1].decode("utf-8", errors="replace"),
        )
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        # Normal gh processes close both pipes on exit. Never wait indefinitely
        # for a descendant that inherited a pipe; daemon readers remain bounded.
        for reader in readers:
            reader.join(timeout=0.1)


@dataclass(frozen=True)
class RepositoryEvidence:
    branches: set[str]
    open_pr_heads: list[str]


def failure_code(stderr: str) -> str:
    """Classify diagnostics in memory; never return server text or credentials."""
    message = stderr.casefold()
    if "rate limit" in message or "http 429" in message:
        return "GitHubRateLimited"
    if "http 401" in message or "gh auth login" in message:
        return "GitHubAuthenticationRequired"
    if "http 403" in message:
        return "GitHubAccessDenied"
    if "http 404" in message:
        return "GitHubRepositoryUnavailable"
    return "GitHubReadDeniedOrUnavailable"


def request_environment() -> dict[str, str]:
    # Retain gh's normal credential resolution, but disable interactive/debug output.
    env = dict(os.environ)
    for name in ("GH_DEBUG", "DEBUG", "GH_FORCE_TTY", "GH_PAGER", "PAGER"):
        env.pop(name, None)
    env.update(GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1", NO_COLOR="1")
    return env


def read_pages(repository: str, resource: str, projection: str) -> list[dict]:
    rows = []
    for page in range(1, 21):
        try:
            result = run_command(
                [
                    "gh",
                    "api",
                    "--hostname",
                    "github.com",
                    "--method",
                    "GET",
                    f"/repos/{repository}/{resource}"
                    f"?per_page=100&page={page}" + ("&state=open" if resource == "pulls" else ""),
                    "--header",
                    "Accept: application/vnd.github+json",
                    "--header",
                    "X-GitHub-Api-Version: 2022-11-28",
                    "--jq",
                    projection,
                ],
                timeout=20,
                env=request_environment(),
            )
        except FileNotFoundError:
            raise GitHubReadFailure("GitHubCliMissing") from None
        except subprocess.TimeoutExpired:
            raise GitHubReadFailure("GitHubTimeout") from None
        except OSError:
            raise GitHubReadFailure("GitHubUnavailable") from None
        if result.returncode:
            raise GitHubReadFailure(failure_code(getattr(result, "stderr", "")))
        if len(result.stdout.encode("utf-8")) > MAX_STDOUT:
            raise GitHubReadFailure("GitHubResponseLimit")
        try:
            items = json.loads(result.stdout)
            if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
                raise ValueError
        except ValueError, TypeError:
            raise GitHubReadFailure("GitHubInvalidResponse") from None
        rows.extend(items)
        if len(items) < 100:
            return rows
    raise GitHubReadFailure("GitHubPageLimit")


def repository_evidence(repository: str) -> RepositoryEvidence:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]+", repository):
        raise GitHubReadFailure("GitHubInvalidRepository")
    if repository.split("/")[1] in {".", ".."}:
        raise GitHubReadFailure("GitHubInvalidRepository")
    branches = read_pages(repository, "branches", "[.[] | {name: .name}]")
    pulls = read_pages(
        repository, "pulls", "[.[] | {branch: .head.ref, repo: .head.repo.full_name}]"
    )
    try:
        if any(not isinstance(row.get("name"), str) or not row["name"] for row in branches):
            raise ValueError
        if len({row["name"] for row in branches}) != len(branches):
            # Duplicate pages can hide a branch during concurrent pagination changes.
            raise ValueError
        if any(
            not isinstance(row.get("branch"), str)
            or not row["branch"]
            or "repo" not in row
            or (row["repo"] is not None and not isinstance(row["repo"], str))
            for row in pulls
        ):
            raise ValueError
        return RepositoryEvidence(
            {row["name"] for row in branches},
            [
                row["branch"]
                for row in pulls
                if row["repo"] is not None and row["repo"].casefold() == repository.casefold()
            ],
        )
    except KeyError, TypeError, AttributeError, ValueError:
        raise GitHubReadFailure("GitHubInvalidResponse") from None
