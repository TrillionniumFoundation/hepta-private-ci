"""Exact original learning-owner subsets in one complete native report."""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import stat
import re
import xml.etree.ElementTree as ET

from hepta_ci_junit import NoDoctypeTreeBuilder

PACKAGE = "codex-hepta-agentd"
PREFIX = "circuit_next_use_receipt_owner::tests::"
INGRESS = "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::"
NEXT_USE_CASES = (
    PREFIX
    + "original_observer_configuration_rejects_substituted_custody_before_journal_creation",
    PREFIX
    + "original_observer_predecessors_require_bound_signed_roles_and_independent_custody",
    PREFIX + "original_observer_deadline_and_saved_signature_window_never_renew",
    PREFIX + "original_observer_pending_claim_reopens_without_signing_or_rewriting",
    INGRESS
    + "q24_ordinary_original_observer_attests_and_recovers_exact_completed_next_use",
    INGRESS
    + "q24_ordinary_original_observer_refuses_uncommitted_or_withdrawn_next_use",
)
MATERIAL_PREFIX = "cell_q24_material_receipt_owner::tests::"
MATERIAL_CASES = tuple(
    MATERIAL_PREFIX + name
    for name in (
        "original_material_pair_signs_recovers_and_feeds_actual_no_update_training",
        "original_material_pair_rejects_changed_custody_prefix_and_valid_freeze_resigning",
        "original_material_pair_withdrawal_refuses_cached_material_without_dataset_claim",
        "original_material_pair_pending_claim_reopens_without_signing_or_replacing_bytes",
        "original_material_pair_expired_work_only_reads_original_completed_windows",
        "original_material_pair_partial_creation_never_finishes_missing_dataset_during_recovery",
    )
)
SELECTION_PREFIX = (
    "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::"
    "observer_support::selection_owner::"
)
SELECTION_CASES = tuple(
    SELECTION_PREFIX + name
    for name in (
        "q24_original_selector_attests_actual_publication_and_recovers_exact_signature",
        "q24_original_selector_refuses_withdrawn_publication_before_claim",
        "q24_original_selector_refuses_valid_training_renewal_live_and_cold",
        "q24_original_selector_preserves_pending_and_recovers_completed_lost_ack",
        "q24_original_selector_rejects_substituted_custody_before_store_creation",
        "q24_original_selector_rejects_another_real_completion_with_same_run_and_manifest",
    )
)
TRAINING_LANE_PREFIX = (
    "neuron_generation_update_bootstrap::adopted_learning::composed_tests::"
    "training::owner::model_proposal::training_lane::"
)
TRAINING_LANE_CASES = tuple(
    TRAINING_LANE_PREFIX + name
    for name in (
        "original_training_model_lane_retains_custody_and_exact_generator_evidence",
        "original_training_model_lane_preserves_pending_and_lost_ack",
        "original_training_model_lane_fences_physical_mutation_after_bytes_restore",
    )
)
SOURCE_PREFIX = "cell_q24_material_receipt_owner::tests::support::training_source::"
SOURCE_CASES = tuple(
    SOURCE_PREFIX + name
    for name in (
        "source_bound_training_preserves_frozen_rule_and_recovers_exact_no_update",
        "source_bound_training_rejects_identical_legacy_batch_before_admission",
        "source_bound_training_withdrawal_before_claim_fences_without_no_update",
        "source_bound_training_withdrawal_after_claim_preserves_pending_without_signature",
        "source_bound_capture_rejects_valid_freeze_resigning_with_identical_training_bytes",
        "source_bound_training_cold_identity_rejects_valid_material_signature_renewal",
    )
)
MATERIAL_SERVICE_PREFIX = "learning_iteration_evidence_client::material::tests::"
MATERIAL_SERVICE_CASES = tuple(
    MATERIAL_SERVICE_PREFIX + "material_readback_service_" + name
    for name in (
        "returns_original_signatures_and_cold_rereads",
        "refuses_request_rebinding_and_replay_without_writes",
        "refuses_withdrawn_source_and_busy_ledger",
        "never_finishes_missing_dataset",
        "rejects_same_uid_peer_and_widened_transport",
        "failed_frame_permanently_consumes_channel",
    )
)
REMOTE_MATERIAL_PREFIX = "learning_iteration_evidence_client::material::source::tests::"
REMOTE_MATERIAL_CASES = tuple(
    REMOTE_MATERIAL_PREFIX + name
    for name in (
        "material_source_peer_reconstructs_exact_sealed_material_and_cold_rereads",
        "material_source_peer_rejects_raw_batch_provenance_and_frozen_optimizer_rebinding",
        "material_source_peer_pins_complete_material_and_freeze_signatures",
        "material_source_service_refuses_withdrawn_missing_or_busy_originals",
        "material_source_service_refuses_request_payload_rebinding_and_public_custody_bypass",
        "material_source_peer_consumes_wrong_purpose_or_failed_frames",
    )
)
TRANSPORT_CASES = (
    "learning_iteration_evidence_client::tests::"
    "original_receipt_fixture_retains_peer_during_owner_work_between_frames",
)
EXECUTION_PACKAGE = "codex-hepta-intelligence-eval"
EXECUTION_PREFIX = "product_runner::tests::execution_tests::original_evidence::"
EXECUTION_CASES = tuple(
    EXECUTION_PREFIX + name
    for name in (
        "original_execution_evidence_survives_recovery_without_work_or_renewal",
        "original_execution_evidence_rechecks_expiry_after_owner_reads",
        "equal_execution_with_validly_renewed_signature_has_different_original_evidence",
        "original_execution_evidence_missing_and_pending_never_claim",
    )
)
OWNER_GROUPS = (
    ("next_use_observer", PACKAGE, NEXT_USE_CASES),
    ("material_observers", PACKAGE, MATERIAL_CASES),
    ("original_selector", PACKAGE, SELECTION_CASES),
    ("training_model_lane", PACKAGE, TRAINING_LANE_CASES),
    ("original_training_source", PACKAGE, SOURCE_CASES),
    ("original_material_service", PACKAGE, MATERIAL_SERVICE_CASES),
    ("original_remote_material_source", PACKAGE, REMOTE_MATERIAL_CASES),
    ("original_peer_lifetime", PACKAGE, TRANSPORT_CASES),
    ("original_execution_evidence", EXECUTION_PACKAGE, EXECUTION_CASES),
)
EXPECTED_CASES = tuple(
    (package, name) for _, package, names in OWNER_GROUPS for name in names
)
CASES = tuple(name for _, name in EXPECTED_CASES)

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TERMINAL = re.compile(
    r"^\s*(PASS|FAIL|TIMEOUT|EXECFAIL|LEAK|SKIP)\s+\[[^\]\n]+\]\s+"
    r"(?:\(\s*\d+/\d+\)\s+)?(\S+)\s+(\S+)\s*$",
    re.MULTILINE,
)


def assess_original_observer_coverage(log: str, xml: bytes) -> dict:
    if len(xml) > 64 * 1024 * 1024:
        raise ValueError("Observer JUnit exceeds its byte bound")
    if len(set(EXPECTED_CASES)) != len(EXPECTED_CASES) or len(set(CASES)) != len(CASES):
        raise ValueError("duplicate Observer inventory")
    expected = Counter(EXPECTED_CASES)
    document = ET.fromstring(xml, parser=ET.XMLParser(target=NoDoctypeTreeBuilder()))
    if document.tag not in ("testsuite", "testsuites"):
        raise ValueError("unexpected native JUnit root")
    suites = (
        [document] if document.tag == "testsuite" else document.findall("testsuite")
    )
    selected = [
        (suite, case)
        for suite in suites
        for case in suite.findall("testcase")
        if case.get("name") in CASES
    ]
    all_named = [
        case for case in document.iter("testcase") if case.get("name") in CASES
    ]
    observed = Counter(
        (case.get("classname"), case.get("name")) for _, case in selected
    )
    xml_ok = (
        len(selected) == len(all_named) == len(CASES)
        and observed == expected
        and all(
            suite.get("name") == case.get("classname")
            and not any(
                node.tag
                in (
                    "failure",
                    "error",
                    "skipped",
                    "flakyFailure",
                    "flakyError",
                    "rerunFailure",
                    "rerunError",
                )
                for node in case.iter()
            )
            for suite, case in selected
        )
    )
    clean_log = ANSI.sub("", log)
    summary = re.search(r"^\s*Summary\s+\[[^\]\n]+\]\s+", clean_log, re.MULTILINE)
    # Pinned nextest prints final-output status headers again after Summary.
    # Keep the whole log, but count only its original execution-status phase.
    rows = TERMINAL.findall(clean_log[: summary.start()]) if summary is not None else []
    named = [row for row in rows if row[2] in CASES]
    log_ok = Counter((package, name) for _, package, name in named) == expected and all(
        status == "PASS" for status, _, _ in named
    )
    return {
        "expected_count": len(CASES),
        "required_owner_groups": {name: len(cases) for name, _, cases in OWNER_GROUPS},
        "required_group_packages": {name: package for name, package, _ in OWNER_GROUPS},
        "expected": sorted(expected),
        "junit_observed": sorted(observed.elements(), key=repr),
        "terminal_rows": named,
        "terminal_phase": "before_first_nextest_summary",
        "exact_pass_coverage": xml_ok and log_ok,
    }


def assess_retained_original_observer_coverage(
    execution_path: Path, junit_path: Path
) -> dict:
    """Read the recorder's original bounded log, never a guessed log name."""
    encoded_record = execution_path.read_bytes()
    record = json.loads(encoded_record)
    if (
        record.get("status") != "passed"
        or any(
            type(record.get(field)) is not int or record[field] != 0
            for field in ("returncode", "command_exit_code", "exit_code")
        )
        or record.get("timed_out") is not False
        or record.get("output_limit_exceeded") is not False
    ):
        raise ValueError("Observer coverage requires a successful retained execution")
    name = record.get("log_file")
    if (
        not isinstance(name, str)
        or re.fullmatch(re.escape(execution_path.name) + r"\.[0-9a-f]{32}\.log", name)
        is None
    ):
        raise ValueError("retained execution log must be its exact relative basename")
    expected_size = record.get("log_bytes")
    expected_digest = record.get("log_sha256")
    if (
        type(expected_size) is not int
        or not 0 <= expected_size <= 64 * 1024 * 1024
        or not isinstance(expected_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None
    ):
        raise ValueError("retained execution lacks bounded original log identity")
    path = execution_path.parent / name

    def identity(value):
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("retained execution log is not an original regular file")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(expected_size + 1)
        after = os.fstat(stream.fileno())
    current = path.lstat()
    if (
        identity(before) != identity(opened)
        or identity(opened) != identity(after)
        or identity(after) != identity(current)
        or len(raw) != expected_size
        or hashlib.sha256(raw).hexdigest() != expected_digest
    ):
        raise ValueError("retained original log bytes or identity changed")
    with junit_path.open("rb") as stream:
        xml = stream.read(64 * 1024 * 1024 + 1)
    if execution_path.read_bytes() != encoded_record:
        raise ValueError("retained execution record changed during coverage read")
    result = assess_original_observer_coverage(
        raw.decode("utf-8", errors="replace"), xml
    )
    return {
        "execution_record_sha256": hashlib.sha256(encoded_record).hexdigest(),
        "log_file": name,
        "log_bytes": len(raw),
        "log_sha256": expected_digest,
        **result,
    }
