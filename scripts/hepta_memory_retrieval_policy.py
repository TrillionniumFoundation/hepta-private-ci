#!/usr/bin/env python3
"""Load and validate the single repository-controlled memory.retrieval policy."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

POLICY_RELATIVE_PATH = Path("qualification/memory-retrieval/qualification-policy.json")
IMPLEMENTATION_MAP_RELATIVE_PATH = Path(
    "docs/modules/memory.retrieval/IMPLEMENTATION_MAP.json"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")

MANDATORY_REQUIRED_CHECKS = {
    "Memory retrieval exact source": (
        ".github/workflows/hepta-memory-retrieval-convergence.yml"
    ),
    "Memory retrieval source-head": (
        ".github/workflows/hepta-memory-retrieval-convergence.yml"
    ),
    "Memory retrieval base-merge": (
        ".github/workflows/hepta-memory-retrieval-convergence.yml"
    ),
    "Memory retrieval current-main": (
        ".github/workflows/hepta-memory-retrieval-convergence.yml"
    ),
    "Memory retrieval structural probes": (
        ".github/workflows/hepta-memory-retrieval-qualification-host.yml"
    ),
    "Memory retrieval maintenance tests": (
        ".github/workflows/hepta-memory-retrieval-maintenance.yml"
    ),
    "Memory retrieval calibration contract": (
        ".github/workflows/hepta-memory-retrieval-calibration.yml"
    ),
    "CI required": ".github/workflows/blocking-ci.yml",
    "Agentd process qualification result": (
        ".github/workflows/hepta-gap-agentd-process.yml"
    ),
    "Cargo workspace preflight": (
        ".github/workflows/hepta-repository-integrity.yml"
    ),
    "Verify ordinary read-only candidate source": (
        ".github/workflows/hepta-repository-integrity.yml"
    ),
}
MANDATORY_SECURITY_CHECKS = {"CodeQL": "success"}
MANDATORY_SOURCE_OBJECTS = frozenset(
    {
        "codex-rs/hepta-agentd/src/cognitive_retrieval_context.rs",
        "codex-rs/hepta-agentd/src/lib.rs",
        "codex-rs/hepta-agentd/src/retrieval_delivery.rs",
        "codex-rs/hepta-agentd/src/retrieval_delivery_append.rs",
        "codex-rs/hepta-agentd/src/retrieval_executor.rs",
        "codex-rs/hepta-agentd/src/retrieval_product_mode.rs",
        "codex-rs/hepta-memory-retrieval",
        "codex-rs/hepta-memory-retrieval/Cargo.toml",
        "codex-rs/hepta-memory-retrieval/src/lib.rs",
        "codex-rs/hepta-memory-retrieval/src/lifecycle.rs",
        "codex-rs/hepta-memory-retrieval/src/lifecycle_append.rs",
        "codex-rs/hepta-memory-retrieval/src/product.rs",
        "codex-rs/hepta-memory-retrieval/src/semantics.rs",
        "codex-rs/hepta-memory-retrieval/src/vector_publication.rs",
        "codex-rs/hepta-memory-retrieval/src/work.rs",
        "codex-rs/hepta-memory-retrieval/tests/lifecycle_api.rs",
        "codex-rs/hepta-memory-retrieval/tests/lifecycle_append_api.rs",
        "docs/modules/memory.retrieval/CONTROLLED_API.md",
        "docs/modules/memory.retrieval/PRODUCT_ADMISSION.md",
        "docs/modules/memory.retrieval/QUALIFICATION_IDENTITY.md",
        "docs/modules/memory.retrieval/RECOVERY_AND_OUTBOX.md",
        "qualification/memory-retrieval/product-composition.json",
        "qualification/memory-retrieval/production-qualification.json",
        "qualification/memory-retrieval/qualification-policy.json",
        "qualification/memory-retrieval/recovery-matrix.json",
        "scripts/hepta_memory_retrieval_policy.py",
        "scripts/hepta_memory_retrieval_qualification.py",
        "scripts/hepta_memory_retrieval_refresh_map.py",
        "scripts/hepta_memory_retrieval_status.py",
        "scripts/tests/test_hepta_memory_retrieval_policy.py",
        "scripts/tests/test_hepta_memory_retrieval_qualification.py",
        "scripts/tests/test_hepta_memory_retrieval_refresh_map.py",
        "scripts/tests/test_hepta_memory_retrieval_status.py",
    }
)
MANDATORY_EXTERNAL_GATES = frozenset(
    {
        "Memory retrieval target-host full-chain E2E",
        "production text encoder release",
        "durable vector-index publisher and store",
        "external frontier capability revocation authority",
        "tenant withdrawal revocation deletion qualification",
        "durable lifecycle outbox and real-process recovery",
        "held-out quality calibration and ablations",
        "exact binary source-tree receipt",
        "protected killable worker and hard resource isolation",
        "external immutable raw-evidence retention",
        "independent human exact-head acceptance and signature",
        "canary activation and automatic rollback",
        "operator security release approval and signed evidence",
    }
)


class PolicyError(ValueError):
    """The qualification policy is malformed or internally inconsistent."""


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PolicyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def safe_path(value: Any) -> str:
    if not isinstance(value, str):
        raise PolicyError("repository path must be a string")
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or value.startswith(":")
        or "\\" in value
        or "\x00" in value
    ):
        raise PolicyError(f"unsafe repository path: {value!r}")
    return value


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyError(f"{field} must be a non-empty string")
    return value


def _validate_external_evidence(value: Any, gate: str) -> None:
    if not isinstance(value, dict):
        raise PolicyError(f"satisfied external gate lacks evidence object: {gate}")
    subject = _nonempty_string(value.get("subjectSha"), f"{gate} subjectSha")
    digest = _nonempty_string(value.get("sha256"), f"{gate} sha256")
    _nonempty_string(value.get("uri"), f"{gate} uri")
    _nonempty_string(value.get("signer"), f"{gate} signer")
    _nonempty_string(value.get("signature"), f"{gate} signature")
    _nonempty_string(value.get("observedAt"), f"{gate} observedAt")
    if not SHA40.fullmatch(subject):
        raise PolicyError(f"external gate subjectSha is not exact: {gate}")
    if not SHA256.fullmatch(digest):
        raise PolicyError(f"external gate sha256 is not exact: {gate}")


def _frozen_source_identity(root: Path) -> str:
    path = root / IMPLEMENTATION_MAP_RELATIVE_PATH
    if not path.is_file():
        raise PolicyError("satisfied external gates require an implementation map")
    data = path.read_bytes()
    if len(data) > 256 * 1024:
        raise PolicyError("implementation map exceeds 256 KiB")
    value = json.loads(data, object_pairs_hook=unique_object)
    if not isinstance(value, dict) or value.get("module") != "memory.retrieval":
        raise PolicyError("external evidence implementation map is malformed")
    if value.get("sourceIdentityPolicy") != "candidate_or_exact_observation_v1":
        raise PolicyError("external evidence requires exact-observation identity")
    source_base = value.get("sourceBase")
    observed = value.get("observedAtHead")
    if not isinstance(source_base, dict) or not isinstance(observed, dict):
        raise PolicyError("implementation map lacks frozen source identity")
    source_commit = source_base.get("commit")
    observed_commit = observed.get("commit")
    source_tree = source_base.get("tree")
    observed_tree = observed.get("tree")
    if (
        not isinstance(source_commit, str)
        or not SHA40.fullmatch(source_commit)
        or source_commit != observed_commit
        or not isinstance(source_tree, str)
        or not SHA40.fullmatch(source_tree)
        or source_tree != observed_tree
    ):
        raise PolicyError("implementation map frozen source identity is inconsistent")
    return source_commit


def load_policy(root: Path | str = REPOSITORY_ROOT) -> dict[str, Any]:
    root = Path(root)
    path = root / POLICY_RELATIVE_PATH
    data = path.read_bytes()
    if len(data) > 256 * 1024:
        raise PolicyError("qualification policy exceeds 256 KiB")
    value = json.loads(data, object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise PolicyError("qualification policy must be an object")
    if value.get("schema") != "hepta.memory-retrieval.qualification-policy.v1":
        raise PolicyError("unsupported qualification policy schema")
    if value.get("module") != "memory.retrieval":
        raise PolicyError("qualification policy targets the wrong module")
    safe_path(value.get("implementationMap"))
    root_path = safe_path(value.get("sourceRoot"))
    activation = value.get("activationMode")
    if activation not in {"compatibility", "shadow", "canary", "required"}:
        raise PolicyError("unsupported activation mode")

    source_inputs = value.get("sourceInputs")
    object_inputs = value.get("sourceObjectInputs")
    if not isinstance(source_inputs, list) or not source_inputs:
        raise PolicyError("sourceInputs must be a non-empty list")
    if not isinstance(object_inputs, list) or not object_inputs:
        raise PolicyError("sourceObjectInputs must be a non-empty list")
    inputs = [safe_path(item) for item in source_inputs]
    objects = [safe_path(item) for item in object_inputs]
    if len(inputs) != len(set(inputs)) or inputs != sorted(inputs):
        raise PolicyError("sourceInputs must be unique and sorted")
    if len(objects) != len(set(objects)) or objects != sorted(objects):
        raise PolicyError("sourceObjectInputs must be unique and sorted")
    missing_objects = sorted(MANDATORY_SOURCE_OBJECTS - set(objects))
    if missing_objects:
        raise PolicyError(
            "mandatory source objects are absent: " + ", ".join(missing_objects)
        )
    if root_path not in objects:
        raise PolicyError("sourceRoot must be explicitly object-bound")
    for item in objects:
        if not any(
            item == parent or item.startswith(parent.rstrip("/") + "/")
            for parent in inputs
        ):
            raise PolicyError(f"source object is outside sourceInputs: {item}")

    claims = value.get("promotionClaims")
    boundary = value.get("claimBoundary")
    if not isinstance(claims, list) or not claims:
        raise PolicyError("promotionClaims must be a non-empty list")
    if not isinstance(boundary, dict):
        raise PolicyError("claimBoundary must be an object")
    for claim in claims:
        _nonempty_string(claim, "promotion claim")
        if boundary.get(claim) is not False:
            raise PolicyError(f"policy claim must remain false: {claim}")

    checks = value.get("requiredChecks")
    if not isinstance(checks, list) or not checks:
        raise PolicyError("requiredChecks must be a non-empty list")
    names: set[str] = set()
    observed_checks: dict[str, str] = {}
    for row in checks:
        if not isinstance(row, dict):
            raise PolicyError("required check rows must be objects")
        name = _nonempty_string(row.get("name"), "required check name")
        workflow = safe_path(row.get("workflow"))
        if name in names:
            raise PolicyError(f"duplicate required check: {name}")
        names.add(name)
        observed_checks[name] = workflow
    for name, workflow in MANDATORY_REQUIRED_CHECKS.items():
        if observed_checks.get(name) != workflow:
            raise PolicyError(
                f"mandatory required check is absent or misbound: {name}"
            )

    security = value.get("securityChecks")
    if not isinstance(security, list):
        raise PolicyError("securityChecks must be a list")
    security_names: set[str] = set()
    observed_security: dict[str, str] = {}
    for row in security:
        if not isinstance(row, dict):
            raise PolicyError("security check rows must be objects")
        name = _nonempty_string(row.get("name"), "security check name")
        conclusion = _nonempty_string(
            row.get("requiredConclusion"), "security conclusion"
        )
        if conclusion not in {"success", "neutral"}:
            raise PolicyError("unsupported security conclusion")
        if name in security_names:
            raise PolicyError(f"duplicate security check: {name}")
        security_names.add(name)
        observed_security[name] = conclusion
    for name, conclusion in MANDATORY_SECURITY_CHECKS.items():
        if observed_security.get(name) != conclusion:
            raise PolicyError(
                f"mandatory security check is absent or weakened: {name}"
            )

    external = value.get("externalGates")
    if not isinstance(external, list) or not external:
        raise PolicyError("externalGates must be a non-empty list")
    external_names: set[str] = set()
    frozen_source: str | None = None
    for row in external:
        if not isinstance(row, dict):
            raise PolicyError("external gate rows must be objects")
        name = _nonempty_string(row.get("name"), "external gate name")
        if name in external_names:
            raise PolicyError(f"duplicate external gate: {name}")
        external_names.add(name)
        state = row.get("state")
        if state not in {"missing_external", "satisfied_external"}:
            raise PolicyError("unsupported external gate state")
        evidence = row.get("evidence")
        if state == "missing_external":
            if evidence is not None:
                raise PolicyError(
                    f"missing external gate must not carry evidence: {name}"
                )
        else:
            _validate_external_evidence(evidence, name)
            if frozen_source is None:
                frozen_source = _frozen_source_identity(root)
            if evidence["subjectSha"] != frozen_source:
                raise PolicyError(
                    f"external gate is not bound to the frozen source: {name}"
                )
    missing_external = sorted(MANDATORY_EXTERNAL_GATES - external_names)
    if missing_external:
        raise PolicyError(
            "mandatory external gates are absent: " + ", ".join(missing_external)
        )
    return value


POLICY = load_policy()
MAP = POLICY["implementationMap"]
ROOT = POLICY["sourceRoot"]
INPUTS = tuple(POLICY["sourceInputs"])
OBJECT_INPUTS = tuple(POLICY["sourceObjectInputs"])
CLAIMS = tuple(POLICY["promotionClaims"])
REQUIRED_CHECKS = {
    row["name"]: row["workflow"] for row in POLICY["requiredChecks"]
}
SECURITY_CHECKS = {
    row["name"]: row["requiredConclusion"] for row in POLICY["securityChecks"]
}
