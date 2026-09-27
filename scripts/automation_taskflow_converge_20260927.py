#!/usr/bin/env python3
"""One-shot semantic convergence for automation.taskflow.

This script updates source declarations only. It never issues deployment,
independent acceptance, activation, promotion, or release evidence. The
companion temporary workflow commits the semantic delta, rebinds exact Git
objects from the clean commit, verifies the repository gates, and then removes
both one-shot files.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "docs/modules/automation.taskflow"
MAP = MODULE / "IMPLEMENTATION_MAP.json"
CONTRACT = MODULE / "SCHEMA_CONTRACT.json"


def git_object(path: str) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", f"HEAD:{path}"], cwd=ROOT, text=True
    ).strip()


def replace_once(path: Path, old: str, new: str) -> None:
    body = path.read_text(encoding="utf-8")
    count = body.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:80]!r}")
    path.write_text(body.replace(old, new, 1), encoding="utf-8")


def append_unique(rows: list[dict], row: dict, key: str) -> None:
    value = row[key]
    for index, existing in enumerate(rows):
        if existing.get(key) == value:
            rows[index] = row
            return
    rows.append(row)


def update_contract() -> None:
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    data["storeSchemaVersion"] = 22
    migrations = [row for row in data["migrationTopology"] if row.get("version") != 22]
    migrations.append(
        {
            "version": 22,
            "path": "codex-rs/hepta-automation/migrations/0022_durable_neural_circuit.sql",
            "blobSha": git_object(
                "codex-rs/hepta-automation/migrations/0022_durable_neural_circuit.sql"
            ),
            "requiredMarker": "CREATE TABLE neural_circuit_runs",
            "purpose": (
                "durable Neural Circuit activation intents, conserved reservations, "
                "immutable outcomes, checkpoints and recorded choices"
            ),
        }
    )
    data["migrationTopology"] = sorted(migrations, key=lambda row: row["version"])
    composition = data.setdefault("productComposition", {})
    composition.update(
        {
            "durableNeuralCircuitOwner": True,
            "durableNeuralCircuitRecovery": True,
            "boundedNativeStartupVerification": False,
            "selectedHostRuntimeBinding": False,
            "crossHostRecoveryController": False,
        }
    )
    CONTRACT.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def operation(
    name: str,
    path: str,
    symbol: str,
    semantics: str,
    tests: list[tuple[str, str, str]],
    delegated: list[tuple[str, str, str]] | None = None,
) -> dict:
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
                    "codex-hepta-agentd" if owner == "runtime.agentd" else "codex-hepta-automation"
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


def update_map() -> None:
    data = json.loads(MAP.read_text(encoding="utf-8"))
    data["stateOwnerDisposition"] = (
        "Owns schema-22 durable V1 schedules, occurrences, TaskFlow runs/steps, "
        "timer epochs, provider evidence, fair recovery sweeps and durable Neural "
        "Circuit activation/choice/checkpoint state without owning model, organ, "
        "provider, deployment or release authority."
    )
    operations = data.setdefault("operations", [])
    append_unique(
        operations,
        operation(
            "execute_durable_neural_circuit",
            "codex-rs/hepta-automation/src/durable_neural_circuit.rs",
            "pub async fn execute_durable_neural_circuit_v1<",
            (
                "Persists ingress and activation identity, reserves the conserved cost "
                "budget before owner calls, commits exact choices/outcomes, and resumes "
                "Wait/Effect boundaries from validated checkpoints without replaying "
                "historical DecisionCell or organ work."
            ),
            [
                (
                    "codex-rs/hepta-automation/tests/durable_neural_circuit.rs",
                    "durable_activation_choice_budget_wait_effect_and_reopen",
                    "just test --locked -p codex-hepta-automation --test durable_neural_circuit",
                ),
                (
                    "codex-rs/hepta-automation/tests/durable_neural_circuit_recovery.rs",
                    "unknown_owner_outcome_quarantine_and_identity_bound_settlement",
                    "just test --locked -p codex-hepta-automation --test durable_neural_circuit_recovery",
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
    append_unique(
        operations,
        operation(
            "settle_durable_neural_circuit_recovery",
            "codex-rs/hepta-automation/src/durable_neural_circuit_recovery.rs",
            "pub async fn settle_durable_neural_circuit_recovery_v1<",
            (
                "Re-arms only the immutable original reservation for an explicitly "
                "quarantined activation and accepts an identity-bound owner observation; "
                "it never allocates a new activation or calls the DecisionCell/organ/wait "
                "owner again."
            ),
            [
                (
                    "codex-rs/hepta-automation/tests/durable_neural_circuit_recovery.rs",
                    "close_reopen_quarantine_later_observation_and_terminal_settlement",
                    "just test --locked -p codex-hepta-automation --test durable_neural_circuit_recovery",
                )
            ],
        ),
        "designOperation",
    )
    append_unique(
        operations,
        operation(
            "admit_cross_host_recovery",
            "codex-rs/hepta-automation/src/cross_host_recovery.rs",
            "pub fn admit_target(",
            (
                "Validates owner, schema, exact checkpoint, host identity and monotone "
                "next writer epoch. Physical transfer and independently enforced source "
                "fencing remain deployment-controller responsibilities."
            ),
            [
                (
                    "codex-rs/hepta-automation/src/cross_host_recovery.rs",
                    "owner_checkpoint_fence_and_next_epoch_contract",
                    "just test --locked -p codex-hepta-automation cross_host_recovery",
                ),
                (
                    "scripts/test_automation_taskflow_checkpoint.py",
                    "create_only_checkpoint_staged_restore_and_tamper_rejection",
                    "python3 -m unittest -v scripts/test_automation_taskflow_checkpoint.py",
                ),
            ],
        ),
        "designOperation",
    )

    data["remainingModuleGaps"] = [
        (
            "Exact-head and deterministic synthetic-merge formatting, compile, strict "
            "Clippy, native owner tests and product qualification must pass on this "
            "revision; source presence and Python fixtures are not those receipts."
        ),
        (
            "The selected-host path must bind tests to the exact consumed timezone "
            "profile, provider configuration, final-use trust/revocation bytes and native "
            "SQLite runtime; metadata-only digests are insufficient."
        ),
        (
            "Cross-host recovery still requires an independently verified external source "
            "fence, actual checkpoint transport, target writer installation and a two-host "
            "fault/recovery receipt."
        ),
        (
            "Native startup validation still materializes occurrence/run pages and each "
            "individual TaskFlow event chain; bounded native paging and long-retention "
            "selected-host capacity evidence remain required."
        ),
    ]
    data["repositoryControlledProductCompositionGaps"] = [
        data["remainingModuleGaps"][1],
        data["remainingModuleGaps"][2],
    ]
    claims = data.setdefault("claimBoundary", {})
    claims.update(
        {
            "durableStoreSchemaVersion": 22,
            "boundedAdmissionBatchComplete": True,
            "separateRecoveryBudgetComplete": True,
            "externalEffectProductCompositionComplete": True,
            "neuralCircuitRuntimeVerticalSliceComplete": True,
            "durableNeuralCircuitProductComplete": True,
            "crossHostRecoveryContractComplete": True,
            "crossHostRecoveryProductComplete": False,
            "selectedHostQualificationPathComplete": True,
            "independentAcceptanceVerificationPathComplete": True,
            "repositoryControlledSourceBoundaryGapsClosed": False,
            "repositoryControlledProductCompositionGapsClosed": False,
            "repositoryControlledDocumentationGapsClosed": True,
            "nativeSourceComplete": False,
            "nativeComposedCallerComplete": True,
            "productExecutionProved": False,
            "deploymentQualificationComplete": False,
            "independentAcceptance": False,
            "activation": False,
            "promotion": False,
            "release": False,
            "claimCeiling": (
                "Schema-22 repository source includes fair recovery, exact error/cancel "
                "boundaries, durable Neural Circuit activation/continuation, authorized "
                "effects and checkpoint contracts. Native exact-candidate execution, "
                "selected-host runtime binding, external two-host fencing, independent "
                "acceptance and release remain separate gates."
            ),
        }
    )
    data["nativeSourceMappingComplete"] = True
    data["productionImplementation"] = False
    data["productCallerState"] = (
        "agentd_scheduler_calendar_effect_host_and_schema22_durable_circuit_owner_"
        "source_composed_selected_host_and_cross_host_execution_pending"
    )
    data["productionWriterState"] = (
        "schema_v22_durable_owner_with_fair_recovery_and_circuit_activation_"
        "exact_candidate_execution_pending"
    )

    paths = set(data.get("observedSourcePaths", []))
    paths.update(
        {
            "codex-rs/hepta-automation/migrations/0022_durable_neural_circuit.sql",
            "codex-rs/hepta-automation/src/durable_neural_circuit.rs",
            "codex-rs/hepta-automation/src/durable_neural_circuit_recovery.rs",
            "codex-rs/hepta-automation/tests/durable_neural_circuit.rs",
            "codex-rs/hepta-automation/tests/durable_neural_circuit_recovery.rs",
            "scripts/automation_taskflow_checkpoint.py",
            "scripts/test_automation_taskflow_checkpoint.py",
            "docs/modules/automation.taskflow/REVIEW_REMEDIATION_2026_09_27.md",
        }
    )
    data["observedSourcePaths"] = sorted(paths)

    objects = data.setdefault("sourceObjects", [])
    existing = {row.get("path") for row in objects}
    for path in sorted(paths):
        if path == "docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json":
            continue
        if not (ROOT / path).exists() or path in existing:
            continue
        objects.append({"path": path, "object": git_object(path)})
    objects.sort(key=lambda row: row["path"])

    evidence = data.setdefault(
        "exactSourceEvidence", {"kind": "path_blob_manifest_v1", "entries": []}
    )
    entries = evidence.setdefault("entries", [])
    evidence_paths = {row.get("path") for row in entries}
    for op in operations:
        path = op.get("sourcePath")
        if path and (ROOT / path).is_file() and path not in evidence_paths:
            entries.append({"path": path, "blobSha": git_object(path)})
            evidence_paths.add(path)
    entries.sort(key=lambda row: row["path"])

    MAP.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def update_contract_markers() -> None:
    path = ROOT / "scripts/automation_taskflow_contract.py"
    body = path.read_text(encoding="utf-8")
    anchor = (
        '    "codex-rs/hepta-automation/src/cross_host_recovery.rs": '
        '("observed_owner_agent_id: &AgentId", "AgentId::parse(&self.owner_agent_id)"),\n'
    )
    addition = anchor + (
        '    "codex-rs/hepta-automation/src/durable_neural_circuit.rs": '
        '("execute_durable_neural_circuit_v1", "begin_circuit_activation", '
        '"checkpoint_for_circuit_outcome_v1", "RecoveryRequired"),\n'
        '    "codex-rs/hepta-automation/src/durable_neural_circuit_recovery.rs": '
        '("settle_durable_neural_circuit_recovery_v1", '
        '"recovery_required", "activation reservation lost its activation fence"),\n'
        '    "codex-rs/hepta-automation/migrations/0022_durable_neural_circuit.sql": '
        '("CREATE TABLE neural_circuit_runs", '
        '"CREATE TABLE neural_circuit_activation_intents", '
        '"CREATE TABLE neural_circuit_activation_outcomes"),\n'
    )
    if "execute_durable_neural_circuit_v1" not in body:
        if anchor not in body:
            raise SystemExit("contract source-marker anchor is missing")
        body = body.replace(anchor, addition, 1)
    path.write_text(body, encoding="utf-8")


def update_documents() -> None:
    technical = MODULE / "TECHNICAL.md"
    body = technical.read_text(encoding="utf-8")
    body = re.sub(r"\*\*Durable store schema:\*\* \*\*v\d+\*\*", "**Durable store schema:** **v22**", body, count=1)
    body = body.replace("Schema v19 is the convergence head:", "Schema v22 is the current additive convergence head:")
    durable = """
### Durable Neural Circuit owner (schema 22)

The existing TaskFlow owner now persists circuit ingress identity, an activation
intent and a conservative cost reservation before DecisionCell, organ or wait
contact. Immutable outcome and recorded-choice rows bind the exact runtime
profile and checkpoint. Wait and Effect continuations resume from that checkpoint
without rerunning historical choices or organ work. A crash after intent but
before an owner outcome blocks automatic replay; only an identity-bound recovery
observation can settle or explicitly quarantine the original activation.

This is repository source composition, not deployment or efficacy evidence. The
Circuit owner still cannot issue final-use authority, select a provider, mutate
organ-private state, activate topology or grant release.
"""
    marker = "## 7. Calendar V2 and timezone evidence"
    if "### Durable Neural Circuit owner (schema 22)" not in body:
        if marker not in body:
            raise SystemExit("TECHNICAL insertion marker is missing")
        body = body.replace(marker, durable + "\n" + marker, 1)
    technical.write_text(body, encoding="utf-8")

    runbook = MODULE / "MIGRATION_V19_RUNBOOK.md"
    body = runbook.read_text(encoding="utf-8")
    body = body.replace("schema v19 migration and recovery runbook", "schema v22 migration and recovery runbook", 1)
    body = body.replace("v17–v19", "v17–v22")
    if "| 22 | `0022_durable_neural_circuit.sql`" not in body:
        marker = "| 21 |"
        lines = body.splitlines()
        insert_at = next((i + 1 for i, line in enumerate(lines) if line.startswith(marker)), None)
        if insert_at is None:
            raise SystemExit("runbook migration table marker is missing")
        lines.insert(insert_at, "| 22 | `0022_durable_neural_circuit.sql` | durable activation intents, reservations, outcomes, choices and checkpoints |")
        body = "\n".join(lines) + "\n"
    body = body.replace("schema-v19-capable", "schema-v22-capable")
    body = body.replace("through 19", "through 22")
    body = body.replace("schema 19", "schema 22")
    body = body.replace("schema-v19-aware", "schema-v22-aware")
    runbook.write_text(body, encoding="utf-8")

    dossier = ROOT / "qualification/module-execution-dossiers/detail/automation.taskflow.md"
    body = dossier.read_text(encoding="utf-8")
    body = body.replace("schema v19 implementation design", "schema v22 implementation design", 1)
    body = body.replace("schema v19 durable owner", "schema v22 durable owner")
    body = body.replace("`AUTOMATION_SCHEMA_VERSION` is 19", "`AUTOMATION_SCHEMA_VERSION` is 22")
    if "## 6. Durable Neural Circuit execution" not in body:
        body = body.replace(
            "## 6. Neural Circuit vertical slice",
            "## 6. Durable Neural Circuit execution",
            1,
        )
        body = body.replace(
            "Candidate v1 remains an acyclic bounded TaskFlow compilation.",
            "Candidate v1 remains an acyclic bounded TaskFlow compilation. Schema 22 persists each admitted activation, conservative budget reservation, immutable owner outcome, recorded choice and resumable Wait/Effect checkpoint on the existing TaskFlow run.",
            1,
        )
    dossier.write_text(body, encoding="utf-8")

    review = MODULE / "REVIEW_REMEDIATION_2026_09_27.md"
    body = review.read_text(encoding="utf-8")
    body += """

## Schema-22 continuation

Subsequent ordinary commits added migration 22 and the existing-owner durable
Neural Circuit path. Ingress, activation intent, conservative reservation,
immutable outcome/choice evidence and Wait/Effect checkpoints are now persisted.
An unknown owner result blocks automatic replay and is settled only by an
identity-bound recovery observer; quarantined activation recovery reuses the
original reservation and never calls DecisionCell, organ or wait code again.

These source changes remove the earlier durable-circuit repository gap. Exact-head
and synthetic-merge native qualification, selected-host runtime/configuration
binding, externally fenced two-host recovery, independent acceptance, activation,
promotion and release remain separate and false until their own receipts exist.
"""
    review.write_text(body, encoding="utf-8")


def remove_obsolete_one_shots() -> None:
    for relative in (
        "scripts/automation_taskflow_fact_sync.py",
        "scripts/automation_taskflow_qualification_repair.py",
    ):
        path = ROOT / relative
        if path.exists():
            path.unlink()


def main() -> None:
    update_contract()
    update_map()
    update_contract_markers()
    update_documents()
    remove_obsolete_one_shots()


if __name__ == "__main__":
    main()
