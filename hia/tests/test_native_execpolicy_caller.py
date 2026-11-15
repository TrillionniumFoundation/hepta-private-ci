#!/usr/bin/env python3
"""Compare the actual public prefix matcher with its original Rust owner.

The production PatternToken/PrefixPattern section is compiled independently
with the native feature off and on. All 286 original tokens are pinned to the
f75abe3 source; only the feature attributes and exact native delegation may be
added. This component differential does not substitute for full Policy, Core,
CLI, installation or platform qualification.
"""

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
PUBLIC_SOURCE = ROOT / "codex-rs/execpolicy/src/rule.rs"
ADAPTER = PUBLIC_SOURCE.with_name("hia_native_prefix.rs")
HIA_SOURCE = ROOT / "hia/prefix_match.hepta"
ADMISSION_SOURCE = ROOT / "hia/prefix_admission.hepta"
TEST_SOURCE = ROOT / "hia/tests/native_execpolicy_caller.rs"
ORIGINAL_REVISION = "f75abe3e54ac6a37bf348b9237f0b64c4c40e1fc"
ORIGINAL_TOKEN_COUNT = 286
ORIGINAL_TOKEN_SHA256 = "bca355c433aa366dddf83417e1e6e70e0c0dd2a1374319a36cff690581c0f8ce"
TOKEN = re.compile(
    r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])\''
    r'|[A-Za-z_][A-Za-z_0-9]*|\d[\d_]*(?:[a-z]\w*)?'
    r'|::|->|=>|==|!=|<=|>=|&&|\|\||\.\.=|\.\.|\S'
)


def extract_public_source():
    source = PUBLIC_SOURCE.read_text()
    start = source.index("/// Matches a single command token")
    end = source.index("#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]", start)
    section = source[start:end]
    native_method = re.compile(
        r'\s*#\[cfg\(feature\s*=\s*"hia-native"\)\]\s+'
        r'pub fn matches_prefix\(&self, cmd: &\[String\]\) -> Option<Vec<String>>\s*\{\s*'
        r'crate::hia_native_prefix::matches_prefix\(self, cmd\)\s*\}'
    )
    original, native_count = native_method.subn("", section)
    original, cfg_count = re.subn(
        r'#\[cfg\(not\(feature\s*=\s*"hia-native"\)\)\]', "", original
    )
    if (native_count, cfg_count) != (1, 2):
        raise RuntimeError("the public matcher must retain both original methods and one native delegation")
    tokens = [token for token in TOKEN.findall(original) if not token.startswith(("//", "/*"))]
    token_hash = hashlib.sha256(json.dumps(tokens, separators=(",", ":")).encode()).hexdigest()
    if len(tokens) != ORIGINAL_TOKEN_COUNT or token_hash != ORIGINAL_TOKEN_SHA256:
        raise RuntimeError("the original PatternToken/PrefixPattern source differs from its pinned Rust oracle")
    return "use std::sync::Arc;\n\n" + section, token_hash


def verify(args, report):
    rustc = shutil.which(args.rustc)
    if rustc is None:
        raise RuntimeError(f"a real Rust compiler is required: {args.rustc}")
    library = args.library_dir.resolve(strict=True)
    archive = library / "libcodex_hia_prefix_match.a"
    admission_archive = library / "libcodex_hia_prefix_admission.a"
    section, token_hash = extract_public_source()
    report["inputs"] = {
        "public_source_sha256": sha256(PUBLIC_SOURCE),
        "extracted_public_section_sha256": hashlib.sha256(section.encode()).hexdigest(),
        "original_revision": ORIGINAL_REVISION,
        "original_token_count": ORIGINAL_TOKEN_COUNT,
        "original_token_sha256": token_hash,
        "adapter_sha256": sha256(ADAPTER),
        "hia_source_sha256": sha256(HIA_SOURCE),
        "admission_source_sha256": sha256(ADMISSION_SOURCE),
        "admission_archive_sha256": sha256(admission_archive),
        "test_source_sha256": sha256(TEST_SOURCE),
        "archive_sha256": sha256(archive),
        "build_report_sha256": sha256(library / "build.json"),
    }
    report["rustc"] = run([rustc, "--version", "--verbose"], report).strip()
    with tempfile.TemporaryDirectory(prefix="codex-hia-execpolicy-caller-") as directory:
        temporary = Path(directory)
        extracted = temporary / "prefix_public.rs"
        reference = temporary / "libexecpolicy_reference.rlib"
        binary = temporary / "native_execpolicy_caller"
        extracted.write_text(section)
        run([
            rustc, "--edition=2024", "--crate-type=rlib", "--crate-name=execpolicy_reference",
            "-C", "opt-level=3", str(extracted), "-o", str(reference),
        ], report)
        environment = os.environ.copy()
        environment["CODEX_HIA_EXECPOLICY_SOURCE"] = str(extracted)
        run([
            rustc, "--edition=2024", "--test", "--cfg", 'feature="hia-native"',
            "-C", "opt-level=3", str(TEST_SOURCE),
            "--extern", f"execpolicy_reference={reference}",
            "-L", f"native={library}", "-l", "static=codex_hia_prefix_match",
            "-l", "static=codex_hia_prefix_admission",
            "-o", str(binary),
        ], report, env=environment)
        symbols = run(["nm", "--defined-only", "--extern-only", str(binary)], report)
        for symbol in ("codex_hia_prefix_match", "codex_hia_prefix_admission"):
            if not re.search(rf"\bT {symbol}$", symbols, re.MULTILINE):
                raise RuntimeError(f"the public differential executable lacks {symbol}")
        report["outputs"] = {
            "reference_rlib_sha256": sha256(reference),
            "native_test_binary_sha256": sha256(binary),
        }
        report["native_symbol_present"] = True
        stdout = run([str(binary), "--test-threads=1", "--nocapture"], report)
    summary = re.search(
        r"test result: ok\. (\d+) passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;",
        stdout,
    )
    counts = re.findall(r"native_execpolicy_original_rust_comparisons=(\d+)", stdout)
    if summary is None or int(summary.group(1)) != TEST_SOURCE.read_text().count("#[test]") or not counts:
        raise RuntimeError("the actual public differential did not execute all tests")
    report.update({
        "passed": True, "tests_passed": int(summary.group(1)), "tests_skipped": 0,
        "original_rust_comparisons": max(map(int, counts)),
        "benchmarks": re.findall(r"native_execpolicy_benchmark ([^\n]+)", stdout),
        "oracle": "complete production prefix types and methods compiled without hia-native; original tokens pinned",
        "caller": "same public source compiled with hia-native and the actual production adapter",
        "full_policy_or_core_qualification": False,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", type=Path, required=True)
    parser.add_argument("--rustc", default="rustc")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.report = args.report.resolve()
    if args.report == ROOT or ROOT in args.report.parents:
        parser.error("reports and build products must be outside the source checkout")
    report = {"schema": "codex.hia.native-execpolicy-caller.v1", "passed": False, "commands": []}
    try:
        verify(args, report)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(report["error"], file=sys.stderr)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
