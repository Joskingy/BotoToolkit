"""Build both package archives and verify installation away from the source checkout."""

import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PARTS = {
    ".aws",
    ".amplify-ops",
    ".local",
    ".uv",
    ".venv",
    "__pycache__",
    "private",
    "reports",
}


def run(*args: str, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True, timeout=180)


def inspect_archive(path: Path) -> None:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    else:
        with tarfile.open(path, "r:gz") as archive:
            names = archive.getnames()
    for name in names:
        entry = PurePosixPath(name.casefold())
        if (
            entry.is_absolute()
            or ".." in entry.parts
            or "\\" in name
            or PRIVATE_PARTS.intersection(entry.parts)
            or entry.name == "credentials"
            or entry.name.startswith(".env")
            or entry.suffix.lower() in {".pem", ".key", ".log", ".code-workspace"}
        ):
            raise ValueError("Distribution contains an unexpected private or generated path.")
    for package in ("amplify_ops", "bototoolkit"):
        if not any(name.endswith(f"{package}/__init__.py") for name in names):
            raise ValueError(f"Distribution is missing the {package} package.")


def smoke_install(wheel: Path, requirements: Path, target: Path, env: dict[str, str]) -> None:
    run("uv", "venv", "--python", sys.executable, str(target), cwd=target.parent, env=env)
    binaries = target / ("Scripts" if os.name == "nt" else "bin")
    python = binaries / ("python.exe" if os.name == "nt" else "python")
    run(
        "uv",
        "pip",
        "install",
        "--python",
        str(python),
        "--require-hashes",
        "-r",
        str(requirements),
        cwd=target.parent,
        env=env,
    )
    run(
        "uv",
        "pip",
        "install",
        "--python",
        str(python),
        "--no-deps",
        str(wheel),
        cwd=target.parent,
        env=env,
    )
    # -I excludes the current directory and inherited Python path configuration.
    run(
        str(python),
        "-I",
        "-c",
        "import pathlib, sys, amplify_ops, bototoolkit; "
        "root = pathlib.Path(sys.prefix).resolve(); "
        "assert all(pathlib.Path(m.__file__).resolve().is_relative_to(root) "
        "for m in (amplify_ops, bototoolkit))",
        cwd=target.parent,
        env=env,
    )
    suffix = ".exe" if os.name == "nt" else ""
    run(str(binaries / f"amplify-ops{suffix}"), "--help", cwd=target.parent, env=env)
    run(str(binaries / f"amplify-ops{suffix}"), "tui", "--help", cwd=target.parent, env=env)
    # Base installs must remain usable without the optional terminal framework.
    result = subprocess.run(
        [str(binaries / f"amplify-ops{suffix}"), "tui", "--demo"],
        cwd=target.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1 and "Install the TUI extra" in result.stderr
    assert not result.stdout
    # Exercise doctor outside any checkout, with no AWS options or repository tools.
    result = subprocess.run(
        [str(binaries / f"amplify-ops{suffix}"), "doctor", "--format", "json"],
        cwd=target.parent,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    report = json.loads(result.stdout)
    assert report["report_type"] == "doctor" and report["schema_version"] == 1
    assert report["complete"] is True and not result.stderr
    statuses = {check["name"]: check["status"] for check in report["checks"]}
    assert statuses["identity"] == statuses["project_files"] == "skip"
    assert not any(status == "fail" for status in statuses.values())
    run(str(binaries / f"bototoolkit{suffix}"), cwd=target.parent, env=env)


def main() -> None:
    env = {
        key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}
    }
    with tempfile.TemporaryDirectory(prefix="distribution-check-") as directory:
        temporary = Path(directory).resolve()
        archives = temporary / "dist"
        run(
            "uv",
            "build",
            "--force-pep517",
            "--no-sources",
            "--out-dir",
            str(archives),
            cwd=ROOT,
            env=env,
        )
        (wheel,) = archives.glob("*.whl")
        (source,) = archives.glob("*.tar.gz")
        inspect_archive(wheel)
        inspect_archive(source)
        requirements = temporary / "requirements.txt"
        run(
            "uv",
            "export",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--no-header",
            "--quiet",
            "--output-file",
            str(requirements),
            cwd=ROOT,
            env=env,
        )
        smoke_install(wheel, requirements, temporary / "wheel-env", env)
        rebuilt = temporary / "rebuilt"
        run(
            "uv",
            "build",
            str(source),
            "--force-pep517",
            "--wheel",
            "--no-sources",
            "--out-dir",
            str(rebuilt),
            cwd=temporary,
            env=env,
        )
        (rebuilt_wheel,) = rebuilt.glob("*.whl")
        inspect_archive(rebuilt_wheel)
        smoke_install(rebuilt_wheel, requirements, temporary / "source-env", env)
        # Install the locked optional extra into the rebuilt source environment.
        run(
            "uv",
            "export",
            "--locked",
            "--no-dev",
            "--extra",
            "tui",
            "--no-emit-project",
            "--no-header",
            "--quiet",
            "--output-file",
            str(requirements),
            cwd=ROOT,
            env=env,
        )
        binaries = temporary / "source-env" / ("Scripts" if os.name == "nt" else "bin")
        python = binaries / ("python.exe" if os.name == "nt" else "python")
        run(
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--require-hashes",
            "-r",
            str(requirements),
            cwd=temporary,
            env=env,
        )
        run(
            str(python),
            "-I",
            "-c",
            "import asyncio\n"
            "import boto3\n"
            "from amplify_ops.tui import InventoryBrowser\n"
            "from textual.widgets import DataTable\n"
            "def forbidden(*args, **kwargs):\n"
            "    raise AssertionError('Demo must not create an AWS session')\n"
            "boto3.Session = forbidden\n"
            "async def smoke():\n"
            "    app = InventoryBrowser()\n"
            "    async with app.run_test() as pilot:\n"
            "        assert app.query_one(DataTable).row_count > 0\n"
            "        await pilot.press('ctrl+q')\n"
            "asyncio.run(smoke())\n",
            cwd=temporary,
            env=env,
        )
    print("Wheel and source-distribution installation checks passed.")


if __name__ == "__main__":
    main()
