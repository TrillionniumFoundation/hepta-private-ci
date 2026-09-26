"""Bind native Agentd qualification to an exact checkout and tested fixture.

This is CI evidence, not a deployment attestation or independent acceptance.
Every required step must execute successfully; tree sharing is not qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

REQUIRED_STEPS = (
    "execution", "native_build", "fixture_identity", "owner_libraries",
    "optional_retirement", "automation_retirement", "memory_recovery",
    "plasticity", "runtime_cutover", "writer_admission", "daemon_e2e",
    "strict_lint", "unchanged",
)


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "--no-replace-objects", *args], text=True, stderr=subprocess.PIPE
    ).strip()


def context() -> dict:
    values = {key: os.environ.get(key, "") for key in (
        "SOURCE_SHA", "BASE_SHA", "EXPECTED_SHA", "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT", "RUNNER_OS", "RUNNER_ARCH", "HEPTA_CI_LANE",
    )}
    for key in ("SOURCE_SHA", "EXPECTED_SHA"):
        if re.fullmatch(r"[0-9a-f]{40}", values[key]) is None:
            raise ValueError(f"invalid {key}")
    for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        if re.fullmatch(r"[1-9][0-9]*", values[key]) is None:
            raise ValueError(f"invalid {key}")
    if values["RUNNER_OS"] not in ("Linux", "macOS") or not values["RUNNER_ARCH"]:
        raise ValueError("native Linux/macOS runner identity is required")
    lane = values["HEPTA_CI_LANE"]
    if lane not in ("source-head", "merge-candidate"):
        raise ValueError("unknown Agentd qualification lane")
    if git("rev-parse", "HEAD") != values["EXPECTED_SHA"]:
        raise ValueError("checked-out HEAD does not match EXPECTED_SHA")
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("qualification checkout is dirty")
    tree = git("rev-parse", "HEAD^{tree}")
    if lane == "source-head":
        if values["SOURCE_SHA"] != values["EXPECTED_SHA"]:
            raise ValueError("source lane is not the exact source commit")
    else:
        if re.fullmatch(r"[0-9a-f]{40}", values["BASE_SHA"]) is None:
            raise ValueError("invalid merge base")
        if git("show", "-s", "--format=%P", "HEAD").split() != [
            values["BASE_SHA"], values["SOURCE_SHA"],
        ]:
            raise ValueError("merge parents differ from the declared candidate")
        if git("merge-tree", "--write-tree", values["BASE_SHA"], values["SOURCE_SHA"]) != tree:
            raise ValueError("merge tree differs from the recomputed candidate")
    return {**values, "tree_sha": tree}


def fingerprint(path: Path) -> dict:
    # Open the named artifact once, without following a substituted final link.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not before.st_mode & 0o111 or before.st_size == 0:
            raise ValueError("fixture must be a nonempty executable regular file")
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if identity(before) != identity(after):
            raise ValueError("fixture changed while hashing")
    return {"path": str(path.absolute()), "sha256": digest.hexdigest(), "bytes": before.st_size}


def write_new(path: Path, record: dict) -> None:
    root = Path(git("rev-parse", "--show-toplevel")).resolve()
    if not path.is_absolute() or path.resolve().is_relative_to(root):
        raise ValueError("receipts must be outside the source checkout")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def validate_steps(steps: dict) -> list[str]:
    if not isinstance(steps, dict):
        raise ValueError("step evidence must be an object")
    errors = []
    for name in REQUIRED_STEPS:
        step = steps.get(name)
        if not isinstance(step, dict) or step.get("outcome") != "success" or step.get("conclusion") != "success":
            errors.append(f"required step did not succeed: {name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("capture", "finish"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.phase == "capture":
            write_new(args.directory / "fixture.json", {
                "schema_version": 1, "context": context(),
                "fixture": fingerprint(args.binary), "status": "captured",
            })
            return 0
        errors = []
        record = {"schema_version": 1, "status": "failed", "production_activation": False}
        try:
            captured_bytes = (args.directory / "fixture.json").read_bytes()
            before = json.loads(captured_bytes)
            after = {"context": context(), "fixture": fingerprint(args.binary)}
            record.update(after)
            record["capture_sha256"] = hashlib.sha256(captured_bytes).hexdigest()
            if before.get("schema_version") != 1 or before.get("status") != "captured":
                errors.append("invalid fixture capture")
            if any(before.get(key) != after[key] for key in after):
                errors.append("source, runner or fixture changed during qualification")
            steps = json.loads(os.environ["AGENTD_STEPS"])
            errors.extend(validate_steps(steps))
            record["steps"] = {name: steps.get(name) for name in REQUIRED_STEPS}
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            errors.append(str(error))
        record["errors"] = errors
        record["status"] = "passed" if not errors else "failed"
        write_new(args.directory / "qualification.json", record)
        print(json.dumps(record, sort_keys=True))
        return 1 if errors else 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Agentd receipt rejected: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
