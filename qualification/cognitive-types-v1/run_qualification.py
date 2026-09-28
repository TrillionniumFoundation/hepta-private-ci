#!/usr/bin/env python3
"""Read-only, exact-source cognitive qualification. Never repairs or pushes source."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import time

SHA = re.compile(r"[0-9a-f]{40}")
GROUPS = {
    "native": ["codex-hepta-cognitive-types"],
    "consumers": ["codex-hepta-cognitive-read", "codex-hepta-cognitive-store",
                  "codex-hepta-memory-retrieval", "codex-hepta-compact-engine",
                  "codex-hepta-intelligence"],
    "owners": ["codex-hepta-memory", "codex-hepta-agentd"],
}


def git(root: Path, *args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.check_output(["git", *args], cwd=root, env=env, text=True).strip()


def prepare_candidate(root: Path, source: str, base: str, kind: str) -> dict:
    if not SHA.fullmatch(source) or not SHA.fullmatch(base):
        raise ValueError("source and base must be full immutable commit SHAs")
    for commit in (source, base):
        if git(root, "rev-parse", commit + "^{commit}") != commit:
            raise ValueError("commit identity mismatch")
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("candidate preparation requires a clean worktree")
    identity = {
        "source_commit": source, "source_tree": git(root, "rev-parse", source + "^{tree}"),
        "base_commit": base, "base_tree": git(root, "rev-parse", base + "^{tree}"),
        "candidate_kind": kind,
    }
    if kind == "exact-head":
        candidate = source
    elif kind == "synthetic-merge":
        # merge-tree fails on conflicts. No conflict markers or generated repairs
        # are ever accepted as a candidate; author/time make this reproducible.
        tree = git(root, "merge-tree", "--write-tree", base, source)
        if not SHA.fullmatch(tree):
            raise ValueError("merge-tree did not produce one unambiguous tree")
        epoch = git(root, "show", "-s", "--format=%ct", source)
        env = dict(os.environ, GIT_AUTHOR_NAME="Cognitive qualification",
                   GIT_AUTHOR_EMAIL="qualification@invalid.example",
                   GIT_COMMITTER_NAME="Cognitive qualification",
                   GIT_COMMITTER_EMAIL="qualification@invalid.example",
                   GIT_AUTHOR_DATE=f"@{epoch} +0000", GIT_COMMITTER_DATE=f"@{epoch} +0000")
        candidate = git(root, "commit-tree", tree, "-p", base, "-p", source,
                        "-m", "Deterministic cognitive.types qualification merge", env=env)
    else:
        raise ValueError("unknown candidate kind")
    git(root, "checkout", "--detach", candidate)
    actual = git(root, "rev-parse", "HEAD")
    parents = git(root, "show", "-s", "--format=%P", "HEAD").split()
    if actual != candidate or (kind == "synthetic-merge" and parents != [base, source]):
        raise ValueError("candidate commit or ordered parents drifted")
    identity.update(candidate_commit=actual, candidate_tree=git(root, "rev-parse", "HEAD^{tree}"),
                    parents=parents, identity_valid=True)
    return identity


def run_check(name: str, argv: list[str], cwd: Path, output: Path, timeout: int = 1800) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    log = output / (name + ".log")
    started = time.time_ns()
    error = None
    status = "failed"
    code = None
    with log.open("wb") as stream:
        try:
            process = subprocess.Popen(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                       start_new_session=os.name == "posix")
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    process.kill()
                process.wait()
                raise
            status = "passed" if code == 0 else "failed"
        except (OSError, subprocess.TimeoutExpired) as exc:
            error = f"{type(exc).__name__}: {exc}"
            stream.write((error + "\n").encode())
            status = "infrastructure_invalid"
    digest = hashlib.sha256(log.read_bytes()).hexdigest()
    print(f"{name}: {status} (exit={code}; log_sha256={digest})", flush=True)
    if status != "passed":
        print(log.read_text(errors="replace")[-8000:], flush=True)
    return {"name": name, "argv": argv, "cwd": str(cwd), "exit_code": code,
            "status": status, "started_unix_ns": started, "finished_unix_ns": time.time_ns(),
            "log": log.name, "log_sha256": digest, "error": error}


def command_plan(root: Path, group: str, output: Path) -> list[tuple[str, list[str], Path]]:
    rust = root / "codex-rs"
    packages = [arg for package in GROUPS[group] for arg in ("-p", package)]
    plan = [("rust-toolchain", ["rustc", "--version", "--verbose"], rust),
            ("cargo-toolchain", ["cargo", "--version", "--verbose"], rust),
            ("nextest-toolchain", ["cargo", "nextest", "--version"], rust),
            ("format", ["cargo", "fmt", *packages, "--", "--check"], rust),
            ("all-targets", ["cargo", "check", "--locked", "--all-targets", *packages], rust),
            ("package-tests", ["just", "test", "--locked", *packages], root),
            ("strict-clippy", ["cargo", "clippy", "--locked", "--all-targets", *packages,
                               "--", "-D", "warnings"], rust)]
    if group == "native":
        target = output.parent / "cognitive-probe-target"
        probe = target / "debug/examples/canonical_probe"
        plan += [("python-regressions", [sys.executable, "-m", "unittest", "discover", "-s",
                                        "qualification/cognitive-types-v1", "-p", "test_*.py"], root),
                 ("traceability", [sys.executable, "qualification/cognitive-types-v1/render_traceability.py", "--check"], root),
                 ("registry-self-test", [sys.executable, "scripts/hepta-hnmf.py", "self-test"], root),
                 ("registry", [sys.executable, "scripts/hepta-hnmf.py", "verify"], root),
                 ("v1-vectors", [sys.executable, "qualification/cognitive-types-v1/verify_vectors.py"], root),
                 ("v2-vectors", [sys.executable, "qualification/cognitive-types-v2/verify_vectors.py"], root),
                 ("bound-python", [sys.executable, "qualification/cognitive-types-v1/verify_bound_vector.py"], root),
                 ("bound-node", ["node", "qualification/cognitive-types-v1/verify_bound_vector.mjs"], root),
                 ("probe-build", ["cargo", "build", "--locked", "-p", "codex-hepta-cognitive-types",
                                   "--example", "canonical_probe", "--target-dir", str(target)], rust),
                 ("differential-quality", [sys.executable, "qualification/cognitive-types-v1/quality_checks.py",
                                          "--probe", str(probe), "--output", str(output / "quality-receipt.json")], root),
                 ("targeted-source-mutations", [sys.executable, "qualification/cognitive-types-v1/run_mutations.py",
                                               "--probe", str(probe), "--output", str(output / "mutations")], root),
                 ("fuzz-build", ["cargo", "check", "--manifest-path",
                                  "hepta-cognitive-types/fuzz/Cargo.toml", "--all-targets"], rust)]
    return plan


def finish_receipt(receipt: dict, output: Path) -> bool:
    checks = receipt.get("checks", [])
    passed = bool(checks) and receipt.get("identity_valid") is True and all(
        check["status"] == "passed" for check in checks)
    receipt["qualification_passed"] = passed
    receipt["product_acceptance"] = False
    receipt["activation"] = False
    receipt["release"] = False
    output.mkdir(parents=True, exist_ok=True)
    path = output / "receipt.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    (output / "receipt.sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest() + "\n")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--kind", choices=["exact-head", "synthetic-merge"], required=True)
    parser.add_argument("--group", choices=list(GROUPS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if output == root or root in output.parents:
        parser.error("receipts must be outside the source worktree")
    os.environ["CARGO_TARGET_DIR"] = str(output.parent / "cognitive-cargo-target")
    receipt = {"schema": "hepta.cognitive-types.readonly-execution.v1", "group": args.group,
               "workflow_sha": os.environ.get("GITHUB_WORKFLOW_SHA"),
               "workflow_ref": os.environ.get("GITHUB_WORKFLOW_REF"),
               "run_id": os.environ.get("GITHUB_RUN_ID"),
               "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
               "runner_image": {"os": os.environ.get("ImageOS"), "version": os.environ.get("ImageVersion"),
                                "platform": platform.platform()}, "checks": []}
    try:
        receipt.update(prepare_candidate(root, args.source, args.base, args.kind))
        for name, argv, cwd in command_plan(root, args.group, output):
            receipt["checks"].append(run_check(name, argv, cwd, output))
        status = git(root, "status", "--porcelain", "--untracked-files=all")
        unchanged = (not status and git(root, "rev-parse", "HEAD") == receipt["candidate_commit"]
                     and git(root, "rev-parse", "HEAD^{tree}") == receipt["candidate_tree"])
        receipt["checks"].append({"name": "clean-tree", "status": "passed" if unchanged else "failed",
                                  "exit_code": 0 if unchanged else 1, "porcelain": status})
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        receipt["identity_valid"] = False
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        print(receipt["error"], file=sys.stderr)
    return 0 if finish_receipt(receipt, output) else 1


if __name__ == "__main__":
    raise SystemExit(main())
