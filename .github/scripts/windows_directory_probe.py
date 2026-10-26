#!/usr/bin/env python3
"""Collect native directory facts; assess capability separately from collection."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from windows_current_ci import execute_groups, git, source, valid_source
from windows_final_safety import assess_exact

TEST = "sqlite_recovery::windows::tests::directory_probe::records_native_directory_flush_capability"
GROUP = {
    "id": "native-directory-probe",
    "package": "codex-state",
    "filter": f"test(={TEST})",
    "expectedTestCount": 1,
    "requiredTests": [TEST],
}
MODES = [
    "ordinary-read",
    "backup-read",
    "backup-read-write",
    "backup-read-write-reparse",
]


def valid_facts(row):
    identity = row.get("fileId128", [])
    descriptor = row.get("descriptorBytes", [])
    return (
        row.get("fileIdQuery", {}).get("ok") is True
        and isinstance(row.get("volumeSerialNumber"), int)
        and row["volumeSerialNumber"] > 0
        and len(identity) == 16
        and all(type(value) is int and 0 <= value <= 255 for value in identity)
        and any(identity)
        and row.get("descriptorRead", {}).get("ok") is True
        and row.get("statePrivateSecurity", {}).get("ok") is True
        and row.get("stateFullSnapshotAccepted") is True
        and row.get("descriptorSha256") == row["statePrivateSecurity"].get("sha256")
        and isinstance(descriptor, list)
        and 0 < len(descriptor) <= 64 * 1024
        and all(type(value) is int and 0 <= value <= 255 for value in descriptor)
        and hashlib.sha256(bytes(descriptor)).hexdigest() == row["descriptorSha256"]
    )


def same_facts(a, b):
    return (
        valid_facts(a)
        and valid_facts(b)
        and all(
            a[key] == b[key]
            for key in ("volumeSerialNumber", "fileId128", "descriptorSha256")
        )
    )


def capability(trace):
    if not (
        trace.get("schema") == "hepta.windows-directory-native-probe.v1"
        and trace.get("diagnosticCollectionCompleted") is True
        and trace.get("productQualification") is False
        and trace.get("originalOperator26OrShadow31Executed") is False
        and trace.get("physicalPowerLossQualified") is False
        and trace.get("ownedScratchCleanup", {}).get("ok") is True
        and trace.get("retainedFull128IdentityAndDaclUnchanged") is True
        and same_facts(trace.get("retainedBefore", {}), trace.get("retainedAfter", {}))
    ):
        raise ValueError("missing or inconsistent retained native facts")
    modes = trace.get("modes", [])
    if [mode.get("mode") for mode in modes] != MODES:
        raise ValueError("missing, duplicate or unexpected native mode")
    results = []
    for mode in modes:
        supported = (
            mode.get("open", {}).get("ok") is True
            and mode.get("sameRetainedDirectoryBefore") is True
            and mode.get("sameRetainedDirectoryAfter") is True
            and same_facts(trace["retainedBefore"], mode.get("before", {}))
            and same_facts(mode.get("before", {}), mode.get("after", {}))
            and mode.get("rustSyncAll", {}).get("ok") is True
            and mode.get("flushFileBuffers", {}).get("ok") is True
            and mode["flushFileBuffers"].get("rawReturn") != 0
            and mode["flushFileBuffers"].get("rawWin32Error") is None
        )
        results.append(
            {"mode": mode["mode"], "retainedDirectoryFlushSupported": supported}
        )
    return results, (
        results[-1]["retainedDirectoryFlushSupported"]
        and trace.get("unchangedStateDirectorySync", {}).get("ok") is True
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    receipt = {
        "schema": "hepta.windows-directory-diagnostic-receipt.v1",
        "startedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "FAIL_DIAGNOSTIC_COLLECTION",
        "testRetries": 0,
        "diagnosticCollectionSucceeded": False,
        "retainedDirectoryCapabilitySupported": False,
        "productQualification": False,
        "originalOperator26OrShadow31Executed": False,
    }
    if output.exists() or output.is_relative_to(root):
        raise ValueError("fresh diagnostic output outside source required")
    output.mkdir(parents=True)
    try:
        if sys.platform != "win32" or os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
            raise ValueError("one actual native Windows attempt required")
        before = source(root)
        receipt.update(
            sourceBefore=before,
            sourceStatusBefore=git(
                root, "status", "--porcelain", "--untracked-files=all"
            ),
            platform=platform.platform(),
            machine=platform.machine(),
        )
        if before["head"] != args.expected_head or receipt["sourceStatusBefore"]:
            raise ValueError("exact clean source required")
        versions = {
            name: subprocess.check_output(command, text=True)
            for name, command in {
                "rustc": ["rustc", "--version", "--verbose"],
                "cargo": ["cargo", "--version"],
                "just": ["just", "--version"],
                "nextest": ["cargo", "nextest", "--version"],
            }.items()
        }
        receipt["toolVersions"] = versions
        if not (
            versions["rustc"].startswith("rustc 1.96.0 ")
            and "host: x86_64-pc-windows-msvc" in versions["rustc"]
            and versions["cargo"].startswith("cargo 1.96.0 ")
            and versions["just"].strip() == "just 1.51.0"
            and versions["nextest"].startswith("cargo-nextest 0.9.103")
        ):
            raise ValueError("native compiler/runner pins differ")
        binaries = {
            name: Path(
                subprocess.check_output(
                    ["rustup", "which", "--toolchain", "1.96.0", name], text=True
                ).strip()
            ).resolve(strict=True)
            for name in ("rustc", "cargo")
        }
        binaries.update(
            {
                name: Path(shutil.which(name)).resolve(strict=True)
                for name in ("just", "cargo-nextest")
            }
        )
        hashes = {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in binaries.items()
        }
        receipt["toolFiles"] = {
            name: {"path": str(binaries[name]), "sha256": digest}
            for name, digest in hashes.items()
        }
        case_temp = Path(os.environ["RUNNER_TEMP"]) / "hepta-directory-probe-case-temp"
        case_temp.mkdir(exist_ok=False)
        os.environ["TEMP"] = os.environ["TMP"] = str(case_temp.resolve(strict=True))
        os.environ["HEPTA_WINDOWS_DIRECTORY_PROBE_OUTPUT"] = str(
            output / "native-probe.json"
        )

        def invoke(command):
            # The new manual diagnostic is ignored in ordinary State suites.
            # Explicitly execute this exact ignored collector here; no old case
            # is skipped, relabelled or given a changed expectation.
            command.extend(["--run-ignored", "only"])
            process = subprocess.run(
                command, cwd=root / "codex-rs", capture_output=True, text=True
            )
            return process.returncode, process.stdout + process.stderr

        groups = execute_groups(root, output, [GROUP], invoke=invoke)
        receipt["groups"] = groups
        if len(groups) != 1 or not groups[0]["passed"]:
            raise ValueError("exact one native collector test did not pass")
        strict = assess_exact(
            GROUP,
            groups[0]["exitCode"],
            (output / "native-directory-probe.log").read_text(),
        )
        receipt["strictCollectorAssessment"] = strict
        if not strict["passed"]:
            raise ValueError("native collector terminal identity set differs")
        trace = json.loads((output / "native-probe.json").read_text())
        modes, supported = capability(trace)
        after = source(root)
        clean = git(root, "status", "--porcelain", "--untracked-files=all")
        intact = valid_source(args.expected_head, before, after) and not clean
        tools_intact = all(
            hashlib.sha256(path.read_bytes()).hexdigest() == hashes[name]
            for name, path in binaries.items()
        )
        receipt.update(
            sourceAfter=after,
            sourceStatusAfter=clean,
            sourceUnchanged=intact,
            toolFilesUnchanged=tools_intact,
            nativeModeAssessments=modes,
            diagnosticCollectionSucceeded=intact and tools_intact,
            retainedDirectoryCapabilitySupported=supported and intact and tools_intact,
            nativeTraceSha256=hashlib.sha256(
                (output / "native-probe.json").read_bytes()
            ).hexdigest(),
        )
        if intact and tools_intact:
            receipt["status"] = (
                "CAPABILITY_SUPPORTED_DIAGNOSTIC_ONLY"
                if supported
                else "FAIL_NO_RETAINED_DIRECTORY_FLUSH_CAPABILITY"
            )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as error:
        receipt["error"] = str(error)
    receipt["finishedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)
    return 0 if receipt["status"] == "CAPABILITY_SUPPORTED_DIAGNOSTIC_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
