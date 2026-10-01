#!/usr/bin/env python3
"""Execute and verify the existing exact-source/ordered-merge command plan.

Reuse the protected-host verifier and bounded CI runner; do not introduce a
second acceptance issuer. Native integration with a fixture provider is not
live peer authentication, five-path gRPC qualification or deployment acceptance.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import platform
from pathlib import Path
import subprocess
import sys

from platform_wire_target_qualification import SHA, git, read_local, verify_command
from platform_wire_receipt_subject import unique_object


# This is the single argv/floor definition used for execution and verification.
# $RECORDS expansion applies to non-shell arguments only. Shell commands retain
# literal environment references, bound separately by the runner's context.
PLAN = (
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
        "path-tests",
        10,
        [
            "python3",
            "-m",
            "unittest",
            "discover",
            "-s",
            "scripts",
            "-p",
            "test_generate_lane_a_workflow_paths.py",
        ],
    ),
    (
        "path-drift",
        0,
        ["python3", "scripts/generate_lane_a_workflow_paths.py", "check"],
    ),
    ("lane-truth", 0, ["python3", "scripts/verify_lane_a_foundation.py", "verify"]),
    ("status-tests", 0, ["python3", "scripts/platform_wire_status.py", "self-test"]),
    ("status-drift", 0, ["python3", "scripts/platform_wire_status.py", "check-doc"]),
    (
        "target-evidence-tests",
        16,
        [
            "python3",
            "-m",
            "unittest",
            "discover",
            "-s",
            "scripts/tests",
            "-p",
            "test_platform_wire_target_qualification.py",
        ],
    ),
    (
        "receipt-subject-tests",
        10,
        [
            "python3",
            "-m",
            "unittest",
            "discover",
            "-s",
            "scripts/tests",
            "-p",
            "test_platform_wire_receipt_subject.py",
        ],
    ),
    (
        "performance-gate-tests",
        8,
        ["python3", "scripts/platform_wire_performance_gate.py", "--self-test"],
    ),
    (
        "wire",
        102,
        [
            "cargo",
            "test",
            "--locked",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            "-p",
            "codex-hepta-wire",
            "--all-targets",
        ],
    ),
    (
        "production-surface",
        0,
        ["python3", "scripts/platform_wire_production_surface.py", "verify"],
    ),
    (
        "consumer-contracts",
        5,
        [
            "cargo",
            "test",
            "--locked",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            "-p",
            "codex-hepta-wire",
            "--test",
            "managed_consumer_contracts",
        ],
    ),
    (
        "wire-doc",
        0,
        [
            "cargo",
            "test",
            "--locked",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            "-p",
            "codex-hepta-wire",
            "--doc",
        ],
    ),
    (
        "ports",
        12,
        [
            "cargo",
            "test",
            "--locked",
            "--manifest-path",
            "codex-rs/Cargo.toml",
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
        [
            "cargo",
            "test",
            "--locked",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            "-p",
            "codex-hepta-shadow-qualification",
            "--test",
            "cross_runtime_wire_session",
        ],
    ),
    (
        "gateway",
        18,
        [
            "cargo",
            "test",
            "--locked",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            "-p",
            "codex-hepta-native-gateway",
            "--lib",
            "http_accept",
        ],
    ),
    (
        "strict-clippy",
        0,
        [
            "cargo",
            "clippy",
            "--locked",
            "--manifest-path",
            "codex-rs/Cargo.toml",
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
        "managed-fleet-profile-selftest",
        11,
        ["python3", "scripts/platform_wire_managed_fleet_profile.py", "--self-test"],
    ),
    (
        "managed-fleet-profile-build",
        0,
        [
            "cargo",
            "build",
            "--release",
            "--locked",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            "-p",
            "codex-hepta-wire",
            "--example",
            "managed_fleet_profile",
        ],
    ),
    (
        "managed-fleet-profile-run",
        0,
        [
            "bash",
            "-c",
            '"$CARGO_TARGET_DIR/release/examples/managed_fleet_profile" 8 > "$RECORDS/managed-fleet-profile.measurements.json"',
        ],
    ),
    (
        "managed-fleet-profile-validation",
        0,
        [
            "python3",
            "scripts/platform_wire_managed_fleet_profile.py",
            "--input",
            "$RECORDS/managed-fleet-profile.measurements.json",
            "--rounds",
            "8",
        ],
    ),
    (
        "managed-fleet-emitter-contract",
        7,
        [
            "python3",
            "scripts/platform_wire_fleet_contract.py",
            "--input",
            "$RECORDS/managed-fleet-profile.measurements.json",
            "--rounds",
            "8",
        ],
    ),
    (
        "native-worker",
        1,
        [
            "cargo",
            "test",
            "--locked",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            "-p",
            "codex-hepta-infer-worker-host",
            "--lib",
            "real_agentd_worker_accepts_fresh_context_and_rejects_final_use_tombstone",
        ],
    ),
    (
        "exact-evidence-tests",
        12,
        [
            "python3",
            "-m",
            "unittest",
            "discover",
            "-s",
            "scripts/tests",
            "-p",
            "test_platform_wire_exact_qualification.py",
        ],
    ),
    (
        "retention-selftest",
        10,
        ["python3", "scripts/platform_wire_retention_profile.py", "--self-test"],
    ),
    (
        "retention-build",
        0,
        [
            "cargo",
            "build",
            "--release",
            "--locked",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            "-p",
            "codex-hepta-wire",
            "--example",
            "managed_retention_profile",
        ],
    ),
    (
        "retention-run",
        0,
        [
            "bash",
            "-c",
            '"$CARGO_TARGET_DIR/release/examples/managed_retention_profile" 32 > "$RECORDS/retention.measurements.json"',
        ],
    ),
    (
        "retention-validation",
        0,
        [
            "python3",
            "scripts/platform_wire_retention_profile.py",
            "--input",
            "$RECORDS/retention.measurements.json",
            "--iterations",
            "32",
        ],
    ),
    (
        "retention-emitter-contract",
        10,
        [
            "python3",
            "scripts/platform_wire_retention_profile.py",
            "--input",
            "$RECORDS/retention.measurements.json",
            "--iterations",
            "32",
            "--contract",
        ],
    ),
    (
        "clean-diff",
        0,
        [
            "bash",
            "-c",
            'git diff --exit-code && git diff --cached --exit-code && test -z "$(git status --porcelain --untracked-files=all)"',
        ],
    ),
)


def commands(records):
    return [
        (
            name,
            floor,
            [
                arg.replace("$RECORDS/", str(records) + "/")
                if argv[0] != "bash"
                else arg
                for arg in argv
            ],
        )
        for name, floor, argv in PLAN
    ]


def context(source, base, lane):
    for value in (source, base):
        if SHA.fullmatch(value) is None:
            raise ValueError("invalid immutable source/base SHA")
    if source == base or lane not in ("source-head", "synthetic-merge"):
        raise ValueError("invalid source/base/lane tuple")
    tested, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    parents = git("show", "-s", "--format=%P", "HEAD").split()
    errors = []
    execution_lane = "source-head" if lane == "source-head" else "base-merge"
    if lane == "source-head":
        if tested != source:
            errors.append("source-head identity mismatch")
    elif tested in (source, base) or parents != [base, source]:
        errors.append("ordered merge parents differ from base,source")
    elif tree != git("merge-tree", "--write-tree", base, source):
        errors.append("ordered merge tree differs from independently recomputed tree")
    if git("status", "--porcelain", "--untracked-files=all"):
        errors.append("dirty source checkout")
    for name, expected in (
        ("SOURCE_SHA", source),
        ("TESTED_SHA", tested),
        ("BASE_SHA", base),
        ("HEPTA_CI_LANE", execution_lane),
    ):
        if os.environ.get(name) != expected:
            errors.append(f"unbound {name}")
    for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        value = os.environ.get(name, "")
        if not value.isascii() or not value.isdigit() or int(value) <= 0:
            errors.append(f"invalid {name}")
    prefix = (
        os.environ.get("GITHUB_REPOSITORY", "")
        + "/.github/workflows/platform-wire-exact.yml@"
    )
    if not os.environ.get("GITHUB_WORKFLOW_REF", "").startswith(prefix):
        errors.append("wrong exact workflow")
    if SHA.fullmatch(os.environ.get("GITHUB_WORKFLOW_SHA", "")) is None:
        errors.append("missing workflow SHA")
    if os.environ.get("GITHUB_EVENT_NAME") not in ("pull_request", "workflow_dispatch"):
        errors.append("unsupported exact-workflow event")
    return dict(
        source_sha=source,
        tested_sha=tested,
        tested_tree=tree,
        tested_parents=parents,
        run_id=os.environ.get("GITHUB_RUN_ID"),
        run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"),
        lane=execution_lane,
    ), errors


def receipt(records, source, base, lane, setup, execution):
    subject, errors = context(source, base, lane)
    if setup != "success" or execution != "success":
        errors.append("setup or command execution did not pass")
    verified = {}
    for name, floor, argv in commands(records):
        try:
            verified[name] = verify_command(records, name, floor, argv, subject)
        except (OSError, ValueError, TypeError, KeyError) as error:
            errors.append(f"{name}: {error}")
    from platform_wire_managed_fleet_profile import validate as fleet
    from platform_wire_retention_profile import validate as retention

    measurements = {}
    for name, validator, count in (
        ("managed-fleet-profile.measurements.json", fleet, 8),
        ("retention.measurements.json", retention, 32),
    ):
        try:
            raw = read_local(records, name, 4 * 1024 * 1024)
            report = json.loads(raw, object_pairs_hook=unique_object)
            validator(report, count)
            measurements[name] = dict(
                sha256=hashlib.sha256(raw).hexdigest(),
                scenario_count=len(report["scenarios"]),
            )
        except (OSError, ValueError, TypeError, KeyError) as error:
            errors.append(f"{name}: {error}")
    status = (
        "infrastructure_invalid"
        if setup != "success" or execution in ("", "skipped", "cancelled")
        else ("failed" if errors else "passed")
    )
    payload = {
        "schema": "hepta.platform-wire.receipt.v2",
        "kind": "platform-wire-exact-head"
        if lane == "source-head"
        else "platform-wire-synthetic-merge",
        **subject,
        "source_tree": git("rev-parse", source + "^{tree}"),
        "base_sha": base,
        "base_tree": git("rev-parse", base + "^{tree}"),
        "lane": lane,
        "execution_lane": subject["lane"],
        "workflow": os.environ.get("GITHUB_WORKFLOW"),
        "workflow_ref": os.environ.get("GITHUB_WORKFLOW_REF"),
        "workflow_sha": os.environ.get("GITHUB_WORKFLOW_SHA"),
        "event": os.environ.get("GITHUB_EVENT_NAME"),
        "run_id": int(subject["run_id"])
        if str(subject["run_id"]).isascii() and str(subject["run_id"]).isdigit()
        else 0,
        "run_attempt": int(subject["run_attempt"])
        if str(subject["run_attempt"]).isascii()
        and str(subject["run_attempt"]).isdigit()
        else 0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runner_image": os.environ.get("ImageOS"),
        "runner_image_version": os.environ.get("ImageVersion"),
        "runner": platform.platform(),
        "runner_name": os.environ.get("RUNNER_NAME"),
        "runner_os": os.environ.get("RUNNER_OS"),
        "runner_arch": os.environ.get("RUNNER_ARCH"),
        "toolchain_evidence": verified.get("toolchain"),
        "status": status,
        "errors": errors,
        "command_records": verified,
        "measurements": measurements,
        "qualification_scope": "native integration with fixture provider and in-process release measurements",
        "authenticated_network_ingress": False,
        "five_path_grpc_qualified": False,
        "independent_acceptance": False,
        "activation": False,
        "release": False,
    }
    records.mkdir(parents=True, exist_ok=True)
    (records / "receipt.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    hashes = {}
    for path in sorted(records.iterdir()):
        if path.is_file() and not path.is_symlink() and path.name != "SHA256SUMS.json":
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(65536), b""):
                    digest.update(block)
            hashes[path.name] = digest.hexdigest()
    (records / "SHA256SUMS.json").write_text(
        json.dumps(hashes, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            dict(
                status=status,
                source_sha=source,
                tested_sha=subject["tested_sha"],
                errors=errors,
            ),
            indent=2,
        )
    )
    return 0 if status == "passed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "receipt"))
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument(
        "--lane", required=True, choices=("source-head", "synthetic-merge")
    )
    parser.add_argument("--setup-outcome", default="")
    parser.add_argument("--execution-outcome", default="")
    args = parser.parse_args()
    try:
        records = args.records.resolve()
        root = Path(git("rev-parse", "--show-toplevel")).resolve()
        if args.records.is_symlink() or records.is_relative_to(root):
            raise ValueError("evidence must be outside the source checkout")
        if args.action == "receipt":
            return receipt(
                records,
                args.source_sha,
                args.base_sha,
                args.lane,
                args.setup_outcome,
                args.execution_outcome,
            )
        _, errors = context(args.source_sha, args.base_sha, args.lane)
        if os.environ.get("RECORDS") != str(records):
            errors.append("profile output directory differs from records")
        if errors:
            raise ValueError("; ".join(errors))
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
        print(f"exact qualification rejected: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
