#!/usr/bin/env python3
"""Converge the objective.compiler implementation map before generic migration.

The generic implementation-map migrator refreshes exact Git identities for paths
already represented in the map. This module-specific step owns the semantic
inventory introduced by the indexed admission, proof/result split, publication
binding and normative execution contract. It changes source-navigation evidence
only and cannot grant qualification, acceptance, activation or release.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "docs/modules/objective.compiler/IMPLEMENTATION_MAP.json"


class MapConvergenceError(ValueError):
    pass


def load(path: Path) -> dict[str, Any]:
    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise MapConvergenceError(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise MapConvergenceError(f"{path} must contain an object")
    return value


def test(path: str, symbol: str) -> dict[str, str]:
    return {"path": path, "symbol": symbol}


def callee(path: str, symbol: str, role: str) -> dict[str, str]:
    return {"path": path, "symbol": symbol, "role": role}


def operation(
    name: str,
    symbol: str,
    source: str,
    inputs: list[str],
    outputs: list[str],
    state: str,
    authority: str,
    tests: list[dict[str, str]],
    delegated: list[dict[str, str]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "operation": name,
        "nativeSymbol": symbol,
        "sourcePath": source,
        "inputs": inputs,
        "outputs": outputs,
        "state": state,
        "authority": authority,
        "tests": tests,
        "designOperation": name,
        "mappingClass": "owner_native",
        "delegatedCallees": delegated or [],
        "sourcePathExists": True,
    }
    row.update(extra)
    return row


def upsert(operations: list[dict[str, Any]], row: dict[str, Any]) -> None:
    name = row["operation"]
    for index, current in enumerate(operations):
        if isinstance(current, dict) and current.get("operation") == name:
            operations[index] = row
            return
    operations.append(row)


def remove_stale_gaps(value: Any) -> Any:
    stale = (
        "admission proof persistence",
        "durable proof persistence",
        "validated profile indexes are not used",
        "proof-bearing projection is not bound",
        "raw compiler bypass",
    )
    if isinstance(value, list):
        return [
            item
            for item in value
            if not (
                isinstance(item, str)
                and any(fragment in item.lower() for fragment in stale)
            )
        ]
    return value


def converge(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("module") != "objective.compiler":
        raise MapConvergenceError("map is not objective.compiler")
    operations = row.get("operations")
    if not isinstance(operations, list):
        raise MapConvergenceError("operations must be a list")

    upsert(
        operations,
        operation(
            "validate_admission_profile_v1",
            "ValidatedAdmissionProfileV1::new",
            "codex-rs/hepta-objective/src/validated_admission.rs",
            ["ObjectiveAdmissionProfileV1"],
            [
                "opaque generation-local ValidatedAdmissionProfileV1",
                "profile digest/revision/compiler-contract reuse key",
                "locale/source/constraint/predicate/action/soft/evidence/abstention indexes",
                "global semantic identity collision proof",
            ],
            "source_implemented_generation_local_indexed_validation",
            "none_static_validation_only",
            [
                test(
                    "codex-rs/hepta-objective/src/validated_admission_tests.rs",
                    "validated_profile_matches_raw_admission_and_compile",
                ),
                test(
                    "codex-rs/hepta-objective/src/validated_admission_tests.rs",
                    "validated_profile_rejects_cross_category_identity_collision",
                ),
            ],
            [
                callee(
                    "codex-rs/hepta-objective/src/indexed_admission.rs",
                    "admit_indexed_objective_v1",
                    "generation_frozen_indexed_request_admission",
                )
            ],
            productRole="generation_local_static_profile_owner",
        ),
    )
    upsert(
        operations,
        operation(
            "admit_validated_objective_v1",
            "codex_hepta_objective::admit_validated_objective_v1",
            "codex-rs/hepta-objective/src/validated_admission.rs",
            [
                "ObjectiveSourceEnvelopeV1",
                "ValidatedAdmissionProfileV1",
                "fresh ObjectiveAdmissionContextV1",
            ],
            [
                "opaque non-cloneable ValidatedObjectiveAdmissionV1",
                "ObjectiveAdmissionProofV1",
            ],
            "source_implemented_canonical_indexed_product_admission",
            "deny_all",
            [
                test(
                    "codex-rs/hepta-objective/src/validated_admission_tests.rs",
                    "validated_profile_matches_raw_admission_and_compile",
                ),
                test(
                    "codex-rs/hepta-objective/src/proof_projection_tests.rs",
                    "frozen_profile_does_not_cache_authentication_or_freshness",
                ),
            ],
            [
                callee(
                    "codex-rs/hepta-objective/src/indexed_admission.rs",
                    "admit_indexed_objective_v1",
                    "indexed_authenticated_lowering",
                ),
                callee(
                    "codex-rs/hepta-objective/src/admission_proof.rs",
                    "build_admission_proof_v1",
                    "opaque_versioned_proof_issuance",
                ),
                callee(
                    "codex-rs/hepta-objective/src/admission_results.rs",
                    "ValidatedObjectiveAdmissionV1",
                    "non_cloneable_admission_capability",
                ),
            ],
            productRole="canonical_agentd_product_admission",
        ),
    )
    upsert(
        operations,
        operation(
            "compile_authoritative_objective_v1",
            "codex_hepta_objective::compile_authoritative_objective_v1",
            "codex-rs/hepta-objective/src/validated_admission.rs",
            [
                "ObjectiveSourceEnvelopeV1",
                "ValidatedAdmissionProfileV1",
                "fresh ObjectiveAdmissionContextV1",
            ],
            ["opaque non-cloneable ProofBearingObjectiveCompileV1"],
            "source_implemented_canonical_agentd_product_compile",
            "deny_all",
            [
                test(
                    "codex-rs/hepta-objective/src/proof_projection_tests.rs",
                    "proof_projection_matches_independent_authenticated_recompilation",
                ),
                test(
                    "codex-rs/hepta-objective/src/proof_projection_tests.rs",
                    "q32_boundaries_preserve_exact_scalar_semantics_through_product_projection",
                ),
            ],
            [
                callee(
                    "codex-rs/hepta-objective/src/indexed_admission.rs",
                    "admit_indexed_objective_v1",
                    "indexed_request_admission",
                ),
                callee(
                    "codex-rs/hepta-objective/src/admission_proof.rs",
                    "ObjectiveAdmissionProofV1",
                    "proof_integrity_owner",
                ),
                callee(
                    "codex-rs/hepta-objective/src/admission_results.rs",
                    "ProofBearingObjectiveCompileV1",
                    "single_use_authoritative_compile_result",
                ),
                callee(
                    "codex-rs/hepta-objective/src/compiler.rs",
                    "crate::compiler::compile",
                    "deterministic_native_compile",
                ),
            ],
            productRole="canonical_agentd_product_compile",
        ),
    )
    upsert(
        operations,
        operation(
            "bind_objective_publication_v1",
            "ProofBearingObjectiveCompileV1::bind_publication",
            "codex-rs/hepta-objective/src/admission_results.rs",
            [
                "opaque ProofBearingObjectiveCompileV1",
                "destination owner digest",
                "run id",
                "expected predecessor",
                "generation",
                "fence digest",
            ],
            ["non-cloneable BoundObjectivePublicationV1"],
            "source_implemented_destination_run_bound_publication_typestate",
            "deny_all_single_use_projection_token",
            [
                test(
                    "codex-rs/hepta-objective/src/proof_projection_tests.rs",
                    "publication_binding_rejects_zero_owner_generation_and_fence",
                ),
                test(
                    "codex-rs/hepta-objective/src/proof_projection_tests.rs",
                    "proof_projection_matches_independent_authenticated_recompilation",
                ),
            ],
            productRole="required_before_canonical_protocol_projection",
        ),
    )
    upsert(
        operations,
        operation(
            "encode_proof_bearing_objective_function_v1",
            "codex_hepta_objective::encode_proof_bearing_objective_function_v1",
            "codex-rs/hepta-objective/src/proof_projection.rs",
            [
                "BoundObjectivePublicationV1",
                "ObjectiveSourceEnvelopeV1",
                "ValidatedAdmissionProfileV1",
            ],
            [
                "canonical ObjectiveFunctionV1 bytes",
                "protocol digest",
                "native semantic digest binding",
            ],
            "source_implemented_proof_and_destination_bound_projection",
            "deny_all",
            [
                test(
                    "codex-rs/hepta-objective/src/proof_projection_tests.rs",
                    "proof_projection_matches_independent_authenticated_recompilation",
                ),
                test(
                    "codex-rs/hepta-objective/src/proof_projection_tests.rs",
                    "proof_projection_rejects_metadata_intent_and_profile_substitution",
                ),
                test(
                    "codex-rs/hepta-objective/src/proof_projection_tests.rs",
                    "proof_projection_rejects_conflict_but_preserves_explicit_abstain",
                ),
            ],
            [
                callee(
                    "codex-rs/hepta-objective/src/admission_proof.rs",
                    "source_envelope_proof_digest_v1",
                    "complete_source_envelope_rebinding",
                ),
                callee(
                    "codex-rs/hepta-objective/src/objective_function_v1.rs",
                    "encode_validated_profile_objective_function_v1",
                    "strict_canonical_protocol_projection",
                ),
            ],
            productRole="canonical_agentd_product_projection",
        ),
    )
    upsert(
        operations,
        operation(
            "verify_normative_execution_contract_v1",
            "scripts/hepta-objective-spec-consistency.py::verify",
            "scripts/hepta-objective-spec-consistency.py",
            [
                "NORMATIVE_EXECUTION.json",
                "source/document/workflow inventory",
                "exact checkout commit/tree",
            ],
            ["fail-closed consistency result"],
            "source_implemented_qualification_consistency_check",
            "none_no_acceptance_authority",
            [
                test(
                    "scripts/test_hepta_objective_spec_consistency.py",
                    "ObjectiveSpecConsistencyTests.test_repository_contract_is_consistent",
                )
            ],
            [
                callee(
                    "docs/modules/objective.compiler/NORMATIVE_EXECUTION.md",
                    "objective.compiler normative execution contract",
                    "sole_normative_product_contract",
                ),
                callee(
                    "docs/modules/objective.compiler/NORMATIVE_EXECUTION.json",
                    "hepta.objective-compiler-normative-execution.v1",
                    "machine_readable_normative_contract",
                ),
                callee(
                    "docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md",
                    "Objective compiler execution specification",
                    "readiness_procedure_supplement",
                ),
            ],
            productRole="qualification_consistency_not_product_runtime",
        ),
    )

    for name in (
        "admit_and_compile_objective_v1",
        "admit_objective_v1",
        "compile_admitted_objective_v1",
        "encode_authenticated_objective_function_v1",
    ):
        for current in operations:
            if isinstance(current, dict) and current.get("operation") == name:
                current["productRole"] = "explicit_compatibility_feature_not_product_path"
                current["publicCompatibilityFeature"] = "objective-compatibility-api"
                current["state"] = "source_implemented_feature_gated_compatibility"
                break

    operations.sort(key=lambda item: str(item.get("operation", "")))
    row["operations"] = operations
    row["productCallerState"] = "source_composed_durable_proof_bound_not_activated"
    row["authorityDelta"] = "none"
    row["productionImplementation"] = False
    row["status"] = {
        "implemented": True,
        "composed": True,
        "qualified": False,
    }
    claim = row.get("claimBoundary")
    if not isinstance(claim, dict):
        claim = {}
    claim.update(
        productionImplementation=False,
        productExecutionProved=False,
        independentAcceptance=False,
        activation=False,
        release=False,
    )
    row["claimBoundary"] = claim
    for key in ("repositoryControlledGaps", "remainingGaps", "gaps"):
        if key in row:
            row[key] = remove_stale_gaps(row[key])
    return row


def sync() -> None:
    row = converge(load(MAP_PATH))
    MAP_PATH.write_text(
        json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def verify() -> None:
    current = load(MAP_PATH)
    expected = converge(json.loads(json.dumps(current)))
    if current != expected:
        raise SystemExit("FAIL_OBJECTIVE_MAP_CONVERGENCE: semantic inventory drift")
    required = {
        "admit_validated_objective_v1",
        "compile_authoritative_objective_v1",
        "bind_objective_publication_v1",
        "encode_proof_bearing_objective_function_v1",
        "verify_normative_execution_contract_v1",
    }
    observed = {
        row.get("operation")
        for row in current.get("operations", [])
        if isinstance(row, dict)
    }
    missing = sorted(required.difference(observed))
    if missing:
        raise SystemExit(
            "FAIL_OBJECTIVE_MAP_CONVERGENCE: missing operations " + ", ".join(missing)
        )
    print(
        json.dumps(
            {
                "status": "PASS_OBJECTIVE_MAP_CONVERGENCE",
                "module": "objective.compiler",
                "operations": len(observed),
                "productionImplementation": False,
                "qualified": False,
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("sync", "verify"))
    args = parser.parse_args()
    if args.command == "sync":
        sync()
    else:
        verify()


if __name__ == "__main__":
    main()
