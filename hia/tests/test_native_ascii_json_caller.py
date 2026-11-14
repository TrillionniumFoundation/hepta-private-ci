#!/usr/bin/env python3
"""Compare actual default/native string crates using the public JSON API."""

import argparse
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
TEST = ROOT / "hia/tests/native_ascii_json_caller.rs"


def verify(args, report):
    rustc = shutil.which(args.rustc)
    if rustc is None:
        raise RuntimeError(f"a real Rust compiler is required: {args.rustc}")
    library = args.library_dir.resolve(strict=True)
    report["inputs"] = {name: sha256(ROOT / name) for name in [
        "codex-rs/utils/string/src/json.rs", "codex-rs/utils/string/src/hia_native_ascii_json.rs",
        "hia/ascii_json_fragment.hepta", "hia/tests/native_ascii_json_caller.rs",
    ]}
    report["inputs"]["archive_sha256"] = sha256(library / "libcodex_hia_ascii_json_fragment.a")
    report["inputs"]["build_report_sha256"] = sha256(library / "build.json")
    report["rustc"] = run([rustc, "--version", "--verbose"], report).strip()
    os.chdir(ROOT / "codex-rs")
    report["working_directory"] = str(Path.cwd())
    with tempfile.TemporaryDirectory(prefix="codex-hia-ascii-json-") as directory:
        temporary = Path(directory)
        environment = os.environ.copy()
        environment["RUSTC"] = rustc
        environment["CARGO_TARGET_DIR"] = str(Path(environment.get("CARGO_TARGET_DIR", temporary / "target")).resolve())
        variants = {}
        for variant, flags in [("native", ["--features", "hia-native"]), ("reference", [])]:
            child = environment.copy()
            child.pop("CODEX_HIA_NATIVE_LIB_DIR", None)
            if variant == "native":
                child["CODEX_HIA_NATIVE_LIB_DIR"] = str(library)
            stdout = run([
                "cargo", "build", "--locked", "-p", "codex-utils-string", "--message-format=json", *flags,
            ], report, env=child)
            artifacts = [json.loads(line) for line in stdout.splitlines() if line.startswith('{"reason":')]
            by_name = {a["target"]["name"]: a for a in artifacts if a.get("reason") == "compiler-artifact"}
            rlib = next(Path(p) for p in by_name["codex_utils_string"]["filenames"] if p.endswith(".rlib"))
            # Cargo's top-level rlib path is overwritten by the second build.
            copied = temporary / f"lib{variant}_string.rlib"
            shutil.copyfile(rlib, copied)
            variants[variant] = {"path": str(copied), "sha256": sha256(copied), "dependencies": {}}
            for dependency in ["serde", "serde_json"]:
                path = next(Path(p) for p in by_name[dependency]["filenames"] if p.endswith(".rlib"))
                variants[variant]["dependencies"][dependency] = {"path": str(path), "sha256": sha256(path)}
        if variants["native"]["sha256"] == variants["reference"]["sha256"]:
            raise RuntimeError("the independent native and original crate builds are identical")
        if variants["native"]["dependencies"] != variants["reference"]["dependencies"]:
            raise RuntimeError("the native and original crates use different Serde dependencies")
        report["crate_builds"] = variants
        binary = temporary / "ascii_json_caller"
        command = [rustc, "--edition=2024", "--test", str(TEST)]
        for variant, item in variants.items():
            command += ["--extern", f"{variant}_string={item['path']}"]
        for name, item in variants["native"]["dependencies"].items():
            command += ["--extern", f"{name}={item['path']}"]
        dependency_dir = str(Path(variants["native"]["dependencies"]["serde"]["path"]).parent)
        command += ["-L", f"dependency={dependency_dir}", "-L", f"native={library}", "-o", str(binary)]
        run(command, report, env=environment)
        symbols = run(["nm", "--defined-only", "--extern-only", str(binary)], report)
        if not any(line.endswith(" codex_hia_ascii_json_fragment") for line in symbols.splitlines()):
            raise RuntimeError("the differential executable does not contain the native HIA encoder")
        report["test_binary_sha256"] = sha256(binary)
        report["native_symbol_present"] = True
        stdout = run([str(binary), "--test-threads=1", "--nocapture"], report)
    summary = re.search(r"test result: ok\. (\d+) passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;", stdout)
    counts = re.findall(r"native_ascii_json_original_rust_comparisons=(\d+)", stdout)
    if summary is None or int(summary.group(1)) != TEST.read_text().count("#[test]") or not counts:
        raise RuntimeError("the actual crate differential did not execute all tests")
    report.update({"passed": True, "tests_passed": int(summary.group(1)), "skipped": 0,
                   "original_rust_comparisons": max(map(int, counts)),
                   "oracle": "actual complete string crate built without hia-native"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", required=True, type=Path)
    parser.add_argument("--rustc", default="rustc")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    args.report = args.report.resolve()
    report = {"schema": "codex.hia.native-ascii-json-caller.v1", "passed": False, "commands": []}
    try:
        verify(args, report)
    except (OSError, RuntimeError, KeyError, StopIteration, subprocess.TimeoutExpired) as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(report["error"], file=sys.stderr)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
