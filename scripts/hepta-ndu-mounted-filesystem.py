#!/usr/bin/env python3
"""Qualify the real NDU writer against bounded private Linux tmpfs faults.

No injected errno and no production paths: a fresh mount is filled to ENOSPC
or remounted read-only while the native writer is open. Missing mount privilege
is a failed qualification, never a skip or a substituted mock observation.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import selectors
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
MAX_FILL_BYTES = 8 * 1024 * 1024
PHASE_TIMEOUT_SECONDS = 30


def command(args: list[str]) -> str:
    result = subprocess.run(args, check=True, capture_output=True, text=True, timeout=30)
    return result.stdout.strip()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def fill_to_enospc(path: Path) -> int:
    written = 0
    with path.open("xb", buffering=0) as stream:
        block = b"\0" * 65536
        try:
            while written < MAX_FILL_BYTES:
                count = stream.write(block)
                if not count:
                    raise RuntimeError("filler made no progress without ENOSPC")
                written += count
        except OSError as error:
            if error.errno != errno.ENOSPC:
                raise
            return written
    raise RuntimeError("private mount did not return ENOSPC within the fixed bound")


def probe_erofs(path: Path) -> None:
    try:
        with path.open("xb") as stream:
            stream.write(b"read-only qualification probe")
    except OSError as error:
        if error.errno == errno.EROFS:
            return
        raise
    raise RuntimeError("read-only mount accepted a write")


def expect_phase(process: subprocess.Popen, expected: str) -> str:
    # Binary pipe, one byte at a time: buffered readline must not hide a second
    # already-read line from select, and a missing newline must remain bounded.
    deadline = time.monotonic() + PHASE_TIMEOUT_SECONDS
    data = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while len(data) < 128:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise TimeoutError(f"native fixture did not reach {expected}")
            byte = os.read(process.stdout.fileno(), 1)
            if not byte:
                raise RuntimeError(f"native fixture exited before {expected}")
            data.extend(byte)
            if byte == b"\n":
                line = data.decode("ascii").strip()
                if line != expected:
                    raise RuntimeError(f"native phase mismatch: {line!r}, expected {expected!r}")
                return line
    raise RuntimeError("native fixture emitted an oversized phase")


def send_phase(process: subprocess.Popen, phase: str) -> None:
    process.stdin.write((phase + "\n").encode("ascii"))
    process.stdin.flush()


def one_fault(binary: Path, fault: str, output: Path) -> dict:
    directory = Path(tempfile.mkdtemp(prefix="ndu-fs-", dir="/tmp"))
    mount = directory / "mount"
    mount.mkdir(mode=0o700)
    view = directory / "view"
    view.mkdir(mode=0o700)
    mounted = False
    bound = False
    process = None
    record = {"fault": fault, "passed": False, "phases": [], "cleanupPassed": False}
    started = time.monotonic_ns()
    privilege = [] if os.geteuid() == 0 else ["sudo", "-n"]
    with (output / f"{fault}.stderr.log").open("wb") as stderr:
        try:
            options = f"size=4m,mode=0700,uid={os.getuid()},gid={os.getgid()},nodev,nosuid,noexec"
            command(privilege + ["mount", "-t", "tmpfs", "-o", options, "ndu-qualification", str(mount)])
            mounted = True
            filesystem = command(["findmnt", "-n", "-o", "FSTYPE", "--target", str(mount)])
            if filesystem != "tmpfs" or os.stat(mount).st_dev == os.stat(directory).st_dev:
                raise RuntimeError("the private fault mount was not independently established")
            record["filesystem"] = filesystem
            # Separate view isolates the VFS read-only transition. The Linux
            # owner holds a read-only flock descriptor, not a writable FD that
            # pins this mount writable. EROFS must come from native creation.
            command(privilege + ["mount", "--bind", str(mount), str(view)])
            bound = True
            record["readOnlyBoundary"] = "vfs-bind-mount"
            process = subprocess.Popen(
                [str(binary), str(view), fault], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=stderr, bufsize=0,
            )
            record["phases"].append(expect_phase(process, "READY"))
            filler = mount / "qualification-filler"
            if fault == "enospc":
                record["filledBytes"] = fill_to_enospc(filler)
                record["observedErrno"] = errno.ENOSPC
            elif fault == "erofs":
                command(privilege + ["mount", "-o", "remount,bind,ro,nodev,nosuid,noexec", str(view)])
                probe_erofs(view / "read-only-probe")
                record["observedErrno"] = errno.EROFS
            else:
                raise ValueError("unregistered fault")
            send_phase(process, "APPLY")
            record["phases"].append(expect_phase(process, "FAULT_OBSERVED"))
            if fault == "enospc":
                filler.unlink()
            else:
                command(privilege + ["mount", "-o", "remount,bind,rw,nodev,nosuid,noexec", str(view)])
            send_phase(process, "RECOVER")
            record["phases"].append(expect_phase(process, "RECOVERED"))
            record["exitCode"] = process.wait(timeout=10)
            if record["exitCode"] != 0:
                raise RuntimeError("native fixture failed after recovery")
            record["passed"] = True
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            record["error"] = str(error)
            if isinstance(error, subprocess.CalledProcessError):
                record["commandStderr"] = (error.stderr or "")[:4096]
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=10)
                process.stdin.close()
                process.stdout.close()
            try:
                if bound:
                    command(privilege + ["umount", str(view)])
                if mounted:
                    command(privilege + ["umount", str(mount)])
                # Never recursively delete an unconfirmed mount. Once unmounted,
                # this is only the empty directory created by this invocation.
                view.rmdir()
                mount.rmdir()
                directory.rmdir()
                record["cleanupPassed"] = True
            except (OSError, subprocess.SubprocessError) as error:
                record["passed"] = False
                record["cleanupError"] = str(error)
                record["retainedFixturePath"] = str(directory)
    record["elapsedNs"] = time.monotonic_ns() - started
    record["stderrSha256"] = digest(output / f"{fault}.stderr.log")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=os.environ.get("HEPTA_NDU_MOUNTED_OUTPUT"))
    parser.add_argument("--source-sha", default=os.environ.get("HEPTA_NDU_SOURCE_SHA"))
    parser.add_argument("--source-tree", default=os.environ.get("HEPTA_NDU_SOURCE_TREE"))
    parser.add_argument("--lane", choices=["source-head", "synthetic-merge"], default=os.environ.get("HEPTA_NDU_QUALIFICATION_LANE"))
    args = parser.parse_args()
    if args.output is None or args.lane is None:
        parser.error("evidence output and lane must be supplied explicitly or by the qualification runner")
    for identity in (args.source_sha, args.source_tree):
        if not isinstance(identity, str) or re.fullmatch(r"[0-9a-f]{40}", identity) is None:
            parser.error("exact commit/tree identities are required")
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error("evidence output must be outside the source checkout")
    if output.exists() and any(output.iterdir()):
        parser.error("previous evidence may not be overwritten")
    output.mkdir(parents=True, exist_ok=True)
    binary = args.binary.resolve(strict=True)
    before = digest(binary)
    cases = [one_fault(binary, fault, output) for fault in ("enospc", "erofs")]
    receipt = {
        "schema": "hepta.ndu.mounted-filesystem-qualification.v1",
        "sourceSha": args.source_sha, "sourceTree": args.source_tree,
        "lane": args.lane, "host": platform.node(), "kernel": platform.release(),
        "binarySha256": before, "binaryUnchanged": before == digest(binary),
        "cases": cases, "productionActivation": False,
    }
    receipt["passed"] = receipt["binaryUnchanged"] and all(case["passed"] for case in cases)
    (output / "mounted-filesystem.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
