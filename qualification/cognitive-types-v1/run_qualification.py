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
import subprocess
import sys
import time

from command_process import capture_command, closed_capture
from evidence_inventory import collect_inventory, require_files, require_fresh_output

SHA = re.compile(r"[0-9a-f]{40}")
CHECK_PLAN_VERSION = 3
GROUPS = {
    "native": ["codex-hepta-cognitive-types"],
    "consumers": ["codex-hepta-cognitive-read", "codex-hepta-cognitive-store",
                  "codex-hepta-memory-retrieval", "codex-hepta-compact-engine",
                  "codex-hepta-intelligence"],
    "owners": ["codex-hepta-memory", "codex-hepta-agentd"],
}


def git(root: Path, *args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.check_output(["git", *args], cwd=root, env=env, text=True).strip()


def resolve_candidate(root: Path, source: str, base: str, kind: str) -> dict:
    """Resolve immutable identities without checking out or changing source files."""
    if not SHA.fullmatch(source) or not SHA.fullmatch(base):
        raise ValueError("source and base must be full immutable commit SHAs")
    for commit in (source, base):
        if git(root, "rev-parse", commit + "^{commit}") != commit:
            raise ValueError("commit identity mismatch")
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
    parents = git(root, "show", "-s", "--format=%P", candidate).split()
    if kind == "synthetic-merge" and parents != [base, source]:
        raise ValueError("candidate ordered parents drifted")
    identity.update(candidate_commit=candidate,
                    candidate_tree=git(root, "rev-parse", candidate + "^{tree}"),
                    parents=parents, identity_valid=True)
    return identity


def prepare_candidate(root: Path, source: str, base: str, kind: str) -> dict:
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("candidate preparation requires a clean worktree")
    identity = resolve_candidate(root, source, base, kind)
    git(root, "checkout", "--detach", identity["candidate_commit"])
    if (git(root, "rev-parse", "HEAD") != identity["candidate_commit"]
            or git(root, "rev-parse", "HEAD^{tree}") != identity["candidate_tree"]):
        raise ValueError("checked-out candidate identity drifted")
    return identity


def file_sha256(path: Path) -> str:
    """Hash complete logs with bounded memory, without changing their bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def log_tail(path: Path) -> str:
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        stream.seek(max(0, stream.tell() - 32_000))
        return stream.read(32_000).decode("utf-8", errors="replace")[-8000:]


def run_check(name: str, argv: list[str], cwd: Path, output: Path, timeout: int = 1800) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name):
        raise ValueError("unsafe command evidence name")
    output.mkdir(parents=True, exist_ok=True)
    log = output / (name + ".log")
    started = time.time_ns()
    result = capture_command(argv, cwd, log, timeout)
    digest = file_sha256(log)
    status, code = result["status"], result["exit_code"]
    print(f"{name}: {status} (exit={code}; log_sha256={digest})", flush=True)
    if status != "passed":
        print(log_tail(log), flush=True)
        if result["error"]:
            print(result["error"], flush=True)
    return {"name": name, "argv": argv, "cwd": str(cwd), **result,
            "started_unix_ns": started, "finished_unix_ns": time.time_ns(),
            "log": log.name, "log_sha256": digest}


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
        mutation_output = output.parent / "cognitive-mutation-work" / "evidence"
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
                                               "--probe", str(probe), "--output", str(mutation_output)], root),
                 ("archive-mutation-evidence", [sys.executable, "qualification/cognitive-types-v1/evidence_inventory.py",
                                                "--archive", str(mutation_output),
                                                "--destination", str(output / "mutations")], root),
                 ("fuzz-build", ["cargo", "check", "--manifest-path",
                                  "hepta-cognitive-types/fuzz/Cargo.toml", "--all-targets"], rust)]
    return plan


def validate_execution_paths(root: Path, output: Path) -> None:
    """Reject source/evidence overlap, including resolved scratch symlinks."""
    root, output = root.resolve(), output.resolve()
    if output == root or root in output.parents or output in root.parents:
        raise ValueError("receipts must be disjoint from the source worktree")
    scratch = (output.parent / "cognitive-types-cargo-target",
               output.parent / "cognitive-probe-target",
               output.parent / "cognitive-mutation-work")
    for path in scratch:
        resolved = path.resolve()
        if (resolved == root or root in resolved.parents or resolved in root.parents
                or resolved == output or output in resolved.parents or resolved in output.parents):
            raise ValueError("build and mutation scratch must be disjoint from source and evidence")


def finish_receipt(receipt: dict, output: Path) -> bool:
    checks = receipt.get("checks", [])
    group = receipt.get("group")
    expected = ([name for name, _, _ in command_plan(Path("/candidate"), group, Path("/evidence"))]
                + ["clean-tree"]) if group in GROUPS else []
    # A nonempty passing prefix is not a complete qualification. Require the
    # exact reviewed plan, one outcome per command, and the final clean cut.
    passed = (bool(expected) and receipt.get("identity_valid") is True
              and type(receipt.get("check_plan_version")) is int
              and receipt["check_plan_version"] == CHECK_PLAN_VERSION
              and isinstance(checks, list)
              and all(isinstance(check, dict) for check in checks)
              and [check.get("name") for check in checks] == expected
              and all(check.get("status") == "passed"
                      and type(check.get("exit_code")) is int and check["exit_code"] == 0
                      and check.get("error") is None for check in checks)
              and all(closed_capture(check) for check in checks[:-1])
              and checks[-1].get("porcelain") == "")
    # Seal all logs and nested result files, not just their console summaries.
    output.mkdir(parents=True, exist_ok=True)
    try:
        inventory = collect_inventory(output)
        receipt["evidence_files"] = inventory
        required = [name + ".log" for name in expected if name != "clean-tree"]
        if group == "native":
            required += ["quality-receipt.json", "mutations/mutation-receipt.json"]
        require_files(inventory, required)
        if passed:
            files = {row["path"]: row for row in inventory["files"]}
            passed = all(
                check.get("log") == check["name"] + ".log"
                and check["log_bytes"] == files[check["log"]]["bytes"]
                and check.get("log_sha256") == files[check["log"]]["sha256"]
                for check in checks[:-1]
            )
    except (OSError, ValueError) as exc:
        receipt["evidence_error"] = f"{type(exc).__name__}: {exc}"
        passed = False
    passed = passed and receipt.get("error") is None and receipt.get("evidence_error") is None
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
    try:
        require_fresh_output(args.output)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    output = args.output.resolve()
    try:
        validate_execution_paths(root, output)
    except ValueError as exc:
        parser.error(str(exc))
    # Keep all compiler artifacts and disposable mutation work outside both the
    # qualified source and the uploaded evidence, without changing any checks.
    cargo_target = output.parent / "cognitive-types-cargo-target"
    mutation_evidence = output.parent / "cognitive-mutation-work" / "evidence"
    try:
        require_fresh_output(mutation_evidence)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    os.environ["CARGO_TARGET_DIR"] = str(cargo_target)
    receipt = {"schema": "hepta.cognitive-types.readonly-execution.v1", "group": args.group,
               "check_plan_version": CHECK_PLAN_VERSION,
               "cargo_target_directory": str(cargo_target),
               "source_worktree": str(root), "evidence_directory": str(output),
               "python_executable": sys.executable,
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
