"""Lane A matrix, receipt and self-test helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from lane_a_foundation_core import *  # noqa: F403

CANDIDATE_KINDS = frozenset({"source-head", "synthetic-merge"})
SHA1 = re.compile(r"[0-9a-f]{40}")


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
    module_names = (
        [row.get("module") for row in modules if isinstance(row, dict)]
        if isinstance(modules, list)
        else []
    )
    if (
        not isinstance(modules, list)
        or len(module_names) != len(EXPECTED_MODULES)
        or len(set(module_names)) != len(module_names)
        or set(module_names) != set(EXPECTED_MODULES)
    ):
        raise VerificationError("closed-world module set mismatch")
    by_name = {row["module"]: row for row in modules}
    ordered_modules = [by_name[module] for module in EXPECTED_MODULES]
    for row in ordered_modules:
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
    exact = {
        ("kernel.operations", "implementation"): "durable_owner_source_implemented",
        ("kernel.operations", "durability"): "sqlite_wal_full_integrated_owner",
        ("auth.authbus", "implementation"): "durable_policy_quota_reservation_owner",
        (
            "auth.authbus",
            "durability",
        ): "sqlite_dual_checkpointed_authbus_owners",
        ("platform.wire", "implementation"): "versioned_v1_v2_codec",
        (
            "kernel.authority",
            "implementation",
        ): "final_use_and_authority_lease_owner",
        ("kernel.evidence", "durability"): "sqlite_migrations_0001_0012",
        (
            "secrets.heptabao",
            "implementation",
        ): "bounded_kv_v2_reader_with_registered_final_use_host",
    }
    for (module, axis), value in exact.items():
        if by_name[module]["states"][axis] != value:
            raise VerificationError(f"{module}: {axis} drift")
    normalized_matrix = dict(matrix)
    normalized_matrix["modules"] = ordered_modules
    capability = read_json(root / "docs/lane-a-foundation/CAPABILITY_EVIDENCE_MAP.json")
    validate_capability_map(normalized_matrix, capability, root)
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


def _exact_commit(value: str | None, name: str) -> str:
    if not isinstance(value, str) or SHA1.fullmatch(value) is None:
        raise VerificationError(f"{name} must be an exact 40-character Git commit id")
    if git_value("cat-file", "-t", value) != "commit":
        raise VerificationError(f"{name} does not identify a commit")
    return value


def candidate_identity(
    candidate_kind: str,
    candidate_sha: str,
    candidate_tree: str,
    *,
    source_sha: str | None,
    base_sha: str | None = None,
    pull_request_number: int | None = None,
) -> dict[str, Any]:
    """Return an exact, non-interchangeable Lane A candidate identity."""
    if candidate_kind not in CANDIDATE_KINDS:
        raise VerificationError(f"unsupported candidate kind: {candidate_kind!r}")
    candidate_sha = _exact_commit(candidate_sha, "candidate SHA")
    if SHA1.fullmatch(candidate_tree) is None:
        raise VerificationError("candidate tree must be an exact 40-character Git tree id")
    if git_value("rev-parse", f"{candidate_sha}^{{tree}}") != candidate_tree:
        raise VerificationError("candidate SHA/tree mismatch")
    source_sha = _exact_commit(source_sha, "source SHA")

    identity: dict[str, Any] = {
        "schema": "hepta.lane-a.candidate-identity.v1",
        "kind": candidate_kind,
        "candidateSha": candidate_sha,
        "candidateTree": candidate_tree,
        "sourceSha": source_sha,
    }
    if candidate_kind == "source-head":
        if source_sha != candidate_sha:
            raise VerificationError("source-head source SHA must equal candidate SHA")
        if base_sha is not None or pull_request_number is not None:
            raise VerificationError(
                "source-head identity cannot carry merge base or pull-request number"
            )
        return identity

    base_sha = _exact_commit(base_sha, "base SHA")
    if not isinstance(pull_request_number, int) or pull_request_number <= 0:
        raise VerificationError(
            "synthetic-merge identity requires a positive pull-request number"
        )
    parents = git_value("rev-list", "--parents", "-n", "1", candidate_sha).split()[1:]
    if source_sha not in parents or base_sha not in parents:
        raise VerificationError(
            "synthetic-merge candidate must directly parent both source and base SHAs"
        )
    identity.update(
        {
            "baseSha": base_sha,
            "pullRequestNumber": pull_request_number,
        }
    )
    return identity


def write_receipt(
    output: Path,
    expected: str | None,
    native: bool,
    *,
    candidate_kind: str,
    source_sha: str,
    base_sha: str | None = None,
    pull_request_number: int | None = None,
) -> None:
    matrix = read_json(MATRIX_PATH)
    binding = validate_matrix(matrix)
    source, tree = exact_source(expected)
    if (source, tree) != (binding["sourceSha"], binding["sourceTree"]):
        raise VerificationError("checkout changed while producing source receipt")
    identity = candidate_identity(
        candidate_kind,
        source,
        tree,
        source_sha=source_sha,
        base_sha=base_sha,
        pull_request_number=pull_request_number,
    )
    common: dict[str, Any] = {
        "lane": "LANE-A-FOUNDATION",
        "candidateKind": candidate_kind,
        "candidateIdentity": identity,
        "candidateSha": source,
        "candidateTree": tree,
        # Compatibility fields identify the exact checked-out candidate. The
        # originating PR source is candidateIdentity.sourceSha.
        "sourceSha": source,
        "sourceTree": tree,
        "githubRunId": os.environ.get("GITHUB_RUN_ID"),
        "githubRunAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "productionActivation": "not_claimed",
        "externalAcceptance": "not_claimed",
    }
    if native:
        receipt: dict[str, Any] = {
            **common,
            "schemaVersion": 1,
            "receiptClass": "native-qualification",
            "packages": PACKAGES,
            "cargoVersion": command_value("cargo", "--version"),
            "rustcVersion": command_value("rustc", "--version"),
            "status": "passed_in_current_job",
        }
    else:
        capabilities = read_json(CAPABILITY_MAP_PATH)
        bindings = read_json(NATIVE_BINDINGS_PATH)
        receipt = {
            **common,
            "schemaVersion": 2,
            "receiptClass": "source-truth",
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
        }
    receipt["nativeSourceObservations"] = binding["observations"]
    receipt["nativeSourceObservationSha256"] = hashlib.sha256(
        canonical(binding)
    ).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_source_receipt(
    output: Path,
    expected: str | None,
    *,
    candidate_kind: str = "source-head",
    source_sha: str | None = None,
    base_sha: str | None = None,
    pull_request_number: int | None = None,
) -> None:
    write_receipt(
        output,
        expected,
        native=False,
        candidate_kind=candidate_kind,
        source_sha=source_sha or expected or exact_source(None)[0],
        base_sha=base_sha,
        pull_request_number=pull_request_number,
    )


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

    current, tree = exact_source(None)
    identity = candidate_identity(
        "source-head", current, tree, source_sha=current
    )
    if identity["kind"] != "source-head" or identity["sourceSha"] != current:
        raise VerificationError("source-head identity self-test failed")
    for invalid in (
        lambda: candidate_identity(
            "source-head", current, tree, source_sha=current, base_sha=current
        ),
        lambda: candidate_identity(
            "synthetic-merge", current, tree, source_sha=current
        ),
    ):
        try:
            invalid()
        except VerificationError:
            pass
        else:
            raise VerificationError("self-test accepted interchangeable candidate identity")
