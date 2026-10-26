#!/usr/bin/env python3
"""Execute six native refusal controls separately from the original scope."""

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


GROUPS = []
for role in ("workspace", "readonly"):
    names = [
        f"legacy_{role}_unavailable_tests::legacy_ambient_{role}_{suffix}"
        for suffix in (
            "capture_never_reaches_process_creation",
            "preflight_refuses_before_acl_setup",
            "returns_no_token",
        )
    ]
    GROUPS.append(
        {
            "id": f"legacy-{role}-refusal-controls",
            "package": "codex-windows-sandbox",
            "filter": " | ".join(f"test(={name})" for name in names),
            "expectedTestCount": 3,
            "requiredTests": names,
        }
    )


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
        "schema": "hepta.windows-final-safety-receipt.v1",
        "startedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "FAIL_NEW_LEGACY_REFUSAL_CONTROLS",
        "groups": [],
        "testRetries": 0,
        "productionAuthorityGranted": False,
        "finalProductQualification": False,
        "scope": "Six refusal controls only; never combined with original91 functional results",
    }
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
        ]
        hashes = {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in protected
        }
        receipt["protectedInputSha256"] = hashes
        temporary = Path(os.environ["RUNNER_TEMP"]) / "hepta-final-safety-case-temp"
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
            receipt["status"] = "PASS_NEW_LEGACY_REFUSAL_CONTROLS"
    except (
        OSError,
        ValueError,
        RuntimeError,
        KeyError,
        subprocess.SubprocessError,
    ) as error:
        receipt["error"] = str(error)
    receipt["finishedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)
    return 0 if receipt["status"] == "PASS_NEW_LEGACY_REFUSAL_CONTROLS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
