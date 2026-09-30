#!/usr/bin/env python3
"""Verify the single normative objective.compiler execution contract.

This verifier checks source, document and workflow consistency. It does not
compile Rust, authenticate external receipts, qualify a target host, issue
acceptance or advance release truth.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "docs/modules/objective.compiler/NORMATIVE_EXECUTION.json"
NORMATIVE_PATH = ROOT / "docs/modules/objective.compiler/NORMATIVE_EXECUTION.md"


class ConsistencyError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in items:
            if key in output:
                raise ConsistencyError(f"duplicate JSON key in {path}: {key}")
            output[key] = value
        return output

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (OSError, json.JSONDecodeError) as error:
        raise ConsistencyError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise ConsistencyError(f"{path} must contain an object")
    return value


def read(rel: str) -> str:
    path = ROOT / rel
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConsistencyError(f"cannot read {rel}: {error}") from error


def require_markers(rel: str, markers: list[str]) -> None:
    text = read(rel)
    missing = [marker for marker in markers if marker not in text]
    if missing:
        raise ConsistencyError(f"{rel} is missing markers: {missing}")


def forbid_markers(rel: str, markers: list[str]) -> None:
    text = read(rel)
    found = [marker for marker in markers if marker in text]
    if found:
        raise ConsistencyError(f"{rel} retains superseded markers: {found}")


def git(*args: str) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def validate_manifest(manifest: dict[str, Any]) -> None:
    if (
        manifest.get("schema") != "hepta.objective-compiler-normative-execution.v1"
        or manifest.get("schemaVersion") != 1
        or manifest.get("module") != "objective.compiler"
        or manifest.get("normativeDocument")
        != "docs/modules/objective.compiler/NORMATIVE_EXECUTION.md"
    ):
        raise ConsistencyError("invalid normative manifest identity")

    expected_path = {
        "validatedProfileType": "ValidatedAdmissionProfileV1",
        "indexedAdmission": "admit_indexed_objective_v1",
        "authoritativeCompile": "compile_authoritative_objective_v1",
        "proofBearingResult": "ProofBearingObjectiveCompileV1",
        "publicationBinding": "ObjectivePublicationBindingV1",
        "boundPublicationResult": "BoundObjectivePublicationV1",
        "protocolProjection": "encode_proof_bearing_objective_function_v1",
        "publicationFacade": "compile_and_publish_validated_objective_run_v1",
        "runtimeOwner": "ObjectiveRuntimeHost",
        "durableOwner": "RunStartJournal",
    }
    if manifest.get("productPath") != expected_path:
        raise ConsistencyError("normative product path drifted")

    if manifest.get("durableFormats") != {
        "runStartRecordVersion": 3,
        "conflictRecordVersion": 2,
        "admissionProofVersion": 1,
        "admissionProofDomain": "hepta.objective.admission-proof.v1",
        "legacyFinalUseAllowed": False,
    }:
        raise ConsistencyError("normative durable formats drifted")

    compatibility = manifest.get("compatibility")
    if (
        not isinstance(compatibility, dict)
        or compatibility.get("rawCompatibilityFeature")
        != "objective-compatibility-api"
        or compatibility.get("legacyCompileFeature")
        != "qualification-legacy-compile"
        or compatibility.get("productDefault") is not False
    ):
        raise ConsistencyError("compatibility boundary drifted")

    if manifest.get("errorCodes") != [f"OBJ-E{index:03d}" for index in range(1, 10)]:
        raise ConsistencyError("objective error-code inventory drifted")
    if manifest.get("staticTruth") != {
        "productionImplementation": False,
        "accepted": False,
        "activated": False,
        "released": False,
    }:
        raise ConsistencyError("normative static truth must remain fail-closed")


def verify() -> dict[str, Any]:
    manifest = load_json(MANIFEST_PATH)
    validate_manifest(manifest)

    canonical = [
        "admit_indexed_objective_v1",
        "compile_authoritative_objective_v1",
        "ObjectivePublicationBindingV1",
        "BoundObjectivePublicationV1",
        "encode_proof_bearing_objective_function_v1",
        "compile_and_publish_validated_objective_run_v1",
        "RunStart record V3",
        "objective-conflict record V2",
        "objective-compatibility-api",
        "qualification-legacy-compile",
        "exact source head",
        "deterministic synthetic merge",
    ]
    require_markers(
        "docs/modules/objective.compiler/NORMATIVE_EXECUTION.md", canonical
    )

    normative_link = "docs/modules/objective.compiler/NORMATIVE_EXECUTION.md"
    for rel in (
        "docs/modules/objective.compiler/TECHNICAL.md",
        "docs/modules/objective.compiler/SEMANTIC_SUPPORT.md",
        "docs/modules/objective.compiler/DELIVERY_EVIDENCE.md",
        "docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md",
        "docs/readiness/OBJECTIVE_TARGET_HOST_MEASUREMENT.md",
        "docs/modules/objective.compiler/CLOSEOUT_20260930.md",
    ):
        require_markers(rel, [normative_link])

    forbid_markers(
        "docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md",
        [
            "-> admit_objective_v1\n",
            "-> durable RunStart v2 record",
            "uses `encode_authenticated_objective_function_v1`",
        ],
    )

    source_markers = {
        "codex-rs/hepta-objective/src/lib.rs": [
            "mod indexed_admission;",
            "ObjectivePublicationBindingV1",
            "BoundObjectivePublicationV1",
            "objective-compatibility-api",
        ],
        "codex-rs/hepta-objective/src/indexed_admission.rs": [
            "pub(crate) fn admit_indexed_objective_v1",
            "profile.constraint(",
            "profile.predicate(",
            "profile.action(",
            "profile.soft_dimension(",
            "profile.evidence_requirement(",
            "profile.abstention_rule(",
        ],
        "codex-rs/hepta-objective/src/validated_admission.rs": [
            "admit_indexed_objective_v1",
            "pub fn compile_authoritative_objective_v1",
            "ValidatedAdmissionProfileV1",
        ],
        "codex-rs/hepta-objective/src/admission_results.rs": [
            "pub struct ObjectivePublicationBindingV1",
            "pub struct BoundObjectivePublicationV1",
            "pub fn bind_publication",
        ],
        "codex-rs/hepta-objective/src/proof_projection.rs": [
            "BoundObjectivePublicationV1",
            "source_envelope_proof_digest_v1",
        ],
        "codex-rs/hepta-intelligence/src/objective_run.rs": [
            "ObjectivePublicationBindingV1::new",
            ".bind_publication(publication_binding)",
            "compile_and_publish_validated_objective_run_v1",
        ],
        "codex-rs/hepta-learning-ledger/src/run_start_proof.rs": [
            "hepta.objective.admission-proof.v1",
            "pub struct RunStartAdmissionProofV1",
        ],
        "codex-rs/hepta-objective/Cargo.toml": [
            "objective-compatibility-api = []",
            'qualification-legacy-compile = ["objective-compatibility-api"]',
        ],
    }
    for rel, markers in source_markers.items():
        require_markers(rel, markers)

    error_registry = read("docs/contracts/OBJECTIVE_ERRORS.json")
    for code in manifest["errorCodes"]:
        if code not in error_registry:
            raise ConsistencyError(f"canonical error registry omits {code}")

    state = load_json(ROOT / "docs/modules/objective.compiler/CURRENT_STATE.json")
    if state.get("truth") != manifest["staticTruth"]:
        raise ConsistencyError("CURRENT_STATE truth differs from normative manifest")
    required_checks = state.get("requiredChecks")
    if not isinstance(required_checks, list) or (
        "objective.compiler normative consistency" not in required_checks
    ):
        raise ConsistencyError("CURRENT_STATE omits normative consistency check")

    require_markers(
        "docs/modules/objective.compiler/IMPLEMENTATION_MAP.json",
        [
            "codex-rs/hepta-objective/src/indexed_admission.rs",
            "codex-rs/hepta-objective/src/admission_proof.rs",
            "codex-rs/hepta-objective/src/admission_results.rs",
            "docs/modules/objective.compiler/NORMATIVE_EXECUTION.md",
            "scripts/hepta-objective-spec-consistency.py",
        ],
    )
    require_markers(
        "scripts/hepta-objective-map-convergence.py",
        [
            "bind_objective_publication_v1",
            "verify_normative_execution_contract_v1",
            "objective-compatibility-api",
        ],
    )
    require_markers(
        ".github/workflows/hepta-objective-exact-execution.yml",
        [
            "hepta-objective-spec-consistency.py verify",
            "--module objective.compiler",
            "--expected-sha",
            "--expected-tree",
        ],
    )
    require_markers(
        ".github/workflows/hepta-objective-release-gate.yml",
        ["refs/heads/main", "trusted-control", "--candidate-root"],
    )
    require_markers(
        ".github/workflows/hepta-objective-target-host.yml",
        [
            "objective-target-host",
            "ephemeral",
            "trusted-control",
            "actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8",
            "id-token: write",
            "attestations: write",
        ],
    )
    require_markers(
        "scripts/hepta-objective-current-state.py",
        [normative_link, "normativeExecutionContract"],
    )

    commit = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    if len(commit) != 40 or len(tree) != 40:
        raise ConsistencyError("exact source commit/tree identity is unavailable")
    return {
        "status": "PASS_OBJECTIVE_NORMATIVE_CONSISTENCY",
        "module": "objective.compiler",
        "candidateCommit": commit,
        "candidateTree": tree,
        "productionImplementationProved": False,
        "acceptanceIssued": False,
        "activationIssued": False,
        "releaseIssued": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify",))
    args = parser.parse_args()
    if args.command == "verify":
        try:
            print(json.dumps(verify(), sort_keys=True))
        except (ConsistencyError, subprocess.CalledProcessError) as error:
            raise SystemExit(f"FAIL_OBJECTIVE_NORMATIVE_CONSISTENCY: {error}") from error


if __name__ == "__main__":
    main()
