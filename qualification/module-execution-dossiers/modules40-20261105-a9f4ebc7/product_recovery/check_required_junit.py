#!/usr/bin/env python3
"""Audit named Rust tests in existing JUnit files; never runs or changes tests."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


def local_tag(tag):
    return tag.rsplit("}", 1)[-1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def target_ids(expected):
    package, binary = expected["package"], expected["binary"]
    kind = expected.get("binary_kind", "lib" if binary == package.replace("-", "_") else "bin")
    return set(expected["target_aliases"]) | {
        f"{package}::{binary}", f"{package}::{kind}/{binary}",
    }


def case_names(case, expected):
    name = case["name"]
    classname = case["classname"]
    names = {name, f"{classname}::{name}"} if classname else {name}
    for _ in range(3):
        more = set()
        for value in names:
            for alias in target_ids(expected):
                if value.startswith(alias + "::"):
                    more.add(value[len(alias) + 2:])
        names |= more
    return names


def correct_target(case, expected):
    allowed = target_ids(expected)
    classname = case["classname"]
    suite = case["nearest_testsuite"]
    module = expected["test"].rsplit("::", 1)[0]
    class_target = classname in allowed or any(
        classname == target + "::" + module for target in allowed
    )
    suite_target = suite in allowed
    # Only the nearest actual testsuite may identify the executable. Aggregate
    # testsuites names never do. Explicit conflicting target metadata is refused.
    class_permitted = class_target or classname in {"", module}
    suite_permitted = suite_target or not suite
    return (class_target or suite_target) and class_permitted and suite_permitted


def load_junit(path):
    data = path.read_bytes()
    root = ET.fromstring(data)
    cases, aggregate_failures = [], []

    def walk(node, suites, nearest_suite=""):
        tag = local_tag(node.tag)
        if tag in {"testsuites", "testsuite"}:
            suites = suites + [node.attrib.get("name", "")]
            if tag == "testsuite":
                nearest_suite = node.attrib.get("name", "")
            for key in ["failures", "errors"]:
                if key in node.attrib:
                    try:
                        count = int(node.attrib[key])
                    except ValueError:
                        aggregate_failures.append({"suite": suites, "field": key,
                                                   "invalid_value": node.attrib[key]})
                    else:
                        if count:
                            aggregate_failures.append({"suite": suites, "field": key,
                                                       "count": count})
        if tag == "testcase":
            tags = {local_tag(child.tag).lower() for child in node.iter() if child is not node}
            attrs = node.attrib
            disposition = (attrs.get("status", "") + " " + attrs.get("result", "")).lower()
            skipped = "skipped" in tags or bool(re.search(
                r"\b(skipped|ignored|disabled|notrun|not_run|suppressed)\b", disposition))
            failed = bool(tags & {"failure", "error"}) or bool(re.search(
                r"\b(failed|failure|error|timeout|timed_out)\b", disposition))
            flaky = bool(tags & {"flakyfailure", "flakyerror", "rerunfailure", "rerunerror"})
            for key in ["retry_count", "rerun_count", "retries"]:
                if key in attrs:
                    try:
                        flaky |= int(attrs[key]) > 0
                    except ValueError:
                        failed = True
            cases.append({
                "junit": str(path), "name": attrs.get("name", ""),
                "classname": attrs.get("classname", ""), "suites": suites,
                "nearest_testsuite": nearest_suite,
                "skipped": skipped, "failed": failed, "flaky_or_retried": flaky,
                "status_attribute": attrs.get("status"), "result_attribute": attrs.get("result"),
                "time": attrs.get("time"),
            })
        else:
            for child in node:
                walk(child, suites, nearest_suite)

    walk(root, [])
    return cases, aggregate_failures, {"path": str(path), "bytes": len(data),
                                       "sha256": digest(data)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--junit", type=Path, action="append", required=True,
                        help="Exact existing report path; repeat for separate package reports.")
    parser.add_argument("--suite-exit-code", type=int, required=True,
                        help="Recorded original runner exit, not the checker exit.")
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--candidate-tree", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    for label in ["candidate_commit", "candidate_tree"]:
        if not re.fullmatch(r"[0-9a-f]{40}", getattr(args, label)):
            parser.error(f"--{label.replace('_', '-')} requires a full 40-character SHA")

    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    required = manifest["required_tests"]
    if not required or len({(x["package"], x["binary"], x["test"]) for x in required}) != len(required):
        parser.error("manifest must contain a nonempty, unique required test set")
    reports = [path.resolve() for path in args.junit]
    if len(set(reports)) != len(reports):
        parser.error("the same JUnit file was supplied more than once")

    cases, inputs, aggregate_failures, parse_errors = [], [], [], []
    for path in reports:
        try:
            found, aggregates, evidence = load_junit(path)
        except (OSError, ET.ParseError) as error:
            parse_errors.append({"path": str(path), "error": str(error)})
            continue
        cases.extend(found)
        inputs.append(evidence)
        aggregate_failures.extend({"junit": str(path), **value} for value in aggregates)

    results = []
    for expected in required:
        named = [case for case in cases if expected["test"] in case_names(case, expected)]
        matches = [case for case in named if correct_target(case, expected)]
        if not matches:
            status = "WRONG_TARGET" if named else "MISSING"
        elif len(matches) != 1:
            status = "DUPLICATE"
        elif matches[0]["skipped"]:
            status = "SKIPPED"
        elif matches[0]["failed"]:
            status = "FAILED"
        elif matches[0]["flaky_or_retried"]:
            status = "FLAKY_OR_RETRIED"
        else:
            status = "PASS"
        results.append({"package": expected["package"], "binary": expected["binary"],
                        "test": expected["test"], "area": expected["area"],
                        "status": status, "matches": matches,
                        "same_name_wrong_target": [case for case in named if case not in matches]})

    failed_cases = [case for case in cases if case["failed"]]
    flaky_cases = [case for case in cases if case["flaky_or_retried"]]
    skipped_cases = [case for case in cases if case["skipped"]]
    clean = bool(cases) and args.suite_exit_code == 0 and not parse_errors \
        and not aggregate_failures and not failed_cases and not flaky_cases \
        and all(value["status"] == "PASS" for value in results)
    report = {
        "gate_result": "CLEAN" if clean else "NOT_CLEAN",
        "original_suite_exit_code": args.suite_exit_code,
        "candidate_identity_supplied_by_operator": {
            "commit": args.candidate_commit, "tree": args.candidate_tree,
        },
        "manifest": {"path": str(args.manifest), "sha256": digest(manifest_bytes)},
        "junit_inputs": inputs, "required_count": len(required),
        "required_clean_passes": sum(value["status"] == "PASS" for value in results),
        "observed_case_count": len(cases), "required_results": results,
        "all_failed_cases": failed_cases, "all_flaky_or_retried_cases": flaky_cases,
        "all_skipped_cases": skipped_cases, "aggregate_failures": aggregate_failures,
        "parse_errors": parse_errors,
        "semantics": [
            "This checks existing results; it does not run tests or change profiles, timeouts, retries or filters.",
            "NOT_CLEAN is a completeness/outcome audit result, not a rewrite of the original runner exit code.",
            "A retry remains visible even if the original profile permits it and the runner exits zero.",
            "Noncritical skips are listed; a skipped/missing required case or any failed/flaky case prevents CLEAN.",
            "Test names match exact Rust module paths plus known target aliases; no leaf-name-only matching.",
            "Target identity requires exact testcase class or nearest actual testsuite metadata; aggregate names and conflicting target metadata cannot supply it.",
            "JUnit cannot prove absence of in-test early returns; process tests must keep their completion-marker assertions.",
            "The operator must bind these report hashes to the recorded command, frozen source tree and run interval; XML alone cannot authenticate candidate provenance.",
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['gate_result']}: {report['required_clean_passes']}/{len(required)} "
          f"required clean passes; {len(cases)} cases, {len(skipped_cases)} skips, "
          f"{len(flaky_cases)} flaky/retried, {len(failed_cases)} failed; "
          f"original runner exit={args.suite_exit_code}")
    for result in results:
        if result["status"] != "PASS":
            print(f"{result['status']}: {result['package']} {result['test']}")
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
