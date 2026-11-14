#!/usr/bin/env python3
"""Verify HIA components in a relocated full Codex CLI against its Rust build.

Require all production HIA symbols in the full executable. Exercise its
apply_patch alias and internal patch dispatch, both newline modes, and ordinary
help/version startup after removing HIA artifact and shared-library paths.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from test_installed_patch import inspect_binary
from test_installed_patch import run_case
from test_installed_patch import sha256


NATIVE_SYMBOLS = (
    "codex_hia_seek_sequence",
    "codex_hia_utf8_prefix",
    "codex_hia_metric_tag",
    "codex_hia_markdown_location",
    "codex_hia_ascii_json_fragment",
)


def verify(args: argparse.Namespace, report: dict) -> None:
    binary = args.binary.resolve(strict=True)
    reference = args.reference_binary.resolve(strict=True)
    for path in (binary, reference):
        if not path.is_file() or not os.access(path, os.X_OK):
            raise RuntimeError(f"an executable full Codex binary is required: {path}")
    report["binary"] = str(binary)
    report["binary_sha256"] = sha256(binary)
    inspect_binary(binary, report, required_symbols=NATIVE_SYMBOLS)
    report["reference_binary"] = {"path": str(reference), "sha256": sha256(reference)}
    inspect_binary(reference, report["reference_binary"], native=False, required_symbols=NATIVE_SYMBOLS)

    environment = os.environ.copy()
    removed = ["CODEX_HIA_NATIVE_LIB_DIR", "LD_LIBRARY_PATH"]
    for name in removed:
        environment.pop(name, None)
    report["removed_child_environment_variables"] = removed
    with tempfile.TemporaryDirectory(prefix="codex-hia-installed-cli-") as directory:
        root = Path(directory)
        (root / "home").mkdir()
        environment["CODEX_HOME"] = str(root / "home")
        paths = {}
        for variant, source in (("native", binary), ("reference", reference)):
            install = root / variant / "bin"
            install.mkdir(parents=True)
            for name in ("codex", "apply_patch"):
                destination = install / name
                shutil.copy2(source, destination)
                if sha256(destination) != sha256(source):
                    raise RuntimeError("the relocated executable differs from its inspected source")
                paths[variant, name] = destination
        report["relocated_copies_match"] = True

        for option in ("--help", "--version"):
            outputs = []
            for variant in ("native", "reference"):
                result = subprocess.run(
                    [str(paths[variant, "codex"]), option], cwd=root,
                    env=environment, capture_output=True, timeout=60,
                )
                outputs.append((result.returncode, result.stdout, result.stderr))
            passed = outputs[0] == outputs[1] and outputs[0][0] == 0 and bool(outputs[0][1])
            report["startup_cases"].append({
                "argument": option, "passed": passed,
                "returncode": outputs[0][0],
                "stdout": outputs[0][1].decode(errors="replace"),
                "stderr": outputs[0][2].decode(errors="replace"),
                "original_output_matches": outputs[0] == outputs[1],
            })
            if not passed:
                raise RuntimeError(f"relocated Codex startup differs from the original: {option}")
            print(f"PASS full Codex {option}: original Rust parity")

        for dispatch, name in (("stdin", "apply_patch"), ("codex_arg1", "codex")):
            for preserve in (False, True):
                work = root / f"{dispatch}-{'crlf' if preserve else 'lf'}"
                run_case(
                    paths["native", name], paths["reference", name], work,
                    preserve, environment, report, dispatch=dispatch,
                )
    report["passed"] = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--reference-binary", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = {
        "schema": "codex.hia.installed-cli.v1", "passed": False,
        "cases": [], "startup_cases": [], "skipped": 0,
        "whole_codex_rewritten": False,
    }
    try:
        verify(args, report)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        report["error"] = str(error)
        print(str(error), file=sys.stderr)
    report["cases_passed"] = sum(case["passed"] for case in report["cases"])
    report["startup_cases_passed"] = sum(case["passed"] for case in report["startup_cases"])
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
