"""Exact Observer subset coverage within a complete native nextest report."""

from collections import Counter
import re
import xml.etree.ElementTree as ET

from hepta_ci_junit import NoDoctypeTreeBuilder

PACKAGE = "codex-hepta-agentd"
PREFIX = "circuit_next_use_receipt_owner::tests::"
INGRESS = "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::"
CASES = (
    PREFIX + "original_observer_configuration_rejects_substituted_custody_before_journal_creation",
    PREFIX + "original_observer_predecessors_require_bound_signed_roles_and_independent_custody",
    PREFIX + "original_observer_deadline_and_saved_signature_window_never_renew",
    PREFIX + "original_observer_pending_claim_reopens_without_signing_or_rewriting",
    INGRESS + "q24_ordinary_original_observer_attests_and_recovers_exact_completed_next_use",
    INGRESS + "q24_ordinary_original_observer_refuses_uncommitted_or_withdrawn_next_use",
)
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TERMINAL = re.compile(
    r"^\s*(PASS|FAIL|TIMEOUT|EXECFAIL|LEAK|SKIP)\s+\[[^\]\n]+\]\s+"
    r"(?:\(\s*\d+/\d+\)\s+)?(\S+)\s+(\S+)\s*$",
    re.MULTILINE,
)


def assess_original_observer_coverage(log: str, xml: bytes) -> dict:
    if len(xml) > 64 * 1024 * 1024:
        raise ValueError("Observer JUnit exceeds its byte bound")
    if len(set(CASES)) != len(CASES):
        raise ValueError("duplicate Observer inventory")
    expected = Counter((PACKAGE, name) for name in CASES)
    document = ET.fromstring(xml, parser=ET.XMLParser(target=NoDoctypeTreeBuilder()))
    if document.tag not in ("testsuite", "testsuites"):
        raise ValueError("unexpected native JUnit root")
    suites = [document] if document.tag == "testsuite" else document.findall("testsuite")
    selected = [
        (suite, case)
        for suite in suites
        for case in suite.findall("testcase")
        if case.get("name") in CASES
    ]
    all_named = [case for case in document.iter("testcase") if case.get("name") in CASES]
    observed = Counter((case.get("classname"), case.get("name")) for _, case in selected)
    xml_ok = (
        len(selected) == len(all_named) == len(CASES)
        and observed == expected
        and all(
            suite.get("name") == case.get("classname")
            and not any(node.tag in ("failure", "error", "skipped") for node in case.iter())
            for suite, case in selected
        )
    )
    clean_log = ANSI.sub("", log)
    summary = re.search(r"^\s*Summary\s+\[[^\]\n]+\]\s+", clean_log, re.MULTILINE)
    # Pinned nextest prints final-output status headers again after Summary.
    # Keep the whole log, but count only its original execution-status phase.
    rows = TERMINAL.findall(clean_log[:summary.start()]) if summary is not None else []
    named = [row for row in rows if row[2] in CASES]
    log_ok = (
        Counter((package, name) for _, package, name in named) == expected
        and all(status == "PASS" for status, _, _ in named)
    )
    return {
        "expected_count": len(CASES),
        "expected": sorted(expected),
        "junit_observed": sorted(observed.elements(), key=repr),
        "terminal_rows": named,
        "terminal_phase": "before_first_nextest_summary",
        "exact_pass_coverage": xml_ok and log_ok,
    }
