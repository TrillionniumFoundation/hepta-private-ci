#!/usr/bin/env python3
"""Validate complete frozen-scope archive/replay evidence."""

import hashlib
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

SOURCE = "4223fc77944e9beb5651df063158b22ae1a4f701"
TREE = "7c19c9903d4e82baf3a61111214ff3fe46605cef"
BASE = "de0ddaa41bd91c4f46a2f1b6034d25fa84c4469c"
SHARDS = 4
JSON_LIMIT = 64 * 1024**2


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    require(path.is_file() and not path.is_symlink(), f"missing regular file: {path}")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(path):
    require(path.stat().st_size <= JSON_LIMIT, f"oversized JSON: {path}")
    return json.loads(path.read_text())


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def inventory(document, packages, partition=False):
    all_tests, selected, ignored = set(), set(), set()
    for binary, suite in document["rust-suites"].items():
        require(
            binary == suite["binary-id"] and suite["status"] == "listed",
            "unlisted/aliased binary",
        )
        require(suite["package-name"] in packages, "binary outside selected packages")
        for name, case in suite["testcases"].items():
            key = (binary, name)
            require(
                key not in all_tests and type(case["ignored"]) is bool,
                "invalid test identity",
            )
            all_tests.add(key)
            match = case["filter-match"]
            if case["ignored"]:
                require(
                    match == {"status": "mismatch", "reason": "ignored"},
                    "ignored boundary changed",
                )
                ignored.add(key)
            elif match == {"status": "matches"}:
                selected.add(key)
            else:
                require(
                    partition
                    and match == {"status": "mismatch", "reason": "partition"},
                    "unexpected filter",
                )
    require(
        document["test-count"] == len(all_tests) and selected,
        "empty/incomplete test inventory",
    )
    return all_tests, selected, ignored


def junit_passes(path, expected):
    require(path.stat().st_size <= JSON_LIMIT, "oversized JUnit")
    data = path.read_bytes()
    require(b"<!DOCTYPE" not in data, "unexpected JUnit document type")
    root = ET.fromstring(data)
    require(
        root.tag == "testsuites" and int(root.attrib["tests"]) == len(expected),
        "JUnit count differs",
    )
    require(
        root.attrib.get("failures") == "0" and root.attrib.get("errors") == "0",
        "JUnit failed",
    )
    observed, retried = set(), []
    for suite in root.findall("testsuite"):
        cases = suite.findall("testcase")
        require(int(suite.attrib["tests"]) == len(cases), "incomplete JUnit suite")
        for case in cases:
            key = (suite.attrib["name"], case.attrib["name"])
            require(
                case.attrib["classname"] == key[0] and key not in observed,
                "aliased/duplicate JUnit test",
            )
            require(
                not any(
                    case.find(tag) is not None
                    for tag in ("failure", "error", "skipped")
                ),
                "test did not pass",
            )
            observed.add(key)
            attempts = len(case.findall("flakyFailure")) + len(
                case.findall("flakyError")
            )
            if attempts:
                retried.append((*key, attempts))
    require(observed == expected, "JUnit identities differ from selected inventory")
    return sorted(retried)


def summarize(out, build, shards, needs):
    out.mkdir(parents=True, exist_ok=False)
    require(
        set(needs) == {"archive", "replay"}
        and all(n["result"] == "success" for n in needs.values()),
        "a required job did not succeed",
    )
    manifest = load(build / "manifest.json")
    require(manifest["status"] == "built", "archive stage missing")
    bound = manifest["identity"]
    require(
        (bound["source_sha"], bound["source_tree"], bound["base_sha"])
        == (SOURCE, TREE, BASE),
        "wrong frozen product",
    )
    require(
        bound["workflow_sha"] == os.environ["WORKFLOW_SHA"]
        and bound["qualification_helper_sha256"] == digest(Path(__file__).resolve())
        and bound["run_id"] == os.environ["GITHUB_RUN_ID"]
        and bound["run_attempt"] == os.environ["GITHUB_RUN_ATTEMPT"],
        "stale/foreign qualification evidence",
    )
    for name in ("identity.json", "plan.json", "inventory.json"):
        require(
            digest(build / name) == manifest["files"][name]["sha256"],
            "build inputs changed",
        )
    require(
        set(manifest["records"])
        == {"plan-command.json", "archive-command.json", "helper-command.json"},
        "missing build stage",
    )
    for name, expected in manifest["records"].items():
        record = load(build / name)
        require(
            digest(build / name) == expected
            and record["status"] == "passed"
            and record["exit_code"] == 0
            and record["tested_sha"] == SOURCE
            and record["before"] == record["after"]
            and record["before"]["dirty"] is False,
            "build record missing/failed",
        )
    packages = load(build / "plan.json")["packages"]
    require(len(packages) == len(set(packages)) == 124, "incomplete package scope")
    all_tests, expected, ignored = inventory(load(build / "inventory.json"), packages)
    require(
        (manifest["all_tests"], manifest["runnable_tests"], manifest["ignored_tests"])
        == (len(all_tests), len(expected), len(ignored)),
        "archive inventory counts differ",
    )
    observed, retried = set(), []
    require(
        {p.name for p in shards.iterdir()}
        == {f"shard-{i}" for i in range(1, SHARDS + 1)},
        "missing/extra shards",
    )
    for i in range(1, SHARDS + 1):
        directory = shards / f"shard-{i}"
        result = load(directory / "result.json")
        require(
            result["status"] == "passed"
            and result["shard"] == i
            and result["manifest_sha256"] == digest(build / "manifest.json"),
            "shard identity differs",
        )
        for name, key in (
            ("junit.xml", "junit_sha256"),
            ("inventory.json", "inventory_sha256"),
            ("test-command.json", "record_sha256"),
        ):
            require(digest(directory / name) == result[key], "shard evidence changed")
        shard_all, selected, shard_ignored = inventory(
            load(directory / "inventory.json"), packages, partition=True
        )
        require(
            shard_all == all_tests
            and shard_ignored == ignored
            and not observed & selected,
            "overlap/inventory mismatch",
        )
        require(
            result["ignored_not_qualified"] == len(ignored)
            and result["missing"] == 0
            and result["partition_excluded"] == len(expected - selected),
            "shard accounting changed",
        )
        require(
            sorted(selected) == [tuple(x) for x in result["selected"]],
            "shard result differs",
        )
        attempts = junit_passes(directory / "junit.xml", selected)
        require(
            attempts == [tuple(x) for x in result["retried"]],
            "retry accounting changed",
        )
        retried.extend(attempts)
        record = load(directory / "test-command.json")
        require(
            record["status"] == "passed"
            and record["exit_code"] == 0
            and record["tested_sha"] == SOURCE
            and record["minimum_tests"]
            == record["observed_passed_tests"]
            == len(selected)
            and record["observed_failed_tests"] == 0
            and not record["timed_out"]
            and not record["output_limit_exceeded"]
            and record["after"] == record["before"]
            and record["before"]["commit"] == SOURCE
            and record["before"]["tree"] == TREE
            and record["before"]["dirty"] is False,
            "native test record failed",
        )
        observed |= selected
    require(
        observed == expected,
        "shard union does not equal complete runnable test inventory",
    )
    save(
        out / "summary.json",
        {
            "status": "passed",
            "source_sha": SOURCE,
            "source_tree": TREE,
            "manifest_sha256": digest(build / "manifest.json"),
            "packages": len(packages),
            "runnable_passed": len(observed),
            "ignored_not_qualified": len(ignored),
            "ignored_tests": sorted(ignored),
            "retried_tests": sorted(retried),
            "missing_tests": 0,
            "shards": SHARDS,
            "product_qualified": False,
            "replaces_required_gate": False,
        },
    )
