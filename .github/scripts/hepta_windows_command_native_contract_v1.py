"""Exact Windows command-runner discovery, transcript and fresh XML data gates."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

BINARY = "codex-windows-sandbox::bin/codex-command-runner"
NAMES = (
    "win::child_exit::tests::initial_observation_error_does_not_start_another_wait",
    "win::child_exit::tests::native_observed_exit_preserves_23_and_259",
    "win::child_exit::tests::native_pending_wait_does_not_query_an_exit_code",
    "win::child_exit::tests::native_signaled_non_process_handle_cannot_supply_an_exit_code",
    "win::child_exit::tests::native_wait_failure_is_not_an_exit",
    "win::child_exit::tests::normal_exit_keeps_status_and_never_requests_termination",
    "win::child_exit::tests::termination_grace_observation_error_cannot_become_an_exit",
    "win::child_exit::tests::termination_grace_timeout_cannot_become_an_exit",
    "win::child_exit::tests::timeout_requires_native_exit_within_the_same_grace",
    "win::child_exit::tests::unexpected_wait_results_do_not_query_or_report_exit",
)
TARGET = "x86_64-pc-windows-msvc"
PARENT = "5b9b1c5e123aa69bd71c0fb810af8f6b8c9d4ed1"
PARENT_TREE = "a720083f7bd3d1df4222908bd5aa946c9eb43dce"
BRANCH = "fix/hepta-windows-command-exit-native10-20261126-7c9e"
BUDGET = {
    "whole_seconds": 1500,
    "source_seconds": 60,
    "tools_seconds": 90,
    "discovery_seconds": 1110,
    "native_seconds": 120,
    "evidence_seconds": 120,
}
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def require(value, message):
    if not value:
        raise ValueError(message)


def strict_json(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "duplicate-json-key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("nonfinite-json-number:" + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def listing(value, target):
    suites = value["rust-suites"]
    require(set(suites) == {BINARY}, "binary-roster")
    suite = suites[BINARY]
    require(
        suite["binary-id"] == BINARY
        and suite["binary-name"] == "codex-command-runner"
        and suite["package-name"] == "codex-windows-sandbox"
        and suite["kind"] == "bin"
        and suite["status"] == "listed"
        and suite["build-platform"] == "target",
        "binary-identity",
    )
    cases = suite["testcases"]
    selected = sorted(
        name
        for name, case in cases.items()
        if case["filter-match"]["status"] == "matches"
    )
    require(
        selected == list(NAMES)
        and all(cases[name]["ignored"] is False for name in selected),
        "selected-roster-or-ignored",
    )
    binary = Path(suite["binary-path"]).resolve(strict=True)
    require(
        binary.is_relative_to(target.resolve(strict=True))
        and binary.suffix.lower() == ".exe",
        "binary-output-ownership",
    )
    digest, size = hashlib.sha256(), 0
    with binary.open("rb") as stream:
        header = stream.read(64)
        pe = int.from_bytes(header[60:64], "little") if len(header) == 64 else 0
        require(header[:2] == b"MZ" and 64 <= pe <= 1024 * 1024, "native-x86-64-binary")
        stream.seek(pe)
        require(stream.read(6) == b"PE\0\0\x64\x86", "native-x86-64-binary")
        stream.seek(0)
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return {
        "binary": str(binary),
        "bytes": size,
        "sha256": digest.hexdigest(),
        "selected": selected,
        "unselected": len(cases) - len(selected),
    }


def transcript(raw, unselected):
    clean = ANSI.sub("", raw.decode("utf-8", "replace")).replace("\r\n", "\n")
    statuses = re.findall(
        r"^\s*(PASS|FAIL|TIMEOUT|EXECFAIL|LEAK|SKIP)\s+\[[^\]\n]+\]\s+"
        r"(?:\(\s*\d+/\d+\)\s+)?(\S+)\s+(\S+)\s*$",
        clean,
        re.MULTILINE,
    )
    starts = re.findall(r"Starting (\d+) tests? across", clean)
    summaries = re.findall(r"^\s*Summary\s+\[[^\]]+\]\s+(.*)$", clean, re.MULTILINE)
    wanted = Counter(("PASS", BINARY, name) for name in NAMES)
    require(
        Counter(statuses) == wanted and len(statuses) == 10,
        "terminal-roster-status-or-duplicate",
    )
    require(starts == ["10"] and len(summaries) == 1, "start-or-summary-count")
    match = re.fullmatch(
        r"10 tests run: 10 passed(?: \(([1-9][0-9]*) slow\))?(?:, (\d+) skipped)?",
        summaries[0],
    )
    require(
        match is not None
        and int(match.group(1) or 0) <= 10
        and int(match.group(2) or 0) == unselected,
        "summary-counts",
    )
    return {"passed": 10, "failed": 0, "selected_skips": 0, "unselected": unselected}


def exact_xml(raw, no_doctype_builder):
    root = ET.fromstring(raw, parser=ET.XMLParser(target=no_doctype_builder()))
    require(root.tag in ("testsuites", "testsuite"), "xml-root")
    cases = list(root.iter("testcase"))
    observed = Counter((case.get("classname"), case.get("name")) for case in cases)
    require(
        observed == Counter((BINARY, name) for name in NAMES) and len(cases) == 10,
        "xml-roster-or-duplicate",
    )
    require(
        all(
            not list(case.findall(tag))
            for case in cases
            for tag in (
                "skipped",
                "failure",
                "error",
                "rerunFailure",
                "flakyFailure",
                "rerunError",
                "flakyError",
            )
        ),
        "xml-nonpass-or-retry",
    )
    return {"total": 10, "passed": 10, "skipped": 0, "native_qualification_only": True}
