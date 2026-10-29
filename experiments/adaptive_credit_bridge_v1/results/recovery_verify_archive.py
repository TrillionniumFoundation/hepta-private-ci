#!/usr/bin/env python3
"""Verify every archive member and replay its delivered, unchanged entrypoint."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import resource
import subprocess
import sys
import tarfile
import time


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write(path, value):
    with path.open("x") as output:
        json.dump(value, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def verify(args):
    receipt = json.loads(args.archive_receipt.read_text())
    if sha(args.archive) != receipt["archive_sha256"]:
        raise ValueError("Archive identity mismatch")
    args.destination.mkdir(parents=True, exist_ok=False)
    root_name = PurePosixPath(receipt["portable_replay_entrypoint"]).parts[0]
    seen = {}
    with tarfile.open(args.archive) as archive:
        manifest_name = root_name + "/ARCHIVE_MANIFEST.json"
        manifest = json.load(archive.extractfile(manifest_name))["files"]
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if (not member.isfile() or path.is_absolute() or ".." in path.parts
                    or not path.parts or path.parts[0] != root_name
                    or member.name in seen):
                raise ValueError("Unsafe or duplicate archive member")
            data = archive.extractfile(member).read()
            identity = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            relative = path.relative_to(root_name).as_posix()
            if relative == "ARCHIVE_MANIFEST.json":
                if identity["sha256"] != receipt["manifest_sha256"]:
                    raise ValueError("Archive manifest identity mismatch")
            elif manifest.get(relative) != identity:
                raise ValueError("Archive member identity mismatch: " + relative)
            target = args.destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(data)
            target.chmod(member.mode & 0o777)
            seen[member.name] = identity
        expected = {root_name + "/" + name for name in manifest}
        expected.add(manifest_name)
        if set(seen) != expected or len(seen) != receipt["verified_archive_members"]:
            raise ValueError("Archive member inventory mismatch")
    bundle = args.destination / root_name
    working = args.destination / "delivered-replay"
    nested_receipt = args.destination / "nested-replay-launch"
    command = [sys.executable, str(bundle / "REPLAY.py"), "replay", "--bundle", str(bundle),
               "--destination", str(working), "--receipt", str(nested_receipt)]
    subprocess.run(command, check=True)
    verification = json.loads((working / "REPLAY_VERIFICATION.json").read_text())
    if not verification["passed"] or verification["episodes"] != 16:
        raise ValueError("Delivered entrypoint replay failed")
    result = {"passed": True, "archive_sha256": receipt["archive_sha256"],
              "verified_archive_members": len(seen), "extracted_root": str(bundle),
              "delivered_entrypoint_sha256": sha(bundle / "REPLAY.py"),
              "replay": verification, "nested_replay_cost_is_not_additive": True}
    write(args.destination / "DELIVERED_ARCHIVE_VERIFICATION.json", result)
    print(json.dumps(result, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    for name in ("archive", "archive-receipt", "destination", "receipt"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    if args.worker:
        verify(args)
        return 0
    started = time.perf_counter()
    own_before = resource.getrusage(resource.RUSAGE_SELF)
    child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    args.receipt.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", *sys.argv[1:]]
    write(args.receipt / "START.json", {
        "schema": "hepta.recovery.outer-launch.v1", "stage": "delivered_archive_verification",
        "command": command, "helper_sha256": sha(__file__),
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Includes child Python startup, archive verification, extraction and delivered replay; excludes this launcher's interpreter startup. All descendant costs are included, not additive."})
    with (args.receipt / "stdout.log").open("xb") as out, (args.receipt / "stderr.log").open("xb") as err:
        process = subprocess.run(command, stdout=out, stderr=err)
    own = resource.getrusage(resource.RUSAGE_SELF)
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {"stage": "delivered_archive_verification", "exit_code": process.returncode,
              "complete": process.returncode == 0, "wall_seconds": time.perf_counter() - started,
              "self_cpu_seconds": own.ru_utime + own.ru_stime - own_before.ru_utime - own_before.ru_stime,
              "child_cpu_seconds": child.ru_utime + child.ru_stime - child_before.ru_utime - child_before.ru_stime,
              "nested_costs_not_additive": True,
              "stdout_sha256": sha(args.receipt / "stdout.log"),
              "stderr_sha256": sha(args.receipt / "stderr.log")}
    write(args.receipt / ("COMPLETE.json" if result["complete"] else "FAILED.json"), result)
    print(json.dumps(result, sort_keys=True))
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
