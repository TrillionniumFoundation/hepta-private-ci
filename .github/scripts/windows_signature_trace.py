#!/usr/bin/env python3
"""Collect two original signature fixtures; collection grants no admission."""

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
import time

from windows_current_ci import ANSI, git, source, valid_source

PACKAGE = "codex-hepta-operator-acceptance"
CASES = {
    "trust": "sshsig_verifies_only_exact_namespace_against_pinned_policy",
    "g5_trust": "independently_signed_challenge_is_verified_but_not_accepted",
}
TESTS = [
    f"{role}::tests::windows_signature_trace::records_original_detached_signature_identity"
    for role in CASES
]


def assess_collector(code, log):
    text = ANSI.sub("", log)
    starts = re.findall(r"^\s*Starting (\d+) tests? across", text, re.M)
    summaries = re.findall(r"^\s*Summary \[", text, re.M)
    terminals = re.findall(
        r"^\s*(PASS|FAIL|TIMEOUT|EXECFAIL|LEAK|SKIP)\s+\[[^\]\n]+\]\s+"
        r"(?:\(\s*\d+/\d+\)\s+)?(\S+)\s+(\S+)\s*$",
        text,
        re.M,
    )
    expected = sorted(("PASS", PACKAGE, name) for name in TESTS)
    return {
        "exitCode": code,
        "terminalCount": len(terminals),
        "observedTests": [name for _, _, name in terminals],
        "passed": code == 0
        and starts == ["2"]
        and len(summaries) == 1
        and sorted(terminals) == expected,
    }


def validate_trace(role, trace):
    if not (
        trace.get("schema") == "hepta.windows-original-signature-metadata.v1"
        and trace.get("original_case") == f"{role}::tests::{CASES[role]}"
        and trace.get("collection_is_not_functional_qualification") is True
        and trace.get("effective_token", {}).get("ok") is True
        and trace.get("namespace") == "hepta-vnext-operator-acceptance-v1"
    ):
        raise ValueError("wrong, incomplete or duplicate original fixture identity")
    for kind in ("user_sid", "owner_sid"):
        sid = trace["effective_token"].get(kind, {})
        if not (
            sid.get("ok") is True
            and isinstance(sid.get("facts"), str)
            and re.fullmatch(r'"S-\d+(?:-\d+)+"', sid["facts"])
        ):
            raise ValueError("missing effective token user/owner SID")
    for key in (
        "generated_signature_before",
        "generated_signature_after",
        "private_allowed_signers_control",
        "private_policy_control",
    ):
        row = trace.get(key, {})
        for operation in (
            "canonical_held_id",
            "canonical_private_security",
            "canonical_full_snapshot",
            "canonical_current_path",
        ):
            fact = row.get(operation, {})
            if not (
                type(fact.get("ok")) is bool
                and (
                    isinstance(fact.get("facts"), str)
                    if fact["ok"]
                    else "raw_win32_error" in fact
                    and isinstance(fact.get("kind"), str)
                    and isinstance(fact.get("message"), str)
                )
            ):
                raise ValueError("missing canonical operation result: " + operation)
        identity = row.get("id_before", {})
        file_id = identity.get("file_id_16_bytes", [])
        descriptor = row.get("owner_dacl", {})
        raw = descriptor.get("descriptor_bytes", [])
        if not (
            identity.get("ok") is True
            and len(file_id) == 16
            and any(file_id)
            and all(type(b) is int and 0 <= b <= 255 for b in file_id)
            and re.fullmatch(r"[0-9a-f]{16}", identity.get("volume_serial_hex", ""))
            and row.get("retained_full_id_unchanged") is True
            and row.get("current_path_matches_retained_full_id") is True
            and row.get("id_after") == row.get("current_path_id") == identity
            and descriptor.get("ok") is True
            and descriptor.get("descriptor_valid") is True
            and isinstance(raw, list)
            and 0 < len(raw) <= 128 * 1024
            and all(type(b) is int and 0 <= b <= 255 for b in raw)
            and isinstance(descriptor.get("owner_and_dacl_sddl"), str)
            and descriptor["owner_and_dacl_sddl"]
        ):
            raise ValueError(
                "missing native owner/DACL/full-128-ID observation: " + key
            )
    before = trace["generated_signature_before"]
    after = trace["generated_signature_after"]
    if not (
        before["id_before"] == after["id_before"]
        and before["owner_dacl"] == after["owner_dacl"]
    ):
        raise ValueError("original verification changed signature identity/security")
    operation = trace.get(
        "original_verify" if role == "trust" else "original_assess", {}
    )
    if type(operation.get("ok")) is not bool or not isinstance(
        operation.get("result"), str
    ):
        raise ValueError("missing original production operation result")
    return operation


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(root):
        raise ValueError("fresh dedicated output outside checkout required")
    output.mkdir(parents=True)
    receipt = {
        "schema": "hepta.windows-signature-diagnostic-receipt.v1",
        "startedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "FAIL_DIAGNOSTIC_COLLECTION",
        "diagnosticCollectionSucceeded": False,
        "originalFunctionalQualification": False,
        "productionAuthorityGranted": False,
        "testRetries": 0,
        "exactCollectors": TESTS,
    }
    before, binaries, tools_before = None, {}, {}
    collected = False
    try:
        if (
            sys.platform != "win32"
            or os.environ.get("GITHUB_RUN_ATTEMPT") != "1"
            or not re.fullmatch(r"[0-9a-f]{40}", args.expected_head)
        ):
            raise ValueError(
                "one actual native attempt and full source commit required"
            )
        removed = [key for key in os.environ if key.startswith("GIT_")]
        for key in removed:
            os.environ.pop(key)
        os.environ["GIT_NO_REPLACE_OBJECTS"] = "1"
        receipt["removedGitOverrideNames"] = removed
        before = source(root)
        clean = git(root, "status", "--porcelain", "--untracked-files=all")
        receipt.update(
            sourceBefore=before, sourceStatusBefore=clean, platform=platform.platform()
        )
        if before["head"] != args.expected_head or clean:
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
            raise ValueError("compiler or runner pin differs")
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
        candidates = [
            Path(os.environ["SystemRoot"]) / "System32/OpenSSH/ssh-keygen.exe"
        ]
        candidates += [
            Path(directory) / "ssh-keygen.exe"
            for directory in os.environ.get("PATH", "").split(os.pathsep)
        ]
        binaries["fixture-ssh-keygen"] = next(
            path.resolve(strict=True)
            for path in candidates
            if path.is_absolute() and path.is_file()
        )
        tools_before = {
            name: {"path": str(path), "sha256": sha(path)}
            for name, path in binaries.items()
        }
        receipt["toolFilesBefore"] = tools_before
        temporary = Path(os.environ["RUNNER_TEMP"]) / "hepta-signature-trace-case-temp"
        temporary.mkdir(exist_ok=False)
        os.environ["TEMP"] = os.environ["TMP"] = str(temporary.resolve(strict=True))
        os.environ["HEPTA_WINDOWS_SIGNATURE_TRACE_DIR"] = str(output)
        command = [
            "just",
            "test",
            "--locked",
            "-p",
            PACKAGE,
            "--lib",
            "--cargo-profile",
            "dev-small",
            "-E",
            " | ".join(f"test(={name})" for name in TESTS),
            "--test-threads",
            "1",
            "--no-tests",
            "fail",
            "--retries",
            "0",
            "--run-ignored",
            "only",
        ]
        started = time.monotonic()
        log = output / "native-signature-trace.log"
        with log.open("x", encoding="utf-8") as stream:
            process = subprocess.run(
                command,
                cwd=root / "codex-rs",
                stdout=stream,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                check=False,
            )
        strict = assess_collector(process.returncode, log.read_text())
        receipt.update(
            command=command,
            durationSeconds=round(time.monotonic() - started, 3),
            strictCollectorAssessment=strict,
            collectorLogSha256=sha(log),
        )
        if not strict["passed"]:
            raise ValueError("exact two collectors did not complete")
        operations = {}
        for role, name in (
            ("trust", "trust-signature-original.json"),
            ("g5_trust", "g5-signature-original.json"),
        ):
            trace = json.loads((output / name).read_text())
            operations[role] = validate_trace(role, trace)
            if not os.path.samefile(
                trace["fixture_signer"], binaries["fixture-ssh-keygen"]
            ):
                raise ValueError(
                    "actual fixture signer differs from before-bound executable"
                )
        receipt["originalOperationObservations"] = operations
        collected = True
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        StopIteration,
        subprocess.SubprocessError,
    ) as error:
        receipt["error"] = str(error)
    finally:
        try:
            after = source(root)
            clean = git(root, "status", "--porcelain", "--untracked-files=all")
            receipt.update(
                sourceAfter=after,
                sourceStatusAfter=clean,
                sourceUnchanged=before is not None
                and valid_source(args.expected_head, before, after)
                and not clean,
            )
            after_tools = {
                name: {"path": str(path), "sha256": sha(path)}
                for name, path in binaries.items()
            }
            receipt.update(
                toolFilesAfter=after_tools,
                toolFilesUnchanged=len(after_tools) == 5
                and tools_before == after_tools,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            receipt["afterObservationError"] = str(error)
    if (
        collected
        and receipt.get("sourceUnchanged") is True
        and receipt.get("toolFilesUnchanged") is True
    ):
        receipt.update(
            status="COLLECTED_DIAGNOSTIC_ONLY", diagnosticCollectionSucceeded=True
        )
    receipt["finishedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)
    return 0 if receipt["diagnosticCollectionSucceeded"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
