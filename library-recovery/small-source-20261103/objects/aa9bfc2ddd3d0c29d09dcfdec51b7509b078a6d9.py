#!/usr/bin/env python3
"""Fail-closed, read-only Hepta local qualification sweep.

This is not a replacement for signed FinalUse, platform CI, or production gates.
Do not execute untrusted project code without the repository's usual sandbox.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

P0_PACKAGES = (
    "codex-hepta-neuron",
    "codex-hepta-plasticity",
    "codex-hepta-operations",
    "codex-hepta-codex-adapter",
)


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root), *args],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=30,
    ).stdout


def identify(root: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    top = Path(git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if top != root:
        raise ValueError(f"--repo must be the Git worktree root ({top})")
    for required in ("codex-rs/Cargo.toml", "scripts/hepta_ci_scope.py"):
        if not (root / required).is_file():
            raise ValueError(f"missing Hepta input: {required}")
    head = git(root, "rev-parse", "HEAD").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("Git HEAD is not an exact commit identity")
    status = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    return {"head": head, "clean": not bool(status), "dirty_entries": len([p for p in status.split(b"\0") if p])}


def steps(profile: str) -> list[tuple[str, list[str], Path]]:
    # Absolute Python interpreter avoids invoking an unreviewed PATH python shim.
    suite = [
        ("ci-scope-tests", [sys.executable, "-m", "unittest", "-v",
                            "scripts.tests.test_hepta_ci_scope",
                            "scripts.tests.test_hepta_ci_dependencies"], Path(".")),
        ("candidate-identity-tests", [sys.executable, "-m", "unittest", "-v",
                                      "scripts.tests.test_hepta_ci_candidate"], Path(".")),
        ("rustfmt", ["cargo", "fmt", "--", "--config", "imports_granularity=Item", "--check"], Path("codex-rs")),
        ("cell-tests", ["cargo", "test", "--locked", *sum((["-p", p] for p in P0_PACKAGES), [])], Path("codex-rs")),
        ("cell-clippy", ["cargo", "clippy", "--locked", "--all-targets", *sum((["-p", p] for p in P0_PACKAGES), []), "--", "-D", "warnings"], Path("codex-rs")),
    ]
    if profile == "full":
        suite.extend([
            ("rust-workspace-tests", ["cargo", "test", "--locked"], Path("codex-rs")),
            ("rust-workspace-clippy", ["cargo", "clippy", "--locked", "--all-targets", "--", "-D", "warnings"], Path("codex-rs")),
        ])
    return suite


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(65536), b""):
            h.update(part)
    return h.hexdigest()


def execute(label: str, command: list[str], cwd: Path, log_dir: Path,
            timeout: int) -> dict[str, object]:
    entry: dict[str, object] = {"gate": label, "argv": command, "cwd": str(cwd)}
    if shutil.which(command[0]) is None and not Path(command[0]).is_file():
        entry.update(state="BLOCKED_ENV", reason=f"executable unavailable: {command[0]}")
        return entry
    logfile = log_dir / (label + ".log")
    start = time.monotonic()
    env = os.environ.copy()
    env.update({"CARGO_INCREMENTAL": "0", "CARGO_BUILD_JOBS": "2", "PYTHONDONTWRITEBYTECODE": "1"})
    proc = None
    try:
        with logfile.open("wb") as out:
            proc = subprocess.Popen(command, cwd=cwd, stdout=out,
                                    stderr=subprocess.STDOUT, env=env,
                                    start_new_session=(os.name == "posix"))
            try:
                code = proc.wait(timeout=timeout)
                entry["state"] = "PASS" if code == 0 else "FAIL"
                entry["returncode"] = code
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
                proc.wait()
                entry.update(state="TIMEOUT", reason=f"exceeded {timeout}s")
    except OSError as error:
        entry.update(state="BLOCKED_ENV", reason=str(error))
    entry["duration_seconds"] = round(time.monotonic() - start, 3)
    if logfile.exists():
        entry["log"] = str(logfile)
        entry["log_sha256"] = digest_file(logfile)
        entry["log_bytes"] = logfile.stat().st_size
    return entry


def sweep(repo: Path, profile: str, out: Path, timeout: int) -> dict[str, object]:
    root = repo.resolve(strict=True)
    before = identify(root)
    out.mkdir(parents=True, exist_ok=True)
    # Guard against qualifications that accidentally alter their own Git tree.
    if out.resolve() == root or root in out.resolve().parents:
        raise ValueError("receipt output must live outside the source worktree")
    result: dict[str, object] = {
        "schema": "hepta.local-blocker-sweep.v1",
        "time_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "repo": str(root), "source": before, "profile": profile,
        "scope": "local Linux/macOS/Windows host only; not cross-platform CI",
        "gates": [],
        "external_gates": {
            "signed_final_use": "UNVERIFIED",
            "macos_ci": "UNVERIFIED",
            "windows_ci": "UNVERIFIED",
            "linux_arm_ci": "UNVERIFIED",
            "release_admission": "UNVERIFIED",
            "performance_and_production_runtime": "UNVERIFIED",
        },
    }
    if not before["clean"]:
        result["gates"].append({"gate": "source-cleanliness", "state": "FAIL",
                                "reason": "source worktree has tracked/untracked modifications"})
    else:
        result["gates"].append({"gate": "source-cleanliness", "state": "PASS"})
    for label, cmd, relcwd in steps(profile):
        result["gates"].append(execute(label, cmd, root / relcwd, out, timeout))
    after = identify(root)
    same_source = before["head"] == after["head"] and before == after
    result["gates"].append({
        "gate": "source-stability", "state": "PASS" if same_source else "FAIL",
        "before": before, "after": after,
    })
    failed = [g["gate"] for g in result["gates"] if g["state"] != "PASS"]
    # Never certify FULLY_CLOSED using only local checks.
    result["overall"] = "LOCAL_FAIL_OR_INCOMPLETE" if failed else "LOCAL_ONLY_PASS_CROSS_PLATFORM_UNVERIFIED"
    result["incomplete_or_failed_gates"] = failed
    dest = out / "hepta-local-qualification.json"
    dest.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="exact Hepta Git worktree root")
    parser.add_argument("--profile", choices=("smoke", "full"), default="full")
    parser.add_argument("--out", type=Path, help="external output directory; defaults to an OS temporary directory")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()
    if not (1 <= args.timeout_seconds <= 21600):
        parser.error("--timeout-seconds must be between 1 and 21600")
    out = args.out or Path(tempfile.mkdtemp(prefix="hepta-local-qual-"))
    try:
        report = sweep(args.repo, args.profile, out, args.timeout_seconds)
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired, UnicodeError) as error:
        print(f"BLOCKED_ENV: cannot qualify source: {error}", file=sys.stderr)
        return 2
    for gate in report["gates"]:
        print(f"{gate['state']:>12}  {gate['gate']}")
    print("Overall:", report["overall"])
    print("Receipt:", out / "hepta-local-qualification.json")
    # Even local full PASS remains non-zero: no cross-platform/authority evidence.
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
