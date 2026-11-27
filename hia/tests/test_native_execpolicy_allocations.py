#!/usr/bin/env python3
"""Measure actual public prefix calls with a separate, single-thread allocator harness."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

from test_native_execpolicy_caller import (
    ADAPTER, ORIGINAL_REVISION, ORIGINAL_TOKEN_COUNT, PUBLIC_SOURCE, ROOT, extract_public_source,
)
from test_native_string_caller import run, sha256

SCRIPT = Path(__file__).resolve()
HARNESS = SCRIPT.with_name("native_execpolicy_allocations.rs")
MODULES = ("prefix_match", "prefix_admission")


def verify(args, report):
    rustc = shutil.which(args.rustc)
    if rustc is None:
        raise RuntimeError(f"a real Rust compiler is required: {args.rustc}")
    library = args.library_dir.resolve(strict=True)
    section, token_hash = extract_public_source()
    sources = [PUBLIC_SOURCE, ADAPTER, HARNESS, SCRIPT, *(
        ROOT / "hia" / f"{module}.hepta" for module in MODULES
    )]
    report["sources"] = {str(path.relative_to(ROOT)): sha256(path) for path in sources}
    report["inputs"] = {
        "original_revision": ORIGINAL_REVISION, "original_token_count": ORIGINAL_TOKEN_COUNT,
        "original_token_sha256": token_hash,
        "extracted_public_section_sha256": hashlib.sha256(section.encode()).hexdigest(),
        "build_report_sha256": sha256(library / "build.json"),
        "archives": {module: sha256(library / f"libcodex_hia_{module}.a") for module in MODULES},
    }
    report["rustc"] = run([rustc, "--version", "--verbose"], report).strip()
    with tempfile.TemporaryDirectory(prefix="hia-prefix-allocations-", dir=args.report.parent) as directory:
        work = Path(directory)
        extracted, binary = work / "prefix_public.rs", work / "allocations"
        extracted.write_text(section)
        environment = os.environ.copy()
        environment["CODEX_HIA_EXECPOLICY_SOURCE"] = str(extracted)
        run([
            rustc, "--edition=2024", "--cfg", 'feature="hia-native"', "-C", "opt-level=3",
            str(HARNESS), "-L", f"native={library}",
            *[flag for module in MODULES for flag in ("-l", f"static=codex_hia_{module}")],
            "-o", str(binary),
        ], report, env=environment)
        symbols = run(["nm", "--defined-only", "--extern-only", str(binary)], report)
        report["native_symbols"] = {
            f"codex_hia_{module}": bool(re.search(rf"\bT codex_hia_{module}$", symbols, re.MULTILINE))
            for module in MODULES
        }
        if not all(report["native_symbols"].values()):
            raise RuntimeError("the actual caller must link both native prefix symbols")
        report["binary_sha256"] = sha256(binary)
        try:
            run([str(binary)], report)
        finally:
            stdout = report["commands"][-1]["stdout"]
            report["cases"] = [
                {"name": name, "alloc": int(a), "realloc": int(r)}
                for name, a, r in re.findall(r"^allocation_case name=(\w+) alloc=(\d+) realloc=(\d+)$", stdout, re.MULTILINE)
            ]
            report["cases_completed"] = len(report["cases"])
            probe = re.search(r"^allocation_probe alloc=(\d+) realloc=(\d+)$", stdout, re.MULTILINE)
            report["positive_probe"] = {"alloc": int(probe[1]), "realloc": int(probe[2])} if probe else None
    summary = re.search(r"^allocation_summary cases=(\d+)$", stdout, re.MULTILINE)
    if summary is None or int(summary[1]) != report["cases_completed"] or report["cases_completed"] != 20:
        raise RuntimeError("not all allocation cases completed")
    if probe is None or not all(int(value) > 0 for value in probe.groups()):
        raise RuntimeError("the allocator positive control did not observe both allocation operations")
    if report["sources"] != {str(path.relative_to(ROOT)): sha256(path) for path in sources}:
        raise RuntimeError("measured sources changed during verification")
    report.update({
        "passed": True,
        "allocation_free_calls": sum(case["alloc"] == case["realloc"] == 0 for case in report["cases"]),
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", required=True, type=Path)
    parser.add_argument("--rustc", default=os.environ.get("RUSTC", "rustc"))
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    args.report = args.report.resolve()
    if args.report.is_relative_to(ROOT):
        parser.error("reports and temporary build products must be outside the source checkout")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {"schema": "codex.hia.native-execpolicy-allocations.v1", "passed": False,
              "commands": [], "cases": [], "cases_completed": 0, "tests_skipped": 0,
              "counter_scope": "calling thread Rust GlobalAlloc alloc/alloc_zeroed/realloc during public call",
              "full_policy_or_core_qualification": False}
    try:
        verify(args, report)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(report["error"], file=sys.stderr)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
