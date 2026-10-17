"""Bounded, opt-in log inspection. Export fixed signatures, never source text."""

import re
from http.client import HTTPException, HTTPSConnection
from time import monotonic
from urllib.parse import urlsplit

from amplify_ops.models import LogEvidence, LogReview

MAX_LOG_BYTES = 256 * 1024
MAX_LOGS = 4
MAX_FINDINGS = 20
SOCKET_TIMEOUT = 5
DOWNLOAD_SECONDS = 15

# Only AWS S3/CloudFront HTTPS endpoints returned by GetJob are eligible.
# No IP literals, userinfo, custom ports, alternate protocols, or redirects.
LOG_HOST = re.compile(
    r"(?:[a-z0-9][a-z0-9.-]*\.)?s3(?:[.-][a-z0-9-]+)*\.amazonaws\.com(?:\.cn)?"
    r"|[a-z0-9]+\.cloudfront\.net"
)
SIGNATURES = (
    (r"\bERESOLVE\b", "dependency_conflict", "Check dependency versions and the lockfile."),
    (
        r"Module not found|Cannot find module|Could not resolve",
        "missing_module",
        "Check module paths, case sensitivity, and installed dependencies.",
    ),
    (r"\bTS[0-9]{4}\b", "typescript_error", "Run the TypeScript check locally."),
    (
        r"heap out of memory|Reached heap limit",
        "memory_limit",
        "Inspect build memory usage and Node runtime settings.",
    ),
    (r"command not found", "missing_command", "Check build commands and available tools."),
    (
        r"AccessDenied|not authorized to perform",
        "access_denied",
        "Review the build role's permissions for the failed operation.",
    ),
    (
        r"YAMLException|Invalid build specification",
        "build_configuration",
        "Validate the Amplify build specification.",
    ),
    (
        r"ELIFECYCLE|Command failed with exit code|exited with code [1-9]",
        "command_failure",
        "Reproduce the build command locally and inspect earlier failures.",
    ),
)
COMPILED_SIGNATURES = tuple((re.compile(p, re.I), c, s) for p, c, s in SIGNATURES)


class LogReadFailure(Exception):
    """Contains a fixed safe code only; never retain a URL or response body."""


def log_target(url: str) -> tuple[str, str]:
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if (
            parts.scheme != "https"
            or parts.username is not None
            or parts.password is not None
            or parts.port not in (None, 443)
            or parts.fragment
            or not LOG_HOST.fullmatch(host)
            or any(ord(char) < 33 or ord(char) > 126 for char in url)
        ):
            raise LogReadFailure("UnsupportedLogURL")
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        return host, target
    except ValueError:
        raise LogReadFailure("UnsupportedLogURL") from None


def download_log(url: str) -> tuple[bytes, bool]:
    host, target = log_target(url)
    connection = HTTPSConnection(host, timeout=SOCKET_TIMEOUT)
    try:
        deadline = monotonic() + DOWNLOAD_SECONDS
        connection.request("GET", target, headers={"Accept-Encoding": "identity"})
        with connection.getresponse() as response:
            if response.status != 200:
                # HTTP status numbers are safe; reasons, headers, and bodies are not.
                raise LogReadFailure(f"LogHTTP{response.status}")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise LogReadFailure("UnsupportedLogEncoding")
            content = bytearray()
            while len(content) <= MAX_LOG_BYTES:
                if monotonic() >= deadline:
                    raise LogReadFailure("LogTimeLimit")
                chunk = response.read1(min(16384, MAX_LOG_BYTES + 1 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
            return bytes(content[:MAX_LOG_BYTES]), len(content) > MAX_LOG_BYTES
    except OSError, HTTPException:
        raise LogReadFailure("LogConnectionFailure") from None
    finally:
        connection.close()


def inspect_log(url: str) -> LogReview:
    content, truncated = download_log(url)
    review = LogReview(state="inspected", bytes_read=len(content), truncated=truncated)
    # Strip terminal escapes for recognition only. No captured source text is exported.
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", content.decode("utf-8", errors="replace"))
    for number, line in enumerate(text.splitlines(), 1):
        review.lines_scanned = number
        for pattern, category, suggestion in COMPILED_SIGNATURES:
            if pattern.search(line):
                if len(review.findings) == MAX_FINDINGS:
                    review.truncated = True
                    return review
                review.findings.append(LogEvidence(number, category, suggestion))
    return review
