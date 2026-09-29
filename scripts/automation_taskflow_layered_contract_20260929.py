#!/usr/bin/env python3
"""Add layered schema-22 delivery truth to TaskFlow projections.

This source editor is intentionally temporary. The convergence workflow deletes
it after committing the resulting ordinary source/document changes.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "docs/modules/automation.taskflow"


def replace_once(body: str, old: str, new: str, label: str) -> str:
    count = body.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return body.replace(old, new, 1)


def update_technical() -> None:
    path = MODULE / "TECHNICAL.md"
    body = path.read_text(encoding="utf-8")
    body = body.replace(
        "**Durable store schema:** **v21**  \n",
        "**Durable store schema:** **v22**\n",
    )
    body = body.replace(
        "## 3. Durable schema v21 and retained history",
        "## 3. Durable schema v22 and retained history",
    )
    body = body.replace("schema 21 must not open", "schema 22 must not open")
    row21 = (
        "| 21 | indexed sparse unknown frontier | preserves migration 20's checksum "
        "and selects the indexed dispatch key |"
    )
    row22 = (
        "| 22 | durable Neural Circuit activation, receipts, choices and checkpoints | "
        "additive existing-owner state; unsettled owner contact prevents handoff |"
    )
    if row22 not in body:
        if row21 not in body:
            raise SystemExit("TECHNICAL migration-table anchor is missing")
        body = body.replace(row21, row21 + "\n" + row22, 1)
    body = body.replace(
        "**Status:** V1 durable owner and configured Agentd product composition are\n"
        "source-present. Exact-head/native/merged-tree execution, durable Circuit product\n"
        "integration, cross-host operation and selected-runtime evidence remain distinct\n"
        "unfinished work. No deployment or independent acceptance is asserted.",
        "**Status:** schema-22 durable Circuit source is present in the native build tree,\n"
        "while its normal Agentd DecisionCell/organ/Wait/Effect product port is still open.\n"
        "Exact-head and merged-tree execution, real process/two-host recovery, bounded\n"
        "TaskFlow startup, selected-host behavior and independent acceptance remain separate.",
    )
    body = body.replace(
        "The bounded Neural Circuit library adapter produces choice/organ/wait traces up\n"
        "to a wait or effect boundary. It is not yet the durable product interpreter.",
        "The bounded Neural Circuit adapter now has a schema-22 durable owner extension: it\n"
        "persists activation intent, reservation, exact outcome, choices and checkpoints.\n"
        "It still lacks the normal Agentd product port that supplies real owner components.",
    )
    body = body.replace(
        "| Neural Circuit activation adapter | `neural_circuit_runtime/` | library "
        "trace/boundary output; durable product continuation remains open |",
        "| Neural Circuit runtime adapter | `neural_circuit_runtime/` | bounded trace and "
        "boundary computation |\n"
        "| Durable Neural Circuit owner | `durable_neural_circuit.rs`, "
        "`durable_neural_circuit_recovery.rs` | schema-22 persistence; normal Agentd "
        "owner-port composition remains open |",
    )
    path.write_text(body, encoding="utf-8")


def update_slo() -> None:
    path = MODULE / "SLO.md"
    body = path.read_text(encoding="utf-8")
    body = body.replace("These schema-21 objectives", "These schema-22 objectives")
    path.write_text(body, encoding="utf-8")


def update_contract_projection() -> None:
    path = ROOT / "scripts/automation_taskflow_contract.py"
    body = path.read_text(encoding="utf-8")
    old = """COMPONENTS = (\"boundedAdmissionBatchComplete\", \"separateRecoveryBudgetComplete\",
              \"externalEffectProductCompositionComplete\",
              \"neuralCircuitRuntimeVerticalSliceComplete\", \"durableNeuralCircuitProductComplete\",
              \"crossHostRecoveryContractComplete\", \"crossHostRecoveryProductComplete\",
              \"selectedHostQualificationPathComplete\", \"independentAcceptanceVerificationPathComplete\")
"""
    new = """COMPONENTS = (\"boundedAdmissionBatchComplete\", \"separateRecoveryBudgetComplete\",
              \"externalEffectProductCompositionComplete\",
              \"neuralCircuitRuntimeVerticalSliceComplete\", \"durableNeuralCircuitSourceComplete\",
              \"durableNeuralCircuitBuildTreeComplete\", \"durableNeuralCircuitProductComplete\",
              \"crossHostRecoveryContractComplete\", \"signedCrossHostFenceReceiptComplete\",
              \"crossHostRecoveryProductComplete\", \"boundedOccurrenceStartupVerificationComplete\",
              \"boundedTaskFlowStartupVerificationComplete\", \"exactConsumedSelectedHostBindingComplete\",
              \"selectedHostQualificationPathComplete\", \"independentAcceptanceVerificationPathComplete\")
DELIVERY_STAGES = (\"schema22SourcePresent\", \"nativeBuildTreeIntegrated\",
                   \"normalProductEntrypointComposed\", \"exactSourceQualificationPassed\",
                   \"deterministicMergeQualificationPassed\", \"selectedHostBehaviorPassed\",
                   \"independentAcceptancePassed\")
"""
    if "DELIVERY_STAGES =" not in body:
        body = replace_once(body, old, new, "contract component list")

    old = """    gaps = implementation.get(\"remainingModuleGaps\")
    product_gaps = implementation.get(\"repositoryControlledProductCompositionGaps\")
"""
    new = """    stages = implementation.get(\"deliveryStages\")
    need(isinstance(stages, dict), \"implementation map deliveryStages is missing\")
    for key in DELIVERY_STAGES:
        need(type(stages.get(key)) is bool, f\"delivery stage {key} must be an explicit boolean\")
    need(stages[\"schema22SourcePresent\"], \"schema-22 source stage must reflect the current source\")
    need(stages[\"nativeBuildTreeIntegrated\"], \"schema-22 native build-tree stage is missing\")
    need(not stages[\"normalProductEntrypointComposed\"],
         \"source map cannot claim the missing normal Agentd Circuit entrypoint\")
    for key in (\"exactSourceQualificationPassed\", \"deterministicMergeQualificationPassed\",
                \"selectedHostBehaviorPassed\", \"independentAcceptancePassed\"):
        need(stages[key] is False, f\"source map cannot self-issue delivery stage {key}\")
    gaps = implementation.get(\"remainingModuleGaps\")
    product_gaps = implementation.get(\"repositoryControlledProductCompositionGaps\")
"""
    if "implementation map deliveryStages is missing" not in body:
        body = replace_once(body, old, new, "contract delivery-stage validation")

    old = """        \"claimBoundary\": {key: claims[key] for key in (*REPOSITORY, *COMPONENTS, *EXTERNAL)},
        \"remainingModuleGaps\": implementation[\"remainingModuleGaps\"],
"""
    new = """        \"claimBoundary\": {key: claims[key] for key in (*REPOSITORY, *COMPONENTS, *EXTERNAL)},
        \"deliveryStages\": {key: implementation[\"deliveryStages\"][key] for key in DELIVERY_STAGES},
        \"remainingModuleGaps\": implementation[\"remainingModuleGaps\"],
"""
    if '"deliveryStages": {key:' not in body:
        body = replace_once(body, old, new, "contract projection")

    old = """    lines += [f\"| `{key}` | `{str(value).lower()}` |\" for key, value in state[\"claimBoundary\"].items()]
    lines += [\"\", \"## Remaining module work\", \"\"]
"""
    new = """    lines += [f\"| `{key}` | `{str(value).lower()}` |\" for key, value in state[\"claimBoundary\"].items()]
    lines += [\"\", \"## Layered delivery status\", \"\", \"| Delivery stage | State |\", \"|---|---|\"]
    lines += [f\"| `{key}` | `{str(value).lower()}` |\" for key, value in state[\"deliveryStages\"].items()]
    lines += [\"\", \"## Remaining module work\", \"\"]
"""
    if "## Layered delivery status" not in body:
        body = replace_once(body, old, new, "contract status rendering")
    path.write_text(body, encoding="utf-8")


def main() -> int:
    update_technical()
    update_slo()
    update_contract_projection()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
