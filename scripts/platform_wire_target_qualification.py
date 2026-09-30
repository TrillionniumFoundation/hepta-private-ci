#!/usr/bin/env python3
"""Record protected-host qualification through the existing CI command owner.

This script does not authenticate a runner, provision keys or issue acceptance.
The protected workflow supplies those execution facts. Its receipt describes
native tests and in-process profiles only, not deployed network ingress.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from hepta_ci_exec import observed_test_counts
from platform_wire_fleet_contract import unique_object

SHA = re.compile(r"[0-9a-f]{40}")
MANIFEST = ["--locked", "--offline", "--manifest-path", "codex-rs/Cargo.toml"]


def commands(records: Path) -> list[tuple[str, int, list[str]]]:
    """One fixed command plan; receipt verification uses the same argv and floors."""
    cargo = ["cargo", "test", *MANIFEST]
    return [
        (
            "toolchain",
            0,
            [
                "bash",
                "-c",
                "rustc --version --verbose && cargo --version && python3 --version && node --version",
            ],
        ),
        (
            "status-selftest",
            0,
            ["python3", "scripts/platform_wire_status.py", "self-test"],
        ),
        (
            "status-drift",
            0,
            ["python3", "scripts/platform_wire_status.py", "check-doc"],
        ),
        ("wire", 102, cargo + ["-p", "codex-hepta-wire", "--all-targets"]),
        (
            "resources",
            6,
            cargo
            + [
                "-p",
                "codex-hepta-wire",
                "--test",
                "managed_stream_resources",
            ],
        ),
        (
            "consumers",
            5,
            cargo
            + [
                "-p",
                "codex-hepta-wire",
                "--test",
                "managed_consumer_contracts",
            ],
        ),
        (
            "ports",
            12,
            cargo
            + [
                "-p",
                "codex-hepta-context-compiler",
                "-p",
                "codex-hepta-codex-adapter",
                "--lib",
                "wire::tests",
            ],
        ),
        (
            "cross-runtime",
            2,
            cargo
            + [
                "-p",
                "codex-hepta-shadow-qualification",
                "--test",
                "cross_runtime_wire_session",
            ],
        ),
        (
            "gateway",
            18,
            cargo
            + [
                "-p",
                "codex-hepta-native-gateway",
                "--lib",
                "http_accept",
            ],
        ),
        (
            "native-worker",
            1,
            cargo
            + [
                "-p",
                "codex-hepta-infer-worker-host",
                "--lib",
                "real_agentd_worker_accepts_fresh_context_and_rejects_final_use_tombstone",
            ],
        ),
        (
            "strict-clippy",
            0,
            [
                "cargo",
                "clippy",
                *MANIFEST,
                "-p",
                "codex-hepta-wire",
                "-p",
                "codex-hepta-codex-adapter",
                "-p",
                "codex-hepta-native-gateway",
                "--all-targets",
                "--no-deps",
                "--",
                "-D",
                "warnings",
            ],
        ),
        (
            "profile-selftest",
            9,
            [
                "python3",
                "scripts/platform_wire_managed_profile.py",
                "--self-test",
            ],
        ),
        (
            "fleet-selftest",
            11,
            [
                "python3",
                "scripts/platform_wire_managed_fleet_profile.py",
                "--self-test",
            ],
        ),
        (
            "profiles-build",
            0,
            [
                "cargo",
                "build",
                "--release",
                *MANIFEST,
                "-p",
                "codex-hepta-wire",
                "--example",
                "managed_record_profile",
                "--example",
                "managed_fleet_profile",
                "--example",
                "managed_retention_profile",
            ],
        ),
        (
            "profile-run",
            0,
            [
                "bash",
                "-c",
                'LC_ALL=C /usr/bin/time -v -o "$RECORDS/managed-profile.time" '
                '"$CARGO_TARGET_DIR/release/examples/managed_record_profile" 512 '
                '> "$RECORDS/managed-profile.json"',
            ],
        ),
        (
            "profile-validation",
            0,
            [
                "python3",
                "scripts/platform_wire_managed_profile.py",
                "--input",
                str(records / "managed-profile.json"),
                "--iterations",
                "512",
            ],
        ),
        (
            "fleet-run",
            0,
            [
                "bash",
                "-c",
                'LC_ALL=C /usr/bin/time -v -o "$RECORDS/managed-fleet.time" '
                '"$CARGO_TARGET_DIR/release/examples/managed_fleet_profile" 64 '
                '> "$RECORDS/managed-fleet.json"',
            ],
        ),
        (
            "fleet-validation",
            0,
            [
                "python3",
                "scripts/platform_wire_managed_fleet_profile.py",
                "--input",
                str(records / "managed-fleet.json"),
                "--rounds",
                "64",
            ],
        ),
        (
            "fleet-emitter-contract",
            7,
            [
                "python3",
                "scripts/platform_wire_fleet_contract.py",
                "--input",
                str(records / "managed-fleet.json"),
                "--rounds",
                "64",
            ],
        ),
        (
            "retention-selftest",
            10,
            [
                "python3",
                "scripts/platform_wire_retention_profile.py",
                "--self-test",
            ],
        ),
        (
            "retention-run",
            0,
            [
                "bash",
                "-c",
                'LC_ALL=C /usr/bin/time -v -o "$RECORDS/retention.time" '
                '"$CARGO_TARGET_DIR/release/examples/managed_retention_profile" 128 '
                '> "$RECORDS/retention.json"',
            ],
        ),
        (
            "retention-validation",
            0,
            [
                "python3",
                "scripts/platform_wire_retention_profile.py",
                "--input",
                str(records / "retention.json"),
                "--iterations",
                "128",
            ],
        ),
        (
            "retention-emitter-contract",
            10,
            [
                "python3",
                "scripts/platform_wire_retention_profile.py",
                "--input",
                str(records / "retention.json"),
                "--iterations",
                "128",
                "--contract",
            ],
        ),
        (
            "clean-tree",
            0,
            [
                "bash",
                "-c",
                "git diff --exit-code && git diff --cached --exit-code && "
                'test -z "$(git status --porcelain --untracked-files=all)"',
            ],
        ),
    ]


def read_local(root: Path, name: str, limit: int) -> bytes:
    if not isinstance(name, str) or name in ("", ".", "..") or Path(name).name != name:
        raise ValueError("evidence filename is not local")
    path = root / name
    if path.is_symlink():
        raise ValueError("symlinked evidence is not allowed")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("evidence exceeds its byte limit")
    return data


def verify_command(
    root: Path,
    name: str,
    floor: int,
    argv: list[str],
    subject: dict[str, Any],
) -> dict[str, Any]:
    raw = read_local(root, name + ".json", 1024 * 1024)
    value = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int:
        raise ValueError("invalid command-record schema")
    if value["schema_version"] != 1 or value.get("status") != "passed":
        raise ValueError("command did not pass in the current schema")
    for field in (
        "command_exit_code",
        "exit_code",
        "returncode",
        "observed_failed_tests",
    ):
        if type(value.get(field)) is not int or value[field] != 0:
            raise ValueError(f"invalid {field}")
    if (
        value.get("timed_out") is not False
        or value.get("output_limit_exceeded") is not False
    ):
        raise ValueError("command exceeded an execution bound")
    if value.get("command") != argv:
        raise ValueError("command set drift")
    if type(value.get("minimum_tests")) is not int or value["minimum_tests"] != floor:
        raise ValueError("test floor drift")
    passed = value.get("observed_passed_tests")
    if type(passed) is not int or passed < floor:
        raise ValueError("required tests were not observed")
    for field in ("source_sha", "tested_sha", "run_id", "run_attempt", "lane"):
        if value.get(field) != subject[field]:
            raise ValueError(f"command {field} mismatch")
    before, after = value.get("before"), value.get("after")
    if not isinstance(before, dict) or before != after:
        raise ValueError("command changed source identity")
    if (
        before.get("commit") != subject["tested_sha"]
        or before.get("tree") != subject["tested_tree"]
    ):
        raise ValueError("command tree mismatch")
    if (
        before.get("parents") != subject["tested_parents"]
        or before.get("dirty") is not False
    ):
        raise ValueError("command checkout is not the bound clean candidate")
    log_name = value.get("log_file")
    log = read_local(root, log_name, 64 * 1024 * 1024)
    digest = hashlib.sha256(log).hexdigest()
    if type(value.get("log_bytes")) is not int:
        raise ValueError("invalid log byte count")
    if digest != value.get("log_sha256") or len(log) != value["log_bytes"]:
        raise ValueError("command raw-log binding mismatch")
    # Reuse the existing runner parser; record counters alone cannot certify tests.
    if observed_test_counts(log.decode("utf-8", errors="replace")) != (passed, 0):
        raise ValueError("test counts differ from the retained raw log")
    return {
        "record": name + ".json",
        "record_sha256": hashlib.sha256(raw).hexdigest(),
        "log": log_name,
        "log_sha256": digest,
        "command": argv,
        "minimum_tests": floor,
        "observed_passed_tests": passed,
    }


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


def receipt(records: Path, expected: str, setup: str, execution: str) -> int:
    from platform_wire_managed_profile import validate as validate_profile
    from platform_wire_managed_fleet_profile import validate as validate_fleet
    from platform_wire_retention_profile import validate as validate_retention

    errors: list[str] = []
    tested = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    subject = {
        "source_sha": expected,
        "tested_sha": tested,
        "tested_tree": tree,
        "tested_parents": git("show", "-s", "--format=%P", "HEAD").split(),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "lane": "source-head",
    }
    if tested != expected or os.environ.get("GITHUB_SHA") != expected:
        errors.append("dispatched source differs from expected source")
    if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        errors.append("target-host evidence requires workflow_dispatch")
    workflow_ref = os.environ.get("GITHUB_WORKFLOW_REF", "")
    prefix = (
        os.environ.get("GITHUB_REPOSITORY", "")
        + "/.github/workflows/platform-wire-target-host.yml@"
    )
    if not workflow_ref.startswith(prefix):
        errors.append("wrong target-host workflow")
    if not SHA.fullmatch(os.environ.get("GITHUB_WORKFLOW_SHA", "")):
        errors.append("workflow SHA is missing")
    for field in ("RUNNER_NAME", "RUNNER_OS", "RUNNER_ARCH", "RUSTUP_TOOLCHAIN"):
        if not os.environ.get(field):
            errors.append(f"missing {field}")
    if git("status", "--porcelain", "--untracked-files=all"):
        errors.append("source checkout is dirty")
    if setup != "success" or execution != "success":
        errors.append("setup or command execution did not pass")
    command_records: dict[str, Any] = {}
    for name, floor, argv in commands(records):
        try:
            command_records[name] = verify_command(records, name, floor, argv, subject)
        except (OSError, ValueError, TypeError, KeyError) as error:
            errors.append(f"{name}: {error}")
    measurements: dict[str, Any] = {}
    profiles = (
        ("managed-profile", validate_profile, 512),
        ("managed-fleet", validate_fleet, 64),
        ("retention", validate_retention, 128),
    )
    for name, validate, count in profiles:
        try:
            raw = read_local(records, name + ".json", 1024 * 1024)
            report = json.loads(raw, object_pairs_hook=unique_object)
            validate(report, count)
            resource = read_local(records, name + ".time", 64 * 1024)
            match = re.search(
                rb"Maximum resident set size \(kbytes\):\s*([0-9]+)", resource
            )
            if match is None or int(match[1]) <= 0:
                raise ValueError("maximum RSS observation missing")
            measurements[name] = {
                "report_sha256": hashlib.sha256(raw).hexdigest(),
                "resource_report_sha256": hashlib.sha256(resource).hexdigest(),
                "maximum_resident_set_size_kib": int(match[1]),
                "scenario_count": len(report["scenarios"]),
                "iterations_or_rounds": count,
            }
        except (OSError, ValueError, TypeError, KeyError) as error:
            errors.append(f"{name}: {error}")
    status = (
        "infrastructure_invalid"
        if setup != "success"
        else ("failed" if errors else "passed")
    )
    payload = {
        "schema": "hepta.platform-wire.receipt.v2",
        "kind": "platform-wire-target-host",
        **subject,
        "source_tree": git("rev-parse", expected + "^{tree}"),
        "status": status,
        "errors": errors,
        "workflow": os.environ.get("GITHUB_WORKFLOW"),
        "workflow_ref": workflow_ref,
        "workflow_sha": os.environ.get("GITHUB_WORKFLOW_SHA"),
        "event": os.environ.get("GITHUB_EVENT_NAME"),
        "run_id": int(os.environ["GITHUB_RUN_ID"]),
        "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": "platform-wire-target-host",
        "host_profile": "hepta-target-host",
        "runner_name": os.environ.get("RUNNER_NAME"),
        "runner_os": os.environ.get("RUNNER_OS"),
        "runner_arch": os.environ.get("RUNNER_ARCH"),
        "toolchain": os.environ.get("RUSTUP_TOOLCHAIN"),
        "command_records": command_records,
        "measurements": measurements,
        "scope": "protected-host native commands and in-process release profiles; not deployed authenticated network ingress or five-path gRPC acceptance",
        "authenticated_network_ingress": False,
        "independent_acceptance": False,
        "activation": False,
        "release": False,
    }
    records.mkdir(parents=True, exist_ok=True)
    (records / "platform-wire-target-host.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"status": status, "source_sha": expected, "errors": errors}, indent=2
        )
    )
    return 0 if status == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "receipt"))
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--setup-outcome", default="")
    parser.add_argument("--execution-outcome", default="")
    args = parser.parse_args()
    if SHA.fullmatch(args.source_sha) is None:
        parser.error("source SHA must be lowercase 40-hex")
    try:
        records = args.records.resolve()
        root = Path(git("rev-parse", "--show-toplevel")).resolve()
        if records.is_relative_to(root) or args.records.is_symlink():
            raise ValueError("records must be outside the source checkout")
        if args.action == "receipt":
            return receipt(
                records, args.source_sha, args.setup_outcome, args.execution_outcome
            )
        if git("rev-parse", "HEAD") != args.source_sha:
            raise ValueError("wrong source checkout")
        if any(
            os.environ.get(field) != args.source_sha
            for field in ("SOURCE_SHA", "TESTED_SHA")
        ):
            raise ValueError("command source context is not bound")
        if os.environ.get("HEPTA_CI_LANE") != "source-head":
            raise ValueError("target-host command must execute the source-head lane")
        if os.environ.get("RECORDS") != str(records):
            raise ValueError("profile output directory differs from command records")
        from hepta_ci_exec import run

        status = 0
        for name, floor, argv in commands(records):
            status |= bool(
                run(
                    records / (name + ".json"),
                    argv,
                    minimum_tests=floor,
                    timeout_seconds=1800,
                )
            )
        return int(status)
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        subprocess.SubprocessError,
    ) as error:
        print(f"target-host evidence rejected: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
