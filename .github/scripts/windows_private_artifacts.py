#!/usr/bin/env python3
"""Execute native retained-artifact controls separately from original91 and six refusals."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

from windows_current_ci import ANSI, assess, execute_groups, git, source, valid_source


NAMES = [
    "private_artifacts_windows::tests::" + suffix
    for suffix in (
        "native_private_roundtrip_flush_and_read_only_custody",
        "native_atomic_replace_uses_original_retained_directory",
        "native_foreign_read_directory_is_refused_without_acl_repair",
        "native_checked_names_and_case_aliases_have_no_effect",
        "native_hardlink_cannot_be_read_hashed_or_replaced",
        "native_retained_directory_replacement_fails_closed",
        "native_sidecar_lock_excludes_second_writer_until_drop",
        "native_directory_acl_change_invalidates_original_custody",
        "native_reparse_directory_is_refused_before_child_effect",
    )
]
GROUPS = [
    {
        "id": "retained-private-artifact-controls",
        "package": "codex-utils-path",
        "filter": " | ".join(f"test(={name})" for name in NAMES),
        "expectedTestCount": 9,
        "requiredTests": NAMES,
    }
]


def assess_exact(group, code, log):
    result = assess(group, code, log)
    text = ANSI.sub("", log)
    terminals = re.findall(
        r"^\s*(PASS|FAIL|TIMEOUT|EXECFAIL|LEAK|SKIP)\s+\[[^\]\n]+\]\s+"
        r"(?:\(\s*\d+/\d+\)\s+)?(\S+)\s+(\S+)\s*$",
        text,
        re.MULTILINE,
    )
    expected = set(group["requiredTests"])
    names = [name for _, _, name in terminals]
    exact = (
        len(re.findall(r"Starting (\d+) tests across", text)) == 1
        and len(terminals) == len(expected) == group["expectedTestCount"]
        and set(names) == expected
        and all(
            status == "PASS" and package == group["package"]
            for status, package, _ in terminals
        )
    )
    result.update(
        strictTerminalSetMatches=exact,
        duplicateTests=sorted({name for name in names if names.count(name) > 1}),
        unexpectedTests=sorted(set(names) - expected),
        terminalCount=len(terminals),
        passed=result["passed"] and exact,
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if sys.platform != "win32" or not re.fullmatch(r"[0-9a-f]{40}", args.expected_head):
        raise RuntimeError("an actual Windows runner and exact commit are required")
    if output.is_relative_to(root) or output.exists():
        raise RuntimeError("choose a new output outside the source checkout")
    output.mkdir(parents=True)
    receipt = {
        "schema": "hepta.windows-private-artifacts-receipt.v1",
        "startedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "FAIL_NEW_PRIVATE_ARTIFACT_CONTROLS",
        "groups": [],
        "testRetries": 0,
        "productionAuthorityGranted": False,
        "finalProductQualification": False,
        "scope": "Nine retained-artifact controls only; never combined with original91 or six legacy refusal results",
    }
    tool_files = {}
    hashes = {}
    before = None
    try:
        before = source(root)
        untracked_before = git(root, "status", "--porcelain", "--untracked-files=all")
        receipt.update(
            sourceBefore=before,
            sourceStatusBefore=untracked_before,
            platform=platform.platform(),
            machine=platform.machine(),
        )
        if before["head"] != args.expected_head or untracked_before:
            raise RuntimeError("source differs from the requested clean head")
        compiler = subprocess.check_output(
            ["rustc", "--version", "--verbose"], text=True
        )
        versions = {
            "rustc": compiler,
            "cargo": subprocess.check_output(["cargo", "--version"], text=True),
            "just": subprocess.check_output(["just", "--version"], text=True),
            "nextest": subprocess.check_output(
                ["cargo", "nextest", "--version"], text=True
            ),
        }
        receipt["toolVersions"] = versions
        if not (
            compiler.startswith("rustc 1.96.0 ")
            and "host: x86_64-pc-windows-msvc" in compiler
            and versions["cargo"].startswith("cargo 1.96.0 ")
            and versions["just"].strip() == "just 1.51.0"
            and versions["nextest"].startswith("cargo-nextest 0.9.103")
        ):
            raise RuntimeError(
                "native compiler or original test runner differs from its pin"
            )
        tool_files = {
            name: Path(
                subprocess.check_output(
                    ["rustup", "which", "--toolchain", "1.96.0", name], text=True
                ).strip()
            ).resolve(strict=True)
            for name in ("rustc", "cargo")
        }
        for name in ("just", "cargo-nextest"):
            executable = shutil.which(name)
            if executable is None:
                raise RuntimeError("a pinned test runner executable is missing")
            tool_files[name] = Path(executable).resolve(strict=True)
        tool_records = {
            name: {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for name, path in tool_files.items()
        }
        receipt["toolFiles"] = tool_records
        protected = [
            root / ".github/scripts/windows_current_ci.py",
            root / ".github/fixtures/windows-current-ci-scope.json",
            root / "codex-rs/Cargo.lock",
            root / ".github/scripts/windows_private_artifacts.py",
            root / "codex-rs/utils/path-utils/src/private_artifacts_windows_tests.rs",
        ]
        hashes = {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in protected
        }
        receipt["protectedInputSha256"] = hashes
        temporary = (
            Path(os.environ["RUNNER_TEMP"]) / "hepta-private-artifacts-case-temp"
        )
        temporary.mkdir(exist_ok=False)
        native_temp = temporary.resolve(strict=True)
        receipt["temporaryEnvironment"] = {
            "originalTemp": os.environ.get("TEMP"),
            "originalTmp": os.environ.get("TMP"),
            "physicalCaseTemp": str(native_temp),
        }
        os.environ["TEMP"] = os.environ["TMP"] = str(native_temp)
        raw = execute_groups(root, output, GROUPS)
        if [row["id"] for row in raw] != [group["id"] for group in GROUPS]:
            raise RuntimeError("missing, duplicate or unknown result group")
        results = []
        for group, row in zip(GROUPS, raw):
            log = output / (group["id"] + ".log")
            result = assess_exact(
                group, row["exitCode"], log.read_text(encoding="utf-8")
            )
            result.update(
                command=row["command"],
                durationSeconds=row["durationSeconds"],
                logSha256=hashlib.sha256(log.read_bytes()).hexdigest(),
            )
            results.append(result)
        after = source(root)
        untracked_after = git(root, "status", "--porcelain", "--untracked-files=all")
        intact = valid_source(args.expected_head, before, after) and not untracked_after
        intact = intact and hashes == {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in protected
        }
        tools_intact = all(
            hashlib.sha256(path.read_bytes()).hexdigest()
            == tool_records[name]["sha256"]
            for name, path in tool_files.items()
        )
        receipt.update(
            sourceAfter=after,
            sourceStatusAfter=untracked_after,
            sourceUnchanged=intact,
            toolFilesUnchanged=tools_intact,
            groups=results,
        )
        if intact and tools_intact and all(result["passed"] for result in results):
            receipt["status"] = "PASS_NEW_PRIVATE_ARTIFACT_CONTROLS"
    except (
        OSError,
        ValueError,
        RuntimeError,
        KeyError,
        subprocess.SubprocessError,
    ) as error:
        receipt["error"] = str(error)
    finally:
        # Actual after facts are collected even if setup/parser/compile refuses.
        # Missing observations remain explicit failures, never inferred matches.
        try:
            after = source(root)
            status_after = git(root, "status", "--porcelain", "--untracked-files=all")
            receipt["sourceAfter"] = after
            receipt["sourceStatusAfter"] = status_after
            receipt["sourceUnchanged"] = (
                before is not None
                and valid_source(args.expected_head, before, after)
                and not status_after
            )
            receipt["toolFilesAfter"] = {
                name: {
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for name, path in tool_files.items()
            }
            receipt["toolFilesUnchanged"] = (
                bool(tool_files)
                and receipt.get("toolFiles") == receipt["toolFilesAfter"]
            )
            protected_after = {
                relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
                for relative in hashes
            }
            receipt["protectedInputsUnchanged"] = (
                bool(hashes) and protected_after == hashes
            )
            if not (
                receipt["sourceUnchanged"]
                and receipt["toolFilesUnchanged"]
                and receipt["protectedInputsUnchanged"]
            ):
                receipt["status"] = "FAIL_NEW_PRIVATE_ARTIFACT_CONTROLS"
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            receipt["afterObservationError"] = str(error)
            receipt["status"] = "FAIL_NEW_PRIVATE_ARTIFACT_CONTROLS"
    receipt["finishedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)
    return 0 if receipt["status"] == "PASS_NEW_PRIVATE_ARTIFACT_CONTROLS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
