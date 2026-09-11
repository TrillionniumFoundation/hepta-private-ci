"""Lane A matrix, receipt and self-test helpers."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from lane_a_foundation_core import *  # noqa: F403


def validate_matrix(matrix: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    if (
        matrix.get("schemaVersion") != 2
        or matrix.get("lane") != "LANE-A-FOUNDATION"
        or matrix.get("documentationPolicy")
        != "docs/lane-a-foundation/BOUNDARY_POLICY.md"
        or matrix.get("capabilityEvidenceMap")
        != "docs/lane-a-foundation/CAPABILITY_EVIDENCE_MAP.json"
        or matrix.get("nativeBindingOverride")
        != "qualification/module-execution-dossiers/NATIVE_BINDINGS_LANE_A.json"
        or matrix.get("moduleCoverage") != 7
        or matrix.get("statusAxes") != AXES
    ):
        raise VerificationError("truth-matrix header mismatch")
    expected_closure = {
        "repositoryControlledDocumentationGaps": "closed",
        "currentImplementationTruth": "source_and_test_anchored",
        "automatedDriftGate": "closed",
        "nativeQualification": "workflow_required",
        "targetArchitectureImplementation": "partial",
        "productionActivation": "not_claimed",
        "externalAcceptance": "not_claimed",
    }
    if matrix.get("closure") != expected_closure:
        raise VerificationError("truth-matrix closure overclaims or drifts")
    policy = read_text(root / "docs/lane-a-foundation/BOUNDARY_POLICY.md")
    for phrase in (
        "Current executable contract",
        "Target architecture",
        "Executed evidence",
        "Forbidden implications",
        "Capability traceability rule",
    ):
        if phrase not in policy:
            raise VerificationError(f"boundary policy missing {phrase!r}")
    modules = matrix.get("modules")
    if (
        not isinstance(modules, list)
        or [row.get("module") for row in modules if isinstance(row, dict)]
        != EXPECTED_MODULES
    ):
        raise VerificationError("closed-world module order mismatch")
    for row in modules:
        module = row["module"]
        states = row.get("states")
        if (
            not isinstance(states, dict)
            or list(states) != AXES
            or states["source"] != "implemented"
            or states["acceptance"] != "not_granted"
            or row.get("formalGuideRole") != "target_architecture"
            or row.get("currentSpecificationRole") != "current_executable_contract"
        ):
            raise VerificationError(f"{module}: role/state mismatch")
        for field in ("formalGuide", "currentSpecification", "implementationDetail"):
            if not isinstance(row.get(field), str) or not (root / row[field]).is_file():
                raise VerificationError(f"{module}: missing {field}")
        current = read_text(root / row["currentSpecification"])
        positions = [current.find(heading) for heading in SECTIONS]
        if -1 in positions or positions != sorted(positions):
            raise VerificationError(
                f"{module}: current-contract sections missing/out of order"
            )
        current_caps = row.get("currentCapabilities")
        target_caps = row.get("targetOnlyCapabilities")
        if (
            not isinstance(current_caps, list)
            or not current_caps
            or not isinstance(target_caps, list)
            or set(current_caps) & set(target_caps)
        ):
            raise VerificationError(f"{module}: capability boundary mismatch")
        anchors = row.get("sourceAnchors")
        if not isinstance(anchors, list) or not anchors:
            raise VerificationError(f"{module}: source anchors required")
        for anchor in anchors:
            validate_anchor(module, anchor, root)
    by_name = {row["module"]: row for row in modules}
    exact = {
        ("kernel.operations", "implementation"): "bounded_reference_model",
        ("kernel.operations", "durability"): "not_implemented",
        ("auth.authbus", "implementation"): "signed_admission_with_legacy_replay",
        (
            "auth.authbus",
            "durability",
        ): "sqlite_admission_outbox_and_process_local_legacy",
        ("platform.wire", "implementation"): "fixed_v1_codec",
        ("kernel.authority", "implementation"): "final_use_boundary",
        ("kernel.evidence", "durability"): "sqlite_migrations_0001_0010",
        ("secrets.heptabao", "implementation"): "bounded_kv_v2_reader",
    }
    for (module, axis), value in exact.items():
        if by_name[module]["states"][axis] != value:
            raise VerificationError(f"{module}: {axis} drift")
    capability = read_json(root / "docs/lane-a-foundation/CAPABILITY_EVIDENCE_MAP.json")
    validate_capability_map(matrix, capability, root)
    native = validate_native_bindings(root)
    validate_wire_vector(root)
    validate_source_specific(root)
    return native["currentSourceBinding"]


def git_value(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise VerificationError(f"git {' '.join(args)} failed: {error}") from error
    return result.stdout.strip()


def command_value(*args: str) -> str:
    try:
        result = subprocess.run(
            args,
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise VerificationError(f"{' '.join(args)} failed: {error}") from error
    return result.stdout.strip()


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def exact_source(expected: str | None) -> tuple[str, str]:
    source = git_value("rev-parse", "HEAD")
    if expected is not None and source != expected:
        raise VerificationError(
            f"exact source mismatch: expected {expected}, got {source}"
        )
    return source, git_value("rev-parse", "HEAD^{tree}")


def write_receipt(output: Path, expected: str | None, native: bool) -> None:
    matrix = read_json(MATRIX_PATH)
    binding = validate_matrix(matrix)
    source, tree = exact_source(expected)
    if (source, tree) != (binding["sourceSha"], binding["sourceTree"]):
        raise VerificationError("checkout changed while producing source receipt")
    if native:
        receipt: dict[str, Any] = {
            "schemaVersion": 1,
            "lane": "LANE-A-FOUNDATION",
            "receiptClass": "native-qualification",
            "sourceSha": source,
            "sourceTree": tree,
            "packages": PACKAGES,
            "cargoVersion": command_value("cargo", "--version"),
            "rustcVersion": command_value("rustc", "--version"),
            "status": "passed_in_current_job",
            "githubRunId": os.environ.get("GITHUB_RUN_ID"),
            "githubRunAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "productionActivation": "not_claimed",
            "externalAcceptance": "not_claimed",
        }
    else:
        capabilities = read_json(CAPABILITY_MAP_PATH)
        bindings = read_json(NATIVE_BINDINGS_PATH)
        receipt = {
            "schemaVersion": 2,
            "lane": "LANE-A-FOUNDATION",
            "receiptClass": "source-truth",
            "sourceSha": source,
            "sourceTree": tree,
            "matrixSha256": hashlib.sha256(canonical(matrix)).hexdigest(),
            "capabilityMapSha256": hashlib.sha256(canonical(capabilities)).hexdigest(),
            "nativeBindingsSha256": hashlib.sha256(canonical(bindings)).hexdigest(),
            "boundaryPolicySha256": hashlib.sha256(
                BOUNDARY_POLICY_PATH.read_bytes()
            ).hexdigest(),
            "currentSpecificationSha256": {
                row["module"]: hashlib.sha256(
                    (ROOT / row["currentSpecification"]).read_bytes()
                ).hexdigest()
                for row in matrix["modules"]
            },
            "moduleCoverage": 7,
            "capabilityCoverage": capabilities["entryCount"],
            "repositoryControlledDocumentationGaps": "closed",
            "currentImplementationTruth": "source_and_test_anchored",
            "nativeQualification": "separate_exact_candidate_receipt_required",
            "targetArchitectureImplementation": "partial",
            "productionActivation": "not_claimed",
            "externalAcceptance": "not_claimed",
        }
    receipt["nativeSourceObservations"] = binding["observations"]
    receipt["nativeSourceObservationSha256"] = hashlib.sha256(
        canonical(binding)
    ).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_source_receipt(output: Path, expected: str | None) -> None:
    write_receipt(output, expected, native=False)


def self_test() -> None:
    matrix = read_json(MATRIX_PATH)
    validate_matrix(matrix)
    for mutation in (
        lambda value: value["modules"][3]["states"].__setitem__(
            "durability", "durable"
        ),
        lambda value: value["closure"].__setitem__("externalAcceptance", "closed"),
    ):
        invalid = deepcopy(matrix)
        mutation(invalid)
        try:
            validate_matrix(invalid)
        except VerificationError:
            pass
        else:
            raise VerificationError("self-test accepted a matrix overclaim")
    capability = read_json(CAPABILITY_MAP_PATH)
    for mutation in (
        lambda value: value["entries"].pop(),
        lambda value: value["entries"][0].__setitem__("productionCaller", "unproven"),
    ):
        invalid = deepcopy(capability)
        mutation(invalid)
        try:
            validate_capability_map(matrix, invalid)
        except VerificationError:
            pass
        else:
            raise VerificationError("self-test accepted invalid capability evidence")
