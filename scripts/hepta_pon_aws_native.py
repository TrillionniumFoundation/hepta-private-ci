#!/usr/bin/env python3
"""Observe five hosted AWS compatibility scenarios on an exact committed tree.

Local use is restricted to parser controls. Test discovery is a real native
operation; a missing discovery or JUnit result remains unknown. This observer
does not qualify other platforms, the complete product, or PoN activation.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET

from hepta_ci_exec import identity as checkout_identity
from hepta_pon_aws_crypto_proposal import check_lock
from hepta_pon_aws_crypto_source import (
    EVIDENCE,
    INPUTS,
    ROOT,
    VENDOR,
    archive_members,
    identity,
    require,
    retain_files,
    safe_relative,
)
from hepta_pon_dependency_proposal import now, require_hosted, write_json


SCENARIOS = {
    "provider-default": ("aws-config", ["--features", "credentials-login"]),
    "provider-login-only": (
        "aws-config",
        ["--no-default-features", "--features", "credentials-login,rt-tokio"],
    ),
    "auth-default": ("codex-aws-auth", []),
    "auth-sigv4a": ("codex-aws-auth", ["--features", "aws-sigv4/sigv4a"]),
    "upstream-sigv4a": ("aws-sigv4", ["--all-features"]),
}
DPOP = {
    "login::dpop::tests::test_header_extracts_public_coordinates",
    "login::dpop::tests::test_build_message",
    "login::dpop::tests::test_calculate_valid_key",
    "login::dpop::tests::test_calculate_invalid_key",
    "login::dpop::migration_tests::migrated_dpop_is_accepted_by_an_independent_es256_verifier",
    "login::dpop::migration_tests::entropy_failure_returns_no_signature",
    "login::dpop::migration_tests::truncated_sec1_key_is_rejected_without_echoing_it",
}


def source_state(source, output):
    require_hosted(source, output)
    expected = "TrillionniumFoundation/hepta-private-ci/.github/workflows/hepta-pon-aws-crypto-native.yml@"
    require(
        os.environ.get("GITHUB_WORKFLOW_REF", "").startswith(expected)
        and os.environ.get("GITHUB_JOB") == "qualify",
        "native observer requires its exact hosted workflow",
    )
    observed = checkout_identity(repository=ROOT)
    require(
        observed["commit"] == source and not observed["dirty"],
        "native source must be the exact clean committed checkout",
    )
    return observed


def discovery(raw):
    """Keep every discovered identity, including ignored and unmatched cases."""
    data = json.loads(raw)
    require(type(data.get("test-count")) is int, "missing discovery denominator")
    suites = data.get("rust-suites")
    require(isinstance(suites, dict) and bool(suites), "missing discovered suites")
    cases = []
    for binary, suite in suites.items():
        require(suite.get("status") == "listed", "unlisted suite is unknown")
        require(isinstance(suite.get("testcases"), dict), "missing case inventory")
        for name, case in suite["testcases"].items():
            status = case.get("filter-match", {}).get("status")
            require(status in {"matches", "mismatch"}, "unknown case selection")
            require(type(case.get("ignored")) is bool, "unknown ignored status")
            cases.append(
                {
                    "binary": binary,
                    "name": name,
                    "ignored": case["ignored"],
                    "selected": status == "matches",
                    "filter_match": case["filter-match"],
                }
            )
    require(len(cases) == data["test-count"], "discovery total mismatch")
    require(any(case["selected"] for case in cases), "empty selected denominator")
    return cases


def reconcile(cases, raw):
    """Join complete nextest identities with its terminal JUnit result."""
    selected = {(case["binary"], case["name"]) for case in cases if case["selected"]}
    observed = {}
    if raw is not None:
        require(
            b"<!DOCTYPE" not in raw and b"<!ENTITY" not in raw,
            "external XML declarations",
        )
        root = ET.fromstring(raw)
        require(root.tag == "testsuites", "unexpected JUnit document")
        for case in root.iter("testcase"):
            key = (case.get("classname"), case.get("name"))
            require(
                key in selected and key not in observed,
                "unexpected or duplicate JUnit identity",
            )
            statuses = [
                tag
                for tag in ("failure", "error", "skipped")
                if case.find(tag) is not None
            ]
            require(len(statuses) <= 1, "ambiguous terminal status")
            require(
                not any(
                    node.tag.startswith(("rerun", "flaky")) for node in case.iter()
                ),
                "unexpected retry result",
            )
            observed[key] = {
                "binary": key[0],
                "name": key[1],
                "status": statuses[0] if statuses else "passed",
                "seconds": case.get("time"),
                "failure_types": [
                    node.get("type")
                    for node in case
                    if node.tag in {"failure", "error"}
                ],
            }
    missing = sorted(selected - observed.keys())
    return {
        "discovered": len(cases),
        "ignored": sum(case["ignored"] for case in cases),
        "selected": len(selected),
        "observed": len(observed),
        "unobserved": [{"binary": key[0], "name": key[1]} for key in missing],
        "results": [observed[key] for key in sorted(observed)],
        "all_selected_passed": not missing
        and all(row["status"] == "passed" for row in observed.values()),
    }


def prepare(output, source, scenario):
    before = source_state(source, output)
    require(scenario in SCENARIOS, "unknown scenario")
    require(not output.exists(), "refusing to overwrite an earlier attempt")
    output.mkdir(parents=True)
    (output / "logs").mkdir()
    review = json.loads(
        (
            ROOT / "qa/pon-aws-crypto-resolution-20261028-r11/import-review.json"
        ).read_text()
    )
    require(
        review["schema"] == "hepta-aws-coherent-import-v1", "unreviewed import schema"
    )
    expected = {
        entry["path"]: {key: entry[key] for key in ("bytes", "sha256")}
        for entry in review["installed_files"]
    }
    actual_paths = set(INPUTS) | {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / VENDOR).rglob("*")
        if path.is_file()
    }
    require(set(expected) == actual_paths, "installed source inventory changed")
    for name, wanted in expected.items():
        path = ROOT / safe_relative(name)
        require(
            path.is_file()
            and not path.is_symlink()
            and identity(path.read_bytes()) == wanted,
            "installed source identity changed: " + name,
        )
    package, features = SCENARIOS[scenario]
    upstream = scenario == "upstream-sigv4a"
    manifest = (
        ROOT / VENDOR / "Cargo.toml"
        if scenario.startswith("provider-")
        else ROOT / "codex-rs/aws-auth/Cargo.toml"
    )
    graph = "committed-product"
    if upstream:
        archive = EVIDENCE / "upstream/aws-sigv4-1.6.4.crate"
        raw = archive.read_bytes()
        require(
            identity(raw)["sha256"]
            == "f385da9b7757ed4c8214797ad663ff534fb622006143530aa80e21f8e06ff85c",
            "upstream archive identity mismatch",
        )
        destination = output / "upstream/aws-sigv4-1.6.4"
        retain_files(destination, archive_members(raw, "aws-sigv4-1.6.4"))
        manifest = destination / "Cargo.toml"
        graph = "published-upstream-lock-separate-from-product"
    config = ROOT / "codex-rs/.config/nextest.toml"
    arguments = ["--locked", "--manifest-path", str(manifest), "-p", package, *features]
    metadata = [
        "cargo",
        "+1.96.0",
        "metadata",
        "--locked",
        "--manifest-path",
        str(manifest),
        *features,
        "--format-version",
        "1",
    ]
    discover = [
        "cargo",
        "+1.96.0",
        "nextest",
        "list",
        *arguments,
        "--config-file",
        str(config),
        "--profile",
        "local",
        "--message-format",
        "json",
    ]
    tests = [
        "just",
        "test",
        *arguments,
        "--config-file",
        str(config),
        "--retries",
        "0",
        "--no-tests",
        "fail",
        "--test-threads",
        "2",
        "--no-capture",
    ]
    locked = (
        manifest.parent / "Cargo.lock" if upstream else ROOT / "codex-rs/Cargo.lock"
    )
    record = {
        "schema": "hepta-aws-native-observation-v1",
        "source": before,
        "scenario": scenario,
        "complete_scenario_denominator": list(SCENARIOS),
        "dependency_graph": graph,
        "run_id": os.environ["GITHUB_RUN_ID"],
        "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "event": os.environ["GITHUB_EVENT_NAME"],
        "github_run_sha": os.environ["GITHUB_SHA"],
        "started_at_utc": now(),
        "job_minutes": 50,
        "native_step_minutes": 35,
        "test_retries": 0,
        "deadline_policy": "Hosted step/job watchdog only; interrupted outcomes stay unknown; original nextest case timeouts unchanged",
        "original_inputs": {
            name: identity((ROOT / name).read_bytes()) for name in INPUTS
        },
        "installed_source_review": identity(
            (
                ROOT / "qa/pon-aws-crypto-resolution-20261028-r11/import-review.json"
            ).read_bytes()
        ),
        "lock_path": str(locked),
        "lock_before": identity(locked.read_bytes()),
        "test_inventory": None,
        "terminal_cases": None,
        "stages": [
            {
                "name": name,
                "command": command,
                "state": "not_started",
                "exit_code": None,
            }
            for name, command in [
                ("rustc-version", ["rustc", "--version", "--verbose"]),
                ("cargo-version", ["cargo", "--version", "--verbose"]),
                ("nextest-version", ["cargo", "nextest", "--version"]),
                ("just-version", ["just", "--version"]),
                ("metadata", metadata),
                ("discovery", discover),
                ("tests", tests),
            ]
        ],
        "native_scenario_passed": False,
        "whole_product_qualified": False,
        "bigint_blocker_closed": False,
        "state": "prepared",
    }
    check_lock((ROOT / "codex-rs/Cargo.lock").read_bytes())
    write_json(output / "record.json", record)


def check_features(raw, scenario):
    metadata = json.loads(raw)
    nodes = {node["id"]: set(node["features"]) for node in metadata["resolve"]["nodes"]}
    packages = {
        package["name"]: package
        for package in metadata["packages"]
        if package["name"] in {"aws-config", "aws-sigv4"}
    }
    if scenario != "upstream-sigv4a":
        provider = packages["aws-config"]
        require(
            provider["source"] is None
            and Path(provider["manifest_path"]) == ROOT / VENDOR / "Cargo.toml",
            "provider owner differs",
        )
        enabled = nodes[provider["id"]]
        require(
            {"credentials-login", "rt-tokio"} <= enabled, "login provider not active"
        )
        if scenario != "provider-login-only":
            require(
                {"default", "sso", "credentials-process", "default-https-client"}
                <= enabled,
                "production provider features trimmed",
            )
        else:
            require(
                not {"default", "sso", "credentials-process"} & enabled,
                "login-only scenario is not isolated",
            )
    signer = packages.get("aws-sigv4")
    if scenario in {"auth-sigv4a", "upstream-sigv4a"}:
        require(
            signer is not None and "sigv4a" in nodes[signer["id"]],
            "SigV4a was not activated",
        )
    return {
        name: sorted(nodes[package["id"]]) for name, package in sorted(packages.items())
    }


def run(output, source):
    source_state(source, output)
    record = json.loads((output / "record.json").read_text())
    require(
        record["source"]["commit"] == source and record["state"] == "prepared",
        "not a fresh prepared observation",
    )
    target = Path(os.environ["CARGO_TARGET_DIR"]).resolve()
    temporary = Path(os.environ["RUNNER_TEMP"]).resolve()
    require(
        target.is_relative_to(temporary) and not target.is_relative_to(output),
        "target must be outside retained evidence",
    )
    junit = target / "nextest/local/junit.xml"
    require(not junit.exists(), "stale JUnit result exists")
    record["state"] = "running"
    write_json(output / "record.json", record)
    for stage in record["stages"]:
        stage.update(state="running", started_at_utc=now())
        write_json(output / "record.json", record)
        started = time.monotonic()
        try:
            with (
                (output / "logs" / (stage["name"] + ".stdout.txt")).open(
                    "wb"
                ) as stdout,
                (output / "logs" / (stage["name"] + ".stderr.txt")).open(
                    "wb"
                ) as stderr,
            ):
                result = subprocess.run(
                    stage["command"],
                    cwd=ROOT,
                    stdout=stdout,
                    stderr=stderr,
                    check=False,
                )
            stage.update(
                state="succeeded" if result.returncode == 0 else "failed",
                exit_code=result.returncode,
                finished_at_utc=now(),
                wall_seconds=time.monotonic() - started,
            )
            if result.returncode != 0:
                record["state"] = "failed"
                write_json(output / "record.json", record)
                return result.returncode
            if stage["name"] == "metadata":
                record["actual_features"] = check_features(
                    (output / "logs/metadata.stdout.txt").read_bytes(),
                    record["scenario"],
                )
            if stage["name"] == "discovery":
                cases = discovery((output / "logs/discovery.stdout.txt").read_bytes())
                if record["scenario"].startswith("provider-"):
                    require(
                        DPOP <= {case["name"] for case in cases if case["selected"]},
                        "original or migration DPoP tests missing",
                    )
                record["test_inventory"] = cases
        except (OSError, ValueError, KeyError) as error:
            stage.update(
                state="failed",
                observer_error=str(error),
                wall_seconds=time.monotonic() - started,
            )
            record["state"] = "failed"
            write_json(output / "record.json", record)
            return 1
        write_json(output / "record.json", record)
    record["state"] = "commands_completed"
    write_json(output / "record.json", record)
    return 0


def finalize(output, source):
    record_path = output / "record.json"
    require(
        record_path.is_file(), "prepared record missing; no observation can qualify"
    )
    record = json.loads(record_path.read_text())
    require(record["source"]["commit"] == source, "finalizer source mismatch")
    record["workflow_native_step_outcome"] = os.environ.get("NATIVE_STEP_OUTCOME")
    for stage in record["stages"]:
        if stage["state"] == "running":
            stage["state"] = "interrupted_or_unknown"
    errors = []
    try:
        record["source_after"] = source_state(source, output)
        require(record["source_after"] == record["source"], "source identity changed")
        require(
            {name: identity((ROOT / name).read_bytes()) for name in INPUTS}
            == record["original_inputs"],
            "product input drift",
        )
        record["lock_after"] = identity(Path(record["lock_path"]).read_bytes())
        require(record["lock_after"] == record["lock_before"], "dependency lock drift")
    except (OSError, ValueError, KeyError) as error:
        errors.append(str(error))
    junit = Path(os.environ["CARGO_TARGET_DIR"]) / "nextest/local/junit.xml"
    raw = None
    if junit.is_file() and not junit.is_symlink():
        raw = junit.read_bytes()
        (output / "junit.xml").write_bytes(raw)
    if record["test_inventory"] is not None:
        try:
            record["terminal_cases"] = reconcile(record["test_inventory"], raw)
        except (ValueError, ET.ParseError) as error:
            errors.append(str(error))
    record["finalizer_errors"] = errors
    record["native_scenario_passed"] = (
        not errors
        and record["state"] == "commands_completed"
        and record["workflow_native_step_outcome"] == "success"
        and bool(
            record["terminal_cases"] and record["terminal_cases"]["all_selected_passed"]
        )
        and all(
            stage["state"] == "succeeded" and stage["exit_code"] == 0
            for stage in record["stages"]
        )
    )
    record["state"] = (
        "passed" if record["native_scenario_passed"] else "failed_or_incomplete"
    )
    record["finished_at_utc"] = now()
    write_json(record_path, record)
    files = [
        {"path": path.relative_to(output).as_posix(), **identity(path.read_bytes())}
        for path in sorted(output.rglob("*"))
        if path.is_file() and not path.is_symlink() and path.name != "files.json"
    ]
    write_json(
        output / "files.json", {"schema": "hepta-aws-native-files-v1", "files": files}
    )
    return 0 if record["native_scenario_passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "run", "finalize"))
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", choices=tuple(SCENARIOS))
    args = parser.parse_args()
    output = args.output.resolve()
    if args.mode == "prepare":
        prepare(output, args.source, args.scenario)
        return 0
    if args.mode == "run":
        return run(output, args.source)
    return finalize(output, args.source)


if __name__ == "__main__":
    raise SystemExit(main())
