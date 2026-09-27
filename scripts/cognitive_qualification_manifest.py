#!/usr/bin/env python3
"""Bind cognitive.store command records into one exact-candidate receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


class Invalid(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def load_record(path: Path, tested_sha: str, lane: str) -> dict:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Invalid(f"cannot decode command record {path.name}: {error}") from error
    if (
        record.get("status") != "passed"
        or record.get("command_exit_code") != 0
        or record.get("tested_sha") != tested_sha
        or record.get("lane") != lane
        or record.get("timed_out")
        or record.get("output_limit_exceeded")
        or record.get("observed_failed_tests", 0) != 0
    ):
        raise Invalid(f"command record is not terminal-success for this candidate: {path.name}")
    before = record.get("before") or {}
    after = record.get("after") or {}
    if (
        before.get("commit") != tested_sha
        or after.get("commit") != tested_sha
        or before.get("tree") != after.get("tree")
        or before.get("dirty")
        or after.get("dirty")
    ):
        raise Invalid(f"command record identity changed or is dirty: {path.name}")
    return {
        "name": path.name,
        "sha256": sha256(path),
        "command": record.get("command"),
        "observedPassedTests": record.get("observed_passed_tests", 0),
        "logBytes": record.get("log_bytes", 0),
        "logSha256": record.get("log_sha256"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--required", action="append", default=[])
    parser.add_argument("--evidence", action="append", default=[])
    args = parser.parse_args()

    try:
        tested_sha = os.environ.get("TESTED_SHA", "")
        source_sha = os.environ.get("SOURCE_SHA", "")
        base_sha = os.environ.get("BASE_SHA", "")
        lane = os.environ.get("HEPTA_CI_LANE", "")
        if re.fullmatch(r"[0-9a-f]{40}", tested_sha) is None:
            raise Invalid("TESTED_SHA is not a full Git object id")
        if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
            raise Invalid("SOURCE_SHA is not a full Git object id")
        if lane not in {"source-head", "base-merge"}:
            raise Invalid("HEPTA_CI_LANE is not source-head or base-merge")
        if git("rev-parse", "HEAD") != tested_sha:
            raise Invalid("checkout HEAD differs from TESTED_SHA")
        if git("status", "--porcelain", "--untracked-files=normal"):
            raise Invalid("qualification checkout is dirty")

        required = sorted(set(args.required))
        if not required:
            raise Invalid("at least one required command record is required")
        records = []
        for name in required:
            path = args.records / name
            if not path.is_file():
                raise Invalid(f"required command record is missing: {name}")
            records.append(load_record(path, tested_sha, lane))

        evidence = []
        for value in sorted(set(args.evidence)):
            path = Path(value)
            if not path.is_file():
                raise Invalid(f"required evidence file is missing: {path}")
            evidence.append(
                {
                    "name": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )

        receipt = {
            "schema": "hepta.cognitive-store-qualification-manifest.v1",
            "sourceSha": source_sha,
            "baseSha": base_sha,
            "testedSha": tested_sha,
            "testedTree": git("rev-parse", "HEAD^{tree}"),
            "parents": git("show", "-s", "--format=%P", "HEAD").split(),
            "lane": lane,
            "runId": os.environ.get("GITHUB_RUN_ID"),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "job": os.environ.get("GITHUB_JOB"),
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "commands": records,
            "evidence": evidence,
            "result": "terminal-success",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except Invalid as error:
        print(f"cognitive qualification manifest rejected: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
