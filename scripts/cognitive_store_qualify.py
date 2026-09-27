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
from string import Template

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    args = parser.parse_args()
    if not args.records.is_absolute() or args.records.resolve().is_relative_to(ROOT):
        raise SystemExit("records must be outside the checkout")
    args.records.mkdir(parents=True, exist_ok=False)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if plan.get("schema") != "hepta.cognitive-store-qualification-plan.v1":
        raise SystemExit("unknown qualification plan")
    failed = False
    seen = set()
    for item in plan["commands"]:
        name = item["record"]
        if Path(name).name != name or name in seen:
            raise SystemExit("duplicate or unsafe record name")
        seen.add(name)
        cwd = (ROOT / item["cwd"]).resolve()
        if not cwd.is_relative_to(ROOT):
            raise SystemExit("working directory escapes checkout")
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        env.update({key: Template(value).substitute(env) for key, value in item.get("env", {}).items()})
        command = [Template(value).substitute(env) for value in item["command"]]
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
            }, indent=2) + "\n", encoding="utf-8")
            failed = True
            continue
        print("::group::" + name, flush=True)
        result = subprocess.run([
            sys.executable, str(ROOT / "scripts/hepta_ci_exec.py"),
            "--output", str(output), "--minimum-tests", str(item.get("minimumTests", 0)),
            "--timeout-seconds", str(item.get("timeoutSeconds", 1800)), "--", *command,
        ], cwd=cwd, env=env, check=False)
        print("::endgroup::", flush=True)
        failed = failed or result.returncode != 0
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
