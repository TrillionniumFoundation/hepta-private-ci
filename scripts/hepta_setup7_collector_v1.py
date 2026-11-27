#!/usr/bin/env python3
"""Strict data collector for the seven newly added setup binary controls."""

import collections
import hashlib
import json
import math
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

PACKAGE = "codex-windows-sandbox"
TARGET = "codex-windows-sandbox-setup"
BINARY_ID = PACKAGE + "::bin/" + TARGET
TESTS = (
    "win::setup_completion::tests::full_setup_commits_only_after_success",
    "win::setup_completion::tests::refresh_success_does_not_rewrite_existing_marker",
    "win::setup_completion::tests::full_setup_acl_failures_keep_marker_unready",
    "win::setup_completion::tests::refresh_acl_failures_do_not_commit_marker",
    "win::setup_completion::tests::collected_acl_errors_survive_later_setup_failure",
    "win::setup_completion::tests::collected_acl_errors_survive_failed_error_log",
    "win::setup_completion::tests::setup_failure_without_collected_acl_errors_is_preserved",
)
MARKER_CASES = (1, 1, 3, 3, 2, 2, 2)
FILTER = (
    "package(="
    + PACKAGE
    + ") & binary(="
    + TARGET
    + ") & ("
    + " | ".join("test(=" + name + ")" for name in TESTS)
    + ")"
)


class CollectionFailure(ValueError):
    pass


def need(value, message):
    if not value:
        raise CollectionFailure(message)


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def parse_json(raw):
    need(isinstance(raw, bytes), "collector requires retained original bytes")
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=no_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(
            CollectionFailure("nonfinite JSON value: " + value)
        ),
    )


def same_path(left, right):
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(
        os.path.abspath(right)
    )


def beneath(child, root):
    left, right = (
        os.path.normcase(os.path.abspath(child)),
        os.path.normcase(os.path.abspath(root)),
    )
    return os.path.commonpath((left, right)) == right and left != right


def metadata(raw, workspace, fresh_target):
    value = parse_json(raw)
    need(value.get("version") == 1, "cargo metadata version")
    need(same_path(value.get("workspace_root", ""), workspace), "metadata workspace")
    need(
        same_path(value.get("target_directory", ""), fresh_target),
        "fresh native target",
    )
    packages = value.get("packages")
    need(isinstance(packages, list) and packages, "complete workspace package list")
    ids = [item["id"] for item in packages]
    need(len(ids) == len(set(ids)), "duplicate Cargo package identity")
    selected = [item for item in packages if item.get("name") == PACKAGE]
    need(len(selected) == 1, "exact setup owning package")
    package = selected[0]
    need(
        package["id"] in value.get("workspace_members", []),
        "setup package is not a workspace member",
    )
    need(
        same_path(
            package.get("manifest_path", ""),
            Path(workspace) / "windows-sandbox-rs/Cargo.toml",
        ),
        "setup package manifest identity",
    )
    targets = [target for target in package["targets"] if target.get("name") == TARGET]
    need(len(targets) == 1, "exact setup target declaration")
    target = targets[0]
    need(
        target.get("kind") == ["bin"] and target.get("test") is True,
        "setup binary test harness must be enabled",
    )
    need(
        same_path(
            target.get("src_path", ""),
            Path(workspace) / "windows-sandbox-rs/src/bin/setup_main/main.rs",
        ),
        "setup binary entry path",
    )
    return value, package


def binaries(raw, package, fresh_target):
    value = parse_json(raw)
    need(
        set(value.get("rust-binaries", {})) == {BINARY_ID},
        "cold build returned extra or missing test binaries",
    )
    binary = value["rust-binaries"][BINARY_ID]
    need(
        binary.get("binary-id") == BINARY_ID and binary.get("binary-name") == TARGET,
        "cold binary identity",
    )
    need(
        binary.get("package-id") == package["id"] and binary.get("kind") == "bin",
        "cold binary owner/kind",
    )
    need(binary.get("build-platform") == "target", "native target binary required")
    need(
        beneath(binary.get("binary-path", ""), fresh_target),
        "binary escaped fresh cold target",
    )
    need(
        Path(binary["binary-path"]).suffix.lower() == ".exe",
        "native Windows executable required",
    )
    need(
        same_path(
            value.get("rust-build-meta", {}).get("target-directory", ""), fresh_target
        ),
        "build metadata target identity",
    )
    return value, binary


def listed(raw, binary_list, package, workspace):
    value = parse_json(raw)
    need(
        value.get("rust-build-meta") == binary_list["rust-build-meta"],
        "list did not reuse original cold build metadata",
    )
    suites = value.get("rust-suites", {})
    need(set(suites) == {BINARY_ID}, "list included another test binary")
    suite = suites[BINARY_ID]
    for key, expected in binary_list["rust-binaries"][BINARY_ID].items():
        need(suite.get(key) == expected, "list binary metadata drift: " + key)
    need(
        suite.get("package-name") == PACKAGE and suite.get("status") == "listed",
        "setup binary was not actually listed",
    )
    need(
        same_path(suite.get("cwd", ""), Path(workspace) / "windows-sandbox-rs"),
        "test working directory",
    )
    cases = suite.get("testcases")
    need(isinstance(cases, dict) and cases, "no actual native listed cases")
    need(value.get("test-count") == len(cases), "test-list total count")
    matched = []
    for name, item in cases.items():
        match = item.get("filter-match")
        need(isinstance(match, dict), "missing explicit native filter result")
        if match.get("status") == "matches":
            need(item.get("ignored") is False, "ignored test cannot satisfy new scope")
            matched.append(name)
        else:
            need(match.get("status") == "mismatch", "unknown test filter result")
    need(
        sorted(matched) == sorted(TESTS),
        "native match set must be the exact seven original names",
    )
    return {
        "binary_id": BINARY_ID,
        "listed_total": len(cases),
        "matched": sorted(matched),
        "unselected": sorted(set(cases) - set(matched)),
        "matched_count": 7,
        "marker_cases_in_source": sum(MARKER_CASES),
        "ignored_selected": 0,
        "first_list_success": True,
    }


def command_terminal(row):
    need(
        row.get("launch_attempts") == 1 and row.get("created") is True,
        "command original launch missing",
    )
    need(
        row.get("successful") is True and row.get("native_complete") is True,
        "command has no full native terminal success",
    )
    need(
        row.get("root_handle_exit_code") == 0
        and row.get("root_handle_signaled") is True,
        "root original native terminal missing",
    )
    need(
        not row.get("errors") and row.get("error_overflow_count") == 0,
        "owned command retained an error",
    )
    need(
        row.get("termination_attempts") == 0 and row.get("cancellation_count") == 0,
        "terminated/cancelled attempt is not a pass",
    )
    members = row.get("members", [])
    need(
        members
        and len({(m["pid"], m["creation_filetime"]) for m in members}) == len(members),
        "native process identity set",
    )
    need(
        all(
            m.get("in_original_job") is True
            and m.get("terminal") is True
            and m.get("exit_continued") is True
            and m.get("closed") is True
            and m.get("actual_exit_code") == m.get("exit_event_code")
            for m in members
        ),
        "a descendant lacks original-handle actual terminal",
    )
    need(
        row.get("accounting_before_handle_release", {}).get("total_processes")
        == len(members),
        "lifetime Job count does not cover every retained process",
    )
    need(
        row.get("accounting_after_handle_release", {}).get("active_processes") == 0,
        "native references remain after terminal-handle release",
    )
    for label in ("stdout", "stderr"):
        stream = row.get(label, {})
        need(
            stream.get("eof") is True and stream.get("truncated") is False,
            "actual complete output EOF is required: " + label,
        )
        need(
            stream.get("observed_bytes") == stream.get("retained_bytes"),
            "output byte truncation",
        )
    need(
        row.get("completed_monotonic", math.inf)
        <= row.get("operation_deadline", -math.inf),
        "command over its original operation budget",
    )


def execution_logs(stdout, stderr, row):
    command_terminal(row)
    for label, raw in (("stdout", stdout), ("stderr", stderr)):
        need(
            len(raw) == row[label]["retained_bytes"]
            and hashlib.sha256(raw).hexdigest() == row[label]["sha256"],
            "retained command stream mismatch: " + label,
        )
    text = (stdout + b"\n" + stderr).decode("utf-8")
    need("\x1b" not in text, "color/control escape in exact native log")
    starts = re.findall(r"\bStarting (\d+) tests? across (\d+) binar(?:y|ies)", text)
    need(starts == [("7", "1")], "exact single Starting 7 / 1 binary evidence")
    terminal = re.findall(
        r"^\s*(PASS|FAIL|TIMEOUT|EXECFAIL|LEAK|SKIP)\s+\[[^\]\n]+\]\s+"
        r"(?:\(\s*\d+/\d+\)\s+)?(\S+)\s+(\S+)\s*$",
        text,
        re.MULTILINE,
    )
    need(len(terminal) == 7, "terminal evidence is not exactly seven lines")
    need(
        all(status == "PASS" and binary == BINARY_ID for status, binary, _ in terminal),
        "failed, skipped or foreign binary terminal",
    )
    need(
        collections.Counter(name for _, _, name in terminal)
        == collections.Counter(TESTS),
        "duplicate/missing/extra test terminal names",
    )
    summaries = re.findall(
        r"\bSummary\s+\[[^\]\n]+\]\s+(\d+) tests? run:\s+(\d+) passed([^\n]*)",
        text,
    )
    need(
        len(summaries) == 1 and summaries[0][:2] == ("7", "7"),
        "original terminal summary is not seven passed",
    )
    need(
        not re.search(
            r"\b(?:flaky|retried|retries|failed|timed out|leaked)\b",
            summaries[0][2],
            re.I,
        ),
        "retry/failure in terminal summary",
    )
    return {"starting": starts, "terminal": terminal, "summary": summaries[0]}


def junit(raw):
    need(len(raw) <= 2 * 1024 * 1024, "JUnit observation bound")
    need(
        b"<!DOCTYPE" not in raw.upper() and b"<!ENTITY" not in raw.upper(),
        "DTD/entity refused",
    )
    root = ET.fromstring(raw)
    need(root.tag == "testsuites", "expected original nextest testsuites document")
    suites = list(root.findall("testsuite"))
    need(len(suites) == 1, "JUnit must contain exactly one native binary suite")
    suite = suites[0]
    need(suite.get("name") == BINARY_ID, "JUnit binary identity")
    for element in (root, suite):
        need(element.get("tests") == "7", "JUnit total must be seven")
        for attribute in ("failures", "errors"):
            need(element.get(attribute) == "0", "JUnit failure/error count")
        need(element.get("skipped", "0") == "0", "JUnit skipped selected test")
        need(element.get("disabled", "0") == "0", "JUnit disabled selected test")
    cases = suite.findall("testcase")
    need(len(cases) == 7, "JUnit case count")
    names = [case.get("name") for case in cases]
    need(collections.Counter(names) == collections.Counter(TESTS), "JUnit exact names")
    for case in cases:
        need(case.get("classname") == BINARY_ID, "JUnit case binary identity")
        need(
            not any(
                child.tag
                in (
                    "failure",
                    "error",
                    "skipped",
                    "rerunFailure",
                    "rerunError",
                    "flakyFailure",
                    "flakyError",
                )
                for child in case
            ),
            "JUnit cannot conceal retries or non-success",
        )
        duration = float(case.get("time", "nan"))
        need(math.isfinite(duration) and duration >= 0, "JUnit duration")
    return {
        "binary_id": BINARY_ID,
        "names": sorted(names),
        "passed": 7,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "retries": 0,
    }
