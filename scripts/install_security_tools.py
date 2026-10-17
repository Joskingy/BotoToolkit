"""Install a pinned, checksum-verified Gitleaks binary into ignored local storage."""

import hashlib
import io
import os
import platform
import tarfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "8.24.3"
ARCHIVES = {
    "Windows": (
        "windows_x64.zip",
        "3f1a35578631dbfe633cc5b49e6c906e55ff14a4bfd7336a10fb27fe33b6dcd2",
        "gitleaks.exe",
    ),
    "Linux": (
        "linux_x64.tar.gz",
        "9991e0b2903da4c8f6122b5c3186448b927a5da4deef1fe45271c3793f4ee29c",
        "gitleaks",
    ),
}
ROOT = Path(__file__).resolve().parents[1]


def install() -> Path:
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("Only Windows/Linux x64 scanner installations are configured.")
    suffix, digest, executable = ARCHIVES[platform.system()]
    url = f"https://github.com/gitleaks/gitleaks/releases/download/v{VERSION}/gitleaks_{VERSION}_{suffix}"
    with urllib.request.urlopen(url, timeout=60) as response:
        archive = response.read(30 * 1024 * 1024 + 1)
    if hashlib.sha256(archive).hexdigest() != digest:
        raise RuntimeError("Scanner archive checksum mismatch.")
    # Extract only the known executable, never arbitrary archive paths.
    if suffix.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            data = zipped.read(executable)
    else:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            member = tar.getmember(executable)
            if not member.isfile():
                raise RuntimeError("Unexpected scanner archive entry.")
            data = tar.extractfile(member).read()
    destination = ROOT / ".uv" / "security-tools" / f"gitleaks-{VERSION}" / executable
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".download")
    temporary.write_bytes(data)
    temporary.chmod(0o755)
    os.replace(temporary, destination)
    return destination


if __name__ == "__main__":
    try:
        install()
    except (OSError, RuntimeError, KeyError, ValueError):
        raise SystemExit("Scanner installation failed; no scan was performed.") from None
    print(f"Installed checksum-verified Gitleaks {VERSION}.")
