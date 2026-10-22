"""Offline checks for verified scanner installation and fail-closed downloads."""

import hashlib
import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path
from unittest.mock import Mock
from urllib.error import URLError

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "security_installer", ROOT / "scripts/install_security_tools.py"
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def configure(monkeypatch, tmp_path, system, archive):
    root = tmp_path / "project"
    suffix, _, executable = installer.ARCHIVES[system]
    monkeypatch.setattr(installer, "ROOT", root)
    monkeypatch.setattr(installer.platform, "system", lambda: system)
    monkeypatch.setattr(installer.platform, "machine", lambda: "x86_64")
    monkeypatch.setitem(
        installer.ARCHIVES,
        system,
        (suffix, hashlib.sha256(archive).hexdigest(), executable),
    )
    download = Mock(return_value=io.BytesIO(archive))
    monkeypatch.setattr(installer.urllib.request, "urlopen", download)
    destination = root / ".uv/security-tools" / f"gitleaks-{installer.VERSION}" / executable
    return destination, download


def fake_archive(system, executable):
    buffer = io.BytesIO()
    entries = [(executable, b"synthetic scanner"), ("../../escape.txt", b"unwanted")]
    if system == "Windows":
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, content in entries:
                archive.writestr(name, content)
    else:
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for name, content in entries:
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
    return buffer.getvalue()


@pytest.mark.parametrize("system", ["Windows", "Linux"])
def test_checksum_mismatch_preserves_existing_binary_without_extraction(
    monkeypatch, tmp_path, system
):
    destination, _ = configure(monkeypatch, tmp_path, system, b"expected download")
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"existing scanner")
    monkeypatch.setattr(
        installer.urllib.request, "urlopen", Mock(return_value=io.BytesIO(b"altered"))
    )
    zip_reader = Mock()
    tar_reader = Mock()
    monkeypatch.setattr(installer.zipfile, "ZipFile", zip_reader)
    monkeypatch.setattr(installer.tarfile, "open", tar_reader)

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        installer.install()

    assert destination.read_bytes() == b"existing scanner"
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == [destination]
    zip_reader.assert_not_called()
    tar_reader.assert_not_called()


@pytest.mark.parametrize("system", ["Windows", "Linux"])
def test_verified_archive_installs_only_expected_executable(monkeypatch, tmp_path, system):
    executable = installer.ARCHIVES[system][2]
    archive = fake_archive(system, executable)
    destination, download = configure(monkeypatch, tmp_path, system, archive)

    assert installer.install() == destination
    assert destination.read_bytes() == b"synthetic scanner"
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == [destination]
    download.assert_called_once()


@pytest.mark.parametrize(
    ("system", "machine", "failure"),
    [("Darwin", "x86_64", KeyError), ("Windows", "arm64", RuntimeError)],
)
def test_unsupported_platform_fails_before_download_or_write(
    monkeypatch, tmp_path, system, machine, failure
):
    _, download = configure(monkeypatch, tmp_path, "Windows", b"unused")
    monkeypatch.setattr(installer.platform, "system", lambda: system)
    monkeypatch.setattr(installer.platform, "machine", lambda: machine)

    with pytest.raises(failure):
        installer.install()

    download.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_download_failure_does_not_write_files(monkeypatch, tmp_path):
    _, download = configure(monkeypatch, tmp_path, "Windows", b"unused")
    download.side_effect = URLError("synthetic download failure")

    with pytest.raises(URLError):
        installer.install()

    assert list(tmp_path.iterdir()) == []


def test_tar_executable_must_be_regular_file(monkeypatch, tmp_path):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        member = tarfile.TarInfo("gitleaks")
        member.type = tarfile.SYMTYPE
        member.linkname = "../../untrusted"
        archive.addfile(member)
    configure(monkeypatch, tmp_path, "Linux", buffer.getvalue())

    with pytest.raises(RuntimeError, match="Unexpected scanner archive entry"):
        installer.install()

    assert list(tmp_path.iterdir()) == []
