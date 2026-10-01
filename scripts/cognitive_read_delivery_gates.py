"""Exact nextest gates for cognitive delivery; no source mutation or activation."""

from __future__ import annotations

import json
from pathlib import Path
import re

from cognitive_read_evidence import nextest_log_problems

GUIDE = "docs/modules/cognitive.read/DELIVERY_EVIDENCE.md"
SOURCE_PATHS = (
    "docs/modules/cognitive.read/PREPARATION_HANDOFF.md",
    "codex-rs/hepta-agentd/src/cognitive_owner_preparation_delivery_tests.rs",
    "codex-rs/hepta-infer-core/src/cognitive_preparation_tests.rs",
    "codex-rs/hepta-agent-protocol/src/cognitive_preparation_tests.rs",
    "codex-rs/hepta-agent-protocol/src/cognitive_preparation.rs",
    "codex-rs/hepta-infer-core/src/cognitive_delivery.rs",
    "codex-rs/hepta-infer-core/src/cognitive_delivery_tests.rs",
    "codex-rs/hepta-infer-core/src/lib.rs",
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "codex-rs/hepta-infer-core/src/native_control_tests.rs",
    "codex-rs/hepta-learning-ledger/src/production.rs",
    "codex-rs/hepta-learning-ledger/src/retrieval_preparation.rs",
    "codex-rs/hepta-learning-ledger/src/retrieval_preparation_tests.rs",
    "codex-rs/hepta-agentd/src/client.rs",
    "codex-rs/hepta-agentd/src/lib.rs",
    "codex-rs/hepta-agentd/src/cognitive_retrieval_learning.rs",
    "codex-rs/hepta-agentd/src/cognitive_retrieval_delivery_tests.rs",
    "codex-rs/hepta-agentd/src/cognitive_context_hnmf_tests.rs",
    "codex-rs/hepta-agentd/tests/cognitive_delivery_join.rs",
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "codex-rs/hepta-infer-worker-host/src/native_run_control.rs",
    "codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs",
    "scripts/apply-cognitive-read-durable-handoff.py",
    "scripts/prepare-cognitive-read-durable-handoff.py",
    "scripts/cognitive_read_delivery_gates.py",
    "scripts/test_cognitive_read_delivery_gates.py",
    "scripts/cognitive_read_full_evidence.py",
    "scripts/prepare-cognitive-read-source.py",
)

# label -> (package, Cargo target selector, nextest binary identity, exact cases)
DELIVERY_GATES = {
    "native-delivery-tests": (
        "codex-hepta-infer-core",
        ("--lib",),
        "codex-hepta-infer-core",
        tuple(
            "cognitive_delivery::tests::" + name
            for name in (
                "dispatch_and_reopen_do_not_prove_cognitive_delivery",
                "exact_owner_generation_request_and_context_are_required",
                "only_durable_pre_effect_proof_establishes_not_sent",
                "cancellation_does_not_erase_observed_acceptance",
                "terminal_delivery_and_authorized_success_are_not_conflated",
                "substituted_source_admission_cannot_join_a_preparation",
                "observed_server_rejection_does_not_claim_the_payload_was_not_sent",
            )
        ),
    ),
    "delivery-preparation-tests": (
        "codex-hepta-learning-ledger",
        ("--lib",),
        "codex-hepta-learning-ledger",
        tuple(
            "production::retrieval_preparation::tests::" + name
            for name in (
                "preparation_read_is_indexed_bound_and_non_mutating",
                "witness_lag_and_revocation_never_become_delivery_preparation",
                "preparation_identity_advances_with_the_durable_owner_after_reopen",
                "owner_preparation_receipt_requires_exact_namespace_witness_and_activity",
            )
        ),
    ),
    "publication-fence-tests": (
        "codex-hepta-agentd",
        ("--lib",),
        "codex-hepta-agentd",
        (
            "cognitive_context::tests::hnmf::publication_rechecks_owner_after_last_awaited_dependency",
            "cognitive_retrieval_learning::tests::ordinary_socket_reads_from_new_clients_do_not_reuse_assignment_identity",
        ),
    ),
    "delivery-join-tests": (
        "codex-hepta-agentd",
        ("--test", "cognitive_delivery_join"),
        "codex-hepta-agentd::cognitive_delivery_join",
        (
            "tests::real_learning_and_native_owners_join_exact_preparation_and_acceptance",
            "tests::owner_preparation_tests::ordinary_preparation_receipt_joins_exact_native_dispatch_after_reopen",
        ),
    ),
    "preparation-protocol-tests": (
        "codex-hepta-agent-protocol",
        ("--lib",),
        "codex-hepta-agent-protocol",
        (
            "cognitive_preparation::tests::preparation_response_preserves_snapshot_bytes_and_separates_receipt",
        ),
    ),
    "native-preparation-handoff-tests": (
        "codex-hepta-infer-core",
        ("--lib",),
        "codex-hepta-infer-core",
        tuple(
            "cognitive_delivery::tests::preparation_tests::" + name
            for name in (
                "persisted_preparation_reopens_without_upgrading_unknown_delivery",
                "invalid_preparation_cannot_enter_the_native_journal",
                "historical_omission_preserves_canonical_event_and_journal_bytes",
                "receipt_substitution_changes_the_native_delivery_binding",
            )
        ),
    ),
}


def delivery_commands() -> dict[str, list[str]]:
    return {
        label: [
            "just",
            "test",
            "--locked",
            "-p",
            package,
            *target,
            "--no-tests=fail",
            "--status-level",
            "pass",
            "-E",
            " | ".join(f"test(={case})" for case in cases),
        ]
        for label, (package, target, _binary, cases) in DELIVERY_GATES.items()
    }


def delivery_log_problems(label: str, text: str) -> list[str]:
    """Require the named binary's actual PASS rows and exact execution count."""
    _package, _target, binary, cases = DELIVERY_GATES[label]
    body = re.sub(r"\x1b\[[0-9;]*m", "", text)
    binary_pattern = re.escape(binary).replace(r"\-", "[-_]")
    problems = nextest_log_problems(label, body, len(cases))
    for case in cases:
        row = (
            rf"(?m)^\s*PASS\s+\[[^]\r\n]+\]\s+{binary_pattern}\s+{re.escape(case)}\s*$"
        )
        if len(re.findall(row, body)) != 1:
            problems.append(f"{label}: exact binary/case not proved: {case}")
    return problems


def delivery_gate_passed(evidence: Path, label: str) -> bool:
    """One gate's status; not an exact-candidate, merge, or release receipt."""
    command = evidence / f"{label}.command.json"
    log = evidence / f"{label}.log"
    code = evidence / f"{label}.exit-code"
    try:
        if any(
            path.is_symlink() or not path.is_file() for path in (command, log, code)
        ):
            return False
        return (
            json.loads(command.read_text()) == delivery_commands()[label]
            and code.read_text().strip() == "0"
            and not delivery_log_problems(label, log.read_text(errors="replace"))
        )
    except (OSError, ValueError):
        return False
