#!/usr/bin/env python3
"""Preserve a same-version host diagnostic when the blocking Docker check fails.

The original pinned cargo-deny action remains the gate. This helper cannot turn
its failure into success; it gives maintainers a durable, downloadable report.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import urllib.request


VERSION = "0.19.0"
ARCHIVE_SHA256 = "0e8c2aa59128612c90d9e09c02204e912f29a5b8d9a64671b94608cbe09e064f"
ARCHIVE_URL = (
    "https://github.com/EmbarkStudios/cargo-deny/releases/download/0.19.0/"
    "cargo-deny-0.19.0-x86_64-unknown-linux-musl.tar.gz"
)


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_and_record(command, repository, output):
    """Keep stdout, stderr and the actual failing process status together."""
    lock = repository / "codex-rs/Cargo.lock"
    before = checksum(lock)
    log = output / "cargo-deny.log"
    with log.open("wb") as stream:
        completed = subprocess.run(
            command,
            cwd=repository,
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=False,
        )
    record = {
        "command": command,
        "exit_code": completed.returncode,
        "cargo_lock_sha256_before": before,
        "cargo_lock_sha256_after": checksum(lock),
        "log_sha256": checksum(log),
        "scope": "Same pinned cargo-deny version and arguments on the host; not the Docker action's original log.",
        "original_blocking_gate_unchanged": True,
    }
    (output / "RESULT.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record), flush=True)
    return completed.returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(ARCHIVE_URL, timeout=30) as response:
            payload = response.read(32 * 1024 * 1024)
        if hashlib.sha256(payload).hexdigest() != ARCHIVE_SHA256:
            raise ValueError("Official cargo-deny release archive checksum differs")
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            members = [
                m
                for m in archive.getmembers()
                if m.isfile() and m.name.endswith("/cargo-deny")
            ]
            if len(members) != 1:
                raise ValueError("Official release has an unexpected executable layout")
            binary = output / "cargo-deny"
            binary.write_bytes(archive.extractfile(members[0]).read())
        binary.chmod(0o755)
        version = subprocess.check_output([str(binary), "--version"], text=True).strip()
        if version != f"cargo-deny {VERSION}":
            raise ValueError("Pinned diagnostic executable version differs")
        environment = {
            "binary_version": version,
            "binary_sha256": checksum(binary),
            "release_archive_sha256": ARCHIVE_SHA256,
            "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip(),
            "cargo": subprocess.check_output(["cargo", "--version"], text=True).strip(),
        }
        (output / "ENVIRONMENT.json").write_text(
            json.dumps(environment, indent=2) + "\n"
        )
        command = [
            str(binary),
            "--log-level",
            "warn",
            "--manifest-path",
            "./codex-rs/Cargo.toml",
            "--all-features",
            "check",
        ]
        return run_and_record(command, args.repository.resolve(), output)
    except Exception as error:
        (output / "BOOTSTRAP_FAILURE.json").write_text(
            json.dumps(
                {
                    "type": type(error).__name__,
                    "message": str(error),
                    "original_blocking_gate_unchanged": True,
                },
                indent=2,
            )
            + "\n"
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
