#!/usr/bin/env python3
"""Verify a copied production apply_patch binary runs without HIA build paths.

This gate requires a defined native HIA search symbol, rejects HIA shared-library
dependencies, and runs the relocated CLI against exact 2 MiB files. Both newline
modes must choose a later ASCII match over an earlier Unicode-normalized match
and reproduce the original Rust executable's bytes and CLI output. The legacy
mode keeps untouched CRLF lines and writes replacement lines with LF.
Missing tools, missing symbols, linker inspection failures, and CLI failures are
errors rather than skipped checks.
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


NATIVE_SYMBOL = "codex_hia_seek_sequence"
NATIVE_SYMBOLS = (NATIVE_SYMBOL, "codex_hia_source_file", "codex_hia_parser")
INPUT_SIZE = 2 * 1024 * 1024
PATCH = (
    "*** Begin Patch\n"
    "*** Update File: large.txt\n"
    "@@\n"
    '-"token"\n'
    "+changed\n"
    "*** End Patch\n"
)


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def inspect_binary(
    binary: Path, report: dict, native: bool = True,
    required_symbols: tuple[str, ...] = NATIVE_SYMBOLS,
) -> None:
    nm = shutil.which("nm")
    readelf = shutil.which("readelf")
    if nm is None or readelf is None:
        raise RuntimeError("nm and readelf are required for the installed-binary gate")
    nm_command = [nm, "--defined-only", "--extern-only", str(binary)]
    symbols = subprocess.run(nm_command, capture_output=True, text=True, timeout=60)
    by_symbol = {
        symbol: [
            line for line in symbols.stdout.splitlines()
            if re.fullmatch(rf"\s*[0-9a-fA-F]+\s+T\s+{re.escape(symbol)}\s*", line)
        ]
        for symbol in required_symbols
    }
    definitions = [line for entries in by_symbol.values() for line in entries]
    report["symbol_check"] = {
        "command": nm_command,
        "returncode": symbols.returncode,
        "definitions": definitions,
        "definitions_by_symbol": by_symbol,
        "symbol_table_sha256": hashlib.sha256(symbols.stdout.encode()).hexdigest(),
        "stderr": symbols.stderr,
        "passed": symbols.returncode == 0 and all(
            len(entries) == int(native) for entries in by_symbol.values()
        ),
    }
    if not report["symbol_check"]["passed"]:
        raise RuntimeError(f"nm did not confirm the expected native={native} symbol profile")

    elf_command = [readelf, "-d", str(binary)]
    dynamic = subprocess.run(elf_command, capture_output=True, text=True, timeout=60)
    dependencies = re.findall(r"\(NEEDED\).*?\[([^\]]+)\]", dynamic.stdout)
    hia_dependencies = [name for name in dependencies if "libcodex_hia" in name]
    report["dynamic_dependency_check"] = {
        "command": elf_command,
        "returncode": dynamic.returncode,
        "needed": dependencies,
        "hia_dependencies": hia_dependencies,
        "stdout": dynamic.stdout,
        "stderr": dynamic.stderr,
        "passed": dynamic.returncode == 0 and not hia_dependencies,
    }
    if not report["dynamic_dependency_check"]["passed"]:
        raise RuntimeError("readelf failed or the executable depends on a HIA shared library")


def run_case(
    binary: Path, reference: Path, work: Path, preserve: bool, environment: dict, report: dict,
    *, dispatch: str = "stdin",
) -> None:
    if dispatch == "stdin":
        arguments = []
        patch_input = PATCH.encode()
    elif dispatch == "codex_arg1":
        arguments = ["--codex-run-as-apply-patch", PATCH]
        patch_input = None
    else:
        raise RuntimeError(f"unknown patch invocation: {dispatch}")
    work.mkdir()
    early_candidate = "“token”".encode()
    exact_candidate = b'"token"'
    unchanged_tail = b"tail"
    original_ending = b"\r\n"
    fixed = original_ending.join([early_candidate, b"", exact_candidate, unchanged_tail])
    filler = b"x" * (INPUT_SIZE - len(fixed) - len(original_ending))
    original = original_ending.join([early_candidate, filler, exact_candidate, unchanged_tail])
    original += original_ending
    if len(original) != INPUT_SIZE:
        raise RuntimeError("the installed test fixture must be exactly 2 MiB")
    target = work / "large.txt"
    target.write_bytes(original)
    ending = original_ending if preserve else b"\n"
    # The legacy API splits on LF; untouched CR bytes remain part of their
    # lines. Only the replacement receives the selected terminator. Require
    # the original executable to confirm this contract as well.
    expected = original_ending.join([early_candidate, filler]) + original_ending
    expected += b"changed" + ending + unchanged_tail + original_ending
    case = {
        "name": "preserve_crlf" if preserve else "legacy_lf_replacement",
        "dispatch": dispatch,
        "preserve_line_endings": "1" if preserve else "0",
        "input_bytes": len(original),
        "input_sha256": hashlib.sha256(original).hexdigest(),
        "expected_sha256": hashlib.sha256(expected).hexdigest(),
        "passed": False,
    }
    report["cases"].append(case)
    child_environment = environment.copy()
    child_environment["CODEX_APPLY_PATCH_PRESERVE_LINE_ENDINGS"] = case["preserve_line_endings"]
    started = time.monotonic()
    result = subprocess.run(
        [str(binary), *arguments], input=patch_input, capture_output=True, cwd=work,
        env=child_environment, timeout=60,
    )
    actual = target.read_bytes()
    case.update({
        "command": [str(binary), *arguments],
        "cwd": str(work),
        "patch": PATCH,
        "returncode": result.returncode,
        "elapsed_seconds": round(time.monotonic() - started, 6),
        "stdout": result.stdout.decode("utf-8", errors="replace"),
        "stderr": result.stderr.decode("utf-8", errors="replace"),
        "output_bytes": len(actual),
        "output_sha256": hashlib.sha256(actual).hexdigest(),
        "exact_contents_match": actual == expected,
        "earlier_fuzzy_candidate_unchanged": actual.startswith(early_candidate + original_ending),
        "later_ascii_candidate_replaced": actual.endswith(b"changed" + ending + unchanged_tail + original_ending),
        "line_endings_match": actual.count(b"\r\n") == (4 if preserve else 3) and actual.count(b"\n") == 4,
    })
    reference_work = work.with_name(work.name + "-reference")
    reference_work.mkdir()
    reference_target = reference_work / "large.txt"
    reference_target.write_bytes(original)
    original_result = subprocess.run(
        [str(reference), *arguments], input=patch_input, capture_output=True, cwd=reference_work,
        env=child_environment, timeout=60,
    )
    original_output = reference_target.read_bytes()
    case["original_rust"] = {
        "command": [str(reference), *arguments],
        "returncode": original_result.returncode,
        "stdout": original_result.stdout.decode("utf-8", errors="replace"),
        "stderr": original_result.stderr.decode("utf-8", errors="replace"),
        "output_bytes": len(original_output),
        "output_sha256": hashlib.sha256(original_output).hexdigest(),
        "exact_contents_match": original_output == actual == expected,
        "cli_output_matches": (original_result.returncode, original_result.stdout, original_result.stderr)
        == (result.returncode, result.stdout, result.stderr),
    }
    expected_stdout = b"Success. Updated the following files:\nM large.txt\n"
    if result.returncode != 0:
        raise RuntimeError(f"installed apply_patch failed: {case['name']}")
    if result.stdout != expected_stdout or result.stderr:
        raise RuntimeError(f"installed apply_patch output differs from the CLI contract: {case['name']}")
    if actual != expected:
        raise RuntimeError(f"installed patch changed the wrong candidate or line endings: {case['name']}")
    if not case["original_rust"]["exact_contents_match"] or not case["original_rust"]["cli_output_matches"]:
        raise RuntimeError(f"installed HIA executable differs from original Rust: {case['name']}")
    case["passed"] = True
    print(f"PASS {case['name']}: {len(original)} input bytes, later ASCII match, original Rust parity")


def run_source_file_case(
    binary: Path, reference: Path, work: Path, environment: dict, report: dict,
    *, dispatch: str = "stdin",
) -> None:
    """Exercise mixed endings and a missing final ending through the installed owner."""
    original = b"alpha\rbeta\r\ngamma\ndelta"
    expected = b"alpha\rbeta one\rbeta two\rgamma\ndelta\r"
    patch = "*** Begin Patch\n*** Update File: mixed.txt\n@@\n-beta\n+beta one\n+beta two\n*** End Patch\n"
    if dispatch == "stdin":
        arguments, patch_input = [], patch.encode()
    elif dispatch == "codex_arg1":
        arguments, patch_input = ["--codex-run-as-apply-patch", patch], None
    else:
        raise RuntimeError(f"unknown patch invocation: {dispatch}")
    child_environment = environment.copy()
    child_environment["CODEX_APPLY_PATCH_PRESERVE_LINE_ENDINGS"] = "1"
    case = {
        "name": "preserve_mixed_endings_and_unterminated_tail", "dispatch": dispatch,
        "preserve_line_endings": "1", "input_bytes": len(original),
        "input_sha256": hashlib.sha256(original).hexdigest(),
        "expected_sha256": hashlib.sha256(expected).hexdigest(), "passed": False,
    }
    report["cases"].append(case)
    observations = []
    for variant, executable in (("native", binary), ("original_rust", reference)):
        directory = work if variant == "native" else work.with_name(work.name + "-reference")
        directory.mkdir()
        target = directory / "mixed.txt"
        target.write_bytes(original)
        started = time.monotonic()
        result = subprocess.run(
            [str(executable), *arguments], input=patch_input, capture_output=True,
            cwd=directory, env=child_environment, timeout=60,
        )
        actual = target.read_bytes()
        observations.append((result.returncode, result.stdout, result.stderr, actual))
        case[variant] = {
            "returncode": result.returncode, "elapsed_seconds": round(time.monotonic() - started, 6),
            "stdout": result.stdout.decode(errors="replace"),
            "stderr": result.stderr.decode(errors="replace"),
            "output_bytes": len(actual), "output_sha256": hashlib.sha256(actual).hexdigest(),
            "exact_contents_match": actual == expected,
        }
    contract = (0, b"Success. Updated the following files:\nM mixed.txt\n", b"", expected)
    if observations != [contract, contract]:
        raise RuntimeError("installed SourceFile behavior differs from original Rust or mixed-ending contract")
    case["original_rust_parity"] = True
    case["passed"] = True
    print(f"PASS mixed endings and unterminated tail: {dispatch}, original Rust parity")


def run_parser_cases(
    binary: Path, reference: Path, work: Path, environment: dict, report: dict,
    *, dispatch: str = "stdin",
) -> None:
    """Check complete grammar and parse-error atomicity in the installed product."""
    initial = {"old.txt": b"first\r\ncontext\r\nold\r\nlast\r\n", "delete.txt": b"remove me\n"}
    rich_patch = (
        "\u2003<<'EOF'\r\n*** Begin Patch \t\r\n"
        "*** Add File: 新文件.txt \t\r\n+alpha\r\n+βeta\r\n"
        "*** Update File: old.txt\r\n*** Move to: renamed.txt\r\n"
        "@@ context\r\n-old\r\n+new\r\n last\r\n*** End of File\r\n"
        "*** Delete File: delete.txt\r\n*** End Patch \t\r\nEOF\u3000"
    )
    repeated_context = (
        "*** Begin Patch\n*** Add File: created.txt\n+must not persist\n"
        "*** Update File: old.txt\n@@\n@@ again\n*** End Patch"
    )
    duplicate_environment = (
        "*** Begin Patch\n*** Environment ID: first\n*** Environment ID: second\n"
        "*** Delete File: old.txt\n*** End Patch"
    )
    fixtures = (
        (
            "heredoc_unicode_paths_move_context_eof", rich_patch, 0,
            "Success. Updated the following files:\nA 新文件.txt\nM renamed.txt\nD delete.txt\n".encode(),
            b"", {"新文件.txt": "alpha\nβeta\n".encode(), "renamed.txt": b"first\r\ncontext\r\nnew\r\nlast\r\n"},
        ),
        (
            "syntax_error_does_not_apply_accepted_prefix", repeated_context, 1, b"",
            b"Invalid patch hunk on line 6: Unexpected line found in update hunk: '@@ again'. "
            b"Every line should start with ' ' (context line), '+' (added line), or '-' (removed line)\n",
            initial,
        ),
        (
            "duplicate_environment_error", duplicate_environment, 1, b"",
            b"Invalid patch: apply_patch environment_id cannot be specified more than once\n", initial,
        ),
    )
    work.mkdir()
    child_environment = environment.copy()
    child_environment["CODEX_APPLY_PATCH_PRESERVE_LINE_ENDINGS"] = "1"
    for name, patch, exit_code, stdout, stderr, expected_files in fixtures:
        if dispatch == "stdin":
            arguments, patch_input = [], patch.encode()
        elif dispatch == "codex_arg1":
            arguments, patch_input = ["--codex-run-as-apply-patch", patch], None
        else:
            raise RuntimeError(f"unknown patch invocation: {dispatch}")
        case = {
            "name": name, "dispatch": dispatch, "passed": False,
            "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
            "expected_exit_code": exit_code,
        }
        report["cases"].append(case)
        observations = []
        for variant, executable in (("native", binary), ("original_rust", reference)):
            directory = work / f"{name}-{variant}"
            directory.mkdir()
            for filename, contents in initial.items():
                (directory / filename).write_bytes(contents)
            started = time.monotonic()
            result = subprocess.run(
                [str(executable), *arguments], input=patch_input, capture_output=True,
                cwd=directory, env=child_environment, timeout=60,
            )
            entries = list(directory.iterdir())
            if any(not entry.is_file() for entry in entries):
                raise RuntimeError(f"installed parser case created an unexpected directory: {name}")
            actual_files = {entry.name: entry.read_bytes() for entry in entries}
            observations.append((result.returncode, result.stdout, result.stderr, actual_files))
            case[variant] = {
                "returncode": result.returncode,
                "elapsed_seconds": round(time.monotonic() - started, 6),
                "stdout": result.stdout.decode(errors="replace"),
                "stderr": result.stderr.decode(errors="replace"),
                "files_sha256": {
                    filename: hashlib.sha256(contents).hexdigest()
                    for filename, contents in sorted(actual_files.items())
                },
                "exact_contents_match": actual_files == expected_files,
            }
        contract = (exit_code, stdout, stderr, expected_files)
        if observations != [contract, contract]:
            raise RuntimeError(f"installed parser differs from original Rust or the exact contract: {name}")
        case["original_rust_parity"] = True
        case["passed"] = True
        print(f"PASS installed parser {name}: {dispatch}, exact original Rust parity")


def verify(args: argparse.Namespace, report: dict) -> None:
    binary = args.binary.resolve(strict=True)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError(f"an executable production apply_patch binary is required: {binary}")
    report["binary"] = str(binary)
    report["binary_sha256"] = sha256(binary)
    inspect_binary(binary, report)
    reference = args.reference_binary.resolve(strict=True)
    if not reference.is_file() or not os.access(reference, os.X_OK):
        raise RuntimeError(f"an executable original Rust apply_patch is required: {reference}")
    report["reference_binary"] = {"path": str(reference), "sha256": sha256(reference)}
    inspect_binary(reference, report["reference_binary"], native=False)
    environment = os.environ.copy()
    removed = ["CODEX_HIA_NATIVE_LIB_DIR", "LD_LIBRARY_PATH"]
    for name in removed:
        environment.pop(name, None)
    report["removed_child_environment_variables"] = removed
    with tempfile.TemporaryDirectory(prefix="codex-hia-installed-patch-") as directory:
        temporary = Path(directory)
        installed_dir = temporary / "bin"
        work_dir = temporary / "work"
        installed_dir.mkdir()
        work_dir.mkdir()
        installed = installed_dir / "apply_patch"
        shutil.copy2(binary, installed)
        report["installed_binary_sha256"] = sha256(installed)
        if report["installed_binary_sha256"] != report["binary_sha256"]:
            raise RuntimeError("the copied executable differs from the inspected binary")
        run_case(installed, reference, work_dir / "legacy-lf", False, environment, report)
        run_case(installed, reference, work_dir / "preserve-crlf", True, environment, report)
        run_source_file_case(installed, reference, work_dir / "mixed-endings", environment, report)
        run_parser_cases(installed, reference, work_dir / "parser", environment, report)
    report["passed"] = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--reference-binary", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = {"schema": "codex.hia.installed-patch.v1", "passed": False, "cases": [], "skipped": 0}
    try:
        verify(args, report)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        report["error"] = str(error)
        print(str(error), file=sys.stderr)
    report["cases_passed"] = sum(case["passed"] for case in report["cases"])
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
