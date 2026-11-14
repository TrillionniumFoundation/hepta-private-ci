#!/usr/bin/env python3
"""Test the real public string caller against separately compiled original Rust.

The reference is extracted from the production source and compiled without the
HIA feature. The caller uses that public source with the feature enabled, the
actual Rust transport module, and the native HIA static archive. Missing rustc
or missing native artifacts is an error; this gate never skips the oracle.
"""

from __future__ import annotations

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
import time


ROOT = Path(__file__).resolve().parents[2]
PUBLIC_SOURCE = ROOT / "codex-rs/utils/string/src/lib.rs"
ADAPTER = ROOT / "codex-rs/utils/string/src/hia_native.rs"
HIA_SOURCE = ROOT / "hia/utf8_prefix.hepta"
TEST_SOURCE = ROOT / "hia/tests/native_string_caller.rs"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], report: dict, *, env: dict | None = None) -> str:
    started = time.monotonic()
    result = subprocess.run(command, text=True, capture_output=True, env=env)
    report["commands"].append({
        "command": command,
        "returncode": result.returncode,
        "elapsed_seconds": round(time.monotonic() - started, 6),
        "stdout": result.stdout,
        "stderr": result.stderr,
    })
    if result.stdout:
        print(result.stdout, end="", flush=True)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr, flush=True)
    if result.returncode:
        raise RuntimeError(f"command failed with status {result.returncode}: {command[0]}")
    return result.stdout


def verify(args: argparse.Namespace, report: dict) -> None:
    rustc = shutil.which(args.rustc)
    if rustc is None:
        raise RuntimeError(f"a real Rust compiler is required: {args.rustc}")
    library_dir = args.library_dir.resolve()
    archive = library_dir / "libcodex_hia_utf8_prefix.a"
    if not archive.is_file():
        raise RuntimeError(f"missing native HIA static archive: {archive}")
    source = PUBLIC_SOURCE.read_text()
    function = re.search(
        r"^pub fn take_bytes_at_char_boundary\(.*?^}",
        source,
        re.MULTILINE | re.DOTALL,
    )
    if function is None:
        raise RuntimeError("could not extract the original public string function")
    function_text = function.group() + "\n"
    if '#[cfg(not(feature = "hia-native"))]' not in function_text:
        raise RuntimeError("original Rust branch is missing from the reference source")
    report["inputs"] = {
        "public_source_sha256": sha256(PUBLIC_SOURCE),
        "public_function_sha256": hashlib.sha256(function_text.encode()).hexdigest(),
        "adapter_sha256": sha256(ADAPTER),
        "hia_source_sha256": sha256(HIA_SOURCE),
        "test_source_sha256": sha256(TEST_SOURCE),
        "archive_sha256": sha256(archive),
    }
    build_report = library_dir / "build.json"
    if build_report.is_file():
        report["inputs"]["build_report_sha256"] = sha256(build_report)
    report["rustc"] = run([rustc, "--version", "--verbose"], report).strip()
    with tempfile.TemporaryDirectory(prefix="codex-hia-string-caller-") as directory:
        temporary = Path(directory)
        extracted = temporary / "string_reference.rs"
        reference = temporary / "libstring_reference.rlib"
        binary = temporary / "native_string_caller"
        extracted.write_text(function_text)
        run([
            rustc, "--edition=2024", "--crate-name", "string_reference",
            "--crate-type", "rlib", str(extracted), "-o", str(reference),
        ], report)
        environment = os.environ.copy()
        environment["CODEX_HIA_STRING_SOURCE"] = str(extracted)
        run([
            rustc, "--edition=2024", "--test", "--cfg", 'feature="hia-native"',
            str(TEST_SOURCE), "--extern", f"string_reference={reference}",
            "-L", f"native={library_dir}", "-l", "static=codex_hia_utf8_prefix",
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
    if summary is None or int(summary.group(1)) != expected_tests:
        raise RuntimeError("the native caller test result did not execute all tests")
    counts = re.findall(r"native_string_original_rust_comparisons=(\d+)", stdout)
    allocation_calls = re.findall(r"native_string_allocation_free_calls=(\d+)", stdout)
    if not counts or not allocation_calls:
        raise RuntimeError("missing original Rust comparison or allocation result")
    report.update({
        "passed": True,
        "tests_passed": int(summary.group(1)),
        "tests_skipped": 0,
        "original_rust_comparisons": max(map(int, counts)),
        "allocation_free_calls": sum(map(int, allocation_calls)),
        "oracle": "public function compiled without hia-native from the actual source",
        "caller": "public function compiled with hia-native and the production adapter",
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", required=True, type=Path)
    parser.add_argument("--rustc", default="rustc")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = {"schema": "codex.hia.native-string-caller.v1", "passed": False, "commands": []}
    try:
        verify(args, report)
    except (OSError, RuntimeError) as error:
        report["error"] = str(error)
        print(str(error), file=sys.stderr)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
