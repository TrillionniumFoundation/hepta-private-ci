#!/usr/bin/env python3
"""Collect unmodified public fixture outputs; never qualify production SSHSIG."""

import argparse
import base64
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

PROBE = "trust::tests::windows_contract_probe::records_unmodified_openssh_stream_and_private_file_output"
JUNCTION = "private_artifacts_windows::tests::native_reparse_directory_is_refused_before_child_effect"
MODES = ("stdin_stdout", "filename_new", "filename_precreated_private")
STATEMENT = b"canonical operator acceptance statement"
TERMINAL = re.compile(
    r"^\s*(PASS|FAIL|TIMEOUT|EXECFAIL|LEAK|SKIP)\s+\[[^\]\n]+\]\s+(\S+)\s+(\S+)\s*$",
    re.M,
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def assess_exact(code, text, package, case):
    text = ANSI.sub("", text)
    start = list(re.finditer(r"^\s*Starting (\d+) tests? across", text, re.M))
    summary = list(
        re.finditer(
            r"^\s*Summary \[[^\]\n]+\] 1 tests? run: 1 passed(?:, (?P<skipped>\d+) skipped)?\s*$",
            text,
            re.M,
        )
    )
    actual = TERMINAL.findall(text)
    passed = (
        code == 0
        and len(start) == len(summary) == 1
        and len(re.findall(r"^\s*Summary \[", text, re.M)) == 1
        and start[0].group(1) == "1"
        and start[0].start() < summary[0].start()
        and actual == [("PASS", package, case)]
        and TERMINAL.search(text, start[0].start(), summary[0].start()) is not None
    )
    if passed:
        start_line = text[start[0].start() :].splitlines()[0]
        skipped = re.search(r"\((\d+) tests? skipped\)$", start_line)
        passed = int(summary[0]["skipped"] or 0) == (
            int(skipped.group(1)) if skipped else 0
        )
    return {"exitCode": code, "actualTerminals": actual, "passed": passed}


def raw_bytes(row):
    encoded = row["public_fixture_bytes_base64"]
    require(
        isinstance(encoded, str) and len(encoded) <= 22000, "unbounded public fixture"
    )
    data = base64.b64decode(encoded, validate=True)
    require(
        len(data) <= 16384 and base64.b64encode(data).decode() == encoded,
        "noncanonical public bytes",
    )
    require(
        type(row["bytes"]) is int and row["bytes"] == len(data),
        "wrong public byte count",
    )
    require(
        row["sha256"] == hashlib.sha256(data).hexdigest(), "wrong public byte digest"
    )
    for name, count in (
        ("cr_bytes", data.count(b"\r")),
        ("lf_bytes", data.count(b"\n")),
        ("crlf_pairs", data.count(b"\r\n")),
    ):
        require(
            type(row[name]) is int and row[name] == count, "wrong newline observations"
        )
    for name, value in (
        ("exact_lf_header", data.startswith(b"-----BEGIN SSH SIGNATURE-----\n")),
        ("exact_lf_footer", data.endswith(b"-----END SSH SIGNATURE-----\n")),
    ):
        require(
            type(row[name]) is bool and row[name] == value,
            "wrong unmodified envelope observation",
        )
    return data


def native_file(row):
    opened = row["open"]
    require(type(opened["ok"]) is bool, "missing actual open result")
    if not opened["ok"]:
        require(
            "raw_win32_error" in opened and isinstance(opened["message"], str),
            "missing native open error",
        )
        return
    for name in ("id_before", "id_after", "current_path_id"):
        identity = row[name]
        require(
            identity["ok"] is True
            and re.fullmatch("[0-9a-f]{16}", identity["volume_serial_hex"]) is not None,
            "missing volume identity",
        )
        file_id = identity["file_id_16_bytes"]
        require(
            isinstance(file_id, list)
            and len(file_id) == 16
            and any(file_id)
            and all(type(v) is int and 0 <= v <= 255 for v in file_id),
            "missing full 128-bit ID",
        )
    require(
        row["id_before"] == row["id_after"] == row["current_path_id"]
        and row["retained_full_id_unchanged"] is True
        and row["current_path_matches_retained_full_id"] is True,
        "identity changed during observation",
    )
    descriptor = row["owner_dacl"]
    raw = descriptor["descriptor_bytes"]
    require(
        descriptor["ok"] is True
        and descriptor["descriptor_valid"] is True
        and isinstance(raw, list)
        and 0 < len(raw) <= 131072
        and all(type(v) is int and 0 <= v <= 255 for v in raw),
        "missing complete owner/DACL",
    )
    for name in (
        "canonical_held_id",
        "canonical_private_security",
        "canonical_full_snapshot",
        "canonical_current_path",
    ):
        fact = row[name]
        require(
            type(fact["ok"]) is bool
            and (
                isinstance(fact.get("facts"), str)
                if fact["ok"]
                else "raw_win32_error" in fact and isinstance(fact.get("message"), str)
            ),
            "missing canonical result/error",
        )


def validate_trace(trace):
    require(
        trace["schema"] == "hepta.windows-openssh-native-contract-probe.v1"
        and trace["diagnostic_only"] is True
        and trace["functional_qualification"] is False
        and trace["production_authority_granted"] is False
        and trace["namespace"] == "hepta-vnext-operator-acceptance-v1",
        "wrong diagnostic boundary",
    )
    require(
        raw_bytes(trace["public_fixture_statement"]) == STATEMENT, "wrong original body"
    )
    require(trace["effective_token"]["ok"] is True, "missing actual effective token")
    for name in ("user_sid", "owner_sid"):
        sid = trace["effective_token"][name]
        require(
            sid["ok"] is True
            and re.fullmatch(r'"S-\d+(?:-\d+)+"', sid["facts"]) is not None,
            "missing native token SID",
        )
    for name in ("fixture_signer_before", "fixture_signer_after"):
        native_file(trace[name])
    require(
        trace["fixture_signer_before"]["id_before"]
        == trace["fixture_signer_after"]["id_before"]
        and trace["fixture_signer_before"]["owner_dacl"]
        == trace["fixture_signer_after"]["owner_dacl"],
        "signer object changed",
    )
    require(
        [row["mode"] for row in trace["modes"]] == list(MODES),
        "missing/duplicate/unknown mode",
    )
    observations = []
    for row in trace["modes"]:
        require(raw_bytes(row["statement_after"]) == STATEMENT, "original body changed")
        before = row["signature_before_sign"]
        if row["mode"] == "filename_precreated_private":
            native_file(before)
            require(
                before["canonical_private_security"]["ok"] is True,
                "precreated object was not private",
            )
        else:
            require(
                before == {"absent": True},
                "producer did not start with absent signature",
            )
        process = row["original_process"]
        require(
            type(process["success"]) is bool
            and type(process["exit_code"]) is int
            and process["success"] == (process["exit_code"] == 0),
            "missing original process status",
        )
        raw_bytes(process["stdout"])
        raw_bytes(process["stderr"])
        signed = row["signature_after_sign"]
        native_file(signed["before_read"])
        native_file(signed["after_read"])
        if signed["before_read"]["open"]["ok"] and signed["after_read"]["open"]["ok"]:
            require(
                signed["before_read"]["id_before"] == signed["after_read"]["id_before"]
                and signed["before_read"]["owner_dacl"]
                == signed["after_read"]["owner_dacl"],
                "signature changed across original verify",
            )
        facts = signed["observations"]
        require(type(facts["read_ok"]) is bool, "missing actual signature read")
        if facts["read_ok"]:
            data = raw_bytes(facts["raw"])
            if row["mode"] == "stdin_stdout":
                require(
                    data == raw_bytes(process["stdout"]),
                    "stdout signature bytes were modified",
                )
            for name in ("strict_rust", "original_production_verify"):
                require(
                    type(facts[name]["ok"]) is bool
                    and isinstance(facts[name]["result"], str),
                    "missing original verification result",
                )
        else:
            require(
                "raw_win32_error" in facts and isinstance(facts["error"], str),
                "missing read error",
            )
        observations.append(
            {
                "mode": row["mode"],
                "originalProcessSuccess": process["success"],
                "originalReadObservations": facts,
            }
        )
    return observations


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    require(
        not output.exists() and not output.is_relative_to(root),
        "fresh output outside source required",
    )
    output.mkdir(parents=True)
    receipt = {
        "schema": "hepta.windows-openssh-contract-probe-receipt.v1",
        "startedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "FAIL_DIAGNOSTIC_COLLECTION",
        "productionAuthorityGranted": False,
        "functionalQualification": False,
        "testRetries": 0,
        "groups": [],
    }
    before, binaries, tools_before, collected = None, {}, {}, False
    try:
        require(
            sys.platform == "win32"
            and os.environ.get("GITHUB_RUN_ATTEMPT") == "1"
            and re.fullmatch("[0-9a-f]{40}", args.expected_head),
            "native Windows exact attempt1 required",
        )
        for key in list(os.environ):
            if key.startswith("GIT_"):
                del os.environ[key]
        os.environ["GIT_NO_REPLACE_OBJECTS"] = "1"
        before = source(root)
        receipt.update(
            sourceBefore=before,
            sourceStatusBefore=git(
                root, "status", "--porcelain", "--untracked-files=all"
            ),
            platform=platform.platform(),
        )
        require(
            before["head"] == args.expected_head and not receipt["sourceStatusBefore"],
            "exact clean source required",
        )
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
        require(
            versions["rustc"].startswith("rustc 1.96.0 ")
            and "host: x86_64-pc-windows-msvc" in versions["rustc"]
            and versions["cargo"].startswith("cargo 1.96.0 ")
            and versions["just"].strip() == "just 1.51.0"
            and versions["nextest"].startswith("cargo-nextest 0.9.103"),
            "compiler/runner pin differs",
        )
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
        binaries["fixture-ssh-keygen"] = (
            Path(os.environ["SystemRoot"]) / "System32/OpenSSH/ssh-keygen.exe"
        ).resolve(strict=True)
        tools_before = {
            name: {"path": str(path), "sha256": sha(path)}
            for name, path in binaries.items()
        }
        receipt["toolFilesBefore"] = tools_before
        protected = [
            ".github/scripts/windows_current_ci.py",
            ".github/fixtures/windows-current-ci-scope.json",
            "codex-rs/.config/nextest.toml",
            "codex-rs/Cargo.lock",
        ]
        receipt["protectedInputsBefore"] = {
            name: sha(root / name) for name in protected
        }
        temporary = Path(os.environ["RUNNER_TEMP"]) / "hepta-openssh-contract-case-temp"
        temporary.mkdir(exist_ok=False)
        os.environ["TEMP"] = os.environ["TMP"] = str(temporary.resolve(strict=True))
        os.environ["HEPTA_WINDOWS_SIGNATURE_TRACE_DIR"] = str(output)
        for group, package, case, ignored in (
            (
                "public-signature-producer",
                "codex-hepta-operator-acceptance",
                PROBE,
                True,
            ),
            ("original-junction-fixture", "codex-utils-path", JUNCTION, False),
        ):
            command = [
                "just",
                "test",
                "--locked",
                "-p",
                package,
                "--lib",
                "--cargo-profile",
                "dev-small",
                "-E",
                f"test(={case})",
                "--test-threads",
                "1",
                "--no-tests",
                "fail",
                "--retries",
                "0",
            ]
            if ignored:
                command += ["--run-ignored", "only"]
            log = output / (group + ".log")
            started = time.monotonic()
            with log.open("x", encoding="utf-8") as stream:
                process = subprocess.run(
                    command,
                    cwd=root / "codex-rs",
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    check=False,
                )
            row = {
                "group": group,
                "command": command,
                "seconds": round(time.monotonic() - started, 3),
                "logSha256": sha(log),
                **assess_exact(process.returncode, log.read_text(), package, case),
            }
            receipt["groups"].append(row)
            print(json.dumps(row), flush=True)
        trace = json.loads((output / "openssh-native-contract.json").read_text())
        receipt["modeObservations"] = validate_trace(trace)
        require(
            os.path.samefile(trace["fixture_signer"], binaries["fixture-ssh-keygen"]),
            "actual signer differs from fixed tool",
        )
        collected = all(row["passed"] for row in receipt["groups"])
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as error:
        receipt["collectionError"] = str(error)
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
                and after_tools == tools_before,
            )
            receipt["protectedInputsAfter"] = {
                name: sha(root / name)
                for name in receipt.get("protectedInputsBefore", {})
            }
            receipt["protectedInputsUnchanged"] = (
                bool(receipt.get("protectedInputsBefore"))
                and receipt["protectedInputsAfter"] == receipt["protectedInputsBefore"]
            )
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            receipt["afterObservationError"] = str(error)
    if collected and all(
        receipt.get(name) is True
        for name in (
            "sourceUnchanged",
            "toolFilesUnchanged",
            "protectedInputsUnchanged",
        )
    ):
        receipt["status"] = "COLLECTED_DIAGNOSTIC_ONLY"
    receipt["finishedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)
    return 0 if receipt["status"] == "COLLECTED_DIAGNOSTIC_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
