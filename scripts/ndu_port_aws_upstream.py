"""Full upstream AWS qualification on a separate exact-source copy and lock."""

import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from ndu_port_candidate_common import checksum
from ndu_port_candidate_common import describe
from ndu_port_candidate_common import prepare_nextest_storage
from ndu_port_candidate_common import relative_path
from ndu_port_candidate_common import tree_files


def suite_inventory(listing, qualification):
    expected = (
        qualification["expected_total"],
        qualification["expected_executed"],
        qualification["expected_ignored"],
    )
    if expected != (245, 244, 1) or qualification["ignored_tests"] != [
        "ecs::test::real_dns_lookup"
    ]:
        raise ValueError(
            "This qualification must retain the complete frozen 245-test inventory"
        )
    executed, ignored, binaries = set(), [], {}
    total = 0
    for suite in listing["rust-suites"].values():
        if suite["package-name"] != "aws-config" or suite["status"] != "listed":
            raise ValueError(
                "Upstream suite belongs to a different package or was not listed"
            )
        binaries[suite["binary-id"]] = suite["binary-path"]
        for name, case in suite["testcases"].items():
            total += 1
            if case["ignored"]:
                ignored.append(name)
            else:
                if case["filter-match"]["status"] != "matches":
                    raise ValueError("A nonignored upstream test was filtered out")
                executed.add((suite["binary-id"], name))
    if (total, len(executed), len(ignored)) != expected or sorted(
        ignored
    ) != qualification["ignored_tests"]:
        raise ValueError("Full upstream inventory or original ignored testcase differs")
    if listing["test-count"] != total:
        raise ValueError("Nextest inventory total differs from listed cases")
    return executed, binaries


def verify_suite_junit(path, expected):
    report = ET.parse(path).getroot()
    cases = list(report.iter("testcase"))
    observed = {(case.get("classname"), case.get("name")) for case in cases}
    if len(cases) != 244 or len(observed) != 244 or observed != expected:
        raise ValueError(
            "JUnit did not execute every one of the 244 expected upstream tests"
        )
    if report.get("tests") != "244" or any(
        int(report.get(key, "0")) for key in ("failures", "errors", "skipped")
    ):
        raise ValueError("Full upstream suite has failures, errors or unexpected skips")
    if any(node.tag in {"failure", "error", "skipped"} for node in report.iter()):
        raise ValueError("An upstream assertion failed or an executed case was skipped")
    retries = sum(
        any(node.tag in {"flakyFailure", "flakyError"} for node in case)
        for case in cases
    )
    return {
        "executed": 244,
        "passed": 244,
        "original_ignored": 1,
        "passed_after_retry": retries,
    }


def qualify_aws(runner, recipe):
    qualification = recipe["aws_qualification"]
    vendor = relative_path(qualification["vendor_dir"])
    if (
        vendor not in recipe["vendor_dirs"]
        or tree_files(runner.root / vendor) != recipe["vendor_dirs"][vendor]
    ):
        raise ValueError(
            "AWS qualification vendor differs from the production candidate"
        )
    resources = qualification["resources"]
    if set(resources) != {"Cargo.lock", ".config/nextest.toml"}:
        raise ValueError(
            "Only the frozen standalone lock and nextest configuration may overlay the copy"
        )
    for resource in resources.values():
        name = relative_path(resource["path"])
        if describe(runner.root, (name,))[name] != {
            "bytes": resource["bytes"],
            "sha256": resource["sha256"],
        }:
            raise ValueError("AWS qualification resource differs from recipe")
    isolated = runner.output / "aws-qualification-copy"
    shutil.copytree(runner.root / vendor, isolated)
    if tree_files(isolated) != recipe["vendor_dirs"][vendor]:
        raise ValueError("Copied AWS source differs before qualification overlays")
    for destination, resource in resources.items():
        path = isolated / destination
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(runner.root / resource["path"], path)
    source_files = tree_files(isolated)
    runner.record["upstream_qualification"] = {
        "production_vendor": vendor,
        "isolated_source_files_before": source_files,
        "qualification_resources": resources,
        "production_workspace_membership_changed": False,
        "test_plan": "Complete aws-config suite with credentials-login and its original single ignored DNS test; both reserved-address timeout assertions remain enabled.",
    }
    environment = {
        "NO_COLOR": "",
        "CARGO_TARGET_DIR": str(
            runner.output.parent / (runner.output.name + "-target")
        ),
    }
    storage = prepare_nextest_storage(runner)
    args = [
        "--manifest-path",
        str(isolated / "Cargo.toml"),
        "--locked",
        "-p",
        "aws-config",
        "--features",
        "credentials-login",
        "--config-file",
        str(isolated / ".config/nextest.toml"),
        "--tool-config-file",
        storage["tool_config_argument"],
    ]
    listing_path = runner.output / "aws-full-test-list.json"
    runner.run(
        "list-all-upstream-tests",
        ["cargo", "nextest", "list", *args, "--message-format", "json"],
        stdout=listing_path,
        environment=environment,
    )
    listing = json.loads(listing_path.read_text())
    expected, binaries = suite_inventory(listing, qualification)
    executable_records = {}
    for identifier, name in binaries.items():
        binary = Path(name)
        if binary.is_symlink() or not binary.is_file():
            raise ValueError(
                "Listed upstream executable is not a regular compiled file"
            )
        digest = checksum(binary)
        copy = runner.output / "binaries" / digest
        copy.parent.mkdir(exist_ok=True)
        shutil.copyfile(binary, copy)
        if checksum(copy) != digest:
            raise ValueError(
                "Saved upstream executable differs from the actual compiled bytes"
            )
        executable_records[identifier] = {
            "original_path": name,
            "saved_path": str(copy.relative_to(runner.output)),
            "sha256": digest,
        }
    runner.record["upstream_qualification"].update(
        binaries=executable_records, expected_executed_tests=sorted(expected)
    )
    target = Path(listing["rust-build-meta"]["target-directory"])
    store = Path(storage["directory"])
    runner.record["upstream_qualification"].update(
        nextest_storage=storage, cargo_target_directory=str(target)
    )
    reports = lambda: {
        p: (p.stat().st_mtime_ns, checksum(p)) for p in store.glob("*/junit.xml")
    }
    before = reports()
    status = runner.run(
        "all-upstream-tests",
        ["just", "test", *args, "--profile", "default"],
        required=False,
        environment=environment,
    )
    outcome = runner.record["upstream_qualification"]
    outcome["exit_code"] = status
    fresh = [path for path, value in reports().items() if before.get(path) != value]
    outcome["fresh_junit_count"] = len(fresh)
    outcome["observed_junit_paths"] = [str(path) for path in fresh]
    outcome["store_config_unchanged_after_execution"] = (
        describe(runner.output, (storage["config_file"],))[storage["config_file"]]
        == storage["config"]
    )
    for index, path in enumerate(fresh):
        shutil.copyfile(path, runner.output / f"aws-upstream-{index}-junit.xml")
    outcome["retained_junit_reports"] = describe(
        runner.output,
        [f"aws-upstream-{index}-junit.xml" for index in range(len(fresh))],
    )
    outcome["binary_bytes_unchanged"] = all(
        checksum(Path(item["original_path"])) == item["sha256"]
        for item in executable_records.values()
    )
    outcome["isolated_source_files_after"] = tree_files(isolated)
    runner.save()
    if source_files != outcome["isolated_source_files_after"]:
        raise ValueError(
            "Full qualification modified source, frozen lock or configuration"
        )
    if (
        status
        or not outcome["binary_bytes_unchanged"]
        or not outcome["store_config_unchanged_after_execution"]
        or fresh != [store / "default/junit.xml"]
    ):
        raise ValueError("Full upstream execution failed or lacks a fresh bound result")
    report = runner.output / "aws-upstream-0-junit.xml"
    outcome["observed"] = verify_suite_junit(report, expected)
    outcome["junit"] = {"file": report.name, "sha256": checksum(report)}
    return True
