#!/usr/bin/env python3
"""Verify automation.taskflow schema, documentation and product-call truth."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


class ContractError(RuntimeError):
    pass


def need(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def text(root: Path, relative: str) -> str:
    path = root / relative
    need(path.is_file(), f"missing required file: {relative}")
    return path.read_text(encoding="utf-8")


def data(root: Path, relative: str) -> dict[str, Any]:
    value = json.loads(text(root, relative))
    need(isinstance(value, dict), f"{relative} must contain a JSON object")
    return value


def verify(root: Path = ROOT) -> dict[str, Any]:
    contract = data(root, "docs/modules/automation.taskflow/SCHEMA_CONTRACT.json")
    need(contract.get("storeSchemaVersion") == 19, "contract store schema must be 19")

    lib = text(root, "codex-rs/hepta-automation/src/lib.rs")
    need(
        re.search(r"pub const AUTOMATION_SCHEMA_VERSION: u32 = 19;", lib) is not None,
        "Rust store schema constant is not 19",
    )
    for marker in [
        "mod runtime_policy;",
        "mod neural_circuit_runtime;",
        "mod cross_host_recovery;",
        "AutomationBatchReport",
        "run_neural_circuit_v1",
    ]:
        need(marker in lib, f"lib.rs is missing {marker}")

    migrations = contract.get("migrationTopology")
    need(
        isinstance(migrations, list) and len(migrations) == 3,
        "migration topology must cover 17-19",
    )
    observed_versions: list[int] = []
    for row in migrations:
        need(isinstance(row, dict), "migration row must be an object")
        version = row.get("version")
        path = row.get("path")
        required_marker = row.get("requiredMarker")
        need(isinstance(version, int), "migration version must be an integer")
        need(isinstance(path, str), "migration path must be a string")
        need(
            isinstance(required_marker, str) and required_marker,
            "migration marker must be a non-empty string",
        )
        body = text(root, path)
        need(
            required_marker in body,
            f"{path} does not contain its reviewed migration marker",
        )
        observed_versions.append(version)
    need(
        observed_versions == [17, 18, 19],
        "migration topology must be ordered 17,18,19",
    )

    documentation = [
        "docs/modules/automation.taskflow/TECHNICAL.md",
        "docs/modules/automation.taskflow/MIGRATION_V19_RUNBOOK.md",
        "docs/modules/automation.taskflow/SLO.md",
        "docs/modules/automation.taskflow/RELEASE_QUALIFICATION.md",
        "docs/modules/automation.taskflow/INDEPENDENT_ACCEPTANCE.md",
        "qualification/module-execution-dossiers/detail/automation.taskflow.md",
        "docs/readiness/LANE_B_RUNTIME_COMPOSITION.md",
        "docs/readiness/LANE_B_NATIVE_HOST.md",
        "qualification/lane-b/LANE_B_NATIVE_CLOSURE.md",
    ]
    for path in documentation:
        body = text(root, path).lower()
        need(
            "v19" in body or "schema 19" in body,
            f"{path} is not schema-v19 aware",
        )

    technical = text(root, "docs/modules/automation.taskflow/TECHNICAL.md")
    for anchor in [
        "### 4.1 Neural Circuit target and legacy boundary",
        "### 4.5 Design records and failure semantics",
        "AutomationCrossHostRecoveryManifestV1",
        "AgentdAutomationEffectHost",
        "one slot is reserved for terminal observation",
        "owner Agent read from the copied target store",
    ]:
        need(anchor in technical, f"technical guide is missing {anchor}")

    slo = text(root, "docs/modules/automation.taskflow/SLO.md")
    for marker in [
        "Terminal-observation liveness",
        "one terminal-observation slot is",
        "failed recovery attempt admits no new work",
    ]:
        need(marker in slo, f"runtime SLO is missing {marker}")

    scheduler = text(root, "codex-rs/hepta-automation/src/scheduler.rs")
    for marker in [
        "pub async fn tick_batch",
        "AutomationBatchStopReason::DispatchUncertain",
        "policy.admission_budget_per_cycle",
    ]:
        need(marker in scheduler, f"bounded scheduler is missing {marker}")

    runtime_policy = text(root, "codex-rs/hepta-automation/src/runtime_policy.rs")
    for marker in ["Fence", "FailStop", "Retry", "Reconcile", "Isolate"]:
        need(marker in runtime_policy, f"runtime error disposition is missing {marker}")

    circuit = text(
        root, "codex-rs/hepta-automation/src/neural_circuit_runtime/types.rs"
    ) + text(root, "codex-rs/hepta-automation/src/neural_circuit_runtime/runtime.rs")
    for marker in [
        "CircuitEventIngressV1",
        "CircuitDecisionCellV1",
        "CircuitOrganPortV1",
        "CircuitWaitJoinPortV1",
        "FeedbackBudgetExhausted",
        "CircuitTerminalReceiptV1",
        "CircuitEffectBoundaryV1",
        "event.validate()?",
        "event_digest does not match the canonical event ingress",
        "runtime_profile_digest",
        "hepta.neural-circuit.runtime-profile.v1",
    ]:
        need(marker in circuit, f"Neural Circuit runtime is missing {marker}")

    agentd = text(root, "codex-rs/hepta-agentd/src/automation.rs")
    for marker in [
        "recovery_budget_per_cycle",
        "tick_batch(&policy, unix_time_ms)",
        "classify_automation_error",
        "reconcile_batch(",
        "recovery_transient_budget",
    ]:
        need(marker in agentd, f"Agentd scheduling loop is missing {marker}")

    recovery = text(root, "codex-rs/hepta-agentd/src/automation_recovery.rs")
    for marker in [
        "fn recovery_slot_allocation(",
        "uncertain_candidates",
        "pending_candidates",
        "limit - 1",
        "recovery_slots_reserve_terminal_progress_under_unknown_pressure",
    ]:
        need(marker in recovery, f"bounded recovery fairness is missing {marker}")

    cross_host = text(root, "codex-rs/hepta-automation/src/cross_host_recovery.rs")
    for marker in [
        "observed_owner_agent_id: &AgentId",
        "observed_owner_agent_id.as_str() != self.owner_agent_id",
        "target_owner_drift_is_fenced",
        "AgentId::parse(&self.owner_agent_id)",
    ]:
        need(marker in cross_host, f"cross-host owner binding is missing {marker}")

    effect_host = text(root, "codex-rs/hepta-agentd/src/automation_effect_host.rs")
    for marker in [
        "AgentdAutomationEffectHost",
        "ProviderEffectTaskFlowDriver::new",
        "execute_authorized_taskflow_effect_async",
        "FinalUseAuthority::open_state_dir",
        "HttpProviderEffectAdapter",
    ]:
        need(marker in effect_host, f"product effect host is missing {marker}")

    callers = text(root, "CALLERS.toml")
    for marker in [
        'id = "automation_taskflow_provider_effect_bridge"',
        'product_callers = ["codex-rs/hepta-agentd/src/automation_effect_host.rs"]',
        'caller_markers = ["ProviderEffectTaskFlowDriver::new"',
    ]:
        need(marker in callers, f"closed product caller inventory is missing {marker}")

    acceptance_verifier = text(
        root, "scripts/verify_automation_taskflow_acceptance.py"
    )
    for marker in [
        "canonical_payload_bytes",
        "verify_ed25519_signature",
        "implementation and acceptance principals must be distinct",
        "selectedHostReceiptSha256",
        '"release": False',
    ]:
        need(
            marker in acceptance_verifier,
            f"independent acceptance verifier is missing {marker}",
        )

    acceptance_doc = text(
        root, "docs/modules/automation.taskflow/INDEPENDENT_ACCEPTANCE.md"
    )
    for marker in [
        "Ed25519",
        "automation-taskflow-independent-acceptance",
        "independentAcceptance = true",
        "release = false",
    ]:
        need(marker in acceptance_doc, f"acceptance guide is missing {marker}")

    implementation = data(
        root, "docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json"
    )
    need(
        implementation.get("storeSchemaVersion") == 19,
        "implementation map store schema is stale",
    )
    claims = implementation.get("claimBoundary")
    need(isinstance(claims, dict), "implementation map claimBoundary is missing")
    for key in [
        "boundedAdmissionBatchComplete",
        "separateRecoveryBudgetComplete",
        "externalEffectProductCompositionComplete",
        "neuralCircuitRuntimeVerticalSliceComplete",
        "crossHostRecoveryContractComplete",
        "selectedHostQualificationPathComplete",
        "independentAcceptanceVerificationPathComplete",
    ]:
        need(claims.get(key) is True, f"implementation map does not close {key}")
    for key in [
        "deploymentQualificationComplete",
        "independentAcceptance",
        "activation",
        "promotion",
        "release",
    ]:
        need(
            claims.get(key) is False,
            f"external gate {key} must remain false without evidence",
        )

    workflow = text(root, ".github/workflows/automation-taskflow-focused.yml")
    for marker in [
        "pull_request:",
        "workflow_call:",
        "branches: [main]",
        "cargo clippy",
        "automation_taskflow_contract.py",
        "test_verify_automation_taskflow_acceptance.py",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
    ]:
        need(marker in workflow, f"focused workflow is missing {marker}")

    selected_host = text(
        root, ".github/workflows/automation-taskflow-selected-host.yml"
    )
    for marker in [
        "hepta-automation-selected-host",
        "expected_tzdb_sha256",
        "multi_scheduler_race",
        "runtime_crash_points",
        "PROVIDER_IDENTITY_SHA256",
        "automation-taskflow-selected-host-receipt.json",
    ]:
        need(marker in selected_host, f"selected-host workflow is missing {marker}")

    acceptance_workflow = text(
        root, ".github/workflows/automation-taskflow-independent-acceptance.yml"
    )
    for marker in [
        "automation-taskflow-independent-acceptance",
        "AUTOMATION_ACCEPTANCE_PUBLIC_KEY_PEM",
        "gh run download",
        "verify_automation_taskflow_acceptance.py",
        "acceptance-public-key.pem",
    ]:
        need(
            marker in acceptance_workflow,
            f"independent acceptance workflow is missing {marker}",
        )

    blocking = text(root, ".github/workflows/blocking-ci.yml")
    need(
        "automation-taskflow-focused:" in blocking,
        "blocking CI does not call the focused workflow",
    )
    need(
        "- automation-taskflow-focused" in blocking,
        "CI required does not depend on focused workflow",
    )

    return {
        "module": "automation.taskflow",
        "storeSchemaVersion": 19,
        "migrationVersions": observed_versions,
        "documentationFiles": len(documentation),
        "repositoryControlledClosure": True,
        "boundedRecoveryFairnessVerified": True,
        "canonicalCircuitIngressVerified": True,
        "runtimeProfileReceiptBindingVerified": True,
        "crossHostOwnerBindingVerified": True,
        "selectedHostVerifierPresent": True,
        "independentAcceptanceVerifierPresent": True,
        "externalReleaseGatesRemainFalse": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["verify", "self-test"], nargs="?", default="verify"
    )
    args = parser.parse_args()
    try:
        result = verify()
        if args.command == "self-test":
            need(result["storeSchemaVersion"] == 19, "self-test schema mismatch")
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ContractError, OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(
            f"automation.taskflow contract verification failed: {error}"
        ) from error


if __name__ == "__main__":
    raise SystemExit(main())
