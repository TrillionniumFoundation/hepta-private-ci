"""Cross-bind the frozen v2 admission, execution freeze, and result manifest.

The original provider source intentionally remains byte-for-byte frozen with
its earlier v1 admission helper.  This module is the narrow compatibility
layer for the later v2 admission and atomic execution-freeze contracts.  It
validates records only; it never invokes the provider, opens frame payloads,
allocates an execution key, or grants scientific or production qualification.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from qualification.hcsn_currentstate_n256_execution_freeze_protocol import (
    execution_freeze,
)
from qualification.hcsn_currentstate_n256_provider_fullstate_bridge import (
    bridge as fullstate_bridge,
)
from qualification.hcsn_currentstate_n256_uniformization_admission_contract import (
    admission_contract,
)
from qualification.hcsn_currentstate_n256_uniformization_provider_intent import (
    provider as frozen_provider,
)


LEGACY_PROVIDER_ADMISSION_SCHEMA = "hcsn-n256-uniformization-provider-admission-v1"
CURRENT_ADMISSION_SCHEMA = "hcsn-n256-uniformization-provider-admission-v2"
EXPECTED_PARENT_IDENTITIES = {
    "provider_source_sha256": "602dcedd5827a35fbee81b51687a8e8bc3f4038f519a308eef3e884d088e2be2",
    "provider_request_sha256": "72cf751d50a43311cc5079e8fe35a5137eafa0f7fed6a0b1a0fcafec40a8b275",
    "precision_policy_source_sha256": "7298330e00de24a4b823dcf62d344437d14f7f9643327489e81c557ed984ab08",
    "precision_policy_request_sha256": "efedc79f156094b00573db681bd934d0b1e426d667d0365315e0a81ec53edbcd",
    "implementation_review_source_sha256": "d767f5a361200ffa200934bb603e3864d32355b8c833b46a5a826c0ddda01753",
    "implementation_review_request_sha256": "4f7e90cdb5901e32e23b335bb8d49c13f7599712564d4b61775e3f5e87054a50",
}
RESOURCE_BINDINGS = {
    "runtime_profile_sha256": "runtime_profile",
    "host_snapshot_sha256": "host_snapshot",
    "ancestor_cgroup_snapshot_sha256": "ancestor_cgroup_snapshot",
    "allocation_sha256": "allocation",
    "calendar_sha256": "calendar",
}
EXTERNAL_BINDINGS = (
    "provider_author_identity_sha256",
    "external_reviewer_identity_sha256",
    "external_reviewer_custody_sha256",
    "external_review_artifact_sha256",
)


class AdmissionBridgeError(ValueError):
    """Raised before mixed-lineage or incompletely bound records are accepted."""


@dataclass(frozen=True)
class PreexecutionBundle:
    bundle_consistent: bool
    admission_sha256: str
    execution_freeze_sha256: str
    execution_key: str
    resource_original_count: int
    external_original_count: int
    provider_calls: int = 0
    dynamic_calls: int = 0
    matrix_exponential_calls: int = 0
    oracle_calls: int = 0
    model_calls: int = 0
    torch_calls: int = 0
    optimizer_calls: int = 0
    training_calls: int = 0
    largegrid_qualification: bool = False
    production_adoption: bool = False


@dataclass(frozen=True)
class PostexecutionBundle:
    preexecution: PreexecutionBundle
    manifest_bound: bool
    certificate_set_sha256: str
    provider_calls: int = 0
    dynamic_calls: int = 0
    matrix_exponential_calls: int = 0
    oracle_calls: int = 0
    model_calls: int = 0
    torch_calls: int = 0
    optimizer_calls: int = 0
    training_calls: int = 0
    largegrid_qualification: bool = False
    production_adoption: bool = False


def _parse_utc(value, field):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AdmissionBridgeError(f"noncanonical UTC timestamp: {field}")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise AdmissionBridgeError(f"noncanonical UTC timestamp: {field}") from error
    if parsed.tzinfo != timezone.utc or parsed.microsecond != 0:
        raise AdmissionBridgeError(f"noncanonical UTC timestamp: {field}")
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise AdmissionBridgeError(f"noncanonical UTC timestamp: {field}")
    return parsed


def _require_frozen_schema_transition():
    if frozen_provider.ADMISSION_SCHEMA != LEGACY_PROVIDER_ADMISSION_SCHEMA:
        raise AdmissionBridgeError("frozen provider v1 admission identity changed")
    if admission_contract.ADMISSION_SCHEMA != CURRENT_ADMISSION_SCHEMA:
        raise AdmissionBridgeError("current v2 admission identity changed")
    if LEGACY_PROVIDER_ADMISSION_SCHEMA == CURRENT_ADMISSION_SCHEMA:
        raise AdmissionBridgeError("admission compatibility bridge is no longer explicit")


def validate_preexecution_bundle(admission, freeze):
    """Validate the two records independently and then require exact cross-links."""

    _require_frozen_schema_transition()
    admission_result = admission_contract.validate_future_admission(
        admission, EXPECTED_PARENT_IDENTITIES
    )
    freeze_result = execution_freeze.validate_future_execution_freeze(freeze)
    if admission["provider_source_sha256"] != execution_freeze.PROVIDER_SOURCE_SHA256:
        raise AdmissionBridgeError("provider source is not cross-bound")
    if admission["operator_roster_sha256"] != fullstate_bridge.OPERATOR_ROSTER_SHA256:
        raise AdmissionBridgeError("operator roster is not cross-bound")
    if admission["segment_roster_sha256"] != fullstate_bridge.SEGMENT_ROSTER_SHA256:
        raise AdmissionBridgeError("segment roster is not cross-bound")
    if admission["execution_key"] != freeze["execution_key"]:
        raise AdmissionBridgeError("execution key is not cross-bound")
    if admission["execution_request_sha256"] != freeze["execution_request_sha256"]:
        raise AdmissionBridgeError("execution request is not cross-bound")
    for admission_field, freeze_name in RESOURCE_BINDINGS.items():
        if admission[admission_field] != freeze["resource_originals"][freeze_name]["sha256"]:
            raise AdmissionBridgeError(f"resource original is not cross-bound: {freeze_name}")
    for field in EXTERNAL_BINDINGS:
        if admission[field] != freeze[field]:
            raise AdmissionBridgeError(f"external original is not cross-bound: {field}")
    admitted_at = _parse_utc(admission["created_at_utc"], "created_at_utc")
    execution_start = _parse_utc(
        freeze["execution_not_before_utc"], "execution_not_before_utc"
    )
    if admitted_at > execution_start:
        raise AdmissionBridgeError("provider admission was created after execution start")
    if not admission_result.admitted or not freeze_result.complete:
        raise AdmissionBridgeError("validated records did not reach their narrow gates")
    return PreexecutionBundle(
        bundle_consistent=True,
        admission_sha256=admission["admission_sha256"],
        execution_freeze_sha256=freeze["freeze_sha256"],
        execution_key=admission["execution_key"],
        resource_original_count=freeze_result.resource_original_count,
        external_original_count=freeze_result.external_original_count,
    )


def validate_postexecution_bundle(admission, freeze, manifest):
    """Bind a validated output manifest to its exact preexecution records."""

    preexecution = validate_preexecution_bundle(admission, freeze)
    fullstate_bridge.validate_future_manifest(manifest)
    if manifest["provider_admission_sha256"] != preexecution.admission_sha256:
        raise AdmissionBridgeError("manifest provider admission is not cross-bound")
    if manifest["execution_freeze_sha256"] != preexecution.execution_freeze_sha256:
        raise AdmissionBridgeError("manifest execution freeze is not cross-bound")
    return PostexecutionBundle(
        preexecution=preexecution,
        manifest_bound=True,
        certificate_set_sha256=manifest["certificate_set_sha256"],
    )
