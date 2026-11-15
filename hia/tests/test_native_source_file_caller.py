#!/usr/bin/env python3
"""Compare actual HIA SourceFile calls with the complete immutable Rust file.

Only the agreed native re-export and five cfg guards are removed. Every byte
of the resulting original file must match both its pinned SHA256 and Git blob.
The offline oracle needs no historical Git objects, network, or Cargo build.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from test_native_string_caller import run, sha256


ROOT = Path(__file__).resolve().parents[2]
PUBLIC_SOURCE = ROOT / "codex-rs/apply-patch/src/text_file.rs"
ADAPTER = ROOT / "codex-rs/apply-patch/src/hia_native_text_file.rs"
HIA_SOURCE = ROOT / "hia/source_file.hepta"
TEST_SOURCE = ROOT / "hia/tests/native_source_file_caller.rs"
BASELINE_REVISION = "a3f319cfba26b3206d9bfecbdefed2515ce4a19c"
BASELINE_BLOB = "b7d598ca973ec73f0ed064d2360f4d218e2a792d"
BASELINE_SHA256 = "35cbbdeb91e86780d99fccd097a5dba2772f048730556b73d685e94658ddc6e3"
BASELINE_BYTES = 3851
NATIVE_PREFIX = (
    b'#[cfg(feature = "hia-native")]\n'
    b'pub(super) use crate::hia_native_text_file::SourceFile;\n\n'
)
ORIGINAL_GUARD = b'#[cfg(not(feature = "hia-native"))]\n'
REFERENCE_WRAPPER = '''
mod original {
    include!("source_file_original.rs");
}

pub type Replacement = (usize, usize, Vec<String>);
pub struct SourceFile(original::SourceFile);
impl SourceFile {
    pub fn parse(contents: &str) -> Self { Self(original::SourceFile::parse(contents)) }
    pub fn line_texts(&self) -> Vec<String> { self.0.line_texts() }
    pub fn apply_replacements(&mut self, replacements: &[Replacement]) {
        self.0.apply_replacements(replacements);
    }
    pub fn into_contents(self) -> String { self.0.into_contents() }
}
'''


def original_rust_source(source):
    if not source.startswith(NATIVE_PREFIX) or source.count(NATIVE_PREFIX) != 1:
        raise RuntimeError("SourceFile lost its exact agreed native re-export prefix")
    if source.count(ORIGINAL_GUARD) != 5:
        raise RuntimeError("SourceFile must have exactly five original-item cfg guards")
    original = source[len(NATIVE_PREFIX):].replace(ORIGINAL_GUARD, b"")
    digest = hashlib.sha256(original).hexdigest()
    blob = hashlib.sha1(b"blob " + str(len(original)).encode() + b"\0" + original).hexdigest()
    if (len(original), digest, blob) != (BASELINE_BYTES, BASELINE_SHA256, BASELINE_BLOB):
        raise RuntimeError("the complete recovered SourceFile differs from the immutable original Git blob")
    return original


def verify(args, report):
    rustc = shutil.which(args.rustc)
    if rustc is None:
        raise RuntimeError(f"a real Rust compiler is required: {args.rustc}")
    original = original_rust_source(PUBLIC_SOURCE.read_bytes())
    library_dir = args.library_dir.resolve(strict=True)
    archive = library_dir / "libcodex_hia_source_file.a"
    build_path = library_dir / "build.json"
    build = json.loads(build_path.read_text())
    if build.get("status") != "built" or build.get("compiler_fixed_point") is not True:
        raise RuntimeError("the SourceFile caller requires an actual fixed-point HIA build")
    component = build["modules"]["source_file"]
    abi = component["codex_link_abi"]
    if component["source_sha256"] != sha256(HIA_SOURCE):
        raise RuntimeError("the SourceFile HIA artifact has a different source")
    if abi["archive_sha256"] != sha256(archive) or abi["symbol"] != "codex_hia_source_file":
        raise RuntimeError("the SourceFile archive or symbol differs from its build report")
    report["inputs"] = {
        "public_source_sha256": sha256(PUBLIC_SOURCE), "adapter_sha256": sha256(ADAPTER),
        "hia_source_sha256": sha256(HIA_SOURCE), "archive_sha256": sha256(archive),
        "build_report_sha256": sha256(build_path), "compiler_sha256": build["compiler_sha256"],
        "test_source_sha256": sha256(TEST_SOURCE), "test_runner_sha256": sha256(Path(__file__)),
        "original_revision": BASELINE_REVISION, "original_blob": BASELINE_BLOB,
        "original_file_sha256": hashlib.sha256(original).hexdigest(), "original_file_bytes": len(original),
        "reference_wrapper_sha256": hashlib.sha256(REFERENCE_WRAPPER.encode()).hexdigest(),
    }
    report["rustc"] = run([rustc, "--version", "--verbose"], report).strip()
    flags = [rustc, "--edition=2024", "-C", "debug-assertions=on", "-C", "overflow-checks=on"]
    with tempfile.TemporaryDirectory(prefix="codex-hia-source-file-caller-") as directory:
        temporary = Path(directory)
        original_path = temporary / "source_file_original.rs"
        wrapper = temporary / "source_file_reference.rs"
        reference = temporary / "libsource_file_reference.rlib"
        binary = temporary / "native_source_file_caller"
        original_path.write_bytes(original)
        wrapper.write_text(REFERENCE_WRAPPER)
        run(flags + ["--crate-name", "source_file_reference", "--crate-type", "rlib",
                     str(wrapper), "-o", str(reference)], report)
        run(flags + ["--test", "--cfg", 'feature="hia-native"', str(TEST_SOURCE),
                     "--extern", f"source_file_reference={reference}", "-L", f"native={library_dir}",
                     "-l", "static=codex_hia_source_file", "-o", str(binary)], report)
        report["outputs"] = {
            "compiled_original_file_sha256": sha256(original_path),
            "reference_rlib_sha256": sha256(reference), "native_test_binary_sha256": sha256(binary),
        }
        stdout = run([str(binary), "--test-threads=1", "--nocapture"], report)
    summary = re.search(r"test result: ok\. (\d+) passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;", stdout)
    counts = re.findall(r"native_source_file_original_rust_comparisons=(\d+)", stdout)
    preconditions = re.findall(r"native_source_file_separate_precondition_failures=(\d+)", stdout)
    if summary is None or int(summary.group(1)) != TEST_SOURCE.read_text().count("#[test]") or not counts:
        raise RuntimeError("the SourceFile caller did not execute all original Rust comparisons")
    if preconditions != ["2"]:
        raise RuntimeError("missing separate nonmonotonic/overflow precondition checks")
    report.update({
        "passed": True, "tests_passed": int(summary.group(1)), "tests_skipped": 0,
        "original_rust_comparisons": max(map(int, counts)), "separate_precondition_failures": 2,
        "oracle": "complete 3851-byte original SourceFile with exact SHA256 and Git blob; independent rlib; no algorithm extraction or normalization",
        "caller": "actual feature-selected production text_file.rs re-export and HIA adapter linked to the source-bound native archive",
        "invalid_input_scope": "nonmonotonic and start+old_len overflow are separate precondition failures; no post-panic state or release-overflow equivalence claim",
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", required=True, type=Path)
    parser.add_argument("--rustc", default="rustc")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = {"schema": "codex.hia.native-source-file-caller.v1", "passed": False, "commands": []}
    try:
        verify(args, report)
    except (OSError, RuntimeError, KeyError, ValueError, subprocess.TimeoutExpired) as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(report["error"], file=sys.stderr)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
