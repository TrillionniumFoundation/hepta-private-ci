#!/usr/bin/env python3
"""Independent exact-source native feedback. All checks run; failures stay failures."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
CHECKS = [
    ("format", ["cargo", "fmt", "-p", "codex-hepta-bao-adapter", "-p", "codex-hepta-authbus", "-p", "codex-state-sqlite", "--", "--check"]),
    ("tests", ["cargo", "test", "--locked", "-p", "codex-hepta-bao-adapter", "-p", "codex-state-sqlite", "--all-targets", "--", "--test-threads=2"]),
    ("clippy", ["cargo", "clippy", "--locked", "-p", "codex-hepta-bao-adapter", "-p", "codex-state-sqlite", "--all-targets", "--", "-D", "warnings"]),
    ("authbus-schema", ["cargo", "test", "--locked", "-p", "codex-hepta-authbus", "authority_schema", "--", "--test-threads=2"]),
]


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--candidate-role", choices=["source-head", "synthetic-merge"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    head, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    before = git("status", "--porcelain", "--untracked-files=no")
    results = []
    environment = dict(os.environ)
    environment.setdefault("CARGO_BUILD_JOBS", "2")
    environment.setdefault("CARGO_PROFILE_DEV_DEBUG", "0")
    environment.setdefault("CARGO_PROFILE_TEST_DEBUG", "0")
    for name, command in CHECKS:
        start = time.monotonic()
        log = args.output / f"{name}.log"
        with log.open("wb") as stream:
            try:
                completed = subprocess.run(command, cwd=ROOT / "codex-rs", env=environment,
                                           stdout=stream, stderr=subprocess.STDOUT, timeout=3000, check=False)
                code = completed.returncode
            except (OSError, subprocess.TimeoutExpired) as error:
                stream.write(f"\nqualification command failed: {error}\n".encode())
                code = 124 if isinstance(error, subprocess.TimeoutExpired) else 127
        results.append({"check": name, "command": command, "exitCode": code,
                        "durationSeconds": round(time.monotonic() - start, 3),
                        "logSha256": hashlib.sha256(log.read_bytes()).hexdigest()})
        print(f"{name}: exit {code}", flush=True)
    after = git("status", "--porcelain", "--untracked-files=no")
    identity_ok = head == args.expected_sha and not before and not after and head == git("rev-parse", "HEAD")
    passed = identity_ok and all(row["exitCode"] == 0 for row in results)
    receipt = {"schema": "hepta.secrets-native-feedback.v1", "head": head, "tree": tree,
               "expectedSha": args.expected_sha, "candidateRole": args.candidate_role,
               "identityClean": identity_ok, "trackedChangesBefore": before, "trackedChangesAfter": after,
               "checks": results, "passed": passed,
               "providerDynamicE2E": False, "productionExecutionProved": False,
               "independentAcceptance": False, "releaseAuthority": False}
    (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
    return 0 if passed else 1

if __name__ == "__main__":
    raise SystemExit(main())
