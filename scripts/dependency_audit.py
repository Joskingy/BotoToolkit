"""Check every public PyPI version in uv.lock against OSV without installing packages."""

import json
import re
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 2 * 1024 * 1024
MAX_PACKAGES = 500
ENDPOINT = "https://api.osv.dev/v1/querybatch"


class AuditFailure(Exception):
    """Fixed diagnostic; never print source URLs or raw service responses."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AuditFailure("Advisory service redirected; audit incomplete.")


def locked_packages(root: Path) -> list[tuple[str, str]]:
    data = (root / "uv.lock").read_bytes()
    if len(data) > MAX_BYTES:
        raise AuditFailure("Lockfile exceeds audit limits.")
    lock = tomllib.loads(data.decode("utf-8"))
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    rows = lock.get("package")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_PACKAGES:
        raise AuditFailure("Invalid or oversized dependency inventory.")
    packages = set()
    local = 0
    for row in rows:
        if not isinstance(row, dict):
            raise AuditFailure("Invalid locked package.")
        name, version, source = row.get("name"), row.get("version"), row.get("source")
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", name)
            or not isinstance(version, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+!_-]{0,127}", version)
        ):
            raise AuditFailure("Invalid locked package identity.")
        if source == {"editable": "."} and name == project["name"]:
            local += 1
        elif source in (
            {"registry": "https://pypi.org/simple"},
            {"registry": "https://pypi.org/simple/"},
        ):
            packages.add((name, version))
        else:
            raise AuditFailure(
                "Non-public or unsupported dependency source; manual review required."
            )
    if local != 1 or not packages:
        raise AuditFailure("Incomplete dependency inventory.")
    return sorted(packages)


def query(packages: list[tuple[str, str]]) -> dict:
    payload = {
        "queries": [
            {"package": {"name": name, "ecosystem": "PyPI"}, "version": version}
            for name, version in packages
        ]
    }
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(request, timeout=20) as response:
        if response.status != 200:
            raise AuditFailure("Advisory service unavailable; audit incomplete.")
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise AuditFailure("Advisory response exceeds audit limits.")
    return json.loads(data)


def findings(packages: list[tuple[str, str]], response: dict) -> list[str]:
    if not isinstance(response, dict):
        raise AuditFailure("Invalid advisory response; audit incomplete.")
    results = response.get("results")
    if not isinstance(results, list) or len(results) != len(packages):
        raise AuditFailure("Missing advisory results; audit incomplete.")
    output = []
    for (name, version), result in zip(packages, results, strict=True):
        if (
            not isinstance(result, dict)
            or set(result) - {"vulns", "next_page_token"}
            or result.get("next_page_token")
        ):
            raise AuditFailure("Invalid or paginated advisory results; audit incomplete.")
        vulnerabilities = result.get("vulns", [])
        if not isinstance(vulnerabilities, list):
            raise AuditFailure("Invalid vulnerability list; audit incomplete.")
        for vulnerability in vulnerabilities:
            identifier = vulnerability.get("id") if isinstance(vulnerability, dict) else None
            if not isinstance(identifier, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}", identifier
            ):
                raise AuditFailure("Invalid vulnerability identifier; audit incomplete.")
            output.append(f"{name}=={version}: {identifier}")
    return sorted(set(output))


def main() -> int:
    try:
        packages = locked_packages(ROOT)
        matches = findings(packages, query(packages))
    except AuditFailure as error:
        print(str(error))
        return 2
    except (OSError, ValueError, KeyError, TypeError, RecursionError, urllib.error.URLError):
        print("Dependency audit unavailable or invalid; check did not pass.")
        return 2
    for match in matches:
        print(match)
    print(f"Checked {len(packages)} locked PyPI versions; {len(matches)} advisory matches.")
    return 1 if matches else 0


if __name__ == "__main__":
    sys.exit(main())
