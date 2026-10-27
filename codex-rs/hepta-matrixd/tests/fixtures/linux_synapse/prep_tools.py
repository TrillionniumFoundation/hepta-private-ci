"""Fixed official ARM64 tool assets; downloaded bytes are retained and reopened."""

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
import struct
import tarfile
import urllib.request

from .files import describe, fsync_directory, relative, verify, write_json


ASSETS = {
    "just": {
        "version": "1.51.0",
        "url": "https://github.com/casey/just/releases/download/1.51.0/just-1.51.0-aarch64-unknown-linux-musl.tar.gz",
        "bytes": 2054214,
        "sha256": "ed7ec466b77709198fd4afed253dba0270203ba5eb1c006bee2b0139090284f5",
    },
    "cargo-nextest": {
        "version": "0.9.103",
        "url": "https://github.com/nextest-rs/nextest/releases/download/cargo-nextest-0.9.103/cargo-nextest-0.9.103-aarch64-unknown-linux-gnu.tar.gz",
        "bytes": 6920070,
        "sha256": "caf1cbf376a485a30795d08dad21f1d9d2baddc6c102d24b60432e7ae7d9d7a4",
    },
    "dotslash": {
        "version": "0.5.9",
        "url": "https://github.com/facebook/dotslash/releases/download/v0.5.9/dotslash-ubuntu-22.04.arm64.v0.5.9.tar.gz",
        "bytes": 691131,
        "sha256": "6e358adfd2125ab3f49967107a60a2683231d4f07f0e136735328fa1f21809b2",
    },
}


def download_asset(asset, path):
    started = datetime.now(timezone.utc).isoformat()
    request = urllib.request.Request(
        asset["url"], headers={"User-Agent": "hepta-linux-qualification-preparation"}
    )
    received = 0
    with (
        urllib.request.urlopen(request, timeout=60) as response,
        path.open("xb") as output,
    ):
        os.fchmod(output.fileno(), 0o600)
        for block in iter(lambda: response.read(1024 * 1024), b""):
            received += len(block)
            if received > asset["bytes"]:
                raise ValueError("Official tool download exceeded its fixed size")
            output.write(block)
        output.flush()
        os.fsync(output.fileno())
        status = response.status
    fsync_directory(path.parent)
    verify(path, {key: asset[key] for key in ("bytes", "sha256")})
    write_json(
        path.with_suffix(path.suffix + ".receipt.json"),
        {
            "url": asset["url"],
            "started_utc": started,
            "completed_utc": datetime.now(timezone.utc).isoformat(),
            "http_status": status,
            "actual": describe(path),
            "fixed_expected": asset,
            "written_closed_reopened": True,
            "qualification_executed": False,
        },
    )


def extract_native_binary(archive, name, destination):
    with tarfile.open(archive, "r:gz") as package:
        selected, members = [], []
        for member in package.getmembers():
            canonical = member.name
            while canonical.startswith("./"):
                canonical = canonical[2:]
            if member.isdir() and not canonical.rstrip("/"):
                continue
            relative(canonical.rstrip("/"))
            if not member.isfile() and not member.isdir():
                raise ValueError("Tool archive contains a link or special member")
            members.append(
                {"name": member.name, "bytes": member.size, "mode": member.mode}
            )
            if member.isfile() and Path(canonical).name == name:
                selected.append(member)
        if len(selected) != 1 or not 0 < selected[0].size <= 128 * 1024 * 1024:
            raise ValueError(
                "Fixed tool archive must contain one bounded named executable"
            )
        with (
            package.extractfile(selected[0]) as original,
            destination.open("xb") as output,
        ):
            shutil.copyfileobj(original, output, 1024 * 1024)
            os.fchmod(output.fileno(), 0o500)
            output.flush()
            os.fsync(output.fileno())
    fsync_directory(destination.parent)
    with destination.open("rb") as executable:
        header = executable.read(20)
    if (
        len(header) != 20
        or header[:6] != b"\x7fELF\x02\x01"
        or struct.unpack("<H", header[18:20])[0] != 183
    ):
        raise ValueError(
            "Downloaded tool is not a native little-endian ARM64 ELF64 executable"
        )
    return {
        "archive": describe(archive),
        "members": members,
        "selected": selected[0].name,
        "binary": describe(destination),
        "native_architecture": "aarch64",
        "executed": False,
    }


def prepare_tools(output):
    archives, bundle = output / "tool-archives", output / "tool-bundle"
    archives.mkdir(mode=0o700)
    bundle.mkdir(mode=0o700)
    records = {}
    for name, asset in ASSETS.items():
        archive = archives / (name + ".tar.gz")
        download_asset(asset, archive)
        records[name] = extract_native_binary(archive, name, bundle / name)
    write_json(
        output / "TOOL_ARCHIVES.json",
        {
            "schema": "hepta.synapse.linux.official-tools.v1",
            "fixed_assets": ASSETS,
            "actual": records,
        },
    )
    return bundle
