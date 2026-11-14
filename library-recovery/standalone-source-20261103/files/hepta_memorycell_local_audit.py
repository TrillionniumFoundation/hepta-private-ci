#!/usr/bin/env python3
"""Read-only local Hepta MemoryCell gate. Does NOT grant acceptance or select artifacts.

Usage: python hepta_memorycell_local_audit.py --repo /path/to/hepta-private-ci --output audit.json
Optional --run-scoped-tests executes owner package test commands on the exact local checkout.
No privilege changes, Git mutations, forced checks, CI overrides, or external effects.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys

OWNER_PACKAGES = (
    "codex-hepta-cognitive-types",
    "codex-hepta-neuron",
    "codex-hepta-memory-retrieval",
    "codex-hepta-memory",
    "codex-hepta-learning-ledger",
    "codex-hepta-learning-artifacts",
    "codex-hepta-intelligence",
    "codex-hepta-agentd",
)


def command(args, cwd, timeout=40):
    try:
        p = subprocess.run(args, cwd=cwd, text=True, errors="replace", stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout, check=False)
        return {"argv": list(args), "returncode": p.returncode,
                "stdout_tail": p.stdout[-3500:], "stderr_tail": p.stderr[-3500:],
                "status": "PASS" if p.returncode == 0 else "FAIL"}
    except (FileNotFoundError, PermissionError) as e:
        return {"argv": list(args), "returncode": None, "status": "UNAVAILABLE", "error": str(e)}
    except subprocess.TimeoutExpired:
        return {"argv": list(args), "returncode": None, "status": "TIMEOUT"}


def audit(repo, run_scoped_tests=False):
    repo = Path(repo).expanduser().resolve()
    record = {"schema": "hepta.memorycell.local-source-audit.v1",
              "observed_at_utc": datetime.now(timezone.utc).isoformat(),
              "requested_repository": str(repo),
              "authority": {"mode": "SHADOW_ONLY", "action": "DENY_ALL",
                            "qualification": "HOLD_NO_GO", "production_accepted": False},
              "limitations": ["local source+tests only, not GitHub exact PR merged-tree CI",
                              "no independent observer or signed final-use acceptance",
                              "no model/task/scaling efficacy acceptance"],
              "tools": {tool: shutil.which(tool) is not None
                        for tool in ("git", "cargo", "rustc", "just")},
              "repository_ready": False,
              "checks": []}
    if not (repo / ".git").exists():
        record["blocker"] = "NO_CHECKOUT"
        return record
    if not record["tools"]["git"]:
        record["blocker"] = "GIT_MISSING"
        return record
    root = command(["git", "rev-parse", "--show-toplevel"], repo)
    record["checks"].append(root)
    if root["status"] != "PASS" or Path(root["stdout_tail"].strip()).resolve() != repo:
        record["blocker"] = "INVALID_REPOSITORY_ROOT"
        return record
    record["repository_ready"] = True
    for args in (["git", "rev-parse", "HEAD"],
                 ["git", "rev-parse", "HEAD^{tree}"],
                 ["git", "status", "--porcelain=v1", "--untracked-files=all"]):
        record["checks"].append(command(args, repo))
    record["source_dirty"] = bool(record["checks"][-1]["stdout_tail"].strip())
    if run_scoped_tests:
        if not all(record["tools"].get(t) for t in ("cargo", "rustc", "just")):
            record["blocker"] = "RUST_TOOLCHAIN_MISSING"
        elif not (repo / "codex-rs" / "justfile").exists():
            record["blocker"] = "CODEX_RUST_WORKSPACE_MISSING"
        else:
            root = repo / "codex-rs"
            for package in OWNER_PACKAGES:
                record["checks"].append(command(["just", "test", "-p", package, "--lib"], root,
                                                timeout=3600))
            record["checks"].append(command(["cargo", "fmt", "--all", "--", "--check"], root, timeout=900))
    record["scope_failures"] = [x["argv"] for x in record["checks"] if x["status"] != "PASS"]
    # Source/build evidence never becomes external independent acceptance.
    record["six_stage_closure"] = {str(i): "NOT_QUALIFIED_BY_THIS_AUDIT" for i in range(1, 7)}
    record["all_blockers_closed"] = False
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-scoped-tests", action="store_true")
    args = parser.parse_args()
    report = audit(args.repo, args.run_scoped_tests)
    out = Path(args.output).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"audit={out} source_ready={report['repository_ready']} posture=HOLD_NO_GO")
    return 0 if report["repository_ready"] and not report.get("scope_failures") and not report.get("blocker") else 2


if __name__ == "__main__":
    sys.exit(main())
