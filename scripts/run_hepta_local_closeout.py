#!/usr/bin/env python3
"""Non-deploying local Hepta P0..P6 acceptance runner.

Runs source/build/unit checks on exact local worktrees and emits immutable-ish
machine-readable results. It NEVER treats a passing test as physical or
independent future-window acceptance; P1..P6 need separate external evidence.
No network requests, background jobs, production effects or Git writes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import signal
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

STAGES = {
    "P0": {
        "required": [("hepta", "codex-rs/hepta-types/src/execution_contract.rs"),
                     ("hepta", "qa/meta-network-scale/check_cell_codex_boundary.py")],
        "checks": [
            ("hepta", "codex-rs", ["cargo", "metadata", "--locked", "--format-version", "1", "--no-deps"]),
            ("hepta", "codex-rs", ["cargo", "fmt", "--all", "--", "--check"]),
            ("hepta", "codex-rs", ["cargo", "test", "--locked", "-p", "codex-hepta-types", "-p", "codex-hepta-codex-adapter"]),
            ("hepta", "codex-rs", ["cargo", "clippy", "--locked", "-p", "codex-hepta-types", "-p", "codex-hepta-codex-adapter", "--all-targets", "--", "-D", "warnings"]),
            ("hepta", ".", [sys.executable, "-m", "unittest", "qa/meta-network-scale/test_cell_codex_boundary.py"]),
        ],
        "external": "compiled transitive dependency and exact-head/merge CI acceptance",
    },
    "P1": {
        "required": [("hepta", "codex-rs/hepta-runtime/src/topology_execution.rs"),
                     ("hepta", "codex-rs/hepta-plasticity/src/topology_governance.rs")],
        "checks": [("hepta", "codex-rs", ["cargo", "test", "--locked", "-p", "codex-hepta-runtime", "-p", "codex-hepta-plasticity", "-p", "codex-hepta-operator-acceptance", "-p", "codex-hepta-supervisor"])],
        "external": "signed real Artifact CAS, state migration, CNS cutover, old-generation fence, ledger, power-loss recovery",
    },
    "P2": {
        "required": [("hepta", "codex-rs/hepta-infer-core/src/neuron_feature.rs"),
                     ("hepta", "codex-rs/hepta-neuron/src/runtime.rs")],
        "checks": [("hepta", "codex-rs", ["cargo", "test", "--locked", "-p", "codex-hepta-infer-core", "-p", "codex-hepta-infer-worker-host", "-p", "codex-hepta-neuron"])],
        "external": "pinned learned encoder weights/tokenizer, real train/heldout inference, backend batch, zero-delta parity",
    },
    "P3": {
        "required": [("runtime", "src/lib.rs"),
                     ("runtime", "tests/native_library_boundary.rs"),
                     ("hepta", "codex-rs/hepta-types/src/execution_contract.rs")],
        "checks": [
            ("runtime", ".", ["cargo", "fmt", "--all", "--", "--check"]),
            ("runtime", ".", ["cargo", "check", "--locked", "--all-targets"]),
            ("runtime", ".", ["cargo", "test", "--locked", "--all-targets"]),
            ("runtime", ".", ["cargo", "clippy", "--locked", "--all-targets", "--", "-D", "warnings"]),
            ("runtime", ".", ["cargo", "build", "--locked", "--release"]),
            ("hepta", "codex-rs", ["cargo", "test", "--locked", "-p", "codex-hepta-operations", "-p", "codex-hepta-codex-adapter"]),
        ],
        "external": "real native adapter + final-use consume-once + host policy + durable idempotency + terminal target readback",
    },
    "P4": {
        "required": [("hepta", "codex-rs/hepta-ndu/src/evaluator.rs"),
                     ("hepta", "codex-rs/hepta-intelligence-eval/src/self_evolution_selection.rs")],
        "checks": [("hepta", "codex-rs", ["cargo", "test", "--locked", "-p", "codex-hepta-ndu", "-p", "codex-hepta-intelligence-eval"])],
        "external": "preregistered heldout/no-change/fixed MoE controls, independent future-window utility, negative-transfer CI",
    },
    "P5": {
        "required": [("hepta", "qa/meta-network-scale/scale_matrix.py"),
                     ("hepta", "docs/learning/CELL_EXECUTION_BENCHMARK_MATRIX.json")],
        "checks": [("hepta", ".", [sys.executable, "-m", "unittest", "qa/meta-network-scale/test_scale_matrix.py"])],
        "external": "physical 1/8/64/256/1024/4096-cell 36-arm host-bound CPU/RSS/GPU/p95/p99/throughput/WAL/fault receipts",
    },
    "P6": {
        "required": [("hepta", "qa/meta-network-scale/p6_fallback_gate.py"),
                     ("hepta", "qa/meta-network-scale/test_p6_fallback_gate.py")],
        "checks": [("hepta", ".", [sys.executable, "-m", "unittest", "qa/meta-network-scale/test_p6_fallback_gate.py"])],
        "external": "real sandboxed Codex/native feature-equivalence cohort, distinct independent signatures, error and restart parity",
    },
}



# Source/tree attestations are not meaningful when process-environment
# overrides can redirect Git, the compiler, Cargo dependencies or Python tests.
# Reject known execution-affecting overrides by NAME; never copy their values
# (which may contain private machine paths/secrets) into a receipt.
UNREVIEWED_ENVIRONMENT_KEYS = frozenset({
    "CARGO_HOME", "RUSTUP_HOME", "RUSTUP_TOOLCHAIN", "RUSTC", "RUSTDOC",
    "RUSTFLAGS", "RUSTDOCFLAGS", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER",
    "RUSTC_BOOTSTRAP", "CARGO_ENCODED_RUSTFLAGS", "CARGO_ENCODED_RUSTDOCFLAGS",
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_EXEC_PATH",
    "GIT_CONFIG", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM",
    "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT",
    "BASH_ENV", "ENV", "CC", "CXX", "AR", "CFLAGS", "CXXFLAGS", "LDFLAGS",
    "MAKEFLAGS", "PKG_CONFIG_PATH", "PKG_CONFIG_LIBDIR", "CMAKE_TOOLCHAIN_FILE",
})
UNREVIEWED_ENVIRONMENT_PREFIXES = (
    "GIT_CONFIG_", "CARGO_BUILD_", "CARGO_TARGET_", "CARGO_PROFILE_",
    "CARGO_REGISTRIES_", "CARGO_SOURCE_", "CARGO_UNSTABLE_",
    "RUSTUP_", "LD_", "DYLD_", "PYTEST_",
)


def unreviewed_environment_keys(environment: dict[str, str] | None = None) -> list[str]:
    """Return only unreviewed override names, never their sensitive values."""
    environ = os.environ if environment is None else environment
    return sorted(
        key
        for key, value in environ.items()
        if value
        and (
            key in UNREVIEWED_ENVIRONMENT_KEYS
            or key.startswith(UNREVIEWED_ENVIRONMENT_PREFIXES)
        )
    )


MAX_PROOF_SOURCE_BYTES = 8 * 1024 * 1024


def committed_regular_file(repo_root: Path, relative: str) -> bool:
    """Bind a required file to bytes and regular-file mode in the exact HEAD.

    Git status can omit ignored files and paths flagged assume-unchanged or
    skip-worktree. Existence and a clean status alone never attest source bytes.
    """
    path = repo_root / relative
    if unreviewed_environment_keys() or not path.is_file() or path.is_symlink():
        return False
    try:
        if path.stat().st_size > MAX_PROOF_SOURCE_BYTES:
            return False
        row = subprocess.run(
            ["git", "-C", str(repo_root), "ls-tree", "HEAD", "--", relative],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
        metadata, separator, found = row.partition("\t")
        fields = metadata.split()
        if (
            not separator or found != relative or len(fields) != 3
            or fields[0] not in ("100644", "100755") or fields[1] != "blob"
        ):
            return False
        length = subprocess.run(
            ["git", "-C", str(repo_root), "cat-file", "-s", fields[2]],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
        if int(length) > MAX_PROOF_SOURCE_BYTES:
            return False
        committed = subprocess.run(
            ["git", "-C", str(repo_root), "cat-file", "blob", fields[2]],
            capture_output=True, check=True, timeout=10,
        ).stdout
        return path.read_bytes() == committed
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def git_snapshot(path: Path) -> dict[str, Any]:
    if not path.is_dir():
        return {"usable": False, "reason": "repository directory not mounted", "path": str(path)}
    overrides = unreviewed_environment_keys()
    if overrides:
        return {
            "usable": False,
            "reason": "unreviewed local execution environment",
            "path": str(path),
            "blocked_environment_keys": overrides,
        }

    def cmd(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(path), *args], capture_output=True, text=True,
            check=True, timeout=10,
        ).stdout.strip()

    try:
        # Git status may run an fsmonitor hook or a configured clean/process
        # filter on a tracked path. Inspect only Git config key NAMES before
        # status, never leaking command paths or tokens in the audit report.
        config_names = {
            name.casefold()
            for name in cmd("config", "--list", "--name-only", "-z").split("\0")
            if name
        }
        executable_git_config = {
            name for name in config_names
            if name == "core.fsmonitor"
            or (name.startswith("diff.") and name.endswith(".command"))
            or (name.startswith("merge.") and name.endswith(".driver"))
        }
        filter_config_names = {
            name for name in config_names
            if name.startswith("filter.")
            and name.rsplit(".", 1)[-1] in ("clean", "smudge", "process")
        }
        if filter_config_names and not executable_git_config:
            # Any fsmonitor/diff/merge executable config blocks immediately.
            # Even ls-files can invoke an enabled fsmonitor hook.
            # Hosted runners install Git LFS filter commands globally. A
            # registered but UNUSED driver cannot run during this worktree's
            # status; refusing it would make ordinary source CI inoperable.
            # check-attr evaluates tracked paths without running filter code.
            tracked = subprocess.run(
                ["git", "-C", str(path), "ls-files", "--cached", "-z"],
                capture_output=True, check=True, timeout=20,
            ).stdout
            attributes = subprocess.run(
                ["git", "-C", str(path), "check-attr", "-z", "--stdin", "filter"],
                input=tracked, capture_output=True, check=True, timeout=20,
            ).stdout.split(b"\0")
            active_drivers = {
                attributes[index + 2].decode("utf-8", "surrogateescape").casefold()
                for index in range(0, len(attributes) - 2, 3)
                if attributes[index + 1] == b"filter"
                and attributes[index + 2] not in
                (b"unspecified", b"unset", b"set")
            }
            executable_git_config.update(
                name for name in filter_config_names
                if name.removeprefix("filter.").rsplit(".", 1)[0]
                in active_drivers
            )
        if executable_git_config:
            return {
                "usable": False,
                "reason": "unreviewed executable Git configuration",
                "path": str(path),
                "blocked_git_config_keys": sorted(executable_git_config),
            }
        # Git porcelain status deliberately ignores assume-unchanged and
        # skip-worktree entries, even when their real bytes differ from HEAD.
        # Reject these flags for the ENTIRE tracked index, not only the
        # smaller declared required-file subset tested elsewhere.
        index_rows = subprocess.run(
            ["git", "-C", str(path), "ls-files", "--cached", "-v", "-z"],
            capture_output=True, check=True, timeout=20,
        ).stdout.split(b"\\0")
        hidden_index_entries = sum(
            1 for entry in index_rows if entry and not entry.startswith(b"H ")
        )
        if hidden_index_entries:
            return {
                "usable": False,
                "reason": "unreviewed tracked index flags",
                "path": str(path),
                "hidden_index_entries": hidden_index_entries,
            }
        # Git's linked worktrees use a .git *file*, not a directory. Verify the
        # canonical top level instead of testing a filesystem suffix.
        if cmd("rev-parse", "--is-inside-work-tree") != "true":
            return {"usable": False, "path": str(path), "reason": "not a Git worktree"}
        if Path(cmd("rev-parse", "--show-toplevel")).resolve() != path.resolve():
            return {"usable": False, "path": str(path), "reason": "not a Git repository root"}
        rev = cmd("rev-parse", "--verify", "HEAD^{commit}")
        tree = cmd("rev-parse", "--verify", "HEAD^{tree}")
        state = cmd("status", "--porcelain=v1", "--untracked-files=all")
        return {"usable": True, "path": str(path), "commit": rev, "tree": tree,
                "clean": state == "", "dirty_paths": len(state.splitlines())}
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return {"usable": False, "path": str(path), "reason": type(exc).__name__}


MAX_CHECK_LOG_BYTES = 64 * 1024 * 1024
CHECK_POLL_SECONDS = 0.05


def _set_kernel_file_output_cap() -> None:
    """Run in a POSIX check child before exec, not in the parent process."""
    import resource

    resource.setrlimit(
        resource.RLIMIT_FSIZE, (MAX_CHECK_LOG_BYTES, MAX_CHECK_LOG_BYTES)
    )
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _stop_check_process_group(child: subprocess.Popen[bytes]) -> None:
    """Kill workers as one owner group, including descendants after launcher exit."""
    try:
        if os.name == "posix":
            os.killpg(child.pid, signal.SIGKILL)
        elif child.poll() is None:
            child.kill()
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("local check descendants escaped cleanup") from exc


def run_check(argv: list[str], cwd: Path, timeout: int, log_path: Path) -> dict[str, Any]:
    overrides = unreviewed_environment_keys()
    if overrides:
        return {
            "argv": argv,
            "status": "BLOCKED_UNREVIEWED_ENVIRONMENT",
            "blocked_environment_keys": overrides,
        }
    if not shutil.which(argv[0]):
        return {"argv": argv, "status": "BLOCKED_TOOL_MISSING", "tool": argv[0]}
    if not cwd.is_dir():
        return {"argv": argv, "status": "BLOCKED_WORKDIR_MISSING"}
    start = time.monotonic()
    try:
        fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(("$ " + json.dumps(argv, ensure_ascii=False) + "\n").encode("utf-8"))
            out.flush()
            child = subprocess.Popen(
                argv, cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                env=os.environ.copy(), start_new_session=(os.name == "posix"),
                preexec_fn=_set_kernel_file_output_cap if os.name == "posix" else None,
            )
            blocked = None
            code = None
            try:
                while True:
                    code = child.poll()
                    if os.fstat(out.fileno()).st_size >= MAX_CHECK_LOG_BYTES:
                        blocked = "BLOCKED_OUTPUT_LIMIT"
                        break
                    if code is not None:
                        break
                    if time.monotonic() - start >= timeout:
                        blocked = "BLOCKED_TIMEOUT"
                        break
                    time.sleep(CHECK_POLL_SECONDS)
                if blocked is not None:
                    _stop_check_process_group(child)
                elif os.name == "posix":
                    try:
                        os.killpg(child.pid, 0)
                    except ProcessLookupError:
                        pass
                    else:
                        _stop_check_process_group(child)
                        blocked = "BLOCKED_DESCENDANTS"
            except BaseException:
                _stop_check_process_group(child)
                raise
            # Include the parent's exit receipt in the budget as well.
            if blocked is None:
                exit_line = f"\nHEPTA_LOCAL_GATE_EXIT: {code}\n".encode("utf-8")
                if os.fstat(out.fileno()).st_size + len(exit_line) > MAX_CHECK_LOG_BYTES:
                    blocked = "BLOCKED_OUTPUT_LIMIT"
                    _stop_check_process_group(child)
            if blocked is not None:
                out.flush()
                if os.fstat(out.fileno()).st_size > MAX_CHECK_LOG_BYTES:
                    os.ftruncate(out.fileno(), MAX_CHECK_LOG_BYTES)
                out.seek(0, os.SEEK_END)
                out.write(("\nHEPTA_LOCAL_GATE: " + blocked + "\n").encode("utf-8"))
            else:
                out.write(exit_line)
            out.flush()
            os.fsync(out.fileno())
        digest = hashlib.sha256()
        with log_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        result = {
            "argv": argv,
            "status": blocked or ("PASS_LOCAL" if code == 0 else "FAIL_LOCAL"),
            "seconds": round(time.monotonic() - start, 3),
            "log_path": str(log_path),
            "log_sha256": digest.hexdigest(),
        }
        if blocked is None:
            result["exit_code"] = code
        return result
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return {"argv": argv, "status": "BLOCKED_SYSTEM", "error_type": type(exc).__name__}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hepta", required=True, type=Path, help="local hepta-private-ci checkout (not a GitHub URL)")
    parser.add_argument("--runtime", required=True, type=Path, help="local hepta-runtime checkout")
    parser.add_argument("--report-dir", type=Path, default=Path(tempfile.gettempdir()) / "hepta-local-closeout-results")
    parser.add_argument("--timeout-sec", type=int, default=900)
    parser.add_argument("--execute-checks", action="store_true", help="opt in to build/test; tests can write to local ephemeral test data; no production dispatch by this script")
    args = parser.parse_args()
    if args.timeout_sec < 1:
        parser.error("--timeout-sec must be positive")
    roots = {"hepta": args.hepta.resolve(), "runtime": args.runtime.resolve()}
    blocked_environment_keys = unreviewed_environment_keys()
    if args.report_dir.is_symlink():
        parser.error("report directory must not be a symlink")
    report_dir = args.report_dir.resolve()
    report_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix" and (report_dir.stat().st_mode & 0o077):
        parser.error("report directory must have private owner-only permissions")
    run_dir = report_dir / ("run-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    run_dir.mkdir(mode=0o700)
    report: dict[str, Any] = {
        "schema": "hepta.local.p0-p6.source-audit.v1", "time_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sources": {name: git_snapshot(path) for name, path in roots.items()},
        "blocked_environment_keys": blocked_environment_keys,
        "production_qualified": False, "stages": {},
        "warning": "Source/test results are NOT signed independent target-host/model acceptance; no deployment rights are conferred.",
    }
    for stage, spec in STAGES.items():
        stage_result: dict[str, Any] = {"status": "BLOCKED", "files": [], "checks": [], "external_evidence_needed": spec["external"]}
        source_names = {name for name, _ in spec["required"]}
        before_checks = {name: git_snapshot(roots[name]) for name in source_names}
        missing = []
        for name, rel in spec["required"]:
            path = roots[name] / rel
            exists = committed_regular_file(roots[name], rel)
            stage_result["files"].append({"path": f"{name}/{rel}", "present": exists})
            if not exists:
                missing.append(f"{name}/{rel}")
        stage_result["missing_files"] = missing
        if blocked_environment_keys:
            stage_result["status"] = "BLOCKED_UNREVIEWED_ENVIRONMENT"
        elif missing:
            stage_result["status"] = "BLOCKED_SOURCE_NOT_PRESENT"
        elif not all(report["sources"][name]["usable"] and before_checks[name]["usable"] for name in source_names):
            stage_result["status"] = "BLOCKED_NO_GIT_CHECKOUT"
        elif not all(report["sources"][name]["clean"] and before_checks[name]["clean"] for name in source_names):
            # A dirty checkout cannot prove which source produced a test result.
            stage_result["status"] = "BLOCKED_DIRTY_WORKTREE"
        elif any(
            before_checks[name][field] != report["sources"][name][field]
            for name in source_names for field in ("commit", "tree")
        ):
            stage_result["status"] = "BLOCKED_SOURCE_IDENTITY_CHANGED"
        elif not args.execute_checks:
            stage_result["status"] = "BLOCKED_NOT_RUN"
        else:
            for index, (name, subdir, argv) in enumerate(spec["checks"]):
                folder = roots[name] / subdir
                stage_result["checks"].append(run_check(argv, folder, args.timeout_sec,
                                                          run_dir / f"{stage.lower()}-{index}.log"))
            states = [c["status"] for c in stage_result["checks"]]
            after_checks = {name: git_snapshot(roots[name]) for name in source_names}
            # A clean Git status is NOT a post-test source-byte proof: an
            # assume-unchanged/skip-worktree path may silently drift from HEAD.
            unchanged_required_files = all(
                committed_regular_file(roots[name], rel)
                for name, rel in spec["required"]
            )
            stage_result["post_check_required_source_bytes_match_head"] = unchanged_required_files
            # Tests may create tracked or untracked files, change checked-out
            # branches or rewrite generated source. Never report success for a
            # test that no longer matches the frozen initial Git identity.
            if not unchanged_required_files or any(
                not after_checks[name]["usable"]
                or not after_checks[name]["clean"]
                or any(after_checks[name][field] != report["sources"][name][field]
                       for field in ("commit", "tree"))
                for name in source_names
            ):
                stage_result["status"] = "BLOCKED_SOURCE_CHANGED_DURING_CHECKS"
            else:
                stage_result["status"] = ("SOURCE_TESTED_EXTERNAL_EVIDENCE_PENDING" if all(s == "PASS_LOCAL" for s in states)
                                          else "BLOCKED_CHECKS_FAILED_OR_UNAVAILABLE")
        report["stages"][stage] = stage_result
    results_path = run_dir / "acceptance.json"
    fd = os.open(results_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"report": str(results_path), "source_shas": {k: v.get("commit") for k, v in report["sources"].items()},
                      "stages": {k: v["status"] for k, v in report["stages"].items()},
                      "production_qualified": False}, ensure_ascii=False, indent=2))
    # Never return success: this runner cannot independently prove production
    # effect/readback provenance or operator admission even if all unit checks pass.
    return 3 if all(v["status"] == "SOURCE_TESTED_EXTERNAL_EVIDENCE_PENDING" for v in report["stages"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
