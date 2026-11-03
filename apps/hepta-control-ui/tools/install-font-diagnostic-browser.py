"""Pinned Linux Chromium; observed vendor-download digests, not signatures.

The shared renderer uses this release for its upstream response-completion fix.
The opt-in font diagnostic also uses it while retaining the old browser baseline.
"""

import argparse
import hashlib
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import tempfile
import urllib.request
import zipfile

URL = "https://storage.googleapis.com/chrome-for-testing-public/157.0.8099.0/linux64/chrome-headless-shell-linux64.zip"
ARCHIVE_BYTES = 126501006
ARCHIVE_SHA = "9541eafbc02f85e3ec0c24b05f8bbffe88094389949860681bf6055aef668d7b"
BINARY_SHA = "37164bfc553db9c17e11bc19c291738a1179c5b13529ec6f20a39bd665e91be0"
BINARY = "chrome-headless-shell-linux64/chrome-headless-shell"


def digest(file):
    value = hashlib.sha256()
    for block in iter(lambda: file.read(1024 * 1024), b""):
        value.update(block)
    return value.hexdigest()


def verify(root):
    binary = root / BINARY
    if binary.is_symlink() or not binary.is_file():
        raise ValueError("Expected a regular diagnostic executable")
    with binary.open("rb") as file:
        if digest(file) != BINARY_SHA:
            raise ValueError("Diagnostic executable digest mismatch")
    return binary


def checked_members(archive):
    members = archive.infolist()
    if len(members) > 512 or sum(item.file_size for item in members) > 512 * 1024 * 1024:
        raise ValueError("Diagnostic archive exceeds limits")
    names = set()
    for item in members:
        name = PurePosixPath(item.filename)
        mode = item.external_attr >> 16
        if (name.is_absolute() or ".." in name.parts or "\\" in item.filename
                or not name.parts or name.parts[0] != "chrome-headless-shell-linux64"
                or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)
                or item.filename in names):
            raise ValueError("Unsafe diagnostic archive member")
        names.add(item.filename)
    if BINARY not in names:
        raise ValueError("Diagnostic executable missing")
    return members


def install(root):
    if root.exists():
        raise ValueError("Use a fresh task-owned diagnostic directory")
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root.parent, prefix=".font-browser-") as temporary:
        work = Path(temporary)
        archive_path = work / "browser.zip"
        with urllib.request.urlopen(URL, timeout=120) as response, archive_path.open("wb") as out:
            if response.url != URL:
                raise ValueError("Unexpected diagnostic download destination")
            remaining = ARCHIVE_BYTES + 1
            while remaining:
                block = response.read(min(1024 * 1024, remaining))
                if not block:
                    break
                out.write(block)
                remaining -= len(block)
        with archive_path.open("rb") as file:
            if archive_path.stat().st_size != ARCHIVE_BYTES or digest(file) != ARCHIVE_SHA:
                raise ValueError("Diagnostic archive digest or length mismatch")
        staged = work / "extracted"
        staged.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            for member in checked_members(archive):
                destination = staged / member.filename
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, destination.open("xb") as out:
                        shutil.copyfileobj(source, out, 1024 * 1024)
        verify(staged).chmod(0o755)
        staged.rename(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValueError("Diagnostic pin is only qualified for Linux x86_64")
    if not args.verify:
        install(args.root)
    print(verify(args.root))
