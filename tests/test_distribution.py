"""Packaging regressions fail CI before an incomplete or private archive is installed."""

import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "check_distribution", Path(__file__).resolve().parents[1] / "scripts/check_distribution.py"
)
distribution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(distribution)


def archive(tmp_path, kind, entries):
    target = tmp_path / f"package.{kind}"
    if kind == "whl":
        with zipfile.ZipFile(target, "w") as output:
            for entry in entries:
                output.writestr(entry, "# synthetic package fixture\n")
    else:
        with tarfile.open(target, "w:gz") as output:
            for entry in entries:
                data = b"# synthetic package fixture\n"
                info = tarfile.TarInfo(entry)
                info.size = len(data)
                output.addfile(info, io.BytesIO(data))
    return target


@pytest.mark.parametrize("kind", ["whl", "tar.gz"])
def test_distributions_keep_both_namespaces(tmp_path, kind):
    target = archive(tmp_path, kind, ["src/amplify_ops/__init__.py", "src/bototoolkit/__init__.py"])
    distribution.inspect_archive(target)


@pytest.mark.parametrize("kind", ["whl", "tar.gz"])
def test_missing_compatibility_package_blocks_distribution(tmp_path, kind):
    target = archive(tmp_path, kind, ["src/amplify_ops/__init__.py"])
    with pytest.raises(ValueError, match="missing the bototoolkit package"):
        distribution.inspect_archive(target)


@pytest.mark.parametrize("kind", ["whl", "tar.gz"])
@pytest.mark.parametrize("private_path", [".aws/credentials", "src/.env", "../outside.py"])
def test_private_or_escaping_paths_block_distribution(tmp_path, kind, private_path):
    target = archive(
        tmp_path,
        kind,
        ["src/amplify_ops/__init__.py", "src/bototoolkit/__init__.py", private_path],
    )
    with pytest.raises(ValueError, match="unexpected private or generated path"):
        distribution.inspect_archive(target)
