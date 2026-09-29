#!/usr/bin/env python3
"""Converge automation.taskflow source truth without upgrading evidence classes.

This one-shot editor runs after the reviewed source patch is applied. It records
what source exists and what remains unproved. It never turns source presence into
exact-head execution, selected-host behavior, two-host operation, independent
acceptance, activation, promotion, or release.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "docs/modules/automation.taskflow"
MAP = MODULE / "IMPLEMENTATION_MAP.json"
CONTRACT = MODULE / "SCHEMA_CONTRACT.json"
MAP_REL = str(MAP.relative_to(ROOT))


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"{path}: expected a JSON object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def git_object(path: str) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", f"HEAD:{path}"], cwd=ROOT, text=True
    ).strip()


def replace_once(body: str, old: str, new: str, label: str) -> str:
    count = body.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}: {old[:100]!r}")
    return body.replace(old, new, 1)


def append_once(path: Path, marker: str, section: str) -> None:
    body = path.read_text(encoding="utf-8")
    if marker not in body:
        path.write_text(body.rstrip() + "\n\n" + section.strip() + "\n", encoding="utf-8")


def upsert(rows: list[dict[str, Any]], row: dict[str, Any], key: str) -> None:
    for index, existing in enumerate(rows):
        if existing.get(key) == row[key]:
            rows[index] = row
            return
    rows.append(row)


def operation(
    name: str,
    path: str,
    symbol: str,
    semantics: str,
    tests: list[tuple[str, str, str]],
    delegated: list[tuple[str, str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "designOperation": name,
        "mappingClass": "owner_native",
        "ownerEntrypoint": {
            "role": "owner_entrypoint",
            "path": path,
            "symbol": symbol,
            "buildTarget": "codex-hepta-automation",
        },
        "delegatedCallees": [
            {
                "role": "delegated_callee",
                "path": item_path,
                "symbol": item_symbol,
                "ownerModule": owner,
                "buildTarget": (
                    "codex-hepta-agentd"
                    if owner == "runtime.agentd"
                    else "codex-hepta-automation"
                ),
            }
            for item_path, item_symbol, owner in (delegated or [])
        ],
        "tests": [
            {"path": test_path, "kind": kind, "command": command}
            for test_path, kind, command in tests
        ],
        "sourceSemantics": semantics,
        "operation": name,
        "nativeSymbol": symbol,
        "sourcePath": path,
        "sourcePathExists": True,
        "sourceBlob": git_object(path),
    }


def update_contract() -> None:
    contract = load(CONTRACT)
    contract["storeSchemaVersion"] = 22
    contract["crossHostRecoverySchemaVersion"] = 2
    migrations = [
        row for row in contract.get("migrationTopology", []) if row.get("version") != 22
    ]
    migrations.append(
        {
            "version": 22,
            "path": "codex-rs/hepta-automation/migrations/0022_durable_neural_circuit.sql",
            "blobSha": git_object(
                "codex-rs/hepta-automation/migrations/0022_durable_neural_circuit.sql"
            ),
            "requiredMarker": "CREATE TABLE neural_circuit_runs",
            "purpose": (
                "durable Neural Circuit activation intents, timer-fenced conservative "
                "reservations, immutable receipts, checkpoints and recorded choices; "
                "unsettled owner contact prevents writer handoff"
            ),
        }
    )
    contract["migrationTopology"] = sorted(migrations, key=lambda row: row["version"])
    composition = contract.setdefault("productComposition", {})
    composition.update(
        {
            "calendarV2Agentd": True,
            "externalEffectAgentdHost": True,
            "boundedAdmissionBatch": True,
            "separateRecoveryBudget": True,
            "neuralCircuitVerticalSlice": True,
            "durableNeuralCircuitOwner": True,
            "durableNeuralCircuitRecovery": True,
            "durableNeuralCircuitAgentdProductPort": False,
            "crossHostRecoveryManifest": True,
            "signedCrossHostFenceContract": True,
            "crossHostRecoveryController": False,
            "boundedOccurrenceStartupVerification": True,
            "boundedTaskFlowStartupVerification": False,
            "selectedHostQualificationPath": True,
            "selectedHostExecutionProved": False,
        }
    )
    write(CONTRACT, contract)


def update_map() -> None:
    data = load(MAP)
    data["stateOwnerDisposition"] = (
        "Owns schema-22 durable schedules, occurrences, TaskFlow runs/steps, timer "
        "epochs, provider evidence, persistent recovery sweeps, and durable Neural "
        "Circuit activation/choice/checkpoint evidence. It does not own model or organ "
        "execution, provider credentials, physical host fencing, deployment, or release."
    )
    operations = data.setdefault("operations", [])
    upsert(
        operations,
        operation(
            "execute_durable_neural_circuit",
            "codex-rs/hepta-automation/src/durable_neural_circuit.rs",
            "pub async fn execute_durable_neural_circuit_v1<",
            (
                "Persists exact circuit/event/profile identity and an immutable activation "
                "intent, reserves remaining cost before owner contact, commits exact choices "
                "and outcomes, and resumes Wait/Effect checkpoints without replaying a "
                "committed predecessor. Unknown owner contact remains recovery-required."
            ),
            [
                (
                    "codex-rs/hepta-automation/tests/durable_neural_circuit.rs",
                    "second_activation_outcome_identity_wait_effect_and_reopen",
                    "cargo test --locked -p codex-hepta-automation --test durable_neural_circuit",
                ),
                (
                    "codex-rs/hepta-automation/tests/durable_neural_circuit_recovery.rs",
                    "identity_bound_quarantine_and_recovery",
                    "cargo test --locked -p codex-hepta-automation --test durable_neural_circuit_recovery",
                ),
            ],
            [
                (
                    "codex-rs/hepta-automation/src/neural_circuit_runtime/runtime.rs",
                    "pub fn run_neural_circuit_v1<",
                    "automation.taskflow",
                )
            ],
        ),
        "designOperation",
    )
    upsert(
        operations,
        operation(
            "settle_durable_neural_circuit_recovery",
            "codex-rs/hepta-automation/src/durable_neural_circuit_recovery.rs",
            "pub async fn settle_durable_neural_circuit_recovery_v1<",
            (
                "Validates exact immutable input and current timer/TaskFlow fencing before "
                "re-arming only the original reservation. The recovery observer settles an "
                "identity-bound owner result; this path never calls DecisionCell, organ, or "
                "wait code a second time."
            ),
            [
                (
                    "codex-rs/hepta-automation/tests/durable_neural_circuit_recovery.rs",
                    "wrong_input_preserves_quarantine_and_exact_observation_settles",
                    "cargo test --locked -p codex-hepta-automation --test durable_neural_circuit_recovery",
                )
            ],
        ),
        "designOperation",
    )
    upsert(
        operations,
        operation(
            "verify_occurrence_startup",
            "codex-rs/hepta-automation/src/lifecycle_bounded.rs",
            "pub(crate) async fn verify_occurrence_store(",
            (
                "Verifies every occurrence in fixed-size keyset pages and rejects owner, "
                "identity, state, cursor, digest, or later-page corruption. This bounds one "
                "occurrence page, not the still-growing TaskFlow definition/run/event audit."
            ),
            [
                (
                    "codex-rs/hepta-automation/src/lifecycle_bounded.rs",
                    "later_page_corruption_rejects_bounded_occurrence_scan",
                    "cargo test --locked -p codex-hepta-automation bounded_startup_scan_rejects_corruption_after_the_first_page",
                )
            ],
        ),
        "designOperation",
    )
    upsert(
        operations,
        operation(
            "admit_cross_host_recovery",
            "codex-rs/hepta-automation/src/cross_host_recovery.rs",
            "pub fn admit_target(",
            (
                "Consumes a still-current Ed25519-verified controller fence and validates "
                "owner, exact checkpoint, source/target host identity, schema, and exactly "
                "the next writer epoch. It does not itself transport bytes, fence the source "
                "host, install a target writer, or prove a two-host exercise."
            ),
            [
                (
                    "codex-rs/hepta-automation/src/external_host_fence.rs",
                    "signed_host_fence_tamper_expiry_and_epoch",
                    "cargo test --locked -p codex-hepta-automation external_host_fence",
                ),
                (
                    "codex-rs/hepta-automation/src/cross_host_recovery.rs",
                    "target_tuple_and_current_fence_admission",
                    "cargo test --locked -p codex-hepta-automation cross_host_recovery",
                ),
            ],
        ),
        "designOperation",
    )

    gaps = [
        (
            "The durable Neural Circuit owner is in the native build tree, but no normal "
            "Agentd control/product port yet composes real DecisionCell, organ, Wait, and "
            "authorized Effect owners. Source fixtures are not that product entrypoint."
        ),
        (
            "Process-level crash cuts must recover a later Wait/Effect activation from an "
            "owner-issued observation without recomputing an outcome in the test process."
        ),
        (
            "Cross-host recovery still requires an operated controller that physically "
            "fences the source, transfers the exact checkpoint, advances/installs the target "
            "writer, and proves the predecessor can no longer write in a real two-host run."
        ),
        (
            "TaskFlow definition/run/event startup verification still grows with retained "
            "history. It needs bounded paging with one coherent snapshot plus native "
            "long-retention recovery, memory, I/O, and latency measurements."
        ),
        (
            "Exact source-head and deterministic synthetic-merge formatting, compile, "
            "strict Clippy, native/product tests, selected-host behavior, and independent "
            "acceptance require separate terminal-success immutable receipts."
        ),
    ]
    data["remainingModuleGaps"] = gaps
    data["repositoryControlledProductCompositionGaps"] = gaps[:4]
    claims = data.setdefault("claimBoundary", {})
    claims.update(
        {
            "durableStoreSchemaVersion": 22,
            "boundedAdmissionBatchComplete": True,
            "separateRecoveryBudgetComplete": True,
            "externalEffectProductCompositionComplete": True,
            "neuralCircuitRuntimeVerticalSliceComplete": True,
            "durableNeuralCircuitSourceComplete": True,
            "durableNeuralCircuitBuildTreeComplete": True,
            "durableNeuralCircuitProductComplete": False,
            "crossHostRecoveryContractComplete": True,
            "crossHostRecoveryProductComplete": False,
            "selectedHostQualificationPathComplete": True,
            "independentAcceptanceVerificationPathComplete": True,
            "boundedOccurrenceStartupVerificationComplete": True,
            "boundedTaskFlowStartupVerificationComplete": False,
            "exactConsumedSelectedHostBindingComplete": False,
            "signedCrossHostFenceReceiptComplete": True,
            "repositoryControlledSourceBoundaryGapsClosed": False,
            "repositoryControlledProductCompositionGapsClosed": False,
            "repositoryControlledDocumentationGapsClosed": True,
            "nativeSourceComplete": False,
            "nativeComposedCallerComplete": False,
            "deploymentQualificationComplete": False,
            "productExecutionProved": False,
            "independentAcceptance": False,
            "activation": False,
            "promotion": False,
            "release": False,
            "claimCeiling": (
                "Schema-22 source and its native build-tree wiring are present. Normal "
                "Agentd durable-Circuit composition, real process/two-host recovery, bounded "
                "TaskFlow startup, exact candidate execution, selected-host behavior, and "
                "independent release decisions remain open evidence classes."
            ),
        }
    )
    data["deliveryStages"] = {
        "schema22SourcePresent": True,
        "nativeBuildTreeIntegrated": True,
        "normalProductEntrypointComposed": False,
        "exactSourceQualificationPassed": False,
        "deterministicMergeQualificationPassed": False,
        "selectedHostBehaviorPassed": False,
        "independentAcceptancePassed": False,
    }
    data["nativeSourceMappingComplete"] = True
    data["productionImplementation"] = False
    data["productCallerState"] = (
        "agentd_scheduler_calendar_and_authorized_effect_host_composed;_"
        "schema22_durable_circuit_owner_is_build_integrated_but_has_no_normal_agentd_port"
    )
    data["productionWriterState"] = (
        "schema_v22_durable_owner_with_fair_recovery_and_circuit_evidence;_"
        "taskflow_long_history_and_exact_candidate_execution_pending"
    )

    paths = set(data.get("observedSourcePaths", []))
    paths.update(
        {
            ".github/workflows/automation-taskflow-selected-host.yml",
            "codex-rs/hepta-agentd/src/automation_effect_host.rs",
            "codex-rs/hepta-agentd/src/state_control.rs",
            "codex-rs/hepta-agentd/tests/automation_selected_host.rs",
            "codex-rs/hepta-automation/migrations/0022_durable_neural_circuit.sql",
            "codex-rs/hepta-automation/src/cross_host_recovery.rs",
            "codex-rs/hepta-automation/src/durable_neural_circuit.rs",
            "codex-rs/hepta-automation/src/durable_neural_circuit_recovery.rs",
            "codex-rs/hepta-automation/src/external_host_fence.rs",
            "codex-rs/hepta-automation/src/lifecycle_bounded.rs",
            "codex-rs/hepta-automation/src/lib.rs",
            "codex-rs/hepta-automation/src/taskflow.rs",
            "codex-rs/hepta-automation/tests/durable_neural_circuit.rs",
            "codex-rs/hepta-automation/tests/durable_neural_circuit_recovery.rs",
            "codex-rs/hepta-automation/tests/selected_host_profile.rs",
            "scripts/automation_taskflow_selected_host.py",
            "scripts/test_automation_taskflow_selected_host.py",
        }
    )
    data["observedSourcePaths"] = sorted(paths)
    objects = {row.get("path"): row for row in data.setdefault("sourceObjects", [])}
    for path in sorted(paths):
        absolute = ROOT / path
        if absolute.is_file() and path != MAP_REL:
            objects[path] = {"path": path, "object": git_object(path)}
    data["sourceObjects"] = sorted(objects.values(), key=lambda row: row["path"])
    evidence = data.setdefault(
        "exactSourceEvidence", {"kind": "path_blob_manifest_v1", "entries": []}
    )
    entries = {row.get("path"): row for row in evidence.setdefault("entries", [])}
    for row in operations:
        path = row.get("sourcePath")
        if path and (ROOT / path).is_file():
            row["sourceBlob"] = git_object(path)
            entries[path] = {"path": path, "blobSha": git_object(path)}
    evidence["entries"] = sorted(entries.values(), key=lambda row: row["path"])
    write(MAP, data)


def update_contract_markers() -> None:
    path = ROOT / "scripts/automation_taskflow_contract.py"
    body = path.read_text(encoding="utf-8")
    anchor = (
        '    "codex-rs/hepta-automation/src/cross_host_recovery.rs": '
        '("observed_owner_agent_id: &AgentId", "AgentId::parse(&self.owner_agent_id)"),\n'
    )
    additions = (
        '    "codex-rs/hepta-automation/src/durable_neural_circuit.rs": '
        '("execute_durable_neural_circuit_v1", "begin_circuit_activation", '
        '"check_circuit_taskflow_fence_tx", "committed circuit outcome has no activation receipt"),\n'
        '    "codex-rs/hepta-automation/src/durable_neural_circuit_recovery.rs": '
        '("settle_durable_neural_circuit_recovery_v1", "load_exact_circuit", '
        '"recovery reservation lost its activation fence"),\n'
        '    "codex-rs/hepta-automation/migrations/0022_durable_neural_circuit.sql": '
        '("CREATE TABLE neural_circuit_runs", "CREATE TABLE neural_circuit_activation_intents", '
        '"CREATE TABLE neural_circuit_activation_receipts", "CREATE TABLE neural_circuit_recorded_choices"),\n'
        '    "codex-rs/hepta-automation/src/lifecycle_bounded.rs": '
        '("OCCURRENCE_VERIFY_PAGE_SIZE", "WHERE task_id > ?", '
        '"bounded_startup_scan_rejects_corruption_after_the_first_page"),\n'
        '    "codex-rs/hepta-automation/src/external_host_fence.rs": '
        '("VerifiedAutomationHostFenceV1", "verify_strict", "expires_at_ms"),\n'
    )
    if "committed circuit outcome has no activation receipt" not in body:
        if anchor not in body:
            raise SystemExit("automation contract source-marker anchor is missing")
        body = body.replace(anchor, anchor + additions, 1)
    workflow_pattern = re.compile(
        r'    "\.github/workflows/automation-taskflow-selected-host\.yml": \([^\n]+\),\n'
    )
    workflow_marker = (
        '    ".github/workflows/automation-taskflow-selected-host.yml": '
        '("hepta-automation-selected-host", "AUTOMATION_TIMEZONE_PROFILE_FILE", '
        '"--test durable_neural_circuit", "--test durable_neural_circuit_recovery", '
        '"automation-taskflow-selected-host-receipt.json"),\n'
    )
    if workflow_pattern.search(body):
        body = workflow_pattern.sub(workflow_marker, body, count=1)
    path.write_text(body, encoding="utf-8")


def update_documents() -> None:
    technical = MODULE / "TECHNICAL.md"
    body = technical.read_text(encoding="utf-8")
    body = re.sub(
        r"\*\*Durable store schema:\*\* \*\*v\d+\*\*",
        "**Durable store schema:** **v22**",
        body,
        count=1,
    )
    body = body.replace("## 3. Durable schema v21 and retained history", "## 3. Durable schema v22 and retained history")
    body = body.replace("schema 21 must not open", "schema 22 must not open")
    if "| 22 | durable Neural Circuit" not in body:
        row21 = "| 21 | indexed sparse unknown frontier | preserves migration 20's checksum and selects the indexed dispatch key |"
        row22 = row21 + "\n| 22 | durable Neural Circuit activation, receipts, choices and checkpoints | additive existing-owner state; unsettled owner contact prevents handoff |"
        if row21 in body:
            body = body.replace(row21, row22, 1)
    old_status = (
        "**Status:** V1 durable owner and configured Agentd product composition are\n"
        "source-present. Exact-head/native/merged-tree execution, durable Circuit product\n"
        "integration, cross-host operation and selected-runtime evidence remain distinct\n"
        "unfinished work. No deployment or independent acceptance is asserted."
    )
    new_status = (
        "**Status:** schema-22 durable Circuit source is present in the native build tree,\n"
        "while its normal Agentd DecisionCell/organ/Wait/Effect product port is still open.\n"
        "Exact-head and merged-tree execution, real process/two-host recovery, bounded\n"
        "TaskFlow startup, selected-host behavior and independent acceptance remain separate."
    )
    if old_status in body:
        body = body.replace(old_status, new_status, 1)
    old_owner = (
        "The bounded Neural Circuit library adapter produces choice/organ/wait traces up\n"
        "to a wait or effect boundary. It is not yet the durable product interpreter."
    )
    new_owner = (
        "The bounded Neural Circuit adapter now has a schema-22 durable owner extension: it\n"
        "persists activation intent, reservation, exact outcome, choices and checkpoints.\n"
        "It still lacks the normal Agentd product port that supplies real owner components."
    )
    if old_owner in body:
        body = body.replace(old_owner, new_owner, 1)
    old_row = "| Neural Circuit activation adapter | `neural_circuit_runtime/` | library trace/boundary output; durable product continuation remains open |"
    new_rows = (
        "| Neural Circuit runtime adapter | `neural_circuit_runtime/` | bounded trace and boundary computation |\n"
        "| Durable Neural Circuit owner | `durable_neural_circuit.rs`, `durable_neural_circuit_recovery.rs` | schema-22 persistence; normal Agentd owner-port composition remains open |"
    )
    if old_row in body:
        body = body.replace(old_row, new_rows, 1)
    append_once(
        technical,
        "## 12. Schema-22 layered delivery status",
        """
## 12. Schema-22 layered delivery status

The current evidence layers are deliberately separate:

```text
source present                         yes
native build-tree wiring               yes
normal Agentd Circuit product port     no
exact source-head qualification        no terminal receipt yet
deterministic merge qualification      no terminal receipt yet
selected-host behavior                 not proved
independent acceptance                 not issued
```

The source closes the reviewed old-outcome/new-activation, pre-call fencing,
wrong-input recovery mutation, terminal-projection mismatch and selected-test
selection counterexamples. It does not convert library fixtures into the missing
Agentd product entry, process recovery, physical two-host fencing or long-history
capacity evidence.
""",
    )

    runbook = MODULE / "MIGRATION_V19_RUNBOOK.md"
    body = runbook.read_text(encoding="utf-8")
    body = body.replace("current native owner schema is **21**", "current native owner schema is **22**")
    if "| 22 | `0022_durable_neural_circuit.sql`" not in body:
        row21 = "| 21 | `0021_recovery_frontier_indexes.sql` | indexed sparse unknown frontier |"
        if row21 in body:
            body = body.replace(
                row21,
                row21 + "\n| 22 | `0022_durable_neural_circuit.sql` | durable activation intents, reservations, receipts, choices and checkpoints |",
                1,
            )
    body = body.replace("schema-21-capable", "schema-22-capable")
    body = body.replace("open schema 21", "open schema 22")
    runbook.write_text(body, encoding="utf-8")

    release = MODULE / "RELEASE_QUALIFICATION.md"
    body = release.read_text(encoding="utf-8")
    body = body.replace("current store schema is 21", "current store schema is 22")
    old = (
        "Durable Circuit ingress/activation, committed-choice replay, conserved budgets and\n"
        "Wait/Effect continuation must be connected to the existing TaskFlow owner and\n"
        "actual product ports."
    )
    new = (
        "Schema-22 durable Circuit ingress, activation, choice evidence, reservation and\n"
        "Wait/Effect checkpoints are source-present. They still must be composed through a\n"
        "normal Agentd product port with real DecisionCell, organ, Wait and authorized Effect\n"
        "owners, then exercised across process failure without recomputing owner outcomes."
    )
    if old in body:
        body = body.replace(old, new, 1)
    release.write_text(body, encoding="utf-8")

    slo = MODULE / "SLO.md"
    body = slo.read_text(encoding="utf-8")
    body = body.replace("These schema-21 objectives", "These schema-22 objectives")
    append_once(
        slo,
        "## Layered capacity evidence",
        """
## Layered capacity evidence

Occurrence startup uses fixed 256-row keyset pages. TaskFlow definition/run/event
verification is not yet bounded end to end and must not inherit that completion
claim. Capacity acceptance must bind retained row/event counts, one coherent read
snapshot, wall time, peak RSS, SQLite I/O/busy work, crash/reopen behavior and the
oldest unresolved age on the selected native host.
""",
    )
    append_once(
        MODULE / "REVIEW_REMEDIATION_2026_09_27.md",
        "## Schema-22 source-correctness continuation",
        """
## Schema-22 source-correctness continuation

The durable owner now rejects replay of an earlier outcome under a newer activation,
checks the current timer and exact TaskFlow fence before owner contact and commit,
validates immutable recovery input before re-arming quarantine, and refuses to
acknowledge a conflicting TaskFlow terminal projection. The selected-host workflow
names both durable Circuit integration-test targets explicitly.

These facts establish source presence only. The normal Agentd Circuit product port,
process-level owner recovery, operated two-host transfer/fencing, bounded TaskFlow
startup, exact-candidate execution and external acceptance remain open.
""",
    )


def main() -> int:
    update_contract()
    update_map()
    update_contract_markers()
    update_documents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
