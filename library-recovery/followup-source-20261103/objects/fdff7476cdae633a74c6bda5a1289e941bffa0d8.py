#!/usr/bin/env python3
"""Fail-closed, read-only* local Hepta + Hepta Runtime source gate runner.

* The runner does not edit source, checkout, fetch, deploy, or request privilege.
  The build and test commands it invokes can create artifacts and execute test
  code, so run it only in trusted, disposable local worktrees.

This is a LOCAL SOURCE/CI PRE-FLIGHT. It never grants production authorization.
Native physical effect receipts, independent FinalUse signatures, scientific
quality, and model/Cell performance qualification require separate witnesses.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


GATES = {
    "hepta": [
        ("ci-scope-unit", ["python3", "-m", "unittest", "-v", "scripts.tests.test_hepta_ci_scope", "scripts.tests.test_hepta_ci_dependencies"]),
        ("readiness-semantics", ["python3", "-m", "unittest", "-v", "scripts.test_hepta_readiness_semantics"]),
        ("github-policy-tests", ["just", "test-github-scripts"]),
        ("full-format-check", ["just", "fmt-check"]),
        ("native-clippy", ["just", "clippy", "--", "-D", "warnings"]),
        ("native-nextest", ["just", "test"]),
    ],
    "runtime": [
        ("rust-format", ["cargo", "fmt", "--all", "--", "--check"]),
        ("rust-check-all-targets", ["cargo", "check", "--locked", "--all-targets"]),
        ("rust-clippy-all-targets", ["cargo", "clippy", "--locked", "--all-targets", "--", "-D", "warnings"]),
        ("rust-tests-all-targets", ["cargo", "test", "--locked", "--all-targets"]),
        ("rust-release-build", ["cargo", "build", "--locked", "--release"]),
    ],
}

EXTERNAL_GATES = {
    "exact-head-and-merge-github-actions": "OPEN: independently corroborate native job steps and immutable commit identity",
    "signed-finaluse-revocation-and-generation-fence": "OPEN: independent trusted authority and exact payload receipt",
    "ssh-host-binding-and-no-replay-crash-ack-loss": "OPEN: original target host and controller fault injection",
    "cell-split-cas-migration-route-and-ledger": "OPEN: actual effects and durable recovery witnesses",
    "independent-ndu-future-ood-negative-transfer": "OPEN: blinded, matched-resource, heldout outcomes",
    "cell-64-256-1024-4096-and-device-performance": "OPEN: native host throughput, RSS, latency and energy",
    "canary-rollback-and-security-review": "OPEN: separate production operator / security acceptance",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_atomic(path: Path, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".manifest-", delete=False) as stream:
        tmp = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.STDOUT, timeout=20).decode().strip()


def snapshot(repo: Path, expected: str | None, repo_name: str) -> dict:
    result = {"path": str(repo), "valid": False, "error": None, "sha": None, "clean": False}
    if not repo.is_dir():
        result["error"] = "repository directory does not exist"
        return result
    if shutil.which("git") is None:
        result["error"] = "git not installed"
        return result
    try:
        root = Path(git(repo, "rev-parse", "--show-toplevel")).resolve()
        if root != repo:
            result["error"] = "path is not the Git repository root"
            return result
        origin = git(repo, "config", "--local", "--get", "remote.origin.url")
        # Do not accidentally qualify a clean but unrelated repository.
        pattern = rf"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)TrillionniumFoundation/{re.escape(repo_name)}(?:\.git)?/?"
        if re.fullmatch(pattern, origin) is None:
            result["error"] = "repository origin is not the exact expected TrillionniumFoundation project"
            return result
        sha = git(repo, "rev-parse", "--verify", "HEAD^{commit}")
        if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
            result["error"] = "invalid commit identity"
            return result
        result["sha"] = sha
        if expected and sha != expected.lower():
            result["error"] = f"requested exact SHA differs from checked-out HEAD: {sha}"
            return result
        # -z ensures filenames with line breaks cannot spoof a clean workspace.
        dirty = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain=v1", "-z", "--untracked-files=normal"], stderr=subprocess.STDOUT, timeout=40)
        if dirty:
            result["error"] = f"working tree is not clean ({len(dirty)} status bytes)"
            return result
        result["clean"] = True
        result["valid"] = True
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as error:
        result["error"] = f"git verification unavailable: {type(error).__name__}"
    return result


def run_gate(repo: Path, group: str, name: str, argv: list[str], output: Path, timeout: int) -> dict:
    entry = {"repository": group, "gate": name, "argv": argv, "started_utc": utc_now(), "result": "BLOCKED", "exit_code": None, "log_file": None, "log_sha256": None, "reason": None}
    if not shutil.which(argv[0]):
        entry["reason"] = f"required executable unavailable: {argv[0]}"
        return entry
    log_path = output / f"{group}__{name}.log"
    entry["log_file"] = log_path.name
    with log_path.open("wb") as stream:
        try:
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", RUSTUP_TOOLCHAIN="1.95.0")
            proc = subprocess.run(argv, cwd=repo, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout, check=False, stdin=subprocess.DEVNULL)
            entry["exit_code"] = proc.returncode
            entry["result"] = "PASS" if proc.returncode == 0 else "FAIL"
            if proc.returncode != 0:
                entry["reason"] = f"command exited {proc.returncode}; inspect log"
        except subprocess.TimeoutExpired:
            entry["result"] = "FAIL"
            entry["reason"] = f"command exceeded operator-specified {timeout}-second limit"
        except OSError as error:
            entry["reason"] = f"unable to launch command: {type(error).__name__}"
    entry["log_sha256"] = hashlib.sha256(log_path.read_bytes()).hexdigest()
    entry["completed_utc"] = utc_now()
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hepta", type=Path, required=True, help="absolute path to clean hepta-private-ci worktree")
    parser.add_argument("--runtime", type=Path, required=True, help="absolute path to clean hepta-runtime worktree")
    parser.add_argument("--hepta-sha", help="optional 40-digit expected Hepta source commit")
    parser.add_argument("--runtime-sha", help="optional 40-digit expected runtime source commit")
    parser.add_argument("--out", type=Path, default=Path("hepta-local-evidence"), help="private evidence output directory outside both repositories")
    parser.add_argument("--timeout", type=int, default=3600, help="per-check timeout in seconds (default 3600)")
    parser.add_argument("--plan", action="store_true", help="print gates and their commands without running them")
    args = parser.parse_args()
    if args.timeout < 10 or args.timeout > 86400:
        parser.error("--timeout must be 10..86400 seconds")
    for label, value in (("--hepta-sha", args.hepta_sha), ("--runtime-sha", args.runtime_sha)):
        if value is not None and (len(value) != 40 or any(c not in "0123456789abcdef" for c in value.lower())):
            parser.error(f"{label} must be an exact 40-character lowercase/uppercase hex SHA")
    roots = {"hepta": args.hepta.expanduser().resolve(), "runtime": args.runtime.expanduser().resolve()}
    output = args.out.expanduser().resolve()
    if any(output == root or root in output.parents or output in root.parents for root in roots.values()):
        parser.error("--out must be outside both Git worktrees")
    os.umask(0o077)
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    report = {"schema": "hepta.local-source-gates.v1", "captured_utc": utc_now(), "mode": "PLAN" if args.plan else "EXECUTE", "platform": {"os": platform.system(), "arch": platform.machine(), "python": platform.python_version()}, "repos": {}, "gates": [], "external_gates": EXTERNAL_GATES, "all_local_source_gates_passed": False, "all_blockers_closed": False, "production_authorized": False, "receipt_provenance": "unsigned local operator environment; verify separately"}
    if args.plan:
        for group, checks in GATES.items():
            for name, command in checks:
                report["gates"].append({"repository": group, "gate": name, "argv": command, "result": "NOT_RUN"})
        write_atomic(output / "manifest.json", report)
        print(f"PLAN ONLY: {output / 'manifest.json'}")
        return 0

    for group, root in roots.items():
        expected = args.hepta_sha if group == "hepta" else args.runtime_sha
        report["repos"][group] = snapshot(root, expected, "hepta-private-ci" if group == "hepta" else "hepta-runtime")
        print(f"{group}: {report['repos'][group]['sha'] or 'NO_SHA'}: {report['repos'][group]['error'] or 'clean source'}", flush=True)

    for group, checks in GATES.items():
        root = roots[group]
        source = report["repos"][group]
        for name, argv in checks:
            # Source HEAD & clean tree must remain stable between each check.
            now = snapshot(root, source["sha"], "hepta-private-ci" if group == "hepta" else "hepta-runtime") if source["valid"] else source
            if not now["valid"]:
                entry = {"repository": group, "gate": name, "argv": argv, "result": "BLOCKED", "reason": now["error"], "exit_code": None}
            else:
                entry = run_gate(root, group, name, argv, output, args.timeout)
            report["gates"].append(entry)
            print(f"[{entry['result']}] {group}/{name} {entry.get('reason') or ''}", flush=True)
            write_atomic(output / "manifest.json", report)

    report["post_run_integrity"] = {
        group: snapshot(roots[group], src["sha"], "hepta-private-ci" if group == "hepta" else "hepta-runtime")
        if src["valid"] else src for group, src in report["repos"].items()
    }
    report["all_local_source_gates_passed"] = (
        bool(report["gates"])
        and all(g["result"] == "PASS" for g in report["gates"])
        and all(src["valid"] for src in report["post_run_integrity"].values())
    )
    # Deliberately never set all_blockers_closed or production_authorized: neither
    # scientific confidence nor physical FinalUse can be concluded by this runner.
    report["finished_utc"] = utc_now()
    write_atomic(output / "manifest.json", report)
    print(f"Evidence: {output / 'manifest.json'}", flush=True)
    return 0 if report["all_local_source_gates_passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
