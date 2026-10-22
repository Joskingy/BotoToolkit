"""Scan publishable files/index and optionally all reachable Git history.

Uses only Python's standard library so the workflow needs no application credentials
or dependencies. Reports contain locations/rule IDs only, never matching content.
"""

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
VERSION = "8.24.3"
MAX_FILE_BYTES = 10 * 1024 * 1024


class ScanFailure(Exception):
    """Safe operational diagnostic; raw subprocess output must never escape."""


def command(args, cwd, *, accepted=(0,)):
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ScanFailure("Required tool missing, unavailable, or timed out.") from None
    if result.returncode not in accepted:
        raise ScanFailure("Tool failed; scan is incomplete and publication is blocked.")
    return result


def git(root, *args):
    return command(["git", *args], root).stdout


def forbidden_path(name):
    path = PurePosixPath(name)
    return (
        any(part in {".aws", ".amplify-ops", "reports", "private", ".local"} for part in path.parts)
        or path.name in {"credentials", ".env"}
        or path.name.startswith(".env.")
        or path.suffix.lower() in {".pem", ".key", ".json", ".jsonl", ".log"}
    )


def repository_path(raw_name):
    name = raw_name.decode("utf-8", errors="strict")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
        raise ScanFailure("Unsupported repository path; scan blocked.")
    return name


def check_private_path(name):
    if forbidden_path(name):
        raise ScanFailure(f"Private artifact cannot be published: {json.dumps(name)}")


def snapshot(root, target, staged=False):
    if staged:
        entries = git(root, "ls-files", "--stage", "-z").split(b"\0")
        files = []
        for entry in filter(None, entries):
            metadata, raw_name = entry.split(b"\t", 1)
            mode, oid, stage = metadata.decode("ascii").split()
            if mode not in {"100644", "100755"} or stage != "0":
                raise ScanFailure("Resolve conflicts, symlinks, or submodules before scanning.")
            files.append((raw_name, oid))
    else:
        files = [
            (name, None)
            for name in set(
                git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split(
                    b"\0"
                )
            )
            if name
        ]
    for raw_name, oid in files:
        name = repository_path(raw_name)
        source = root / name
        if oid is None and not source.exists() and not source.is_symlink():
            continue  # A tracked deletion in the working tree.
        check_private_path(name)
        if oid is None:
            if (
                source.is_symlink()
                or not source.is_file()
                or not source.resolve().is_relative_to(root)
            ):
                raise ScanFailure("Symlinks/submodules need a separate review; scan blocked.")
            size = source.stat().st_size
        else:
            size = int(git(root, "cat-file", "-s", oid))
        if size > MAX_FILE_BYTES:
            raise ScanFailure("Oversized file needs a separate review; scan blocked.")
        data = git(root, "cat-file", "blob", oid) if oid else source.read_bytes()
        output = target / name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)


def history_artifacts(root):
    """Apply publication policy to every reachable tree, including deleted artifacts."""
    trees = set(git(root, "log", "--format=%T", "--all", "HEAD").splitlines())
    for raw_tree in trees:
        tree = raw_tree.decode("ascii")
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", tree):
            raise ScanFailure("Invalid history tree; scan blocked.")
        entries = git(root, "ls-tree", "-r", "-z", "--full-tree", "-l", tree).split(b"\0")
        for entry in filter(None, entries):
            metadata, raw_name = entry.split(b"\t", 1)
            mode, kind, _oid, size = metadata.decode("ascii").split()
            # Check each path, even if another path already used the same blob.
            check_private_path(repository_path(raw_name))
            if mode not in {"100644", "100755"} or kind != "blob":
                raise ScanFailure("History contains symlinks/submodules; publication blocked.")
            if int(size) > MAX_FILE_BYTES:
                raise ScanFailure("History contains an oversized file; publication blocked.")


def scan(executable, cwd, arguments, config, template):
    with tempfile.TemporaryDirectory(prefix="security-result-") as directory:
        report = Path(directory) / "locations.txt"
        empty_ignore = Path(directory) / ".gitleaksignore"
        empty_ignore.write_text("", encoding="utf-8")
        result = command(
            [
                str(executable),
                *arguments,
                "--config",
                str(config),
                "--redact=100",
                "--no-banner",
                "--no-color",
                "--ignore-gitleaks-allow",
                "--gitleaks-ignore-path",
                str(empty_ignore),
                "--max-decode-depth",
                "2",
                "--exit-code",
                "10",
                "--report-template",
                str(template),
                "--report-format",
                "template",
                "--report-path",
                str(report),
            ],
            cwd,
            accepted=(0, 10),
        )
        findings = []
        if report.exists():
            for line in report.read_text(encoding="utf-8").splitlines():
                if not line:
                    continue
                name, number, rule = line.rsplit("\t", 2)
                if not number.isdigit() or not re.fullmatch(r"[a-z0-9-]+", rule):
                    raise ScanFailure("Invalid scanner report; scan blocked.")
                findings.append((name, int(number), rule))
        if (result.returncode == 10) != bool(findings):
            raise ScanFailure("Scanner result is inconsistent; scan blocked.")
        return findings


def self_test(executable, config, template):
    # Synthetic canaries are assembled at runtime, never real credentials.
    with tempfile.TemporaryDirectory(prefix="security-canary-") as directory:
        target = Path(directory)
        target.joinpath("README.md").write_text(
            "token = "
            + "ghp_"
            + "AbCdEf0123456789" * 2
            + "ABcd\n"
            + "account = "
            + "555566"
            + "667777\n"
            + "app = d"
            + "a1b2c3d4e5f6\n"
            + "--api-id "
            + "a1b2c3d4e5f6"
            + "g7h8i9j0k1l2m3\n",
            encoding="utf-8",
        )
        findings = scan(executable, target, ["dir", "."], config, template)
        expected = {
            "github-pat",
            "private-aws-account",
            "private-amplify-id",
            "private-resource-argument",
            "private-appsync-id",
        }
        if not expected.issubset({finding[2] for finding in findings}):
            raise ScanFailure("Scanner canary failed; detection cannot be trusted.")


def run(root, executable, *, staged=False, history=False, require_history=False):
    config = ROOT / ".gitleaks.toml"
    template = ROOT / "scripts" / "security_report.tmpl"
    version = command([str(executable), "version"], root).stdout.decode().strip()
    if version != VERSION:
        raise ScanFailure("Install the pinned scanner with scripts/install_security_tools.py.")
    self_test(executable, config, template)
    with tempfile.TemporaryDirectory(prefix="security-snapshot-") as directory:
        target = Path(directory)
        snapshot(root, target, staged)
        findings = scan(executable, target, ["dir", "."], config, template)
    if history or require_history:
        head = command(["git", "rev-parse", "--verify", "HEAD"], root, accepted=(0, 128))
        if head.returncode:
            if require_history:
                raise ScanFailure("History required but no commit is available.")
            print("No commits yet; publishable files scanned. History will be checked before push.")
        else:
            if git(root, "rev-parse", "--is-shallow-repository").strip() != b"false":
                raise ScanFailure("Shallow checkout: fetch complete history before scanning.")
            history_artifacts(root)
            findings += scan(
                executable, root, ["git", "--log-opts=--all HEAD", "."], config, template
            )
    for name, line, rule in findings:
        print(f"{json.dumps(name)}:{line}: {rule}")
    if findings:
        print("Sensitive information detected. Remove it before committing or publishing.")
        return 1
    print("Sensitive-information checks passed (including scanner canaries).")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="Scan the complete Git index")
    parser.add_argument("--history", action="store_true", help="Also scan all reachable history")
    parser.add_argument(
        "--require-history", action="store_true", help="Scan history and fail if no commit exists"
    )
    args = parser.parse_args()
    executable = (
        ROOT
        / ".uv"
        / "security-tools"
        / f"gitleaks-{VERSION}"
        / ("gitleaks.exe" if os.name == "nt" else "gitleaks")
    )
    try:
        return run(
            ROOT,
            executable,
            staged=args.staged,
            history=args.history,
            require_history=args.require_history,
        )
    except (ScanFailure, OSError, ValueError):
        # ScanFailure messages are fixed or escaped paths; all other exceptions suppressed.
        import sys

        error = sys.exception()
        print(str(error) if isinstance(error, ScanFailure) else "Scan failed; publication blocked.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
