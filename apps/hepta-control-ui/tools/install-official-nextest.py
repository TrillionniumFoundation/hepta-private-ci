"""Install only the verified official Linux GNU nextest 0.9.146 release."""

import argparse
import hashlib
import io
import os
import platform
import tarfile
import tempfile
import urllib.request
from pathlib import Path

URL = "https://github.com/nextest-rs/nextest/releases/download/cargo-nextest-0.9.146/cargo-nextest-0.9.146-x86_64-unknown-linux-gnu.tar.gz"
ARCHIVE_SHA = "682c21b777c333e96fd532e114d3a5a894e0729ab88d94c0a9f20f8419695428"
BINARY_SHA = "aac21fea56e7ae3f45b5b7c606e02d62d4ec5b3578658fefe4a98a5f29c4bf1a"
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024


def verify(binary: Path) -> None:
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValueError("This pinned release is only for Linux x86_64 GNU")
    if not os.confstr("CS_GNU_LIBC_VERSION").startswith("glibc "):
        raise ValueError("The pinned executable requires a GNU libc host")
    if binary.is_symlink() or not binary.is_file():
        raise ValueError("Expected one ordinary installed executable")
    if hashlib.sha256(binary.read_bytes()).hexdigest() != BINARY_SHA:
        raise ValueError("Installed nextest binary differs from the official digest")


def install(root: Path, data: bytes) -> None:
    if len(data) > MAX_ARCHIVE_BYTES or hashlib.sha256(data).hexdigest() != ARCHIVE_SHA:
        raise ValueError("Official nextest archive digest mismatch")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = archive.getmembers()
        if (
            len(members) != 1
            or members[0].name != "cargo-nextest"
            or not members[0].isfile()
        ):
            raise ValueError("Expected exactly one ordinary cargo-nextest member")
        binary_bytes = archive.extractfile(members[0]).read()
    if hashlib.sha256(binary_bytes).hexdigest() != BINARY_SHA:
        raise ValueError("Official nextest member digest mismatch")
    directory = root / "bin"
    directory.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=directory, prefix=".nextest-", delete=False
        ) as file:
            temporary = Path(file.name)
            file.write(binary_bytes)
        verify(temporary)
        temporary.chmod(0o755)
        temporary.replace(directory / "cargo-nextest")
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify(args.root / "bin" / "cargo-nextest")
    else:
        with urllib.request.urlopen(URL, timeout=60) as response:
            if not response.url.startswith("https://"):
                raise ValueError("Official release transfer must remain HTTPS")
            data = response.read(MAX_ARCHIVE_BYTES + 1)
        install(args.root, data)
