"""Real local child processes exercise pipe limits without GitHub or AWS access."""

import os
import subprocess
import sys
from time import monotonic

import pytest

from amplify_ops import github
from amplify_ops.github import GitHubReadFailure
from amplify_ops.github import run_command as bounded_command


def child(code, timeout=5):
    return bounded_command([sys.executable, "-c", code], timeout=timeout, env=os.environ.copy())


def test_capture_preserves_both_streams_and_exit_status():
    result = child("import sys; print('hello'); print('diagnostic', file=sys.stderr); sys.exit(7)")
    assert result.returncode == 7
    assert result.stdout.strip() == "hello"
    assert result.stderr.strip() == "diagnostic"


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_stream_overflow_is_stopped_with_safe_error(monkeypatch, stream):
    monkeypatch.setattr(github, "MAX_STDOUT", 1024)
    monkeypatch.setattr(github, "MAX_STDERR", 1024)
    with pytest.raises(GitHubReadFailure, match="^GitHubResponseLimit$"):
        child(f"import sys; sys.{stream}.buffer.write(b'private-marker' * 100000)")


def test_exact_byte_limits_pass_and_both_pipes_are_drained(monkeypatch):
    monkeypatch.setattr(github, "MAX_STDOUT", 131072)
    monkeypatch.setattr(github, "MAX_STDERR", 131072)
    result = child(
        "import sys; sys.stderr.buffer.write(b'e'*131072); sys.stderr.flush(); "
        "sys.stdout.buffer.write(b'o'*131072)"
    )
    assert result.stdout == "o" * 131072
    assert result.stderr == "e" * 131072


def test_timeout_kills_and_reaps_child(monkeypatch):
    processes = []
    original = subprocess.Popen

    def track(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(github.subprocess, "Popen", track)
    start = monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        child("import time; time.sleep(10)", timeout=0.5)
    assert monotonic() - start < 5
    assert processes[0].poll() is not None
