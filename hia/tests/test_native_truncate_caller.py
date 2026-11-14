#!/usr/bin/env python3
"""Compare complete public HIA truncation APIs with the original Rust branch."""

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
import textwrap

from test_native_string_caller import run, sha256


ROOT = Path(__file__).resolve().parents[2]
PUBLIC_SOURCE = ROOT / "codex-rs/utils/string/src/truncate.rs"
ADAPTER = ROOT / "codex-rs/utils/string/src/hia_native_truncate.rs"
HIA_SOURCE = ROOT / "hia/truncate.hepta"
TOKEN_BUDGET_SOURCE = ROOT / "hia/token_budget.hepta"
TEST_SOURCE = ROOT / "hia/tests/native_truncate_caller.rs"
BASELINE_REVISION = "a2014bc6bfa1c1c9957edb3f14f8ae7d9ddcc095"
BASELINE_BLOB = "fa5b871774c242fb1380b927dd34fd7f73d3680b"
BASELINE_TOKENS_SHA256 = "4e7972a26775f1ac20903b977becb011a5283bb56bfbf9311ca483593a21b485"


def original_rust_source(source):
    """Select unchanged default bodies and bind them to the original Git blob.

    Whitespace and comments can change through cfg indentation and rustfmt.
    String literals remain single exact tokens, so marker text is protected.
    """
    def select_default(match):
        function = match.group()
        body = re.search(
            r'    #\[cfg\(not\(feature = "hia-native"\)\)\]\n    \{\n(.*)\n    \}\n\}$',
            function, re.S,
        )
        if body is None:
            raise RuntimeError("a public API lost its original Rust branch")
        return function[:function.index("{") + 1] + "\n" + textwrap.dedent(body.group(1)) + "\n}"

    reference = re.sub(r"^pub fn .*?^}", select_default, source, flags=re.M | re.S)
    reference = reference.replace('#[cfg(not(feature = "hia-native"))]\n', "")
    reference = reference.replace('#[cfg(any(test, not(feature = "hia-native")))]\n', "")
    tokens = [match.group() for match in re.finditer(
        r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|[^\s]',
        reference, re.S,
    ) if not match.group().startswith(("//", "/*"))]
    digest = hashlib.sha256(json.dumps(tokens, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    if digest != BASELINE_TOKENS_SHA256:
        raise RuntimeError("the default oracle differs from the pinned original Rust source")
    return reference


def verify(args, report):
    rustc = shutil.which(args.rustc)
    if rustc is None:
        raise RuntimeError(f"a real Rust compiler is required: {args.rustc}")
    library_dir = args.library_dir.resolve(strict=True)
    archive = library_dir / "libcodex_hia_truncate.a"
    token_budget_archive = library_dir / "libcodex_hia_token_budget.a"
    build_report = library_dir / "build.json"
    build = json.loads(build_report.read_text())
    if build.get("status") != "built" or build.get("compiler_fixed_point") is not True:
        raise RuntimeError("the native caller requires an actual fixed-point HIA build")
    for module, hia_source, native_archive in (
        ("truncate", HIA_SOURCE, archive),
        ("token_budget", TOKEN_BUDGET_SOURCE, token_budget_archive),
    ):
        component = build["modules"][module]
        abi = component["codex_link_abi"]
        if component["source_sha256"] != sha256(hia_source):
            raise RuntimeError(f"the native {module} artifact has a different HIA source")
        if abi["archive_sha256"] != sha256(native_archive):
            raise RuntimeError(f"the native {module} archive differs from its build report")
        if abi["symbol"] != f"codex_hia_{module}":
            raise RuntimeError(f"the native {module} entry symbol differs from its contract")
    source = PUBLIC_SOURCE.read_text()
    if '#[cfg(not(feature = "hia-native"))]' not in source:
        raise RuntimeError("the original Rust reference branch is missing")
    # Keep every production function, removing only module documentation and
    # the out-of-line tests that belong to Cargo's separate test target.
    extracted_source = re.sub(r"^//!.*\n", "", source, flags=re.M)
    extracted_source, removed = re.subn(
        r"#\[cfg\((?:all\(test, feature = \"hia-native\"\)|test)\)\]\n"
        r"(?:#\[path = \"[^\"]+\"\]\n)?mod \w+;\n?",
        "", extracted_source,
    )
    if not removed or re.search(r"^mod \w+;", extracted_source, re.M):
        raise RuntimeError("could not isolate the complete production source")
    reference_source = original_rust_source(extracted_source)
    report["inputs"] = {
        "public_source_sha256": sha256(PUBLIC_SOURCE),
        "extracted_source_sha256": hashlib.sha256(extracted_source.encode()).hexdigest(),
        "adapter_sha256": sha256(ADAPTER), "hia_source_sha256": sha256(HIA_SOURCE),
        "test_source_sha256": sha256(TEST_SOURCE), "archive_sha256": sha256(archive),
        "token_budget_source_sha256": sha256(TOKEN_BUDGET_SOURCE),
        "token_budget_archive_sha256": sha256(token_budget_archive),
        "build_report_sha256": sha256(build_report),
        "original_revision": BASELINE_REVISION, "original_blob": BASELINE_BLOB,
        "original_production_tokens_sha256": BASELINE_TOKENS_SHA256,
    }
    report["rustc"] = run([rustc, "--version", "--verbose"], report).strip()
    with tempfile.TemporaryDirectory(prefix="codex-hia-truncate-caller-") as directory:
        temporary = Path(directory)
        extracted = temporary / "truncate_reference.rs"
        native = temporary / "truncate_native.rs"
        reference = temporary / "libtruncate_reference.rlib"
        binary = temporary / "native_truncate_caller"
        extracted.write_text(reference_source)
        native.write_text(extracted_source)
        run([
            rustc, "--edition=2024", "--crate-name", "truncate_reference", "--crate-type", "rlib",
            str(extracted), "-o", str(reference),
        ], report)
        environment = os.environ.copy()
        environment["CODEX_HIA_TRUNCATE_SOURCE"] = str(native)
        run([
            rustc, "--edition=2024", "--test", "--cfg", 'feature="hia-native"', str(TEST_SOURCE),
            "--extern", f"truncate_reference={reference}", "-L", f"native={library_dir}",
            "-l", "static=codex_hia_truncate", "-l", "static=codex_hia_token_budget",
            "-o", str(binary),
        ], report, env=environment)
        report["outputs"] = {
            "reference_rlib_sha256": sha256(reference), "native_test_binary_sha256": sha256(binary),
        }
        stdout = run([str(binary), "--test-threads=1", "--nocapture"], report)
    summary = re.search(r"test result: ok\. (\d+) passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;", stdout)
    counts = re.findall(r"native_truncate_original_rust_comparisons=(\d+)", stdout)
    if summary is None or int(summary.group(1)) != TEST_SOURCE.read_text().count("#[test]") or not counts:
        raise RuntimeError("the native truncation caller did not execute all Rust comparisons")
    report.update({
        "passed": True, "tests_passed": int(summary.group(1)), "tests_skipped": 0,
        "original_rust_comparisons": max(map(int, counts)),
        "oracle": "complete preserved original Rust source; all production tokens match the pinned original Git blob",
        "caller": "same public source compiled with hia-native, production adapter and both source-bound native HIA archives",
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", required=True, type=Path)
    parser.add_argument("--rustc", default="rustc")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = {"schema": "codex.hia.native-truncate-caller.v1", "passed": False, "commands": []}
    try:
        verify(args, report)
    except (OSError, RuntimeError, KeyError, ValueError, subprocess.TimeoutExpired) as error:
        report["error"] = str(error)
        print(str(error), file=sys.stderr)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
