#!/usr/bin/env python3
"""Refresh learning.plasticity implementation truth from one exact source head."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json"
GENERATOR_PATH = ROOT / "scripts/hepta-implementation-maps.py"


def git(*args: str) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    return subprocess.run(
        ["git", "--literal-pathspecs", "-c", "core.fsmonitor=false", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def load_generator():
    spec = importlib.util.spec_from_file_location("hepta_implementation_maps", GENERATOR_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load implementation-map generator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def operation(
    operation_id: str,
    symbol: str,
    source: str,
    state: str,
    authority: str,
    tests: list[str],
    mapping_class: str,
    delegated: list[dict] | None = None,
) -> dict:
    return {
        "operation": operation_id,
        "nativeSymbol": symbol,
        "sourcePath": source,
        "state": state,
        "authority": authority,
        "tests": tests,
        "sourcePathExists": True,
        "designOperation": operation_id,
        "mappingClass": mapping_class,
        "delegatedCallees": delegated or [],
    }


def upsert(operations: list[dict], value: dict, *, before: str | None = None) -> None:
    for index, current in enumerate(operations):
        if current.get("operation") == value["operation"]:
            operations[index] = value
            return
    if before is not None:
        for index, current in enumerate(operations):
            if current.get("operation") == before:
                operations.insert(index, value)
                return
    operations.append(value)


def main() -> None:
    if git("status", "--porcelain=v1", "--untracked-files=no"):
        raise SystemExit("map refresh requires a clean tracked checkout")
    row = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    row["sourceBase"] = {
        "commit": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
    }
    row["productCallerState"] = (
        "control_engineering_iteration_envelope_coordinator_and_named_agentd_learning_"
        "producer_source_composed_terminal_journal_pending_target_host_unqualified"
    )

    operations = row["operations"]
    upsert(
        operations,
        operation(
            "build_generator_coverage_receipt_v1",
            "build_generator_coverage_receipt_v1",
            "codex-rs/hepta-plasticity/src/generator_coverage_v1.rs",
            "source_implemented_exact_expected_signal_gap_partition_grammar_artifact_window_and_owner_frontier_bound",
            "none",
            [
                "codex-rs/hepta-plasticity/src/generator_coverage_v1.rs::tests::active_coverage_is_exact_and_tamper_evident",
                "codex-rs/hepta-plasticity/src/generator_coverage_v1.rs::tests::zero_signal_and_disabled_scale_are_distinct_terminals",
            ],
            "owner_native",
        ),
        before="propose_topology_v2",
    )
    upsert(
        operations,
        operation(
            "verify_generator_coverage_receipt_v1",
            "verify_generator_coverage_receipt_v1",
            "codex-rs/hepta-plasticity/src/generator_coverage_v1.rs",
            "source_implemented_rederives_complete_expected_signal_gap_partition_and_rejects_drift",
            "none",
            [
                "codex-rs/hepta-plasticity/src/generator_coverage_v1.rs::tests::active_coverage_is_exact_and_tamper_evident"
            ],
            "owner_native",
        ),
        before="propose_topology_v2",
    )
    upsert(
        operations,
        operation(
            "generator_coverage_signing_payload_v1",
            "generator_coverage_signing_payload_v1",
            "codex-rs/hepta-plasticity/src/generator_coverage_v1.rs",
            "source_implemented_observer_signing_payload_for_exact_coverage_receipt",
            "none",
            [
                "codex-rs/hepta-plasticity/src/generator_coverage_v1.rs::tests::active_coverage_is_exact_and_tamper_evident"
            ],
            "owner_native",
        ),
        before="propose_topology_v2",
    )
    upsert(
        operations,
        operation(
            "control_engineering_self_iteration_coordinator",
            "prepare_parameter_self_iteration_v1",
            "codex-rs/hepta-agentd/src/control_engineering_self_iteration.rs",
            "source_implemented_iteration_envelope_objective_grammar_generation_coverage_request_and_idempotency_bound_terminal_journal_pending",
            "proposal_submission_only",
            [
                "codex-rs/hepta-agentd/src/control_engineering_self_iteration.rs::tests::envelope_digest_binds_every_budget_and_source_field",
                "codex-rs/hepta-agentd/src/control_engineering_self_iteration.rs::tests::envelope_deadline_cannot_outlive_authorized_window",
                "codex-rs/hepta-agentd/tests/plasticity_grammar_contract.rs::control_engineering_grammar_projects_unambiguously_into_plasticity_policy",
            ],
            "delegated_composition",
            [
                {
                    "path": "codex-rs/hepta-learning-artifacts",
                    "module": "learning.artifacts",
                    "role": "iteration_envelope_owner",
                },
                {
                    "path": "codex-rs/hepta-agentd/src/plasticity_learning_producer.rs",
                    "module": "runtime.agentd",
                    "role": "named_bounded_submission_port",
                },
            ],
        ),
        before="agentd_process_bootstrap",
    )

    for current in operations:
        if current.get("operation") == "parameter_mutation_policy":
            contract_test = (
                "codex-rs/hepta-agentd/tests/plasticity_grammar_contract.rs::"
                "control_engineering_grammar_projects_unambiguously_into_plasticity_policy"
            )
            if contract_test not in current["tests"]:
                current["tests"].append(contract_test)
        if current.get("operation") == "agentd_plasticity_runtime_owner":
            current["state"] = (
                "named_agentd_runtime_owner_dual_bounded_lanes_shared_byte_work_budgets_"
                "deadline_cancellation_blocking_pool_and_metrics_source_implemented_not_target_host_qualified"
            )
            current["tests"] = [
                "codex-rs/hepta-agentd/src/plasticity_runtime.rs::tests::runtime_limits_bound_both_lanes_and_resource_budgets",
                "codex-rs/hepta-agentd/src/plasticity_runtime.rs::tests::absolute_deadline_is_converted_to_bounded_monotonic_time",
                "codex-rs/hepta-agentd/src/plasticity_runtime_lifetime_tests.rs::agentd_lifetime_owner_submits_restarts_and_reconciles_idempotently",
            ]
        if current.get("operation") == "agentd_named_parameter_submission":
            current["state"] = (
                "named_non_test_agentd_parameter_producer_source_implemented_dual_budgeted_"
                "deadline_cancel_aware_final_owner_revalidation_not_target_host_qualified"
            )
        if current.get("operation") == "agentd_named_topology_submission":
            current["state"] = (
                "named_non_test_agentd_topology_producer_source_implemented_dual_budgeted_"
                "deadline_cancel_aware_final_owner_revalidation_not_target_host_qualified"
            )
        if current.get("operation") == "durableproposalregistry":
            property_test = (
                "codex-rs/hepta-plasticity/tests/plasticity_properties.rs::"
                "recovery_repairs_only_incomplete_crash_tails"
            )
            corruption_test = (
                "codex-rs/hepta-plasticity/tests/plasticity_properties.rs::"
                "complete_corruption_and_second_writer_fail_closed"
            )
            for test in (property_test, corruption_test):
                if test not in current["tests"]:
                    current["tests"].append(test)
        if current.get("operation") == "generate_parameter_candidates_v3":
            property_test = (
                "codex-rs/hepta-plasticity/tests/plasticity_properties.rs::"
                "canonical_generation_is_permutation_invariant_and_tamper_evident"
            )
            if property_test not in current["tests"]:
                current["tests"].append(property_test)

    row["repositoryControlledGaps"] = [
        "Persist every control.engineering self-iteration terminal receipt in a crash-safe idempotent journal and reconcile caller cancellation after durable dispatch.",
        "Harden Unix mutable-owner opens with descriptor-relative no-follow semantics, post-open identity verification, parent-directory fsync and target-host rollback-domain identity evidence.",
        "Run exact-head and deterministic synthetic-merge document verification, build, tests, strict lint, Agentd process E2E, Lane F qualification and live-runtime structural-canary regression for the final source/document head.",
        "Add decoder fuzzing plus longer model-based parameter/topology differential, capacity, rollover and multi-process contention sequences.",
    ]
    row["productCallers"] = [
        {
            "sourcePath": "codex-rs/hepta-agentd/src/control_engineering_self_iteration.rs",
            "nativeSymbol": "prepare_parameter_self_iteration_v1",
            "state": "non_test_iteration_envelope_coordinator_terminal_journal_pending",
        },
        {
            "sourcePath": "codex-rs/hepta-agentd/src/plasticity_runtime.rs",
            "nativeSymbol": "PlasticityRuntimeOwnerV1::run",
            "state": "dual_lane_bounded_runtime_owner_source_composed",
        },
        {
            "sourcePath": "codex-rs/hepta-agentd/src/plasticity_learning_producer.rs",
            "nativeSymbol": "AgentdLearningPlasticityProducerV1",
            "state": "named_non_test_bounded_submission_port_source_composed",
        },
    ]

    generator = load_generator()
    row["sourceObjects"] = generator.current_source_objects(row)
    MAP_PATH.write_text(
        json.dumps(row, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    generator.sync_plasticity_status()


if __name__ == "__main__":
    main()
