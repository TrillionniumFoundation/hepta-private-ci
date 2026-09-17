#!/usr/bin/env python3
"""Fail closed on learning.eval qualification-status drift.

The Lane E implementation matrix is the machine-readable status authority for
repository-controlled state. Module-local maps and prose may describe source
inventory or contracts, but they may not upgrade production composition,
future-calendar evidence, independent acceptance, activation, or release.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json"
MODULE_MAP_PATH = ROOT / "docs/modules/learning.eval/IMPLEMENTATION_MAP.json"

EXPECTED_EXTERNAL = {
    "authenticated_live_input_adapters_and_durable_product_scheduler",
    "real_future_calendar_windows_and_independent_snapshots",
    "retention_change_point_privacy_power_and_unlearning_receipts",
    "separate_selector_operator_canary_promotion_and_release_decisions",
}
REQUIRED_OPEN_GATES = {
    "RDY-EXT-001",
    "RDY-EXT-003",
    "RDY-EXT-004",
    "RDY-EXT-008",
    "RDY-EXT-009",
}
NON_AUTHORITY_DOCS = [
    ROOT / "docs/modules/learning.eval/TECHNICAL.md",
    ROOT / "docs/readiness/LEARNING_EVALUATION_EXECUTION.md",
    ROOT / "codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md",
    ROOT / "codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md",
    ROOT / "qualification/module-execution-dossiers/detail/learning.eval.md",
]
FORBIDDEN_UPGRADES = (
    "learning.eval production qualified",
    "learning.eval production-qualified",
    "learning.eval release complete",
    "learning.eval activation complete",
    "learning.eval independently accepted",
)


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AssertionError(f"cannot parse {path.relative_to(ROOT)}: {error}") from error
    if not isinstance(value, dict):
        raise AssertionError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    matrix = load(MATRIX_PATH)
    require(
        matrix.get("schema") == "hepta.lane-e-implementation-matrix.v1",
        "unexpected Lane E implementation-matrix schema",
    )
    require(matrix.get("authorityDelta") == "none", "Lane E must grant no authority")
    require(
        matrix.get("capabilityClosureState") == "external_evidence_required",
        "capability closure must remain external-evidence-required",
    )

    modules = {
        item.get("module"): item
        for item in matrix.get("modules", [])
        if isinstance(item, dict) and isinstance(item.get("module"), str)
    }
    evaluation = modules.get("learning.eval")
    require(isinstance(evaluation, dict), "learning.eval is missing from the Lane E matrix")
    require(
        evaluation.get("implementationState") == "source_implemented_ci_pending",
        "learning.eval repository state must remain source_implemented_ci_pending until exact-head CI closes",
    )
    require(
        evaluation.get("remainingRepositoryGaps") == [],
        "repository-controlled learning.eval gaps must be represented as code/CI failures, not prose debt",
    )
    external = evaluation.get("remainingExternalEvidence")
    require(isinstance(external, list), "learning.eval external evidence must be an array")
    require(
        EXPECTED_EXTERNAL.issubset(set(external)),
        "learning.eval external-evidence boundary lost one or more required gates",
    )

    gates = {
        item.get("id"): item
        for item in matrix.get("externalGates", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    for gate_id in REQUIRED_OPEN_GATES:
        gate = gates.get(gate_id)
        require(isinstance(gate, dict), f"missing external gate {gate_id}")
        state = gate.get("state")
        require(
            isinstance(state, str)
            and ("open" in state or "required" in state)
            and "closed" not in state,
            f"{gate_id} must remain open/evidence-required: {state!r}",
        )
        require(
            gate.get("repositoryMaySelfCertify") is False,
            f"{gate_id} must not be self-certified by repository fixtures",
        )

    module_map = load(MODULE_MAP_PATH)
    boundary = module_map.get("claimBoundary")
    require(isinstance(boundary, dict), "learning.eval implementation map lacks claimBoundary")
    for key in (
        "productionImplementation",
        "productExecutionProved",
        "independentAcceptance",
        "activation",
        "release",
    ):
        require(boundary.get(key) is False, f"module-local map may not upgrade {key}")
    require(
        module_map.get("productCallerState") == "not_composed",
        "module-local map may not claim a product caller before external composition evidence exists",
    )

    for path in NON_AUTHORITY_DOCS:
        require(path.is_file(), f"missing status-bearing document: {path.relative_to(ROOT)}")
        lowered = path.read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN_UPGRADES:
            require(
                phrase not in lowered,
                f"non-authoritative document {path.relative_to(ROOT)} contains forbidden status upgrade: {phrase}",
            )

    print(
        "learning.eval status authority verified: "
        "Lane E matrix is source/CI authority; product, calendar, acceptance and release gates remain external"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as error:
        print(f"learning.eval status drift: {error}", file=sys.stderr)
        raise SystemExit(1) from error
