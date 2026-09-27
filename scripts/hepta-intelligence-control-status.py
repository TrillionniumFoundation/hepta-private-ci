#!/usr/bin/env python3
"""Generate exact intelligence.control implementation and traceability truth.

The tracked documents use the stable `CI_EXACT_HEAD` identity to avoid a
self-referential commit. Exact source-head and deterministic-merge artifacts are
emitted only after native execution. Requirement coverage is read from the
explicit requirement matrix; this generator never infers semantic coverage from
function-name substrings or from an unrelated whole-package test inventory.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE_DOCS = ROOT / "docs/modules/intelligence.control"
IMPLEMENTATION_MAP = MODULE_DOCS / "IMPLEMENTATION_MAP.json"
TEST_TRACEABILITY = MODULE_DOCS / "TEST_TRACEABILITY.json"
REQUIREMENT_MATRIX = MODULE_DOCS / "REQUIREMENT_MATRIX.json"
PLACEHOLDER_HEAD = "CI_EXACT_HEAD"

SOURCE_FILES = {
    "canonical": "codex-rs/hepta-intelligence/src/canonical.rs",
    "invariants": "codex-rs/hepta-intelligence/src/canonical_invariants.rs",
    "ingress": "codex-rs/hepta-agentd/src/intelligence_ingress.rs",
    "runner": "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "product": "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "bound": "codex-rs/hepta-agentd/src/lane_b_bound.rs",
    "learning": "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    "learning_runtime": "codex-rs/hepta-agentd/src/intelligence_learning_runtime.rs",
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
    "durableLearningOutboxPresent": ("learning", "DurableOperationStore"),
    "restartReconciliationPresent": ("learning", "reconcile_unsettled"),
    "exactLearningEvidenceBindingPresent": (
        "learning",
        "VerifiedEvidenceBindingPayloadV1",
    ),
    "exactDestinationEventObservationPresent": (
        "learning",
        "record.event == expected",
    ),
    "currentTimeRecoveryPresent": (
        "learning",
        "pub trait AgentdIntelligenceLearningClockV1",
    ),
    "currentEvidenceWindowPresent": (
        "learning",
        "fn require_current_payload_window",
    ),
    "boundedPayloadReadPresent": (
        "learning",
        "fn read_bounded_regular_file",
    ),
    "temporaryGrantRetryPresent": ("learning", "GRANT_RETRY_DELAY"),
    "daemonLearningReconcilerPresent": (
        "learning_runtime",
        "run_intelligence_learning_runtime_v1",
    ),
    "recoveryFairnessPresent": (
        "learning_runtime",
        "fn split_learning_budget",
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


def read_requirements() -> dict[str, Any]:
    value = json.loads(REQUIREMENT_MATRIX.read_text(encoding="utf-8"))
    if value.get("schema") != "hepta.intelligence-control-requirements.v1":
        raise SystemExit("invalid intelligence.control requirement matrix")
    requirements = value.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        raise SystemExit("empty intelligence.control requirement matrix")
    return value


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
    facts["defaultBinaryCanonicalProfileComposed"] = (
        "with_canonical_intelligence_profile" in sources["main"]
    )
    state_control = (
        ROOT / "codex-rs/hepta-agentd/src/state_control.rs"
    ).read_text(encoding="utf-8")
    facts["capabilityAllOrNoneGuardPresent"] = (
        "canonical_intelligence_enabled()" in state_control
    )
    facts["explicitRequirementMatrixPresent"] = REQUIREMENT_MATRIX.is_file()
    return facts


def identity(source_head: str, execution_status: str, lane: str) -> dict[str, Any]:
    return {
        "policy": "ci_exact_head_artifact_v1",
        "commit": source_head,
        "lane": lane,
        "executionStatus": execution_status,
        "commitMustEqualCheckoutHead": True,
    }


def mapped_tests(
    requirements: dict[str, Any], source_path: str, symbol: str
) -> list[str]:
    names: set[str] = set()
    for requirement in requirements["requirements"]:
        if any(
            source.get("path") == source_path and source.get("symbol") == symbol
            for source in requirement.get("sources", [])
        ):
            names.update(test["name"] for test in requirement.get("tests", []))
    return sorted(names)


def operation(
    name: str,
    source_path: str,
    symbol: str,
    state: str,
    authority: str,
    requirements: dict[str, Any],
) -> dict[str, Any]:
    return {
        "operation": name,
        "sourcePath": source_path,
        "nativeSymbol": symbol,
        "state": state,
        "authority": authority,
        "tests": mapped_tests(requirements, source_path, symbol),
    }


def implementation_document(
    source_head: str,
    execution_status: str,
    lane: str,
    facts: dict[str, bool],
    requirements: dict[str, Any],
) -> dict[str, Any]:
    exact_passed = execution_status == "passed"
    source_complete = all(
        value
        for name, value in facts.items()
        if name != "defaultBinaryCanonicalProfileComposed"
    )
    return {
        "schema": "hepta.module-implementation-map.v4",
        "schemaVersion": 4,
        "module": "intelligence.control",
        "owner": "intelligence-platform",
        "deputy": "qualification-plane",
        "sourceIdentity": identity(source_head, execution_status, lane),
        "generatedBy": "scripts/hepta-intelligence-control-status.py",
        "requirementMatrix": "docs/modules/intelligence.control/REQUIREMENT_MATRIX.json",
        "declaredRoots": ["codex-rs/hepta-intelligence"],
        "integrationRoots": [
            "codex-rs/hepta-agentd",
            "codex-rs/hepta-infer-worker-host",
            "codex-rs/hepta-learning-ledger",
            "codex-rs/hepta-operations",
        ],
        "statusMatrix": {
            "documentationDepthClosed": True,
            "sourceImplementation": source_complete,
            "routeCallsitePresent": facts["daemonObjectiveRoutePresent"],
            "providerImplementationPresent": facts["concreteProviderPresent"],
            "atomicProfileCompositionPresent": facts["atomicProfileCompositionPresent"],
            "defaultBinaryProfileComposed": facts[
                "defaultBinaryCanonicalProfileComposed"
            ],
            "durableRunIdentityPresent": facts["durableRunIdentityPresent"],
            "formalProductLearningWriterPresent": facts[
                "formalDecisionWriterPresent"
            ]
            and facts["formalOutcomeWriterPresent"],
            "durableLearningOutboxPresent": facts["durableLearningOutboxPresent"],
            "restartReconciliationPresent": facts["restartReconciliationPresent"],
            "exactAuthenticatedRecoveryPresent": facts[
                "exactLearningEvidenceBindingPresent"
            ]
            and facts["exactDestinationEventObservationPresent"],
            "currentTimeRecoveryPresent": facts["currentTimeRecoveryPresent"]
            and facts["currentEvidenceWindowPresent"],
            "recoveryFairnessPresent": facts["recoveryFairnessPresent"],
            "boundedPayloadReadPresent": facts["boundedPayloadReadPresent"],
            "temporaryGrantRetryPresent": facts["temporaryGrantRetryPresent"],
            "daemonLearningReconcilerPresent": facts[
                "daemonLearningReconcilerPresent"
            ],
            "physicalTerminalBindingPresent": facts[
                "physicalTerminalBindingPresent"
            ],
            "observabilityPresent": facts["stageTelemetryPresent"],
            "hardTimeoutProcessFencePresent": facts[
                "hardTimeoutProcessFencePresent"
            ],
            "explicitRequirementTraceabilityPresent": facts[
                "explicitRequirementMatrixPresent"
            ],
            "sourceTestsPresent": bool(requirements["requirements"]),
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
                "pub fn prepare_intelligence_run",
                "source_implemented",
                "none",
                requirements,
            ),
            operation(
                "validate_canonical_outcome_v1",
                "codex-rs/hepta-intelligence/src/canonical_invariants.rs",
                "pub fn validate_canonical_outcome_v1",
                "source_implemented_final_product_gate",
                "none",
                requirements,
            ),
            operation(
                "AgentdIntelligenceRunIdentityV1::from_run_start",
                "codex-rs/hepta-agentd/src/intelligence_ingress.rs",
                "pub fn from_run_start",
                "source_implemented_single_identity",
                "none",
                requirements,
            ),
            operation(
                "AgentRunCoordinator::start_bound_run",
                "codex-rs/hepta-agentd/src/lane_b_bound.rs",
                "pub fn start_bound_run",
                "source_implemented_composition_fenced",
                "none",
                requirements,
            ),
            operation(
                "append_intelligence_decision_v1",
                "codex-rs/hepta-agentd/src/intelligence_learning.rs",
                "pub fn append_intelligence_decision_v1",
                "source_implemented_ledger_writer_only",
                "ledger_writer_only",
                requirements,
            ),
            operation(
                "append_intelligence_outcome_v1",
                "codex-rs/hepta-agentd/src/intelligence_learning.rs",
                "pub fn append_intelligence_outcome_v1",
                "source_implemented_physical_terminal_bound",
                "ledger_writer_only",
                requirements,
            ),
            operation(
                "AgentdIntelligenceLearningHostV1::reconcile_unsettled",
                "codex-rs/hepta-agentd/src/intelligence_learning.rs",
                "pub async fn reconcile_unsettled",
                "source_implemented_exact_replay_current_time",
                "fresh_final_use_only",
                requirements,
            ),
            operation(
                "run_intelligence_learning_runtime_v1",
                "codex-rs/hepta-agentd/src/intelligence_learning_runtime.rs",
                "run_intelligence_learning_runtime_v1",
                "source_implemented_fair_bounded_scheduler",
                "none",
                requirements,
            ),
            operation(
                "AppServerModelDriver::run_intelligence",
                "codex-rs/hepta-infer-worker-host/src/native_run_control.rs",
                "pub async fn run_intelligence",
                "source_implemented_exact_physical_binding",
                "existing_app_server_spine",
                requirements,
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
            "real-process host-owned provider plus ObjectiveStart plus App Server plus learning E2E",
            "crash injection at outbox publication destination commit acknowledgement and generation adoption",
            "target-host latency RSS saturation and hard-timeout process-restart qualification",
            "independent semantic and security acceptance",
            "operator canary promotion and release",
        ],
    }


def traceability_document(
    source_head: str,
    execution_status: str,
    lane: str,
    facts: dict[str, bool],
    requirements: dict[str, Any],
) -> dict[str, Any]:
    mapped_product: dict[tuple[str, str], dict[str, Any]] = {}
    mapped_qualification: dict[tuple[str, str], dict[str, Any]] = {}
    projected: list[dict[str, Any]] = []
    for requirement in requirements["requirements"]:
        projected_tests = []
        for test in requirement.get("tests", []):
            item = {
                "sourcePath": test["path"],
                "name": test["name"],
                "class": test.get("class", "product"),
            }
            projected_tests.append(item)
            key = (item["sourcePath"], item["name"])
            if item["class"] == "qualification":
                mapped_qualification[key] = item
            else:
                mapped_product[key] = item
        projected.append(
            {
                "requirement": requirement["id"],
                "statement": requirement["statement"],
                "sources": requirement.get("sources", []),
                "tests": projected_tests,
            }
        )
    return {
        "schema": "hepta.intelligence-control-test-traceability.v2",
        "schemaVersion": 2,
        "module": "intelligence.control",
        "sourceIdentity": identity(source_head, execution_status, lane),
        "generatedBy": "scripts/hepta-intelligence-control-status.py",
        "coveragePolicy": "explicit_exact_path_symbol_and_test_identity_v1",
        "requirementMatrix": "docs/modules/intelligence.control/REQUIREMENT_MATRIX.json",
        "canonicalFacade": "prepare_intelligence_run",
        "namedProductRoute": "ObjectiveRuntimeHost::submit -> AgentdState::start_canonical_intelligence -> AgentdIntelligenceProductRunnerV1::prepare_for_composition -> AgentRunCoordinator::start_bound_run",
        "requirements": projected,
        "ordinaryProductTests": [mapped_product[key] for key in sorted(mapped_product)],
        "qualificationOnlyTests": [
            mapped_qualification[key] for key in sorted(mapped_qualification)
        ],
        "claimBoundary": {
            "sourceTestsPresent": bool(projected),
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


def write_pair(
    directory: Path, implementation: dict[str, Any], trace: dict[str, Any]
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "IMPLEMENTATION_MAP.json").write_text(
        encoded(implementation), encoding="utf-8"
    )
    (directory / "TEST_TRACEABILITY.json").write_text(
        encoded(trace), encoding="utf-8"
    )


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
        "--execution-status",
        choices=("pending", "passed", "failed"),
        default="pending",
    )
    parser.add_argument(
        "--lane",
        choices=("tracked", "source-head", "base-merge"),
        default="tracked",
    )
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
    requirements = read_requirements()
    facts = source_facts(sources)
    implementation = implementation_document(
        source_head, execution_status, args.lane, facts, requirements
    )
    trace = traceability_document(
        source_head, execution_status, args.lane, facts, requirements
    )

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
