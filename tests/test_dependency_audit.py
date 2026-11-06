"""Advisory failures cannot turn into a green check; no advisory service calls."""

import importlib.util
import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "dependency_audit", Path(__file__).resolve().parents[1] / "scripts/dependency_audit.py"
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
PACKAGES = [("example-package", "1.0")]


@pytest.fixture
def project(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="fixture"\n')
    (tmp_path / "uv.lock").write_text("""version = 1
[[package]]
name = "fixture"
version = "0.1"
source = { editable = "." }
[[package]]
name = "example-package"
version = "1.0"
source = { registry = "https://pypi.org/simple" }
[[package]]
name = "other-package"
version = "2.0"
source = { registry = "https://pypi.org/simple" }
""")
    return tmp_path


def test_all_locked_versions_are_checked_including_dev_and_platform_variants(project):
    assert audit.locked_packages(project) == [*PACKAGES, ("other-package", "2.0")]
    with (project / "uv.lock").open("a") as handle:
        handle.write("""
[[package]]
name = "example-package"
version = "1.1"
source = { registry = "https://pypi.org/simple" }
""")
    assert ("example-package", "1.1") in audit.locked_packages(project)


def test_private_registry_blocks_network_without_printing_url(project, monkeypatch, capsys):
    lock = project / "uv.lock"
    lock.write_text(
        lock.read_text().replace("https://pypi.org/simple", "https://private.invalid/simple")
    )
    monkeypatch.setattr(audit, "ROOT", project)
    request = Mock(side_effect=AssertionError("network must not be reached"))
    monkeypatch.setattr(audit, "query", request)
    assert audit.main() == 2
    request.assert_not_called()
    assert "private.invalid" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {"results": []},
        {"results": [None]},
        {"results": [{"error": "private response"}]},
        {"results": [{"next_page_token": "another page"}]},
        {"results": [{"vulns": None}]},
        {"results": [{"vulns": [{}]}]},
        {"results": [{"vulns": [{"id": "unsafe\nprivate"}]}]},
    ],
)
def test_invalid_or_partial_results_never_pass(response):
    with pytest.raises(audit.AuditFailure):
        audit.findings(PACKAGES, response)


@pytest.mark.parametrize("vulns,expected", [([], 0), ([{"id": "GHSA-test-fixture"}], 1)])
def test_clean_and_vulnerable_exit_codes(monkeypatch, capsys, vulns, expected):
    monkeypatch.setattr(audit, "locked_packages", lambda root: PACKAGES)
    monkeypatch.setattr(audit, "query", lambda packages: {"results": [{"vulns": vulns}]})
    assert audit.main() == expected
    assert "Checked 1 locked PyPI versions" in capsys.readouterr().out


@pytest.mark.parametrize(
    "error", [urllib.error.URLError("private"), TimeoutError("private"), ValueError("private")]
)
def test_service_failures_exit_nonzero_without_raw_errors(monkeypatch, capsys, error):
    monkeypatch.setattr(audit, "locked_packages", lambda root: PACKAGES)
    monkeypatch.setattr(audit, "query", Mock(side_effect=error))
    assert audit.main() == 2
    assert "private" not in capsys.readouterr().out


def test_query_sends_only_name_version_and_bounds_response(monkeypatch):
    response = io.BytesIO(b'{"results":[{}]}')
    response.status = 200
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(audit.urllib.request, "build_opener", lambda handler: opener)
    assert audit.query(PACKAGES) == {"results": [{}]}
    request = opener.open.call_args.args[0]
    assert request.full_url == audit.ENDPOINT
    assert json.loads(request.data) == {
        "queries": [{"package": {"name": "example-package", "ecosystem": "PyPI"}, "version": "1.0"}]
    }
    assert opener.open.call_args.kwargs["timeout"] == 20


def test_redirect_and_oversized_response_are_rejected(monkeypatch):
    with pytest.raises(audit.AuditFailure, match="redirected"):
        audit.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid")
    response = io.BytesIO(b"x" * (audit.MAX_BYTES + 1))
    response.status = 200
    monkeypatch.setattr(
        audit.urllib.request, "build_opener", lambda handler: Mock(open=Mock(return_value=response))
    )
    with pytest.raises(audit.AuditFailure, match="limits"):
        audit.query(PACKAGES)


def test_invalid_lock_fails_without_query(project, monkeypatch):
    (project / "uv.lock").write_text("package = []")
    monkeypatch.setattr(audit, "ROOT", project)
    monkeypatch.setattr(audit, "query", Mock(side_effect=AssertionError("no request")))
    assert audit.main() == 2
