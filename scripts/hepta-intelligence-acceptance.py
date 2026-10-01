#!/usr/bin/env python3
"""Validate the five intelligence.control A-D acceptance objectives.

The tracked implementation/test documents remain the canonical source/test
inventory. This verifier groups those reviewed declarations into the five
ordered acceptance objectives requested for product closure and admits a
"passed" receipt only from the exact command records already verified by the
module status projector. It never upgrades source/package evidence into
real-provider, target-host, independent-acceptance, activation or release facts.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = Path(__file__).with_name("hepta-intelligence-control-status.py")
SPEC = importlib.util.spec_from_file_location("intelligence_status", STATUS_PATH)
assert SPEC is not None and SPEC.loader is not None
STATUS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATUS)

SCHEMA = "hepta.intelligence-control-a-d-acceptance.v1"

OBJECTIVES: tuple[dict[str, Any], ...] = (
    {
        "id": "A1-cross-stage-semantic-closure",
        "stage": "A",
        "sourceBindings": [
            {
                "path": "codex-rs/hepta-agentd/src/intelligence_product_ports.rs",
                "symbols": [
                    "actual_stage_outputs_fill_templates_but_reject_substitution",
                    "utility_universe_rejects_foreign_and_missing_candidates",
                ],
            },
            {
                "path": "codex-rs/hepta-agentd/src/intelligence_prompt_binding.rs",
                "symbols": ["PreparedPromptDeliveryV1", "validate_prompt_delivery_v1"],
            },
        ],
        "mappedRequirements": [
            "canonical_candidates_and_outcomes",
            "actual_owner_outputs",
        ],
        "mappedTests": [
            "final_gate_rehashes_every_envelope_dependency",
            "actual_stage_outputs_fill_templates_but_reject_substitution",
            "utility_universe_rejects_foreign_and_missing_candidates",
            "prompt_conditioned_state_rejects_either_stage_substitution",
        ],
        "directTests": [],
        "commandRecords": [
            "intelligence-tests.json",
            "agentd-default-tests.json",
        ],
    },
    {
        "id": "A2-current-time-recovery-closure",
        "stage": "A",
        "sourceBindings": [
            {
                "path": "codex-rs/hepta-agentd/src/intelligence_learning_clock.rs",
                "symbols": ["verification_time", "CLOCK_BEHIND_EVENT"],
            },
            {
                "path": "codex-rs/hepta-agentd/src/intelligence_learning_payload.rs",
                "symbols": [
                    "clock::verification_time(payload.now)",
                    "writer.append_decision",
                    "writer.append_outcome",
                ],
            },
        ],
        "mappedRequirements": [
            "current_learning_time",
            "exact_learning_identity",
        ],
        "mappedTests": [
            "replay_verification_uses_current_time_not_frozen_event_time",
            "learning_clock_rollback_is_not_normalized_into_old_time",
            "v2_payload_round_trip_preserves_event_time_predecessor_and_authentication",
        ],
        "directTests": [],
        "commandRecords": [
            "agentd-default-tests.json",
            "ledger-tests.json",
        ],
    },
    {
        "id": "B-single-product-execution-closure",
        "stage": "B",
        "sourceBindings": [
            {
                "path": "codex-rs/hepta-agentd/src/objective_runtime.rs",
                "symbols": [
                    "start_canonical_intelligence",
                    "complete_canonical_intelligence",
                ],
            },
            {
                "path": "codex-rs/hepta-infer-worker-host/src/native_intelligence_product.rs",
                "symbols": [
                    "record_decision_before_dispatch_v1",
                    "run_intelligence",
                    "record_outcome_after_terminal_v1",
                ],
            },
            {
                "path": "codex-rs/hepta-infer-worker-host/src/native_intelligence_embedding.rs",
                "symbols": ["NativeIntelligenceProductEmbeddingV1"],
            },
        ],
        "mappedRequirements": [
            "generation_fence",
            "exact_learning_identity",
        ],
        "mappedTests": [
            "running_generation_differs_from_spawn_and_is_admitted",
            "exact_destination_recovery_requires_event_predecessor_and_witness",
        ],
        "directTests": [
            {
                "name": "lost_turn_start_ack_reconciles_only_the_exact_in_progress_thread",
                "path": "codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs",
                "package": "codex-hepta-infer-worker-host",
            },
            {
                "name": "only_the_bound_turn_can_complete_the_native_request",
                "path": "codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs",
                "package": "codex-hepta-infer-worker-host",
            },
            {
                "name": "success_requires_both_matching_completion_and_final_ready_owner",
                "path": "codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs",
                "package": "codex-hepta-infer-worker-host",
            },
        ],
        "commandRecords": [
            "native-tests.json",
            "agentd-default-tests.json",
            "ledger-tests.json",
        ],
    },
    {
        "id": "C-bounded-recovery-and-file-closure",
        "stage": "C",
        "sourceBindings": [
            {
                "path": "codex-rs/hepta-agentd/src/intelligence_learning_io.rs",
                "symbols": [
                    "spawn_learning_io_watchdog_v1",
                    "HARD_TIMEOUT_EXIT_CODE",
                    "run_bounded_learning_io_v1",
                ],
            },
            {
                "path": "codex-rs/hepta-agentd/src/intelligence_learning_runtime.rs",
                "symbols": ["single_slot_alternates_instead_of_starving_new_work"],
            },
            {
                "path": "codex-rs/hepta-agentd/src/intelligence_files.rs",
                "symbols": ["read_bounded", "publish_immutable"],
            },
            {
                "path": "codex-rs/hepta-agentd/src/intelligence_authority_rollback.rs",
                "symbols": ["IntelligenceAuthorityRollbackGuardV1"],
            },
        ],
        "mappedRequirements": [
            "fair_recovery",
            "independent_worker_supervision",
            "learning_file_publication",
            "authority_manifest_anti_rollback",
        ],
        "mappedTests": [
            "single_slot_alternates_instead_of_starving_new_work",
            "unused_claim_deferral_preserves_identity_and_fences_old_claim",
            "guard_rejects_rollback_and_same_epoch_drift_and_survives_reopen",
            "immutable_payload_publication_is_idempotent_and_bounded",
        ],
        "directTests": [
            {
                "name": "learning_io_completion_disarms_and_joins_watchdog",
                "path": "codex-rs/hepta-agentd/src/intelligence_learning_io.rs",
                "package": "codex-hepta-agentd",
            },
            {
                "name": "learning_io_hard_timeout_terminates_a_real_child_process",
                "path": "codex-rs/hepta-agentd/src/intelligence_learning_io.rs",
                "package": "codex-hepta-agentd",
            },
        ],
        "commandRecords": [
            "operations-tests.json",
            "agentd-default-tests.json",
            "agentd-all-targets.json",
            "clippy.json",
        ],
    },
    {
        "id": "D-exact-candidate-acceptance",
        "stage": "D",
        "sourceBindings": [
            {
                "path": ".github/workflows/hepta-intelligence-control.yml",
                "symbols": [
                    "source-head",
                    "base-merge",
                    "Project only observed exact execution evidence",
                    "hepta-intelligence-acceptance.py",
                ],
            },
            {
                "path": "scripts/hepta-intelligence-control-status.py",
                "symbols": ["validate_command_record", "project_execution"],
            },
        ],
        "mappedRequirements": [],
        "mappedTests": [],
        "directTests": [],
        "commandRecords": sorted(STATUS.COMMANDS),
    },
)

EXTERNAL_GATES = (
    "live authenticated owner/evidence sources and selected-task quality",
    "real-process ObjectiveStart/provider/Outcome crash and acknowledgement cuts",
    "target-host latency, RSS, saturation and Supervisor replacement measurements",
    "independent semantic/security and operator acceptance",
    "activation, canary promotion and release",
)

TEST_PATTERN = re.compile(
    r"(?P<attrs>(?:\s*#\[[^\n]+\]\s*)+)(?:async\s+)?fn\s+"
    r"(?P<name>[A-Za-z0-9_]+)\s*\(",
    re.MULTILINE,
)


def source_text(relative: str) -> str:
    return STATUS.source_text(relative)


def validate_direct_test(row: dict[str, str]) -> None:
    if row["package"] not in STATUS.PACKAGE_RECORDS:
        raise ValueError(f"unknown direct-test package: {row['package']}")
    text = source_text(row["path"])
    matches = [
        match for match in TEST_PATTERN.finditer(text) if match["name"] == row["name"]
    ]
    if (
        len(matches) != 1
        or "test" not in matches[0]["attrs"]
        or "ignore" in matches[0]["attrs"]
    ):
        raise ValueError(
            f"missing, ambiguous or ignored direct test: {row['path']}::{row['name']}"
        )


def validate_objectives() -> tuple[dict[str, Any], dict[str, Any]]:
    implementation, trace = STATUS.validate_declarations()
    ids = [row["id"] for row in OBJECTIVES]
    if len(ids) != len(set(ids)) or set(ids) != {
        "A1-cross-stage-semantic-closure",
        "A2-current-time-recovery-closure",
        "B-single-product-execution-closure",
        "C-bounded-recovery-and-file-closure",
        "D-exact-candidate-acceptance",
    }:
        raise ValueError("the five reviewed acceptance objectives changed")
    if {row["stage"] for row in OBJECTIVES} != {"A", "B", "C", "D"}:
        raise ValueError("A-D acceptance stages are incomplete")

    requirements = {row["id"] for row in trace["requirements"]}
    mapped_tests = {
        row["name"]
        for row in trace["ordinaryProductTests"] + trace["qualificationOnlyTests"]
    }
    for objective in OBJECTIVES:
        evidence_count = 0
        for binding in objective["sourceBindings"]:
            text = source_text(binding["path"])
            for symbol in binding["symbols"]:
                if symbol not in text:
                    raise ValueError(
                        f"missing acceptance symbol {symbol}: {binding['path']}"
                    )
                evidence_count += 1
        if not set(objective["mappedRequirements"]).issubset(requirements):
            raise ValueError(f"unknown mapped requirement: {objective['id']}")
        if not set(objective["mappedTests"]).issubset(mapped_tests):
            raise ValueError(f"unknown mapped test: {objective['id']}")
        evidence_count += len(objective["mappedTests"])
        for test in objective["directTests"]:
            validate_direct_test(test)
            evidence_count += 1
        unknown_commands = set(objective["commandRecords"]) - set(STATUS.COMMANDS)
        if unknown_commands:
            raise ValueError(
                f"unknown command records for {objective['id']}: {sorted(unknown_commands)}"
            )
        evidence_count += len(objective["commandRecords"])
        if evidence_count == 0:
            raise ValueError(f"acceptance objective has no evidence: {objective['id']}")

    matrix = implementation["statusMatrix"]
    for field in STATUS.FALSE_CLAIMS:
        if matrix.get(field) is not False:
            raise ValueError(f"source acceptance cannot establish {field}")
    return implementation, trace


def objective_digest() -> str:
    encoded = json.dumps(OBJECTIVES, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def emit_receipt(
    head: str,
    lane: str,
    records: Path,
    output: Path,
) -> None:
    if head != STATUS.git("rev-parse", "HEAD"):
        raise ValueError("acceptance source head differs from checkout HEAD")
    if STATUS.git("status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("acceptance projection requires a clean checkout")
    implementation, trace = validate_objectives()
    _, projected_trace = STATUS.project_execution(
        implementation,
        trace,
        head,
        lane,
        "passed",
        records,
    )
    projected_tests = {
        row["name"]: row
        for row in projected_trace["ordinaryProductTests"]
        + projected_trace["qualificationOnlyTests"]
    }
    command_cache: dict[str, tuple[dict[str, Any], str]] = {}

    def command(name: str) -> tuple[dict[str, Any], str]:
        if name not in command_cache:
            command_cache[name] = STATUS.validate_command_record(
                records / name,
                STATUS.COMMANDS[name],
                head,
                lane,
            )
        return command_cache[name]

    results: list[dict[str, Any]] = []
    for objective in OBJECTIVES:
        observed: dict[str, str] = {}
        for name in objective["mappedTests"]:
            row = projected_tests[name]
            if row["executionStatus"] != "passed":
                raise ValueError(f"mapped test did not pass: {name}")
            observed[name] = row["observedTestName"]
        for test in objective["directTests"]:
            record_name = STATUS.PACKAGE_RECORDS[test["package"]]
            _, text = command(record_name)
            observed[test["name"]] = STATUS.observed_test_name(text, test["name"])
        command_digests = {}
        for name in objective["commandRecords"]:
            record, _ = command(name)
            command_digests[name] = record["log_sha256"]
        results.append(
            {
                "id": objective["id"],
                "stage": objective["stage"],
                "status": "passed",
                "observedTests": observed,
                "commandLogSha256": command_digests,
            }
        )

    receipt = {
        "schema": SCHEMA,
        "schemaVersion": 1,
        "module": "intelligence.control",
        "sourceIdentity": {
            "commit": head,
            "lane": lane,
            "executionStatus": "passed",
            "commitMustEqualCheckoutHead": True,
        },
        "objectiveDefinitionSha256": objective_digest(),
        "objectives": results,
        "claimBoundary": {
            "sourceAndExactPackageAcceptance": True,
            "realProcessProviderE2E": False,
            "targetHostQualified": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
        "remainingExternalGates": list(EXTERNAL_GATES),
    }
    resolved = output.resolve()
    if resolved.is_relative_to(ROOT):
        raise ValueError(
            "acceptance receipts must be emitted outside the source checkout"
        )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--source-head")
    parser.add_argument("--lane", choices=("source-head", "base-merge"))
    parser.add_argument("--execution-status", choices=("passed",))
    parser.add_argument("--command-records", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    validate_objectives()
    if args.output is not None:
        if (
            args.source_head is None
            or args.lane is None
            or args.execution_status != "passed"
            or args.command_records is None
        ):
            raise ValueError("a passed receipt requires head, lane and command records")
        emit_receipt(
            args.source_head,
            args.lane,
            args.command_records,
            args.output,
        )
    elif not args.check:
        parser.error("use --check or provide --output")


if __name__ == "__main__":
    main()
