#!/usr/bin/env python3
"""Verify production metric-tag HIA dispatch against the actual Rust branch."""

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

from test_native_string_caller import run, sha256


ROOT = Path(__file__).resolve().parents[2]
PUBLIC_SOURCE = ROOT / "codex-rs/utils/string/src/lib.rs"
ADAPTER = ROOT / "codex-rs/utils/string/src/hia_native_metric.rs"
HIA_SOURCE = ROOT / "hia/metric_tag.hepta"
TEST_SOURCE = ROOT / "hia/tests/native_metric_caller.rs"


def verify(args, report):
    rustc = shutil.which(args.rustc)
    if rustc is None:
        raise RuntimeError(f"a real Rust compiler is required: {args.rustc}")
    library_dir = args.library_dir.resolve(strict=True)
    archive = library_dir / "libcodex_hia_metric_tag.a"
    function = re.search(
        r"^pub fn sanitize_metric_tag_value\(.*?^}",
        PUBLIC_SOURCE.read_text(), re.MULTILINE | re.DOTALL,
    )
    if function is None:
        raise RuntimeError("could not extract the actual public metric function")
    function_text = function.group() + "\n"
    if '#[cfg(not(feature = "hia-native"))]' not in function_text:
        raise RuntimeError("the original Rust reference branch is missing")
    report["inputs"] = {
        "public_source_sha256": sha256(PUBLIC_SOURCE),
        "public_function_sha256": hashlib.sha256(function_text.encode()).hexdigest(),
        "adapter_sha256": sha256(ADAPTER),
        "hia_source_sha256": sha256(HIA_SOURCE),
        "test_source_sha256": sha256(TEST_SOURCE),
        "archive_sha256": sha256(archive),
        "build_report_sha256": sha256(library_dir / "build.json"),
    }
    report["rustc"] = run([rustc, "--version", "--verbose"], report).strip()
    with tempfile.TemporaryDirectory(prefix="codex-hia-metric-caller-") as directory:
        temporary = Path(directory)
        extracted = temporary / "metric_reference.rs"
        reference = temporary / "libmetric_reference.rlib"
        binary = temporary / "native_metric_caller"
        extracted.write_text(function_text)
        run([
            rustc, "--edition=2024", "--crate-name", "metric_reference",
            "--crate-type", "rlib", str(extracted), "-o", str(reference),
        ], report)
        environment = os.environ.copy()
        environment["CODEX_HIA_METRIC_SOURCE"] = str(extracted)
        run([
            rustc, "--edition=2024", "--test", "--cfg", 'feature="hia-native"',
            str(TEST_SOURCE), "--extern", f"metric_reference={reference}",
            "-L", f"native={library_dir}", "-l", "static=codex_hia_metric_tag",
            "-o", str(binary),
        ], report, env=environment)
        report["outputs"] = {
            "reference_rlib_sha256": sha256(reference),
            "native_test_binary_sha256": sha256(binary),
        }
        stdout = run([str(binary), "--test-threads=1", "--nocapture"], report)
    summary = re.search(
        r"test result: ok\. (\d+) passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;",
        stdout,
    )
    expected_tests = TEST_SOURCE.read_text().count("#[test]")
    counts = re.findall(r"native_metric_original_rust_comparisons=(\d+)", stdout)
    if summary is None or int(summary.group(1)) != expected_tests or not counts:
        raise RuntimeError("native metric caller did not execute all Rust comparisons")
    report.update({
        "passed": True, "tests_passed": int(summary.group(1)), "tests_skipped": 0,
        "original_rust_comparisons": max(map(int, counts)),
        "oracle": "actual public function compiled without hia-native",
        "caller": "actual public function, production adapter and native HIA archive",
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", required=True, type=Path)
    parser.add_argument("--rustc", default="rustc")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = {"schema": "codex.hia.native-metric-caller.v1", "passed": False, "commands": []}
    try:
        verify(args, report)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        report["error"] = str(error)
        print(str(error), file=sys.stderr)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
