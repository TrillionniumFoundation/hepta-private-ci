#!/usr/bin/env python3
"""Execute the committed qualification plan without rewriting source or stopping
at the first failed check. Every command has an independent bounded record.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from cognitive_store_plan import SPEC_ENV, load_plan, spec_sha256

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    args = parser.parse_args()
    if not args.records.is_absolute() or args.records.resolve().is_relative_to(ROOT):
        raise SystemExit("records must be outside the checkout")
    # Validate the entire committed plan before reserving records or executing
    # its first command. A malformed late entry cannot leave partial execution.
    canonical_plan = ROOT / "docs/modules/cognitive.store/QUALIFICATION_PLAN.json"
    if args.plan.resolve(strict=True) != canonical_plan:
        raise SystemExit("qualification must execute the canonical committed plan")
    plan_object = subprocess.check_output(
        ["git", "--no-replace-objects", "rev-parse", "HEAD:docs/modules/cognitive.store/QUALIFICATION_PLAN.json"],
        cwd=ROOT, text=True).strip()
    actual_object = subprocess.check_output(
        ["git", "hash-object", str(canonical_plan)], cwd=ROOT, text=True).strip()
    if plan_object != actual_object:
        raise SystemExit("qualification plan differs from the tested Git object")
    commands, _ = load_plan(canonical_plan, ROOT, dict(os.environ))
    args.records.mkdir(parents=True, exist_ok=False)
    failed = False
    for item in commands:
        name = item["record"]
        cwd = Path(item["working_directory"])
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        env.update(item["environment"])
        env[SPEC_ENV] = spec_sha256(item)
        command = item["command"]
        output = args.records / name
        if item.get("native") and env.get("COGNITIVE_NATIVE_READY") != "true":
            def observed_git(*argv):
                return subprocess.check_output(["git", "--no-replace-objects", *argv], cwd=ROOT, text=True).strip()
            identity = {
                "commit": observed_git("rev-parse", "HEAD"),
                "tree": observed_git("rev-parse", "HEAD^{tree}"),
                "dirty": bool(observed_git("status", "--porcelain", "--untracked-files=normal")),
            }
            output.write_text(json.dumps({
                "status": "skipped", "error": "infrastructure_invalid: native preparation did not pass",
                "command": command, "command_exit_code": None,
                "tested_sha": env.get("TESTED_SHA"), "source_sha": env.get("SOURCE_SHA"),
                "base_sha": env.get("BASE_SHA"), "lane": env.get("HEPTA_CI_LANE"),
                "run_id": env.get("GITHUB_RUN_ID"), "run_attempt": env.get("GITHUB_RUN_ATTEMPT"),
                "before": identity, "after": identity,
                "working_directory": str(cwd), "minimum_tests": item["minimum_tests"],
                "timeout_seconds": item["timeout_seconds"], "command_spec_sha256": env[SPEC_ENV],
            }, indent=2) + "\n", encoding="utf-8")
            failed = True
            continue
        print("::group::" + name, flush=True)
        result = subprocess.run([
            sys.executable, str(ROOT / "scripts/hepta_ci_exec.py"),
            "--output", str(output), "--minimum-tests", str(item["minimum_tests"]),
            "--timeout-seconds", str(item["timeout_seconds"]), "--", *command,
        ], cwd=cwd, env=env, check=False)
        print("::endgroup::", flush=True)
        failed = failed or result.returncode != 0
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
