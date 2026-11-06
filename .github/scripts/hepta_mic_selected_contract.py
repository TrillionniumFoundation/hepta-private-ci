"""Validate the fixed Windows MIC selection and preserve original retry evidence."""

import json
import re
import xml.etree.ElementTree as ET

from hepta_mic_selected_evidence import identity
from hepta_mic_selected_evidence import require
from hepta_mic_selected_guard import ROOT
from hepta_mic_selected_guard import SPEC


def report_path():
    parent = ROOT
    for part in ("codex-rs", "target", "nextest", "local"):
        parent = parent / part
        require(
            not parent.is_symlink() and not parent.is_junction(), "JUNIT_PARENT_LINK"
        )
        require(not parent.exists() or parent.is_dir(), "JUNIT_PARENT_NOT_DIRECTORY")
    return parent / "junit.xml"


def expected_commands():
    args = [
        "--locked",
        "-p",
        "codex-windows-sandbox",
        "--lib",
        "--target",
        SPEC["native_target"],
        "--cargo-profile",
        "dev-small",
        "--tool-config-file",
        "hepta-mic-selected:"
        + str(ROOT / ".github/scripts/hepta-mic-selected-report.toml"),
        "-E",
        " | ".join("test(=" + case + ")" for case in SPEC["cases"]),
    ]
    return {
        "python": ["python", "--version"],
        "rustc": ["rustc", "--version", "--verbose"],
        "cargo": ["cargo", "--version"],
        "just": ["just", "--version"],
        "nextest": ["cargo", "nextest", "--version"],
        "list": ["cargo", "nextest", "list", *args, "--message-format", "json"],
        "run": [
            "just",
            "test",
            *args,
            "--success-output",
            "final",
            "--failure-output",
            "immediate-final",
        ],
    }


def version_guard(files):
    expected = {
        "python": "Python 3.12.10",
        "rustc": "rustc 1.96.0 ",
        "cargo": "cargo 1.96.0 ",
        "just": "just 1.51.0",
        "nextest": "cargo-nextest 0.9.103 ",
    }
    for name, prefix in expected.items():
        raw = files["logs/" + name + ".stdout.log"].decode("utf-8", "strict").strip()
        matches = (
            raw == prefix if name in {"python", "just"} else raw.startswith(prefix)
        )
        require(matches, "TOOL_VERSION_MISMATCH")
        if name == "rustc":
            require(
                "host: " + SPEC["native_target"] in raw.splitlines(),
                "RUSTC_HOST_MISMATCH",
            )


def selected_cases(raw):
    selected = []
    for binary_id, suite in json.loads(raw)["rust-suites"].items():
        for name, case in suite["testcases"].items():
            if case["filter-match"]["status"] != "matches":
                continue
            require(
                binary_id == suite["binary-id"] == SPEC["binary_id"]
                and suite["package-name"] == "codex-windows-sandbox"
                and suite["binary-name"] == "codex_windows_sandbox"
                and suite["kind"] == "lib"
                and suite["status"] == "listed"
                and suite["build-platform"] == "target"
                and case["ignored"] is False,
                "INVALID_SELECTED_BINARY_OR_CASE",
            )
            selected.append(name)
    require(sorted(selected) == SPEC["cases"], "NOT_EXACTLY_THREE_CASES")


def outcome_guard(stdout, stderr, junit):
    text = (stdout + b"\n" + stderr).decode("utf-8", "strict")
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    require(not re.search(r"\bskipping test\b", text, re.I), "IN_TEST_SKIP")
    require(b"<!DOCTYPE" not in junit, "UNEXPECTED_XML_DOCTYPE")
    report = ET.fromstring(junit)
    require(
        not re.search(r"\bskipping test\b", "".join(report.itertext()), re.I),
        "IN_TEST_SKIP",
    )
    suites = list(report.iter("testsuite"))
    require(
        report.tag == "testsuites"
        and len(suites) == 1
        and suites[0].attrib.get("name") == SPEC["binary_id"],
        "JUNIT_SUITE_MISMATCH",
    )
    cases = list(report.iter("testcase"))
    require(
        sorted(case.attrib.get("name", "") for case in cases) == SPEC["cases"],
        "JUNIT_CASE_MISMATCH",
    )
    for node in [report, suites[0]]:
        require(
            node.attrib.get("tests") == "3"
            and all(
                node.attrib.get(name, "0") == "0"
                for name in ("failures", "errors", "skipped", "disabled")
            ),
            "JUNIT_COUNT_MISMATCH",
        )
    outcomes = []
    for case in sorted(cases, key=lambda node: node.attrib["name"]):
        name = case.attrib["name"]
        require(
            case.attrib.get("classname") == SPEC["binary_id"], "JUNIT_BINARY_MISMATCH"
        )
        require(
            all(
                child.tag
                in {
                    "flakyFailure",
                    "flakyError",
                    "system-out",
                    "system-err",
                    "properties",
                }
                for child in case
            ),
            "JUNIT_FINAL_NOT_PASS",
        )
        require(
            re.search(r"^\s*test " + re.escape(name) + r" \.\.\. ok\s*$", text, re.M),
            "MISSING_EMITTED_CASE_PASS",
        )
        prior = [child for child in case if child.tag in {"flakyFailure", "flakyError"}]
        require(
            len(prior) <= SPEC["original_policy"]["retries"], "UNEXPECTED_ATTEMPT_COUNT"
        )
        outcomes.append(
            {
                "case": name,
                "final_status": "PASS",
                "attempt_count": 1 + len(prior),
                "passed_without_retry": not prior,
                "prior_failed_attempts": [
                    {
                        "attempt": ordinal + 1,
                        "kind": node.tag,
                        "attributes": dict(node.attrib),
                        "parsed_junit_element_sha256": identity(ET.tostring(node))[
                            "sha256"
                        ],
                    }
                    for ordinal, node in enumerate(prior)
                ],
            }
        )
    require(
        not any(
            list(report.iter(tag))
            for tag in ("failure", "error", "skipped", "rerunFailure", "rerunError")
        ),
        "JUNIT_FAILURE_OR_SKIP",
    )
    require(
        len(re.findall(r"test result: ok\. 1 passed; 0 failed; 0 ignored;", text)) == 3,
        "MISSING_EXACT_BINARY_SUMMARIES",
    )
    return {
        "final_passed_cases": 3,
        "ignored_cases": 0,
        "in_test_skip": False,
        "total_native_attempts": sum(item["attempt_count"] for item in outcomes),
        "cases_with_retries": [
            item["case"] for item in outcomes if not item["passed_without_retry"]
        ],
        "case_outcomes": outcomes,
        "original_retry_timeout_thread_policy_preserved": True,
    }
