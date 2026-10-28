#!/usr/bin/env python3
"""Capture bounded host evidence after the canonical cargo-deny action fails.

This does not replace the Docker check or change its result. The host uses the
same manifest, configuration, features and check set, with an explicit lockfile
guard. Host/container differences and fresh advisory data remain material.
"""

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import selectors
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

ARCHIVE_NAME = "cargo-deny-0.19.0-x86_64-unknown-linux-musl"
ARCHIVE_URL = (
    "https://github.com/EmbarkStudios/cargo-deny/releases/download/0.19.0/"
    f"{ARCHIVE_NAME}.tar.gz"
)
ARCHIVE_BYTES = 8265108
ARCHIVE_SHA256 = "0e8c2aa59128612c90d9e09c02204e912f29a5b8d9a64671b94608cbe09e064f"
BINARY_BYTES = 16086896
BINARY_SHA256 = "06f9d1a0ba92b201bff1215b6dc24e669b212c151ecd52cae5d38aab73931d3c"
MAX_LOG_BYTES = 8 * 1024 * 1024
INPUTS = (
    "codex-rs/Cargo.toml",
    "codex-rs/Cargo.lock",
    "codex-rs/deny.toml",
    "codex-rs/rust-toolchain.toml",
    ".github/workflows/cargo-deny.yml",
    "scripts/capture_cargo_deny_diagnostic.py",
)


def identity(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
    return {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def checkpoint(output: Path, receipt: dict, phase: str, status: str = "in_progress"):
    """Atomically retain the latest complete receipt before a lengthy operation."""
    receipt["phase"] = phase
    receipt["status"] = status
    receipt["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    temporary = output / "receipt.json.tmp"
    try:
        with temporary.open("w", encoding="utf-8") as target:
            json.dump(receipt, target, indent=2)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, output / "receipt.json")
    finally:
        temporary.unlink(missing_ok=True)


def capture(
    command: list[str],
    root: Path,
    output: Path,
    label: str,
    *,
    timeout: float = 600,
    limit: int = MAX_LOG_BYTES,
) -> dict:
    """Drain both pipes while retaining only bounded prefixes, never a tail leak."""
    streams = {}
    with ExitStack() as stack:
        selector = stack.enter_context(selectors.DefaultSelector())
        process = subprocess.Popen(
            command,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        for name in ("stdout", "stderr"):
            pipe = stack.enter_context(getattr(process, name))
            sink = stack.enter_context((output / f"{label}.{name}.log").open("wb"))
            streams[name] = {
                "bytes": 0,
                "kept": 0,
                "digest": hashlib.sha256(),
                "sink": sink,
            }
            selector.register(pipe, selectors.EVENT_READ, name)
        deadline = time.monotonic() + timeout
        timed_out = False
        while selector.get_map() or process.poll() is None:
            if not timed_out and time.monotonic() >= deadline:
                timed_out = True
                # Stop this bounded diagnostic and its own children only.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            for key, _ in selector.select(0.1):
                block = os.read(key.fileobj.fileno(), 65536)
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                state = streams[key.data]
                state["bytes"] += len(block)
                state["digest"].update(block)
                retained = block[: max(0, limit - state["kept"])]
                state["sink"].write(retained)
                state["kept"] += len(retained)
        exit_code = process.wait()
    return {
        "command": command,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "streams": {
            name: {
                "path": f"{label}.{name}.log",
                "observed_bytes": state["bytes"],
                "observed_sha256": state["digest"].hexdigest(),
                "retained_bytes": state["kept"],
                "truncated": state["bytes"] > limit,
                "complete": not timed_out and state["bytes"] <= limit,
                "retained_sha256": identity(output / f"{label}.{name}.log")["sha256"],
            }
            for name, state in streams.items()
        },
    }


def unpack_verified(archive: Path, directory: Path) -> Path:
    if identity(archive) != {"bytes": ARCHIVE_BYTES, "sha256": ARCHIVE_SHA256}:
        raise ValueError("cargo-deny release archive identity mismatch")
    binary = directory / "cargo-deny"
    with tarfile.open(archive, "r:gz") as source:
        member = source.getmember(f"{ARCHIVE_NAME}/cargo-deny")
        if not member.isfile() or member.size != BINARY_BYTES:
            raise ValueError(
                "cargo-deny release member is not the expected regular file"
            )
        payload = source.extractfile(member)
        if payload is None:
            raise ValueError("cargo-deny release member is missing")
        with payload, binary.open("xb") as target:
            for block in iter(lambda: payload.read(65536), b""):
                target.write(block)
    if identity(binary) != {"bytes": BINARY_BYTES, "sha256": BINARY_SHA256}:
        raise ValueError("cargo-deny binary identity mismatch")
    binary.chmod(0o700)
    return binary


def download_tool(directory: Path) -> Path:
    archive = directory / "cargo-deny.tar.gz"
    total = 0
    deadline = time.monotonic() + 90
    with (
        urllib.request.urlopen(ARCHIVE_URL, timeout=30) as response,
        archive.open("xb") as target,
    ):
        while block := response.read(65536):
            if time.monotonic() > deadline:
                raise TimeoutError("cargo-deny release download exceeded 90 seconds")
            total += len(block)
            if total > ARCHIVE_BYTES:
                raise ValueError("cargo-deny release exceeds the pinned byte count")
            target.write(block)
    return unpack_verified(archive, directory)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output_dir.resolve()
    if output == root or root in output.parents:
        parser.error("diagnostic output must be outside the checkout")
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema_version": 1,
        "kind": "cargo_deny_host_diagnostic_after_canonical_failure",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "original_action": "EmbarkStudios/cargo-deny-action@82eb9f621fbc699dd0918f3ea06864c14cc84246",
        "original_failure_preserved": True,
        "qualification": False,
        "platform": {"sys_platform": sys.platform, "machine": platform.machine()},
        "worktree_clean_before": None,
        "worktree_clean_after": None,
        "capture_error": None,
        "differences_from_canonical": [
            "Ubuntu host instead of the pinned Docker image; this is separate diagnostic evidence.",
            "Explicit --locked prevents changing Cargo.lock; the canonical action omits that flag.",
            "JSON output and explicit config path; registry and advisory data may be fetched later.",
        ],
        "tool_release": {
            "url": ARCHIVE_URL,
            "archive_sha256": ARCHIVE_SHA256,
            "archive_bytes": ARCHIVE_BYTES,
            "binary_sha256": BINARY_SHA256,
            "binary_bytes": BINARY_BYTES,
        },
        "runs": {},
    }
    checkpoint(output, receipt, "initializing")
    error = None
    try:
        if receipt["platform"] != {"sys_platform": "linux", "machine": "x86_64"}:
            raise ValueError("the pinned diagnostic executable requires Linux x86_64")
        receipt["inputs_before"] = {path: identity(root / path) for path in INPUTS}
        for label, command in (
            ("source", ["git", "rev-parse", "HEAD", "HEAD^{tree}"]),
            (
                "worktree_before",
                ["git", "status", "--porcelain", "--untracked-files=normal"],
            ),
            ("cargo_version", ["cargo", "--version"]),
            ("rustc_version", ["rustc", "--version"]),
        ):
            checkpoint(output, receipt, f"{label}_running")
            result = capture(command, root, output, label, timeout=30, limit=65536)
            receipt["runs"][label] = result
            checkpoint(output, receipt, f"{label}_captured")
            if result["exit_code"] != 0 or result["timed_out"]:
                raise ValueError(f"{label} did not complete successfully")
            if label == "worktree_before":
                receipt["worktree_clean_before"] = (
                    result["streams"]["stdout"]["observed_bytes"] == 0
                )
            if label == "source":
                receipt["source_commit"], receipt["source_tree"] = (
                    (output / "source.stdout.log").read_text().split()
                )
        for name in ("cargo", "rustc"):
            if (
                not (output / f"{name}_version.stdout.log")
                .read_text()
                .startswith(f"{name} 1.95.0 ")
            ):
                raise ValueError(f"{name} is not the canonical 1.95.0 toolchain")
        checkpoint(output, receipt, "preflight_verified")
        with tempfile.TemporaryDirectory(
            prefix="cargo-deny-tool-", dir=output.parent
        ) as directory:
            checkpoint(output, receipt, "downloading_tool")
            binary = download_tool(Path(directory))
            receipt["verified_binary"] = identity(binary)
            command = [
                str(binary),
                "--log-level",
                "warn",
                "--format",
                "json",
                "--color",
                "never",
                "--manifest-path",
                "./codex-rs/Cargo.toml",
                "--all-features",
                "--locked",
                "check",
                "--config",
                "./codex-rs/deny.toml",
            ]
            receipt["diagnostic_command"] = command
            checkpoint(output, receipt, "running_diagnostic")
            receipt["runs"]["diagnostic"] = capture(
                command,
                root,
                output,
                "cargo_deny",
            )
            checkpoint(output, receipt, "diagnostic_captured")
        receipt["inputs_after"] = {path: identity(root / path) for path in INPUTS}
        receipt["inputs_unchanged"] = (
            receipt["inputs_before"] == receipt["inputs_after"]
        )
        checkpoint(output, receipt, "worktree_after_running")
        result = capture(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            root,
            output,
            "worktree_after",
            timeout=30,
            limit=65536,
        )
        receipt["runs"]["worktree_after"] = result
        if result["exit_code"] != 0 or result["timed_out"]:
            raise ValueError("worktree_after did not complete successfully")
        receipt["worktree_clean_after"] = (
            result["streams"]["stdout"]["observed_bytes"] == 0
        )
        checkpoint(output, receipt, "postflight_recorded")
        if not receipt["inputs_unchanged"]:
            raise ValueError("diagnostic inputs changed during capture")
        if receipt["runs"]["diagnostic"]["timed_out"]:
            raise TimeoutError("host cargo-deny diagnostic timed out")
    except Exception as failure:
        error = f"{type(failure).__name__}: {failure}"
    receipt["capture_error"] = error
    receipt["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    checkpoint(
        output,
        receipt,
        receipt["phase"] if error else "finished",
        "capture_error" if error else "completed",
    )
    print("cargo-deny host evidence captured; the original action failure is unchanged")
    return int(error is not None)


if __name__ == "__main__":
    raise SystemExit(main())
