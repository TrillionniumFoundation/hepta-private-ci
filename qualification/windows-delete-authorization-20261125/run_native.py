#!/usr/bin/env python3
"""Run every preregistered native case once and retain exact source/log receipts."""

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import tomllib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACKAGE = "codex-windows-delete-boundary-probe"
CASES = {
    "matrix::native_delete_distinguishes_target_right_from_parent_delete_child",
    "matrix::full_restriction_has_a_real_controlled_write_positive_and_outside_negative",
    "matrix::null_dacl_is_an_explicit_limit_of_full_restriction",
    "matrix::low_integrity_does_not_protect_a_low_outside_null_dacl_object",
}
LIST_CASE = "list_factor::directory_list_bit_observations"
SOURCES = [
    "codex-rs/Cargo.lock",
    "codex-rs/.config/nextest.toml",
    "codex-rs/windows-sandbox-rs/src/token.rs",
    "codex-rs/windows-sandbox-rs/src/token_delete_matrix_support.rs",
    "codex-rs/windows-sandbox-rs/src/token_delete_open_diagnostics.rs",
    "codex-rs/windows-sandbox-rs/src/token_delete_access_diagnostics.rs",
    "codex-rs/windows-sandbox-rs/src/token_delete_integrity_observations.rs",
    "codex-rs/windows-sandbox-rs/src/token_delete_list_factor_tests.rs",
    "codex-rs/windows-sandbox-rs/src/token_delete_authorization_tests.rs",
    "codex-rs/windows-sandbox-rs/src/filesystem_isolation.rs",
    "qualification/windows-delete-authorization-20261125/probe/lib.rs",
    "qualification/windows-delete-authorization-20261125/probe/list_factor.rs",
    "qualification/windows-delete-authorization-20261125/probe/Cargo.toml",
    "qualification/windows-delete-authorization-20261125/probe/Cargo.lock",
    "qualification/windows-delete-authorization-20261125/probe/nextest.toml",
    "qualification/windows-delete-authorization-20261125/run_native.py",
    "qualification/windows-delete-authorization-20261125/LIST_FACTOR_PROTOCOL.md",
    ".github/workflows/hepta-windows-delete-authorization.yml",
]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def identity():
    return {
        "head": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "parents": [line.split()[1] for line in git("cat-file", "-p", "HEAD")
                    .split("\n\n", 1)[0].splitlines() if line.startswith("parent ")],
        "status": git("status", "--porcelain"),
        "sha256": {name: sha((ROOT / name).read_bytes()) for name in SOURCES},
    }


def external_packages(path):
    lock = tomllib.loads(path.read_text())
    return {(row["name"], row["version"], row["source"], row.get("checksum"))
            for row in lock["package"] if "source" in row}


def command(args, evidence, name):
    start = time.monotonic()
    path = evidence / (name + ".log")
    with path.open("wb") as output:
        result = subprocess.run(args, cwd=ROOT / "codex-rs", stdout=output,
                                stderr=subprocess.STDOUT, check=False)
    raw = path.read_bytes()
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()
    return {"command": args, "exit_code": result.returncode,
            "seconds": time.monotonic() - start, "log": path.name,
            "bytes": len(raw), "sha256": sha(raw)}


def verify_native(log):
    clean = re.sub(r"\x1b\[[0-9;]*m", "", log)
    passed = re.findall(r"^\s*PASS\s+\[[^]]+\]\s+" + re.escape(PACKAGE)
                        + r"\s+(matrix::\w+)\s*$", clean, re.M)
    if len(passed) != 4 or set(passed) != CASES:
        raise RuntimeError("expected exactly the four preregistered passing tests")
    if not re.search(r"Summary\s+\[[^]]+\] 4 tests run: 4 passed, 0 skipped", clean):
        raise RuntimeError("missing complete four-test, zero-skip summary")
    cells = re.findall(r"^\s*HEPTA_DELETE_MATRIX (.+)$", clean, re.M)
    if len(cells) != len(set(cells)) or len(cells) != 18:
        raise RuntimeError("expected 18 distinct completed deletion-cell receipts")
    counts = [sum(cell.startswith(prefix) for cell in cells) for prefix in
              ["mode=", "full_restriction_null_dacl ", "full_restriction_low_null_dacl "]]
    if counts != [12, 4, 2]:
        raise RuntimeError("deletion-cell grouping changed")
    return {"test_identities": sorted(passed), "deletion_cells": cells,
            "rust_tests": 4, "deletion_cell_count": 18,
            "combined_controlled_write_scenarios": 1}


def verify_list_factor(log):
    clean = re.sub(r"\x1b\[[0-9;]*m", "", log)
    passed = re.findall(r"^\s*PASS\s+\[[^]]+\]\s+" + re.escape(PACKAGE + "::list_factor")
                        + r"\s+(list_factor::\S+)\s*$", clean, re.M)
    if passed != [LIST_CASE] or not re.search(
            r"Summary\s+\[[^]]+\] 1 tests? run: 1 passed, 0 skipped", clean):
        raise RuntimeError("the one independent LIST diagnostic did not complete")
    rows = re.findall(r"^\s*HEPTA_DELETE_LIST scenario=(Target|NullParent|Neither) "
                      r"list=(false|true) (.+)$", clean, re.M)
    expected = {(scenario, flag) for scenario in ["Target", "NullParent", "Neither"]
                for flag in ["false", "true"]}
    if len(rows) != 6 or {(scenario, flag) for scenario, flag, _ in rows} != expected:
        raise RuntimeError("expected six distinct LIST-factor observations")
    return {"test_identity": LIST_CASE, "rust_tests": 1, "observations": rows,
            "diagnostic_complete": True, "qualifies_original_matrix": False}


def main():
    evidence = Path(os.environ["RUNNER_TEMP"]) / "hepta-delete-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    receipt = {"windows_native": os.name == "nt", "platform": platform.platform(),
               "architecture": platform.machine(), "commands": []}
    failed = False
    try:
        if os.name != "nt":
            raise RuntimeError("Windows native execution is required; no zero-test fallback")
        before = identity()
        receipt["before"] = before
        if before["status"] or before["head"] != os.environ["EXPECTED_HEAD"]:
            raise RuntimeError("checkout is dirty or not the exact requested source head")
        versions = [command(["rustc", "-Vv"], evidence, "rustc"),
                    command(["cargo", "-V"], evidence, "cargo")]
        receipt["toolchain"] = versions
        rustc = (evidence / "rustc.log").read_text()
        if any(row["exit_code"] != 0 for row in versions):
            raise RuntimeError("could not read actual compiler identities")
        if not re.search(r"^release: 1\.96\.0$", rustc, re.M):
            raise RuntimeError("actual Rust version differs from the fixed 1.96.0")
        if not re.search(r"^host: x86_64-pc-windows-msvc$", rustc, re.M):
            raise RuntimeError("actual compiler host is not native Windows MSVC")
        external = external_packages(HERE / "probe/Cargo.lock")
        if not external or not external <= external_packages(ROOT / "codex-rs/Cargo.lock"):
            raise RuntimeError("probe package identities do not match the production lock")
        receipt["external_package_identities"] = sorted(external)
        production_profile = tomllib.loads(
            (ROOT / "codex-rs/.config/nextest.toml").read_text())["profile"]["default"]
        probe_profile = tomllib.loads((HERE / "probe/nextest.toml").read_text())
        expected_profile = {"profile": {
            "default": {"slow-timeout": production_profile["slow-timeout"],
                        "retries": 0, "junit": production_profile["junit"]},
            "local": {"inherits": "default"},
        }}
        if probe_profile != expected_profile:
            raise RuntimeError("probe timeout/JUnit profile differs from repository defaults")
        receipt["effective_nextest_config"] = probe_profile
        manifest = str(HERE / "probe/Cargo.toml")
        invocations = [
            ("clippy", ["cargo", "clippy", "--manifest-path", manifest, "--locked",
                        "--all-targets", "--", "-D", "warnings"]),
            ("native", ["just", "test", "--manifest-path", manifest, "--locked",
                        "--lib", "-p", PACKAGE, "--config-file", str(HERE / "probe/nextest.toml"),
                        "--test-threads", "1", "--retries", "0",
                        "--success-output", "immediate", "--failure-output", "immediate"]),
            ("list-factor", ["just", "test", "--manifest-path", manifest, "--locked",
                             "--test", "list_factor", "-p", PACKAGE,
                             "--config-file", str(HERE / "probe/nextest.toml"),
                             "--test-threads", "1", "--retries", "0",
                             "--success-output", "immediate", "--failure-output", "immediate"]),
        ]
        for name, args in invocations:
            row = command(args, evidence, name)
            receipt["commands"].append(row)
            failed = failed or row["exit_code"] != 0
        receipt["after"] = identity()
        if receipt["after"] != before:
            raise RuntimeError("source identity changed during qualification")
        try:
            receipt["list_factor_diagnostic"] = verify_list_factor(
                (evidence / "list-factor.log").read_text(encoding="utf-8", errors="replace"))
        except Exception as error:
            failed = True
            receipt["list_factor_error"] = f"{type(error).__name__}: {error}"
        receipt["native_counts"] = verify_native(
            (evidence / "native.log").read_text(encoding="utf-8", errors="replace"))
    except Exception as error:
        failed = True
        receipt["error"] = f"{type(error).__name__}: {error}"
    receipt["qualified"] = not failed
    (evidence / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
