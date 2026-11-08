"""Review foundation bytes and consumption declarations, never execution authority."""

import re

import hepta_cell_joint_config as joint


SCHEMA = "hepta.cell-research-foundation.v1"
SCHEMA_V2 = "hepta.cell-research-foundation.v2"
ARTIFACT_ROLES = (
    "trajectory",
    "source_registry",
    "recovery",
    "successor",
    "evaluator_owner",
)
READBACK_DIGESTS = (
    "bundle_sha256",
    "model_sha256",
    "state_schema_sha256",
    "encoder_sha256",
    "backend_sha256",
)


def review(document, evidence, joint_result):
    """Inspect declarations; the caller must reconcile their shared bindings."""
    if not isinstance(document, dict) or document.get("schema") not in (
        SCHEMA,
        SCHEMA_V2,
    ):
        raise ValueError("unknown foundation schema")
    legacy = document["schema"] == SCHEMA
    fields = {
        "schema",
        "joint_configuration_sha256",
        "protocol_sha256",
        "artifacts",
    } | (set() if legacy else {"declared_successor"})
    if set(document) != fields:
        raise ValueError("foundation has unknown or missing fields")
    artifacts = document["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != set(ARTIFACT_ROLES):
        raise ValueError("all five foundation artifact roles must be bound")
    expectation = None
    if not legacy:
        expectation = document["declared_successor"]
        if not isinstance(expectation, dict) or set(expectation) != {
            "task_id",
            "model_role",
        }:
            raise ValueError(
                "successor expectation requires exactly task and model role"
            )
        if (
            not isinstance(expectation["task_id"], str)
            or re.fullmatch(r"[\w./:@-]{1,256}", expectation["task_id"]) is None
            or expectation["model_role"] not in joint.MODEL_ROLES
        ):
            raise ValueError(
                "successor expectation requires a bounded task and explicit model role"
            )
        expectation = dict(expectation)
    checked, readback = {}, None
    for role in ARTIFACT_ROLES:
        binding = artifacts[role]
        if role == "successor" and not legacy:
            readback = evidence.read(binding)
            checked[role] = dict(binding)
        else:
            checked[role] = evidence.read(binding, document=False)
    successor_review = None
    successor_status = "unsupported" if legacy else "unverified"
    successor_reason = "legacy_foundation_schema"
    if not legacy:
        if (
            not isinstance(readback, dict)
            or set(readback) != {"schema", "task_id", "model_role", *READBACK_DIGESTS}
            or readback["schema"] != "hepta.cell-consumption-readback.v1"
        ):
            raise ValueError("unknown or incomplete successor readback")
        if any(
            not isinstance(readback[key], str)
            or joint.SHA256.fullmatch(readback[key]) is None
            for key in READBACK_DIGESTS
        ):
            raise ValueError("successor readback requires complete SHA256 identities")
        if any(readback[key] != expectation[key] for key in ("task_id", "model_role")):
            raise ValueError(
                "successor readback conflicts with the declared expectation"
            )
        if joint_result is None:
            successor_reason = "missing_joint_configuration"
        elif joint_result.get("legacy", True):
            successor_reason = "legacy_joint_configuration"
        else:
            successor_review = joint.check_consumer_readback(
                joint_result,
                readback,
                expectation["model_role"],
                expectation["task_id"],
            )
            successor_status = "verified"
            successor_reason = "bound_to_verified_configuration"
    return {
        "schema": "hepta.cell-research-foundation-review.v1",
        "foundation_schema": document["schema"],
        "foundation_bytes_verified": True,
        "artifact_bindings": checked,
        "mechanical_ready": legacy or successor_review is not None,
        "trajectory_semantics_verified": False,
        "source_registry_semantics_verified": False,
        "recovery_verified": False,
        "evaluator_owner_authenticated": False,
        "declared_successor": expectation,
        "successor_expectation_source": None if legacy else "foundation_declaration",
        "successor_expectation_authenticated": False,
        "successor_expectation_preregistered": False,
        "successor_binding_integrity": successor_status,
        "successor_binding_reason": successor_reason,
        "successor_review": successor_review,
        "consumer_readback_authenticity_verified": False,
        "actual_successor_consumption_verified": False,
        "model_execution_verified": False,
        "blockers": [
            "ACTUAL_SUCCESSOR_CONSUMPTION_UNVERIFIED"
            if successor_review is not None
            else "SUCCESSOR_ADAPTER_UNSUPPORTED"
        ],
    }
