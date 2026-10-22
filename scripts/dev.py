"""Contributor worktrees, offline checks, and explicit GitHub pull requests."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

UV_VERSION = "0.13.4"
PYTHON_VERSION = "3.15.0"
ROOT = Path(__file__).resolve().parents[1]


class WorkflowError(Exception):
    """An actionable failure; never continue to publication after this error."""


class Workflow:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.env = os.environ.copy()
        for name in (
            "VIRTUAL_ENV",
            "PYTHONHOME",
            "PYTHONPATH",
            "GH_REPO",
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_COMMON_DIR",
        ):
            self.env.pop(name, None)
        self.env["GH_HOST"] = "github.com"
        self.env["UV_PROJECT_ENVIRONMENT"] = str(self.root / ".venv")
        self.env["UV_PYTHON"] = (
            sys.executable if sys.version_info[:3] == (3, 15, 0) else PYTHON_VERSION
        )
        self.uv = "uv"

    def run(self, *args: str, capture: bool = False) -> str:
        result = subprocess.run(
            args,
            cwd=self.root,
            env=self.env,
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            timeout=900,
        )
        return result.stdout.strip() if capture else ""

    def git(self, *args: str) -> str:
        return self.run("git", *args, capture=True)

    def primary(self) -> Path:
        entries = self.git("worktree", "list", "--porcelain", "-z").split("\0")
        return Path(
            next(
                entry.removeprefix("worktree ")
                for entry in entries
                if entry.startswith("worktree ")
            )
        ).resolve()

    def clean(self) -> None:
        if self.git("status", "--porcelain"):
            raise WorkflowError(
                "Commit or save your changes first; nothing was staged or discarded."
            )

    def branch(self) -> str:
        name = self.git("branch", "--show-current")
        if not name:
            raise WorkflowError("Detached HEAD: switch to a feature branch first.")
        return name

    def configure_uv(self) -> None:
        executable = "uv.exe" if os.name == "nt" else "uv"
        pinned = self.primary() / ".uv" / "ci-tools" / f"uv-{UV_VERSION}" / executable
        self.uv = str(pinned) if pinned.is_file() else (shutil.which("uv") or "uv")
        version = self.run(self.uv, "--version", capture=True).split()
        if len(version) < 2 or version[1] != UV_VERSION:
            raise WorkflowError(f"Use uv {UV_VERSION} to match CI, then retry.")
        # Git hooks and the package helper also invoke uv by name.
        self.env["PATH"] = (
            str(Path(self.uv).resolve().parent) + os.pathsep + self.env.get("PATH", "")
        )

    def setup(self) -> None:
        self.configure_uv()
        hooks = self.git("config", "--get-regexp", "^core\\.(hookspath|repositoryformatversion)$")
        hook_paths = [
            line.split(maxsplit=1)[1]
            for line in hooks.splitlines()
            if line.lower().startswith("core.hookspath ")
        ]
        if hook_paths and hook_paths != [".githooks"]:
            raise WorkflowError("Custom Git hooks detected; reconcile them with .githooks first.")
        if not (self.root / ".githooks" / "pre-commit").is_file():
            raise WorkflowError("Versioned security hooks are missing from this checkout.")
        if not hook_paths:
            default_hooks = self.root / self.git("rev-parse", "--git-path", "hooks")
            if any(
                path.is_file() and not path.name.endswith(".sample")
                for path in default_hooks.glob("*")
            ):
                raise WorkflowError(
                    "Custom Git hooks detected in the default directory; "
                    "reconcile them with .githooks first."
                )
            self.run("git", "config", "--local", "core.hooksPath", ".githooks")
        self.run(self.uv, "sync", "--locked")
        scanner = self.root / ".uv" / "security-tools" / "gitleaks-8.24.3"
        if not (scanner / ("gitleaks.exe" if os.name == "nt" else "gitleaks")).is_file():
            self.python("scripts/install_security_tools.py")
        self.python("scripts/security_check.py", "--history", "--require-history")

    def python(self, *args: str) -> None:
        self.run(self.uv, "run", "--locked", "python", *args)

    def check(self) -> None:
        print("Preparing this checkout and verifying its scanner...", flush=True)
        temporary_root = self.root / ".uv" / "check-temp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.env["TEMP"] = str(temporary_root)
        self.env["TMP"] = str(temporary_root)
        self.env["TMPDIR"] = str(temporary_root)
        self.setup()
        commands = [
            ("Lockfile", ("lock", "--check")),
            ("Tests", ("run", "--locked", "pytest", "-q", "--tb=short")),
            ("Lint", ("run", "--locked", "ruff", "check", ".")),
            ("Formatting", ("run", "--locked", "ruff", "format", "--check", ".")),
            (
                "Package installation",
                ("run", "--locked", "python", "scripts/check_distribution.py"),
            ),
        ]
        for label, args in commands:
            print(f"Checking {label.lower()}...", flush=True)
            self.run(self.uv, *args)
        self.run("git", "diff", "--check")
        print("All local checks passed. GitHub checks still apply.")

    def start(self, slug: str, prefix: str) -> Path:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) or len(slug) > 60:
            raise WorkflowError(
                "Use a short lowercase name such as improve-help (maximum 60 characters)."
            )
        if prefix not in {"feature", "codex"}:
            raise WorkflowError("Feature prefix must be feature or codex.")
        self.clean()
        primary = self.primary()
        target = primary.parent / f"{primary.name}-{prefix}-{slug}"
        branch = f"{prefix}/{slug}"
        if target.exists():
            raise WorkflowError("The worktree folder already exists; it was left untouched.")
        self.run("git", "fetch", "origin", "--prune")
        if self.git(
            "for-each-ref",
            "--format=%(refname)",
            f"refs/heads/{branch}",
            f"refs/remotes/origin/{branch}",
        ):
            raise WorkflowError("That branch already exists; choose another feature name.")
        try:
            self.run("git", "cat-file", "-e", "origin/dev:scripts/dev.py")
        except subprocess.CalledProcessError:
            raise WorkflowError(
                "Merge the developer helper into dev before creating worktrees with start."
            ) from None
        self.run("git", "worktree", "add", "--no-track", "-b", branch, str(target), "origin/dev")
        try:
            Workflow(target).setup()
        except (WorkflowError, OSError, subprocess.SubprocessError):
            print(
                f"Worktree preserved at {target}. Fix setup and run dev.ps1 setup there.",
                file=sys.stderr,
            )
            raise
        print(f"Ready: {target}\nOpen that folder in your editor, or use Set-Location '{target}'.")
        return target

    def repository(self) -> str:
        pattern = (
            r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
            r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?"
        )
        fetch = re.fullmatch(pattern, self.git("remote", "get-url", "--all", "origin"))
        push = re.fullmatch(pattern, self.git("remote", "get-url", "--push", "--all", "origin"))
        if not fetch or not push:
            raise WorkflowError(
                "PR commands require a standard github.com origin without embedded credentials."
            )
        if fetch[1].lower() != push[1].lower():
            raise WorkflowError(
                "Origin fetch and push destinations differ; reconcile them before publishing."
            )
        return fetch[1]

    def require_ancestor(self, base: str, head: str, message: str) -> None:
        try:
            self.run("git", "merge-base", "--is-ancestor", base, head)
        except subprocess.CalledProcessError as error:
            if error.returncode != 1:
                raise
            raise WorkflowError(message) from None

    def authenticate(self) -> None:
        try:
            self.run("gh", "auth", "status", "--hostname", "github.com")
        except subprocess.CalledProcessError:
            raise WorkflowError("Sign in with: gh auth login --hostname github.com --web") from None

    def open_pr(self, repo: str, head: str, base: str, title: str, body: str, draft: bool) -> str:
        existing = json.loads(
            self.run(
                "gh",
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "open",
                "--head",
                head,
                "--base",
                base,
                "--json",
                "url,isCrossRepository",
                capture=True,
            )
        )
        for pr in existing:
            if not pr["isCrossRepository"]:
                print(f"Existing PR: {pr['url']}")
                return pr["url"]
        with tempfile.TemporaryDirectory(prefix="toolkit-pr-") as directory:
            body_file = Path(directory) / "body.md"
            body_file.write_text(body, encoding="utf-8")
            args = [
                "gh",
                "pr",
                "create",
                "--repo",
                repo,
                "--base",
                base,
                "--head",
                head,
                "--title",
                title,
                "--body-file",
                str(body_file),
            ]
            if draft:
                args.append("--draft")
            url = self.run(*args, capture=True)
        print(url)
        return url

    def pr(self, title: str | None, body_file: Path | None, draft: bool) -> str:
        self.clean()
        branch = self.branch()
        if not branch.startswith(("feature/", "codex/")):
            raise WorkflowError(
                "Feature PRs must start on feature/* or codex/*; use promote for dev."
            )
        repo = self.repository()
        self.authenticate()
        self.run("git", "fetch", "origin", "--prune")
        head = self.git("rev-parse", "HEAD")
        self.require_ancestor(
            "origin/dev",
            "HEAD",
            "Dev has advanced. Merge origin/dev into your feature, resolve conflicts, "
            "and retry pr.",
        )
        if self.git("rev-list", "--count", "origin/dev..HEAD") == "0":
            raise WorkflowError("No feature commits ahead of dev. Commit your changes first.")
        body = (
            body_file.read_text(encoding="utf-8")
            if body_file
            else "See the commit diff for the change."
        )
        self.check()
        self.clean()
        if self.git("rev-parse", "HEAD") != head or self.branch() != branch:
            raise WorkflowError(
                "The branch changed during checks; run pr again on the intended commit."
            )
        self.run("git", "push", "--set-upstream", "origin", f"HEAD:refs/heads/{branch}")
        body += (
            "\n\nLocal verification: tests, lint, formatting, lockfile, package installation, "
            "and security/history checks passed.\n"
        )
        return self.open_pr(repo, branch, "dev", title or branch.replace("/", ": ", 1), body, draft)

    def promote(self, title: str | None, draft: bool) -> str:
        self.clean()
        repo = self.repository()
        self.authenticate()
        self.run("git", "fetch", "origin", "--prune")
        self.require_ancestor(
            "origin/main",
            "origin/dev",
            "Sync main back into dev through a feature PR before promoting again.",
        )
        if self.git("rev-list", "--count", "origin/main..origin/dev") == "0":
            raise WorkflowError("No dev commits to promote.")
        return self.open_pr(
            repo,
            "dev",
            "main",
            title or "Promote dev to main",
            "Promotes all committed changes on dev. Review the complete diff.\n\n"
            "Required GitHub checks must pass before merging. "
            "This command does not merge or deploy.\n",
            draft,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser(
        "start", help="Create and initialize a sibling feature worktree from origin/dev"
    )
    start.add_argument("name")
    start.add_argument("--prefix", choices=("feature", "codex"), default="feature")
    sub.add_parser("setup", help="Initialize or repair this checkout's environment and scanner")
    sub.add_parser("check", help="Run all local CI checks, stopping at the first failure")
    for command in ("pr", "promote"):
        pr = sub.add_parser(
            command, help="Check/push a feature PR" if command == "pr" else "Open dev -> main PR"
        )
        pr.add_argument("--title")
        pr.add_argument("--draft", action="store_true")
        if command == "pr":
            pr.add_argument("--body-file", type=Path)
    args = parser.parse_args(argv)
    try:
        workflow = Workflow(ROOT)
        if args.command == "start":
            workflow.start(args.name, args.prefix)
        elif args.command == "pr":
            workflow.pr(args.title, args.body_file, args.draft)
        elif args.command == "promote":
            workflow.promote(args.title, args.draft)
        else:
            getattr(workflow, args.command)()
    except WorkflowError as error:
        print(str(error), file=sys.stderr)
        return 1
    except subprocess.CalledProcessError:
        print(
            "A required command failed. Resolve the error above and retry; no later steps ran.",
            file=sys.stderr,
        )
        return 1
    except (OSError, subprocess.TimeoutExpired, ValueError):
        print(
            "A required tool, file, or response was unavailable. Check setup and retry.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
