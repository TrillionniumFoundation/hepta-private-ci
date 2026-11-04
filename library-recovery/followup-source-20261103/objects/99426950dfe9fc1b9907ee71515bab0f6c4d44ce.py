#!/usr/bin/env python3
"""Read-only, fail-closed exact-tree gate runner for a local Hepta checkout.

This tool does not install toolchains, modify source, merge, sign authority,
activate a Cell, or certify deployment. It records actual executed command
receipts; unexecuted and external gates never acquire a PASS result.

Usage:
  python3 hepta_local_closure.py --repo /path/to/hepta-private-ci
  python3 hepta_local_closure.py --repo /path/to/hepta-private-ci --execute
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import secrets
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

CHECKS = (
    ("python_ci_scope", "python", ("-m", "unittest", "discover", "-s", "scripts/tests", "-p", "test_hepta_ci_scope.py")),
    ("readiness", "python", ("scripts/hepta-readiness.py", "verify")),
    ("documents", "python", ("scripts/hepta-docs.py", "verify")),
    ("technical_closure", "python", ("scripts/hepta-technical-closure.py", "verify")),
    ("lane_b_truth", "python", ("scripts/hepta-lane-b-truth.py", "verify")),
    ("rust_format", "cargo", ("fmt", "--manifest-path", "codex-rs/Cargo.toml", "--all", "--", "--check")),
    ("rust_tests", "cargo", ("test", "--manifest-path", "codex-rs/Cargo.toml", "--locked", "--workspace", "--all-targets")),
    ("rust_clippy", "cargo", ("clippy", "--manifest-path", "codex-rs/Cargo.toml", "--locked", "--workspace", "--all-targets", "--", "-D", "warnings")),
)
EXTERNAL = (
    "independent_final_use_issuer_signer_peer_and_revocation",
    "target_host_agentd_and_app_server_process_socket_generation_identity",
    "actual_provider_stream_and_exact_terminal_receipt",
    "delegated_external_tool_effect_and_lost_ack_reconciliation",
    "resolution_and_quarantine_for_irreconcilable_effects",
    "real_encoder_decoder_shared_cell_performance_and_memory_envelope",
    "independent_matched_no_change_learning_efficacy_and_retention",
    "independent_acceptance_canary_rollback_promotion_release",
)


def git(repo: Path, *args: str) -> tuple[int, str]:
    try:
        p = subprocess.run(
            ["git", "-C", str(repo), *args],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", timeout=15,
            check=False,
        )
        return p.returncode, p.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def probe(repo: Path) -> dict:
    result = {"requested_path": str(repo), "tools": {name: shutil.which(name) for name in ("git", "rustc", "cargo", "just", "python3")}}
    rc, root = git(repo, "rev-parse", "--show-toplevel")
    result["git_root_error"] = root if rc else None
    if rc:
        result["checkout_valid"] = False
        return result
    root_path = Path(root).resolve()
    result["git_root"] = str(root_path)
    result["checkout_valid"] = root_path == repo.resolve() and (repo / "codex-rs" / "Cargo.toml").is_file() and (repo / "codex-rs" / "hepta-neuron").is_dir()
    for key, cmd in (
        ("head", ("rev-parse", "HEAD")),
        ("tree", ("rev-parse", "HEAD^{tree}")),
        ("branch", ("rev-parse", "--abbrev-ref", "HEAD")),
        ("dirty_paths", ("status", "--porcelain=v1", "--untracked-files=all")),
    ):
        code, value = git(repo, *cmd)
        result[key] = value if code == 0 else None
    result["tracked_source_clean"] = result["dirty_paths"] == ""
    return result


def requirements(repo: Path, entry: tuple[str, str, tuple[str, ...]]) -> tuple[str | None, list[str]]:
    _, tool, args = entry
    command = [sys.executable if tool == "python" else tool, *args]
    if tool != "python" and shutil.which(tool) is None:
        return f"tool {tool} not installed", command
    if tool == "cargo" and not (repo / "codex-rs" / "Cargo.toml").is_file():
        return "missing codex-rs/Cargo.toml", command
    if tool == "python" and args[0] != "-m" and not (repo / args[0]).is_file():
        return f"required source {args[0]} missing", command
    if tool == "python" and args[0] == "-m" and not (repo / "scripts" / "tests" / "test_hepta_ci_scope.py").is_file():
        return "missing original CI-scope test module", command
    return None, command


def execute(command: list[str], repo: Path, log_path: Path, timeout: int) -> dict:
    start = time.monotonic()
    timed_out = False
    code = None
    # Do not hand ambient cloud/service credentials to arbitrary repo tests.
    allow = {"PATH", "HOME", "USER", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL",
             "SYSTEMROOT", "CARGO_HOME", "RUSTUP_HOME", "CARGO_TARGET_DIR"}
    safe_env = {key: value for key, value in os.environ.items() if key in allow}
    safe_env["PYTHONDONTWRITEBYTECODE"] = "1"
    with log_path.open("xb") as log:
        log_path.chmod(0o600)
        try:
            # The tests themselves are not sandboxed; execute only in a
            # disposable, isolated checkout, never on a production host.
            proc = subprocess.Popen(command, cwd=repo, stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=(os.name != "nt"), env=safe_env)
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                if os.name != "nt":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
                proc.wait(timeout=15)
        except OSError as exc:
            log.write(f"EXECUTION ERROR: {exc}\n".encode("utf-8", "replace"))
            code = 127
        log.flush()
        os.fsync(log.fileno())
    h = hashlib.sha256()
    with log_path.open("rb") as fp:
        while block := fp.read(65536):
            h.update(block)
    return {
        "status": "BLOCKED" if timed_out else ("PASS" if code == 0 else "FAIL"),
        "exit_code": code, "timed_out": timed_out,
        "elapsed_seconds": round(time.monotonic() - start, 3),
        "output_sha256": h.hexdigest(), "log": log_path.name,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="exact hepta-private-ci checkout root")
    parser.add_argument("--output", type=Path, help="private evidence root; default: ~/.cache/hepta-gate-evidence")
    parser.add_argument("--execute", action="store_true", help="actually run local source checks (may require substantial build resources)")
    parser.add_argument("--timeout", type=int, default=3600, help="per-command timeout in seconds, max 21600")
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 21600:
        parser.error("timeout must be 1..21600 seconds")
    repo = args.repo.expanduser().resolve()
    output = (args.output or (Path.home() / ".cache" / "hepta-gate-evidence")).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Refuse a pre-existing world-accessible output directory.
    if os.name != "nt" and output.stat().st_mode & 0o077:
        print("Evidence directory must be private (chmod 700):", output, file=sys.stderr)
        return 2
    status = probe(repo)
    # Each invocation gets immutable, non-overwriting evidence files.
    run_dir = output / ("run-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                        + "-" + secrets.token_hex(6))
    run_dir.mkdir(mode=0o700)
    results = {}
    for name, tool, argv_ in CHECKS:
        entry = (name, tool, argv_)
        why, command = requirements(repo, entry)
        record = {"command": command}
        if not status.get("checkout_valid"):
            record.update(status="BLOCKED", reason="Hepta checkout not mounted or incomplete")
        elif not status.get("tracked_source_clean"):
            record.update(status="BLOCKED", reason="tracked source is dirty; exact HEAD cannot qualify working tree")
        elif why:
            record.update(status="BLOCKED", reason=why)
        elif not args.execute:
            record.update(status="NOT_RUN", reason="--execute not supplied")
        else:
            record.update(execute(command, repo, run_dir / f"{name}.log", args.timeout))
        results[name] = record
    if args.execute and status.get("checkout_valid"):
        final_rc, final_dirty = git(repo, "status", "--porcelain=v1", "--untracked-files=all")
        status["post_execution_dirty_paths"] = final_dirty if final_rc == 0 else None
        status["source_integrity_retained"] = final_rc == 0 and final_dirty == status.get("dirty_paths")
        if not status["source_integrity_retained"]:
            results["source_integrity"] = {
                "status": "FAIL", "reason": "tests changed source/worktree; exact HEAD receipt cannot be promoted"
            }
    states = {r["status"] for r in results.values()}
    if "FAIL" in states:
        local = "FAIL"
    elif states == {"PASS"}:
        local = "PASS"
    else:
        local = "BLOCKED"
    receipt = {
        "schema": "hepta.local.gate-evidence.v1", "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "mode": "execute" if args.execute else "probe", "source": status,
        "local_checks": results, "local_verdict": local,
        "external_checks": {name: {"status": "UNVERIFIED", "reason": "independent target/authority evidence required"} for name in EXTERNAL},
        "overall_verdict": "HOLD_NO_GO", "production_authority": False,
        "note": "A locally passing suite cannot close external or independent acceptance. Only actual subprocess receipts count.",
    }
    destination = run_dir / "verdict.json"
    temporary = run_dir / "verdict.json.new"
    with temporary.open("x", encoding="utf-8") as fp:
        os.chmod(temporary, 0o600)
        json.dump(receipt, fp, indent=2, sort_keys=True, ensure_ascii=False)
        fp.write("\n")
        fp.flush()
        os.fsync(fp.fileno())
    temporary.replace(destination)
    print(json.dumps({"source_head": status.get("head"), "local_verdict": local,
                      "overall_verdict": "HOLD_NO_GO", "output": str(destination)}, ensure_ascii=False))
    # Never emit an overall-green process exit while external gates are open.
    return 3 if local == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
