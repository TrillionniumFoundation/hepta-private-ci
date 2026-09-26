#!/usr/bin/env python3
"""Generate intelligence.control implementation and test truth from source.

Tracked JSON uses a stable `CI_EXACT_HEAD` identity marker to avoid a
self-referential commit. CI regenerates the same documents after execution with
its exact checkout SHA and retains them as qualification artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE_DOCS = ROOT / "docs/modules/intelligence.control"
IMPLEMENTATION_MAP = MODULE_DOCS / "IMPLEMENTATION_MAP.json"
TEST_TRACEABILITY = MODULE_DOCS / "TEST_TRACEABILITY.json"
PLACEHOLDER_HEAD = "CI_EXACT_HEAD"

SOURCE_FILES = {
    "canonical": "codex-rs/hepta-intelligence/src/canonical.rs",
    "invariants": "codex-rs/hepta-intelligence/src/canonical_invariants.rs",
    "ingress": "codex-rs/hepta-agentd/src/intelligence_ingress.rs",
    "runner": "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "product": "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "bound": "codex-rs/hepta-agentd/src/lane_b_bound.rs",
    "learning": "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    "telemetry": "codex-rs/hepta-agentd/src/intelligence_observability.rs",
    "state": "codex-rs/hepta-agentd/src/state.rs",
    "runtime": "codex-rs/hepta-agentd/src/runtime.rs",
    "objective_runtime": "codex-rs/hepta-agentd/src/objective_runtime.rs",
    "physical": "codex-rs/hepta-infer-worker-host/src/native_run_control.rs",
    "main": "codex-rs/hepta-agentd/src/main.rs",
}

EXPECTED_SOURCE_FACTS = {
    "canonicalFacadePresent": ("canonical", "pub fn prepare_intelligence_run"),
    "canonicalCandidateDigestPresent": ("canonical", "candidate_set_digest"),
    "selectedMembershipInvariantPresent": (
        "invariants",
        "selected candidate membership",
    ),
    "rawCandidateOrderCanonicalized": (
        "invariants",
        "raw_candidate_order_does_not_change_canonical_identity",
    ),
    "maliciousSelectionTestPresent": (
        "invariants",
        "malicious_selected_candidate_outside_legal_set_is_rejected",
    ),
    "durableRunIdentityPresent": ("ingress", "AgentdIntelligenceRunIdentityV1"),
    "singleFenceConstructorPresent": ("ingress", "objective_run_fence_digest_v1"),
    "concreteProviderPresent": (
        "ingress",
        "impl<F> AgentdIntelligenceInvocationProviderV1",
    ),
    "atomicProfileCompositionPresent": (
        "runtime",
        "set_provider_configured(true)",
    ),
    "boundCoordinatorAdmissionPresent": ("bound", "start_bound_run"),
    "spawnCurrentLifecycleTestPresent": (
        "bound",
        "running_generation_differs_from_spawn_and_is_admitted",
    ),
    "preparedRunInheritsDurableIdentity": (
        "runner",
        "request_digest: run_identity.request_digest.to_string()",
    ),
    "canonicalOutcomeFinalGatePresent": (
        "runner",
        "validate_canonical_outcome_v1",
    ),
    "formalDecisionWriterPresent": (
        "learning",
        "append_intelligence_decision_v1",
    ),
    "formalOutcomeWriterPresent": (
        "learning",
        "append_intelligence_outcome_v1",
    ),
    "durableLearningOutboxPresent": (
        "learning",
        "DurableOperationStore",
    ),
    "restartReconciliationPresent": (
        "learning",
        "reconcile_unsettled",
    ),
    "physicalTerminalBindingPresent": (
        "learning",
        "intelligence_physical_terminal_binding_digest_v1",
    ),
    "explicitLearningTerminalStatesPresent": (
        "learning",
        "AgentdIntelligenceLearningDispositionV1",
    ),
    "stageTelemetryPresent": (
        "telemetry",
        "AgentdIntelligenceStageTelemetrySnapshotV1",
    ),
    "workerSaturationTelemetryPresent": ("telemetry", "busy_rejections"),
    "lateWorkerTelemetryPresent": ("telemetry", "late_worker_completions"),
    "authorityEpochTelemetryPresent": ("telemetry", "last_authority_epoch"),
    "runPhaseDwellTelemetryPresent": (
        "telemetry",
        "run_phase_dwell_snapshot",
    ),
    "hardTimeoutProcessFencePresent": (
        "runner",
        "with_hard_timeout_process_exit",
    ),
    "capabilityProfileDigestPresent": ("runner", "capability_profile_digest"),
    "daemonObjectiveRoutePresent": (
        "objective_runtime",
        "start_canonical_intelligence",
    ),
    "physicalTurnBindingPresent": ("physical", "run_intelligence"),
}

REQUIRED_TESTS = {
    "raw_candidate_order_does_not_change_canonical_identity",
    "malicious_selected_candidate_outside_legal_set_is_rejected",
    "zero_propensity_selection_is_rejected",
    "running_generation_differs_from_spawn_and_is_admitted",
    "forged_generation_or_fence_is_rejected_before_mutation",
    "worker_timeout_is_visible_after_late_completion",
    "stage_failure_classes_remain_separate",
    "run_phase_dwell_accumulates_exact_transitions",
    "same_phase_idempotent_replay_does_not_reset_dwell",
    "operation_ids_are_kind_separated_and_stable",
    "evidence_payload_rejects_role_substitution",
}

TEST_PATTERN = re.compile(
    r"(?P<attrs>(?:\s*#\[[^\n]+\]\s*)+)(?:async\s+)?fn\s+(?P<name>[A-Za-z0-9_]+)\s*\(",
    re.MULTILINE,
)


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def read_sources() -> dict[str, str]:
    sources: dict[str, str] = {}
    for key, relative in SOURCE_FILES.items():
        path = ROOT / relative
        if not path.is_file():
            raise SystemExit(f"missing required source: {relative}")
        sources[key] = path.read_text(encoding="utf-8")
    return sources


def source_facts(sources: dict[str, str]) -> dict[str, bool]:
    facts = {
        name: needle in sources[source]
        for name, (source, needle) in EXPECTED_SOURCE_FACTS.items()
    }
    missing = [name for name, present in facts.items() if not present]
    if missing:
        raise SystemExit("missing intelligence.control source facts: " + ", ".join(missing))
    config_text = (ROOT / "codex-rs/hepta-agentd/src/config.rs").read_text(
        encoding="utf-8"
    )
    facts["atomicProfileCompositionPresent"] = (
        "with_canonical_intelligence_profile" in config_text
        and "HostOwnedAgentdIntelligenceInvocationProviderV1::new" in config_text
    )
    main_text = sources["main"]
    facts["defaultBinaryCanonicalProfileComposed"] = (
        "with_canonical_intelligence_profile" in main_text
    )
    state_control = (
        ROOT / "codex-rs/hepta-agentd/src/state_control.rs"
    ).read_text(encoding="utf-8")
    facts["capabilityAllOrNoneGuardPresent"] = (
        "canonical_intelligence_enabled()" in state_control
    )
    return facts


def discover_tests() -> list[dict[str, Any]]:
    roots = [
        ROOT / "codex-rs/hepta-intelligence/src",
        ROOT / "codex-rs/hepta-agentd/src",
        ROOT / "codex-rs/hepta-infer-worker-host/src",
    ]
    tests: list[dict[str, Any]] = []
    for root in roots:
        for path in sorted(root.glob("*.rs")):
            text = path.read_text(encoding="utf-8")
            for match in TEST_PATTERN.finditer(text):
                attrs = match.group("attrs")
                if "test" not in attrs:
                    continue
                prefix = text[max(0, match.start() - 600) : match.start()]
                tests.append(
                    {
                        "name": match.group("name"),
                        "sourcePath": str(path.relative_to(ROOT)),
                        "qualificationOnly": (
                            "qualification-legacy-learning-write" in prefix
                            or "qualification-legacy-learning-write" in attrs
                        ),
                        "ignored": "ignore" in attrs,
                    }
                )
    tests.sort(key=lambda value: (value["sourcePath"], value["name"]))
    discovered = {value["name"] for value in tests}
    missing = sorted(REQUIRED_TESTS - discovered)
    if missing:
        raise SystemExit("missing required intelligence.control tests: " + ", ".join(missing))
    return tests


def identity(source_head: str, execution_status: str, lane: str) -> dict[str, Any]:
    return {
        "policy": "ci_exact_head_artifact_v1",
        "commit": source_head,
        "lane": lane,
        "executionStatus": execution_status,
        "commitMustEqualCheckoutHead": True,
    }


def operation(
    name: str,
    source_path: str,
    state: str,
    tests: list[dict[str, Any]],
) -> dict[str, Any]:
    needle = name.split("::")[-1]
    matching = [test["name"] for test in tests if needle in test["name"]]
    return {
        "operation": name,
        "sourcePath": source_path,
        "state": state,
        "authority": "none" if "append_intelligence" not in name else "ledger_writer_only",
        "tests": matching,
    }


def implementation_document(
    source_head: str,
    execution_status: str,
    lane: str,
    facts: dict[str, bool],
    tests: list[dict[str, Any]],
) -> dict[str, Any]:
    exact_passed = execution_status == "passed"
    return {
        "schema": "hepta.module-implementation-map.v4",
        "schemaVersion": 4,
        "module": "intelligence.control",
        "owner": "intelligence-platform",
        "deputy": "qualification-plane",
        "sourceIdentity": identity(source_head, execution_status, lane),
        "generatedBy": "scripts/hepta-intelligence-control-status.py",
        "declaredRoots": ["codex-rs/hepta-intelligence"],
        "integrationRoots": [
            "codex-rs/hepta-agentd",
            "codex-rs/hepta-infer-worker-host",
            "codex-rs/hepta-learning-ledger",
            "codex-rs/hepta-operations",
        ],
        "statusMatrix": {
            "documentationDepthClosed": True,
            "sourceImplementation": all(
                value
                for name, value in facts.items()
                if name != "defaultBinaryCanonicalProfileComposed"
            ),
            "routeCallsitePresent": facts["daemonObjectiveRoutePresent"],
            "providerImplementationPresent": facts["concreteProviderPresent"],
            "atomicProfileCompositionPresent": facts[
                "atomicProfileCompositionPresent"
            ],
            "defaultBinaryProfileComposed": facts[
                "defaultBinaryCanonicalProfileComposed"
            ],
            "durableRunIdentityPresent": facts["durableRunIdentityPresent"],
            "formalProductLearningWriterPresent": facts[
                "formalDecisionWriterPresent"
            ]
            and facts["formalOutcomeWriterPresent"],
            "durableLearningOutboxPresent": facts[
                "durableLearningOutboxPresent"
            ],
            "restartReconciliationPresent": facts[
                "restartReconciliationPresent"
            ],
            "physicalTerminalBindingPresent": facts[
                "physicalTerminalBindingPresent"
            ],
            "observabilityPresent": facts["stageTelemetryPresent"],
            "hardTimeoutProcessFencePresent": facts[
                "hardTimeoutProcessFencePresent"
            ],
            "sourceTestsPresent": bool(tests),
            "exactHeadExecuted": exact_passed and lane == "source-head",
            "syntheticMergeExecuted": exact_passed and lane == "base-merge",
            "realProcessProviderE2E": False,
            "targetHostQualified": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
        "sourceFacts": facts,
        "canonicalOperations": [
            operation(
                "prepare_intelligence_run",
                "codex-rs/hepta-intelligence/src/canonical.rs",
                "source_implemented",
                tests,
            ),
            operation(
                "validate_canonical_outcome_v1",
                "codex-rs/hepta-intelligence/src/canonical_invariants.rs",
                "source_implemented_final_product_gate",
                tests,
            ),
            operation(
                "AgentdIntelligenceRunIdentityV1::from_run_start",
                "codex-rs/hepta-agentd/src/intelligence_ingress.rs",
                "source_implemented_single_identity",
                tests,
            ),
            operation(
                "AgentRunCoordinator::start_bound_run",
                "codex-rs/hepta-agentd/src/lane_b_bound.rs",
                "source_implemented_composition_fenced",
                tests,
            ),
            operation(
                "append_intelligence_decision_v1",
                "codex-rs/hepta-agentd/src/intelligence_learning.rs",
                "source_implemented_ledger_writer_only",
                tests,
            ),
            operation(
                "append_intelligence_outcome_v1",
                "codex-rs/hepta-agentd/src/intelligence_learning.rs",
                "source_implemented_physical_terminal_bound",
                tests,
            ),
            operation(
                "AgentdIntelligenceLearningHostV1::reconcile_unsettled",
                "codex-rs/hepta-agentd/src/intelligence_learning.rs",
                "source_implemented_exact_replay",
                tests,
            ),
        ],
        "capabilityBoundary": {
            "capabilityId": "intelligence.canonical_v1",
            "advertisedOnlyWhenRunnerAndProviderPresent": facts[
                "capabilityAllOrNoneGuardPresent"
            ],
            "capabilityProfileDigestSource": "AgentdIntelligenceProductRunnerV1::capability_profile_digest",
            "defaultCliAdvertises": facts["defaultBinaryCanonicalProfileComposed"],
        },
        "qualificationOnlySurfaces": [
            "AgentdIntelligenceProductRunnerV1::append_decision",
            "AgentdIntelligenceProductRunnerV1::append_outcome",
            "AgentdIntelligenceProductRunnerV1::reconcile_ledger_append",
        ],
        "remainingExternalGates": [
            "real-process host-owned provider plus ObjectiveStart plus App Server E2E",
            "target-host latency RSS and hard-timeout process-restart qualification",
            "independent semantic and security acceptance",
            "operator canary promotion and release",
        ],
    }


def traceability_document(
    source_head: str,
    execution_status: str,
    lane: str,
    facts: dict[str, bool],
    tests: list[dict[str, Any]],
) -> dict[str, Any]:
    ordinary = [test for test in tests if not test["qualificationOnly"]]
    qualification = [test for test in tests if test["qualificationOnly"]]

    def names(*needles: str) -> list[str]:
        return sorted(
            {
                test["name"]
                for test in tests
                if any(needle in test["name"] for needle in needles)
            }
        )

    return {
        "schema": "hepta.intelligence-control-test-traceability.v2",
        "schemaVersion": 2,
        "module": "intelligence.control",
        "sourceIdentity": identity(source_head, execution_status, lane),
        "generatedBy": "scripts/hepta-intelligence-control-status.py",
        "canonicalFacade": "prepare_intelligence_run",
        "namedProductRoute": "ObjectiveRuntimeHost::submit -> AgentdState::start_canonical_intelligence -> AgentdIntelligenceProductRunnerV1::prepare_for_composition -> AgentRunCoordinator::start_bound_run",
        "requirements": [
            {
                "requirement": "generation_fence_single_source",
                "sourceFacts": [
                    "durableRunIdentityPresent",
                    "singleFenceConstructorPresent",
                    "boundCoordinatorAdmissionPresent",
                ],
                "tests": names("running_generation", "forged_generation_or_fence"),
            },
            {
                "requirement": "canonical_candidate_membership_and_order",
                "sourceFacts": [
                    "selectedMembershipInvariantPresent",
                    "rawCandidateOrderCanonicalized",
                ],
                "tests": names(
                    "raw_candidate_order",
                    "malicious_selected_candidate",
                    "zero_propensity",
                    "duplicate_candidate",
                ),
            },
            {
                "requirement": "seven_owner_currentness_and_revocation",
                "sourceFacts": ["canonicalOutcomeFinalGatePresent"],
                "tests": names(
                    "seven_owners",
                    "generation_change",
                    "key_rotation",
                    "revocation",
                    "current_owner",
                ),
            },
            {
                "requirement": "durable_decision_outcome_closure",
                "sourceFacts": [
                    "formalDecisionWriterPresent",
                    "formalOutcomeWriterPresent",
                    "durableLearningOutboxPresent",
                    "restartReconciliationPresent",
                    "physicalTerminalBindingPresent",
                ],
                "tests": names("operation_ids", "evidence_payload", "decision_outcome"),
            },
            {
                "requirement": "bounded_execution_observability",
                "sourceFacts": [
                    "stageTelemetryPresent",
                    "workerSaturationTelemetryPresent",
                    "lateWorkerTelemetryPresent",
                    "runPhaseDwellTelemetryPresent",
                    "hardTimeoutProcessFencePresent",
                ],
                "tests": names(
                    "worker_timeout",
                    "stage_failure_classes",
                    "run_phase_dwell",
                    "same_phase_idempotent",
                    "total_budget_timeout",
                ),
            },
            {
                "requirement": "physical_turn_no_redispatch",
                "sourceFacts": ["physicalTurnBindingPresent"],
                "tests": names("intelligence_handoff", "lost_ack", "reconcile"),
            },
        ],
        "ordinaryProductTests": ordinary,
        "qualificationOnlyTests": qualification,
        "claimBoundary": {
            "sourceTestsPresent": bool(tests),
            "exactHeadExecuted": execution_status == "passed" and lane == "source-head",
            "deterministicMergeExecuted": execution_status == "passed"
            and lane == "base-merge",
            "targetHostQualified": False,
            "realProcessProviderE2E": False,
            "activation": False,
            "release": False,
        },
        "sourceFacts": facts,
    }


def encoded(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=False) + "\n"


def write_pair(directory: Path, implementation: dict[str, Any], trace: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "IMPLEMENTATION_MAP.json").write_text(
        encoded(implementation), encoding="utf-8"
    )
    (directory / "TEST_TRACEABILITY.json").write_text(encoded(trace), encoding="utf-8")


def check_file(path: Path, expected: str) -> None:
    actual = path.read_text(encoding="utf-8") if path.is_file() else ""
    if actual == expected:
        return
    print(f"generated document is stale: {path.relative_to(ROOT)}", file=sys.stderr)
    raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-head")
    parser.add_argument(
        "--execution-status", choices=("pending", "passed", "failed"), default="pending"
    )
    parser.add_argument("--lane", choices=("tracked", "source-head", "base-merge"), default="tracked")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--write-tracked", action="store_true")
    parser.add_argument("--check-tracked", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    current_head = git_head()
    if args.lane == "tracked":
        source_head = PLACEHOLDER_HEAD
        execution_status = "pending"
    else:
        source_head = args.source_head or os.environ.get("GITHUB_SHA") or current_head
        if source_head != current_head:
            raise SystemExit(
                f"source identity mismatch: requested {source_head}, checkout {current_head}"
            )
        execution_status = args.execution_status
    sources = read_sources()
    facts = source_facts(sources)
    tests = discover_tests()
    implementation = implementation_document(
        source_head, execution_status, args.lane, facts, tests
    )
    trace = traceability_document(source_head, execution_status, args.lane, facts, tests)

    if args.write_tracked:
        write_pair(MODULE_DOCS, implementation, trace)
    if args.check_tracked:
        check_file(IMPLEMENTATION_MAP, encoded(implementation))
        check_file(TEST_TRACEABILITY, encoded(trace))
    if args.output_dir:
        write_pair(args.output_dir, implementation, trace)
    if not (args.write_tracked or args.check_tracked or args.output_dir):
        json.dump(
            {"implementation": implementation, "traceability": trace},
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
