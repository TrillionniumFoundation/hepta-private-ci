#!/usr/bin/env python3
"""Fail-closed, read-only native validation receipt for a real Hepta checkout.

No repository updates, artifact substitutions, test skips, credential access,
or production enablement. A scoped success is NEVER full blocker closure.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

REPOSITORY = "hepta-private-ci"
EXPECTED_REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
REQUIRED_TOOLS = ("git", "python", "cargo", "rustc", "just", "bazel", "cargo-deny")
WINDOWS_DELETE_TESTS = (
    "token::tests::delete_diagnostics::workspace_delete_permission_routes_diagnostic_matrix",
    "token::tests::partial_delete_deny_is_repaired_before_native_workspace_writes",
    "token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces",
    "unified_exec::tests::legacy_workspace_write_delete_is_limited_to_writable_roots",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_cmd(repo: Path, *args: str) -> str:
    value = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                           text=True, timeout=30, check=True)
    return value.stdout.strip()


def existing(repo: Path, rel: str) -> bool:
    return (repo / rel).is_file() and not (repo / rel).is_symlink()


def tool_path(name: str) -> str | None:
    return shutil.which(name) or (shutil.which("bazelisk") if name == "bazel" else None)


def scoped_commands(repo: Path, level: str) -> list[dict]:
    python = sys.executable
    commands = []
    def add(name: str, argv: list[str], cwd: Path, needed: tuple[str, ...] = ()) -> None:
        commands.append({"name": name, "argv": argv, "cwd": str(cwd),
                         "required_executables": list(needed)})
    if level in {"quick", "native"}:
        add("multimodal-behavior-tests", [python, "-m", "unittest", "discover", "-s",
            "qa/stem-bakeoff", "-p", "test_multimodal_*.py", "-v"], repo)
        add("prediction-ledger-tests", [python, "-m", "unittest", "discover", "-s",
            "qa/stem-bakeoff", "-p", "test_prediction_ledger.py", "-v"], repo)
        add("head-training-tests", [python, "-m", "unittest", "discover", "-s",
            "qa/stem-bakeoff", "-p", "test_cell_head_training.py", "-v"], repo)
    if level == "native":
        add("cargo-deny-unmodified-policy", ["cargo-deny", "--log-level", "warn",
            "--manifest-path", "./codex-rs/Cargo.toml", "--all-features", "check"],
            repo, ("cargo-deny",))
        if platform.system() == "Windows":
            test_filter = " | ".join(f"test(={s})" for s in WINDOWS_DELETE_TESTS)
            add("windows-delete-four-original-tests", ["just", "test", "--locked", "-p",
                "codex-windows-sandbox", "--lib", "-E", test_filter, "--test-threads", "1",
                "--retries", "0", "--no-tests", "fail"], repo / "codex-rs", ("just",))
        elif platform.system() in {"Linux", "Darwin"}:
            add("agentd-original-product-tests", ["bazel", "test",
                "//codex-rs/hepta-agentd:hepta-agentd-plasticity_process_e2e-test",
                "//codex-rs/hepta-agentd:hepta-agentd-kernel_evidence_product-test"],
                repo, ("bazel",))
            add("agentd-native-clippy", ["bazel", "clippy",
                "//codex-rs/hepta-agentd:hepta-agentd-plasticity_process_e2e-test",
                "//codex-rs/hepta-agentd:hepta-agentd-kernel_evidence_product-test"],
                repo, ("bazel",))
    return commands


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, required=True, help="Path of the actual local hepta-private-ci clone")
    p.add_argument("--expected-sha", help="Fail if checkout HEAD does not exactly match this commit")
    p.add_argument("--level", choices=("audit", "quick", "native"), default="audit",
                   help="audit=tool/revision checks only; quick=Python; native=targeted Rust/Bazel")
    p.add_argument("--output", type=Path, help="New receipt directory (default is mkdtemp)")
    p.add_argument("--timeout-sec", type=int, default=7200)
    p.add_argument("--episode-path", type=Path, help="Real state/action/reward input; presence only, not quality proof")
    p.add_argument("--device-id", help="Actual target-device identifier; not a power measurement")
    args = p.parse_args()
    if args.timeout_sec < 1 or args.timeout_sec > 14400:
        p.error("timeout-sec must be in 1..14400")
    repo = args.repo.expanduser().resolve(strict=True)
    if not (repo.is_dir() and existing(repo, "codex-rs/Cargo.toml")
            and existing(repo, "defs.bzl")):
        p.error("--repo is not a recognisable Hepta checkout")
    try:
        root = Path(git_cmd(repo, "rev-parse", "--show-toplevel")).resolve(strict=True)
        head = git_cmd(repo, "rev-parse", "HEAD")
        tree = git_cmd(repo, "rev-parse", "HEAD^{tree}")
        state = git_cmd(repo, "status", "--porcelain=v1", "--untracked-files=all")
    except (OSError, subprocess.SubprocessError) as e:
        p.error(f"git inspection failed: {e}")
    if root != repo:
        p.error("--repo must point to the Git worktree root, not a subfolder")
    if args.expected_sha and head != args.expected_sha:
        p.error(f"exact commit mismatch: current={head} expected={args.expected_sha}")
    if state:
        p.error("checkout is dirty; refuse to attribute tests to the HEAD tree (no automatic cleanup)")
    output = (Path(tempfile.mkdtemp(prefix="hepta-local-recheck-")) if args.output is None
              else args.output.expanduser().absolute())
    if output == repo or repo in output.parents:
        p.error("--output must not be inside the Git checkout")
    if args.output is not None:
        if output.exists() or output.is_symlink() or not output.parent.is_dir():
            p.error("--output must be a new directory under an existing parent")
        output.mkdir(mode=0o700)
    receipt = {
        "schema": "hepta.local-blocker-preflight.v1",
        "observed_utc": datetime.now(timezone.utc).isoformat(),
        "repository": EXPECTED_REPOSITORY,
        "source": {"head_sha": head, "tree_sha": tree, "dirty": False,
                   "repo_path": str(repo)},
        "execution_environment": {"os": platform.system(), "release": platform.release(),
                                  "machine": platform.machine(), "python": sys.version.split()[0],
                                  "tools": {t: tool_path(t) for t in REQUIRED_TOOLS}},
        "real_episode_path_present": bool(args.episode_path and args.episode_path.exists()),
        "target_device_named": bool(args.device_id),
        "actual_target_energy_or_latency_measured": False,
        "production_activation_allowed": False,
        "authority": "DENY_ALL", "checks": [], "all_blockers_closed": False,
        "reasons_full_closure_unavailable": [
            "Original all-platform CI and required merge/base checks are independently mandatory",
            "State/action/value/uncertainty episode learning is not evaluated by this script",
            "Target-device end-to-end p95/p99/energy is not evaluated by this script",
            "Windows DELETE security checks require an actual Windows runner",
        ],
    }
    for i, command in enumerate(scoped_commands(repo, args.level), start=1):
        env = dict(os.environ)
        env["RUST_BACKTRACE"] = "1"
        required = command["required_executables"]
        missing = [exe for exe in required if tool_path(exe) is None]
        if missing:
            receipt["checks"].append({"name": command["name"], "status": "NOT_RUN_MISSING_TOOL", "tools": missing})
            continue
        # Preserve the same Bazel invocation on workstations that install only
        # Bazelisk. Do not report a missing bazel binary as a tool success.
        argv = list(command["argv"])
        if argv[0] == "bazel" and shutil.which("bazel") is None:
            argv[0] = tool_path("bazel")
        name = command["name"]
        output_file = output / f"{i:02d}-{name}.log"
        t0 = time.monotonic()
        try:
            with output_file.open("wb") as stream:
                completed = subprocess.run(argv, cwd=command["cwd"],
                                           stdout=stream, stderr=subprocess.STDOUT,
                                           env=env, timeout=args.timeout_sec, check=False)
            status = "PASS" if completed.returncode == 0 else "FAIL"
            code = completed.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            with output_file.open("ab") as stream:
                stream.write(f"\nLOCAL RECHECK EXCEPTION: {type(exc).__name__}: {exc}\n".encode())
            status, code = "ERROR_OR_TIMEOUT", None
        receipt["checks"].append({"name": name, "status": status, "exit_code": code,
                                  "argv": argv, "wall_seconds": round(time.monotonic()-t0, 3),
                                  "log": str(output_file.name),
                                  "log_sha256": sha256(output_file.read_bytes())})
    if args.level == "audit":
        receipt["scope_result"] = "AUDIT_ONLY"
    else:
        receipt["scope_result"] = "SCOPED_PASS" if all(x["status"] == "PASS" for x in receipt["checks"]) else "SCOPED_BLOCKED"
    (output / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(output / "receipt.json"), "head": head,
                      "scope_result": receipt["scope_result"],
                      "all_blockers_closed": False}, indent=2))
    return 0 if receipt["scope_result"] in {"SCOPED_PASS", "AUDIT_ONLY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
