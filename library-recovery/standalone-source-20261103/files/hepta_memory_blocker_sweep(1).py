#!/usr/bin/env python3
"""Read-only, source-pinned local Hepta MemoryCell blocker sweep.

This tool does not checkout branches, edit files, approve artifacts, or change CI.
A green test result is NEVER a scientific gain/production qualification claim.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    name: str
    stage: str
    cwd: str
    cmd: tuple[str, ...]
    source: tuple[str, ...]
    purpose: str


# Only existing, inspectable entry points. The research branch and native
# integration branch are distinct: missing checks must be reported, not passed.
CHECKS = [
    Check("architecture-document-contracts", "1", ".",
          (sys.executable, "scripts/hepta-docs.py", "verify", "--profile", "development"),
          ("scripts/hepta-docs.py",), "Document contracts and owner bindings"),
    Check("artifact-retrieval-native", "1", "codex-rs",
          ("just", "test", "-p", "codex-hepta-learning-artifacts", "-p", "codex-hepta-intelligence",
           "-p", "codex-hepta-memory-retrieval", "--lib", "--locked", "--offline", "--retries", "0"),
          ("codex-rs/hepta-learning-artifacts", "codex-rs/hepta-memory-retrieval"),
          "Real Head bytes, MemoryCell recall, checkpoint and artifact integration"),
    Check("memory-agentd-native", "1", "codex-rs",
          ("just", "test", "-p", "codex-hepta-memory", "-p", "codex-hepta-agentd",
           "--lib", "--locked", "--offline", "--retries", "0"),
          ("codex-rs/hepta-memory", "codex-rs/hepta-agentd"),
          "Durable owner, typed admission and Agentd path"),
    Check("locomo-organization", "2", ".",
          (sys.executable, "-m", "unittest", "discover", "-s", "qa/stem-bakeoff",
           "-p", "test_memory_retrieval_probe.py", "-v"),
          ("qa/stem-bakeoff/test_memory_retrieval_probe.py",),
          "Typed episodic/semantic organization, support and abstention mechanics"),
    Check("procedural-replay", "3", ".",
          (sys.executable, "-m", "unittest", "discover", "-s", "qa/stem-bakeoff",
           "-p", "test_procedure_replay.py", "-v"),
          ("qa/stem-bakeoff/test_procedure_replay.py",),
          "Real observed program outcomes and replay-learning mechanics"),
    Check("procedural-export", "3", ".",
          (sys.executable, "-m", "unittest", "discover", "-s", "qa/stem-bakeoff",
           "-p", "test_procedure_native_export.py", "-v"),
          ("qa/stem-bakeoff/test_procedure_native_export.py",),
          "Artifact-native export and byte-preserving controls"),
    Check("procedural-lineage", "3", ".",
          (sys.executable, "-m", "unittest", "discover", "-s", "qa/stem-bakeoff",
           "-p", "test_procedure_replay_verify.py", "-v"),
          ("qa/stem-bakeoff/test_procedure_replay_verify.py",),
          "Replay/source ancestry closure and withdrawal checks"),
    Check("learned-router", "4", ".",
          (sys.executable, "-m", "unittest", "discover", "-s", "qa/stem-bakeoff",
           "-p", "test_cell_router_training.py", "-v"),
          ("qa/stem-bakeoff/test_cell_router_training.py",),
          "Sparse Router training, source split and selection contract"),
    Check("worker-process", "4", ".",
          (sys.executable, "-m", "unittest", "discover", "-s", "qa/stem-bakeoff",
           "-p", "test_cell_process_inference.py", "-v"),
          ("qa/stem-bakeoff/test_cell_process_inference.py",),
          "Actual local process framing, lifetime, crash and withdrawal"),
    Check("cell-evolution", "5", ".",
          (sys.executable, "-m", "unittest", "discover", "-s", "qa/stem-bakeoff",
           "-p", "test_cell_evolution.py", "-v"),
          ("qa/stem-bakeoff/test_cell_evolution.py",),
          "Split/merge/retire/rollback and equal-budget accounting"),
    Check("evolution-heldout-probe", "5", ".",
          (sys.executable, "-m", "unittest", "discover", "-s", "qa/stem-bakeoff",
           "-p", "test_real_evolution_probe.py", "-v"),
          ("qa/stem-bakeoff/test_real_evolution_probe.py",),
          "Held-out evolution evidence and source accounting"),
    Check("shared-student", "6", ".",
          (sys.executable, "-m", "unittest", "discover", "-s", "qa/stem-bakeoff",
           "-p", "test_shared_student_training.py", "-v"),
          ("qa/stem-bakeoff/test_shared_student_training.py",),
          "Text/image/multimodal student training and artifact replay"),
    Check("native-multimodal-head", "6", "codex-rs",
          ("just", "test", "-p", "codex-hepta-neuron", "--lib", "--locked", "--offline", "--retries", "0"),
          ("codex-rs/hepta-neuron/src/task_head_native.rs",),
          "Native trained task-Head parity and mandatory-modality refusal"),
    Check("native-task-export", "6", ".",
          (sys.executable, "-m", "unittest", "discover", "-s", "qa/stem-bakeoff",
           "-p", "test_native_task_head_export.py", "-v"),
          ("qa/stem-bakeoff/test_native_task_head_export.py",),
          "Pinned trained tensor export and shape validation"),
    Check("native-task-cost", "6", ".",
          (sys.executable, "-m", "unittest", "discover", "-s", "qa/stem-bakeoff",
           "-p", "test_native_task_head_cost.py", "-v"),
          ("qa/stem-bakeoff/test_native_task_head_cost.py",),
          "Independent task-Head resource evidence mechanics"),
    Check("rust-format", "CI", "codex-rs", ("cargo", "fmt", "--all", "--", "--check"),
          ("codex-rs/Cargo.toml",), "Read-only exact-HEAD rustfmt"),
    Check("cargo-locked", "CI", "codex-rs", ("cargo", "metadata", "--locked", "--offline", "--format-version", "1"),
          ("codex-rs/Cargo.toml", "codex-rs/Cargo.lock"), "Resolver/lock consistency"),
    Check("cargo-security", "CI", "codex-rs", ("cargo", "deny", "check", "advisories"),
          ("codex-rs/Cargo.toml",), "RustSec vulnerabilities/unmaintained dependencies (no waiver)"),
]

# These blockers require more than test success. They are deliberately never
# auto-closed by this script, including when an output contains 100% accuracy.
SCIENCE_BLOCKERS = [
    {"stage": "2", "id": "MEM-ORG-MULTIHOP", "status": "OPEN",
     "evidence": "#3125: multihop support recall 13.71% -> 10.29%", "closure": "Pre-registered heldout multi-hop non-regression against strong organized/hybrid baselines"},
    {"stage": "2", "id": "MEM-ABSTAIN", "status": "OPEN",
     "evidence": "#3125: all 299 adversarial evaluation questions accepted; balanced abstention 0.50", "closure": "Calibrated abstention/OOD using independent adversarial source families"},
    {"stage": "3", "id": "MEM-LOCAL-PARAM-GAIN", "status": "OPEN",
     "evidence": "#3125: 64/64 forced, but confidence-gated Head coverage 20-21/64 vs NN 57/64, centroid 59/64", "closure": "Paired actual-task improvement versus strong controls at equal total lifecycle budget"},
    {"stage": "4", "id": "MEM-ROUTER-GAIN", "status": "OPEN",
     "evidence": "#3125: learned Router accuracy below pooled control in May, June and publisher-OOD", "closure": "Independent, source-group-disjoint, multi-window task gain and full cost accounting"},
    {"stage": "5", "id": "MEM-STRUCTURE-GAIN", "status": "OPEN",
     "evidence": "#3125: August split declines versus static specialist across seeds", "closure": "Equal-budget split/merge benefit on preregistered future and retention windows"},
    {"stage": "6", "id": "MEM-SHARED-STUDENT", "status": "OPEN",
     "evidence": "#3125: 45/45 train/calibration objectives worse than train-target-mean control", "closure": "Shared Student gains over properly matched modality/mean/reference baselines"},
    {"stage": "6", "id": "MEM-PHYSICAL-CROSS-NODE", "status": "OPEN",
     "evidence": "#3125: only bounded same-host process transport", "closure": "Authenticated physical multi-node failover/consistency/revocation/recovery"},
    {"stage": "ALL", "id": "MEM-LONGITUDINAL-AUTHORITY", "status": "OPEN",
     "evidence": "Research branches are SHADOW_ONLY / DENY_ALL / HOLD_NO_GO", "closure": "Three independent snapshots/two real future windows, valid sources, unlearning, independent operator approval"},
]

PINS = {
    "integration_PR_3123": "71102d79185f1096d6603e76ea2ffb38da0769e0",
    "research_PR_3125": "1197f4a3217e5b5ae80288161e7806623dd19fd5",
    "withdrawal_fix_PR_3249": "17e514787c0a29c4cfc35072002db3473a0a5bed",
    "windows_fmt_fix_PR_3276": "caf8c2d6bfd639e5ee8cc79e34de6de20dd48682",
    "multimodal_PR_3222": "655814111c03bd37b0519a4a468155a58c0e0c35",
}


def git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=15)
    if p.returncode:
        raise ValueError(p.stderr.strip() or p.stdout.strip() or f"git exit {p.returncode}")
    return p.stdout.strip()


def out_file(base: Path, check: Check) -> Path:
    return base / "logs" / (check.stage + "_" + check.name + ".log")


def run_check(check: Check, repo: Path, out: Path, seconds: int, dry_run: bool) -> dict:
    paths = [s for s in check.source if not (repo / s).exists()]
    command = list(check.cmd)
    r = {"name": check.name, "stage": check.stage, "purpose": check.purpose,
         "command": command, "cwd": check.cwd, "required_sources": list(check.source),
         "status": "NOT_RUN", "elapsed_seconds": None, "returncode": None, "log": None}
    if paths:
        r.update(status="BLOCKED_SOURCE_MISSING", details="Missing: " + ", ".join(paths))
        return r
    if not (repo / check.cwd).is_dir():
        r.update(status="BLOCKED_SOURCE_MISSING", details="Missing cwd")
        return r
    executable = command[0]
    if not shutil.which(executable):
        r.update(status="BLOCKED_TOOL_MISSING", details=f"Executable missing: {executable}")
        return r
    if dry_run:
        r.update(status="NOT_RUN_DRY_RUN")
        return r
    log = out_file(out, check)
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with log.open("wb") as f:
        f.write(("# " + " ".join(command) + "\n").encode())
        f.flush()
        try:
            with subprocess.Popen(command, cwd=repo / check.cwd, stdout=f,
                                  stderr=subprocess.STDOUT, start_new_session=(os.name == "posix")) as proc:
                try:
                    ret = proc.wait(timeout=seconds)
                    status = "PASS_MECHANICS" if ret == 0 else "FAIL_MECHANICS"
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        import signal
                        os.killpg(proc.pid, signal.SIGKILL)
                    else:
                        proc.kill()
                    proc.wait()
                    ret, status = None, "TIMEOUT"
        except OSError as e:
            f.write(("\n" + str(e) + "\n").encode())
            ret, status = None, "ERROR_START"
    r.update(status=status, elapsed_seconds=round(time.monotonic()-started, 3),
             returncode=ret, log=str(log), log_sha256=hashlib.sha256(log.read_bytes()).hexdigest())
    return r


def report_md(r: dict) -> str:
    rows=["# Hepta MemoryCell local blocker sweep", "", f"Source: `{r['head']}`",
          f"Tree: `{r['tree']}`", f"UTC: {r['utc']}",
          f"Dirty worktree: `{r['dirty']}`", "", "## Mechanical checks", "",
          "| Stage | Check | Result | Log |", "|---|---|---|---|"]
    for c in r["mechanical"]:
        log = Path(c["log"]).name if c["log"] else "—"
        rows.append(f"| {c['stage']} | `{c['name']}` | {c['status']} | {log} |")
    rows += ["", "## Scientific, lifecycle, and authority blockers (NOT auto-closed)", "",
             "| Stage | ID | Status | Closure |", "|---|---|---|---|"]
    for b in r["scientific_blockers"]:
        rows.append(f"| {b['stage']} | `{b['id']}` | {b['status']} | {b['closure']} |")
    rows += ["", "**Mechanical PASS ≠ empirical gain ≠ production authorization.**",
             "Queued/failed GitHub Actions and non-native OS checks require separate exact-head receipts.",
             "No production/write/merge/selection action was performed.", ""]
    return "\n".join(rows)


def main() -> int:
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument("--repo", type=Path, default=Path.cwd())
    a.add_argument("--out", type=Path, default=None)
    a.add_argument("--expected-sha", default=None, help="Require exact SHA; mismatch blocks running")
    a.add_argument("--stages", default="1,2,3,4,5,6,CI", help="Comma-separated: 1,2,3,4,5,6,CI")
    a.add_argument("--timeout", type=int, default=1200, help="Seconds per check, default 1200")
    a.add_argument("--dry-run", action="store_true")
    args=a.parse_args()
    if args.timeout < 1 or args.timeout > 86400:
        a.error("--timeout must be 1..86400")
    repo=args.repo.resolve()
    try:
        head=git(repo,"rev-parse","HEAD")
        tree=git(repo,"rev-parse","HEAD^{tree}")
        dirty=bool(git(repo,"status","--porcelain=v1"))
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        print("BLOCKED: not an accessible Git worktree:", e, file=sys.stderr)
        return 2
    if args.expected_sha and head != args.expected_sha:
        print(f"BLOCKED exact SHA mismatch: expected {args.expected_sha}, actual {head}",file=sys.stderr)
        return 3
    selection=set(args.stages.split(","))
    if not selection or not selection.issubset({"1","2","3","4","5","6","CI"}):
        a.error("Unknown --stages value")
    stamp=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out=(args.out or (Path(tempfile.gettempdir())/f"hepta-memory-sweep-{stamp}")).resolve()
    if out == repo or repo in out.parents:
        print("BLOCKED: report output must be OUTSIDE the repository worktree",file=sys.stderr)
        return 4
    out.mkdir(parents=True,exist_ok=True)
    result={"schema":"hepta.memorycell.local-blocker-sweep.v1",
            "utc":dt.datetime.now(dt.timezone.utc).isoformat(), "repo":str(repo),
            "head":head,"tree":tree,"dirty":dirty,"pins_reference_only":PINS,
            "mechanical":[], "scientific_blockers":SCIENCE_BLOCKERS,
            "permissions":"READ_ONLY_SOURCE; NO_PRODUCTION_AUTHORITY"}
    # Recoverable atomic updates after every command; partial runs remain visible.
    for c in CHECKS:
        if c.stage not in selection: continue
        outcome=run_check(c,repo,out,args.timeout,args.dry_run)
        result["mechanical"].append(outcome)
        (out/"result.json").write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n")
        (out/"SUMMARY.md").write_text(report_md(result))
        print(f"[{c.stage}] {c.name}: {outcome['status']}",flush=True)
    print(f"Report: {out/'SUMMARY.md'}")
    return int(any(c["status"] not in ("PASS_MECHANICS","NOT_RUN_DRY_RUN") for c in result["mechanical"]))


if __name__=="__main__":
    raise SystemExit(main())
