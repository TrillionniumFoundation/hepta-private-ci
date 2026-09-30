"""Canonical, non-spliceable readiness evidence for control.engineering.

The manifest binds one repository candidate, one workflow run/attempt, the two
product execution lanes, exact GitHub job identities, runner/toolchain closure,
repository evidence hashes, artifacts and externally signed acceptance facts.
Missing, failed, cancelled, skipped or cross-attempt evidence fails closed.

The manifest is evidence only.  It never grants runtime, merge, deployment,
promotion, activation, release or external-effect authority.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import time

from .control_plane import EngineeringError, bounded_tuple, semantic_digest
from .evidence import SignatureTrustStore
from .git_security import run_git
from .key_custody_continuity import (
    KeyCustodyContinuityReceipt,
    verify_key_custody_continuity,
)

MANIFEST_SCHEMA = "hepta.control-engineering-canonical-readiness.v1"
PAIR_SCHEMA = "hepta.control-engineering-product-receipt-pair.v3"
ACCEPTANCE_SCHEMA = "hepta.control-engineering-external-acceptance.v1"
MAX_JOBS = 256
MAX_ARTIFACTS = 128
MAX_REQUIRED_JOBS = 32
MAX_EXCEPTION_RECORDS = 32
MAX_ACCEPTANCE_RECEIPTS = 16
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

_ACCEPTANCE_ISSUERS = {
    "independent_review": "independent_evaluator",
    "external_integration": "integration_observer",
    "deployment_acceptance": "deployment_authority",
    "rollback_rehearsal": "deployment_authority",
    "external_audit_anchor": "audit_anchor_service",
}


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _identity(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or value != value.strip()
        or "\x00" in value
    ):
        raise EngineeringError(label)
    return value


def _sha1(value: object, label: str) -> str:
    if not isinstance(value, str) or value == "0" * 40 or _SHA1.fullmatch(value) is None:
        raise EngineeringError(label)
    return value


def _sha256(value: object, label: str, *, allow_zero: bool = False) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise EngineeringError(label)
    if not allow_zero and value == "0" * 64:
        raise EngineeringError(label)
    return value


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise EngineeringError(label)
    return value


def _canonical_pair(pair: Mapping[str, object]) -> dict[str, object]:
    value = dict(pair)
    if value.get("schema") != PAIR_SCHEMA:
        raise EngineeringError("readiness_pair_schema")
    for field in ("runtimeAuthority", "mergeAuthority", "releaseAuthority"):
        if value.get(field) is not False:
            raise EngineeringError("readiness_pair_authority_delta")
    pair_digest = _sha256(value.get("pairDigest"), "readiness_pair_digest")
    unsigned = dict(value)
    unsigned.pop("pairDigest", None)
    if pair_digest != _digest(unsigned):
        raise EngineeringError("readiness_pair_digest_mismatch")
    source_receipt = _sha256(
        value.get("sourceProductReceiptDigest"),
        "readiness_source_product_receipt",
    )
    merge_receipt = _sha256(
        value.get("mergeProductReceiptDigest"),
        "readiness_merge_product_receipt",
    )
    expected_set = _digest({"baseMerge": merge_receipt, "sourceHead": source_receipt})
    if value.get("readinessReceiptSetDigest") != expected_set:
        raise EngineeringError("readiness_receipt_set_mismatch")
    _identity(value.get("repository"), "readiness_repository")
    _positive_int(value.get("repositoryId"), "readiness_repository_id")
    _positive_int(value.get("runId"), "readiness_run_id")
    _positive_int(value.get("runAttempt"), "readiness_run_attempt")
    _positive_int(value.get("pullRequestNumber"), "readiness_pull_request")
    for field in ("sourceSha", "sourceTree", "baseSha", "mergeSha", "mergeTree"):
        _sha1(value.get(field), "readiness_" + field)
    if value["mergeSha"] in {value["sourceSha"], value["baseSha"]}:
        raise EngineeringError("readiness_pair_merge_identity")
    review = value.get("githubReviewObservation")
    if review is not None:
        if (
            not isinstance(review, Mapping)
            or review.get("independentAcceptance") is not False
            or review.get("mergeAuthority") is not False
            or review.get("expectedHeadSha") != value["sourceSha"]
        ):
            raise EngineeringError("readiness_review_observation")
        observation_digest = _sha256(
            review.get("observationDigest"),
            "readiness_review_observation_digest",
        )
        unsigned_review = dict(review)
        unsigned_review.pop("observationDigest", None)
        if observation_digest != _digest(unsigned_review):
            raise EngineeringError("readiness_review_observation_digest_mismatch")
    return value


@dataclass(frozen=True)
class ExternalAcceptanceReceipt:
    schema: str
    kind: str
    repository: str
    source_sha: str
    source_tree: str
    base_sha: str
    merge_sha: str
    merge_tree: str
    workflow_sha: str
    run_id: int
    run_attempt: int
    evidence_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    accepted: bool
    signature: str = ""


def verify_external_acceptance(
    receipt: ExternalAcceptanceReceipt,
    trust_store: SignatureTrustStore,
    *,
    pair: Mapping[str, object],
    workflow_sha: str,
    now_ns: int | None = None,
) -> str:
    if not isinstance(receipt, ExternalAcceptanceReceipt):
        raise EngineeringError("readiness_acceptance_receipt_required")
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise EngineeringError("invalid_time")
    if receipt.schema != ACCEPTANCE_SCHEMA or receipt.kind not in _ACCEPTANCE_ISSUERS:
        raise EngineeringError("readiness_acceptance_schema")
    if receipt.issuer != _ACCEPTANCE_ISSUERS[receipt.kind]:
        raise EngineeringError("readiness_acceptance_issuer")
    if receipt.accepted is not True:
        raise EngineeringError("readiness_acceptance_not_accepted")
    _identity(receipt.signing_identity, "readiness_acceptance_signing_identity")
    _sha256(receipt.evidence_digest, "readiness_acceptance_evidence_digest")
    _positive_int(receipt.run_id, "readiness_run_id")
    _positive_int(receipt.run_attempt, "readiness_run_attempt")
    if (
        receipt.repository != pair["repository"]
        or receipt.source_sha != pair["sourceSha"]
        or receipt.source_tree != pair["sourceTree"]
        or receipt.base_sha != pair["baseSha"]
        or receipt.merge_sha != pair["mergeSha"]
        or receipt.merge_tree != pair["mergeTree"]
        or receipt.workflow_sha != workflow_sha
        or receipt.run_id != pair["runId"]
        or receipt.run_attempt != pair["runAttempt"]
    ):
        raise EngineeringError("readiness_acceptance_candidate_mismatch")
    if (
        type(receipt.observed_unix_ns) is not int
        or type(receipt.expires_unix_ns) is not int
        or receipt.observed_unix_ns < 0
        or not receipt.observed_unix_ns <= now < receipt.expires_unix_ns
    ):
        raise EngineeringError("readiness_acceptance_stale")
    if not trust_store.verify(
        receipt,
        receipt.issuer,
        receipt.signing_identity,
        receipt.signature,
    ):
        raise EngineeringError("readiness_acceptance_signature")
    return semantic_digest(asdict(receipt))


def _jobs(
    document: Mapping[str, object],
    *,
    pair: Mapping[str, object],
    workflow_sha: str,
    required_job_names: Sequence[str],
) -> tuple[dict[str, dict[str, object]], list[str]]:
    _positive_int(document.get("runId"), "readiness_run_id")
    _positive_int(document.get("runAttempt"), "readiness_run_attempt")
    if (
        document.get("runId") != pair["runId"]
        or document.get("runAttempt") != pair["runAttempt"]
        or document.get("workflowSha") != workflow_sha
    ):
        raise EngineeringError("readiness_job_attempt_splice")
    rows = document.get("jobs")
    if not isinstance(rows, list) or len(rows) > MAX_JOBS:
        raise EngineeringError("readiness_jobs_shape")
    if (
        not required_job_names
        or len(required_job_names) > MAX_REQUIRED_JOBS
    ):
        raise EngineeringError("readiness_required_jobs")
    for name in required_job_names:
        _identity(name, "readiness_required_job_name")
    if len(set(required_job_names)) != len(required_job_names):
        raise EngineeringError("readiness_required_jobs")

    by_name: dict[str, dict[str, object]] = {}
    seen_ids: set[int] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise EngineeringError("readiness_job_shape")
        name = _identity(row.get("name"), "readiness_job_name")
        if name not in required_job_names:
            continue
        if name in by_name:
            raise EngineeringError("readiness_duplicate_required_job")
        job_id = _positive_int(row.get("id"), "readiness_job_id")
        if job_id in seen_ids:
            raise EngineeringError("readiness_job_identity_collision")
        seen_ids.add(job_id)
        status = row.get("status")
        conclusion = row.get("conclusion")
        if status not in {"queued", "in_progress", "completed"}:
            raise EngineeringError("readiness_job_status")
        if conclusion not in {
            None,
            "success",
            "failure",
            "cancelled",
            "skipped",
            "timed_out",
            "action_required",
            "stale",
            "startup_failure",
            "neutral",
        }:
            raise EngineeringError("readiness_job_conclusion")
        by_name[name] = {
            "jobId": job_id,
            "status": status,
            "conclusion": conclusion,
            "startedAt": row.get("started_at"),
            "completedAt": row.get("completed_at"),
            "runnerName": row.get("runner_name"),
            "runnerGroupId": row.get("runner_group_id"),
        }
    blockers: list[str] = []
    for name in required_job_names:
        observed = by_name.get(name)
        if observed is None:
            blockers.append("required_job_missing:" + name)
        elif observed["status"] != "completed":
            blockers.append("required_job_not_completed:" + name)
        elif observed["conclusion"] != "success":
            blockers.append(
                "required_job_" + str(observed["conclusion"] or "unknown") + ":" + name
            )
    return by_name, blockers


def _runner_profile(value: Mapping[str, object]) -> dict[str, object]:
    required = (
        "runnerImageDigest",
        "toolchainDigest",
        "environmentAllowlistDigest",
        "sbomDigest",
        "isolationProfileDigest",
    )
    result = dict(value)
    for field in required:
        _sha256(result.get(field), "readiness_" + field)
    _identity(result.get("targetTriple"), "readiness_target_triple")
    _identity(result.get("runnerImage"), "readiness_runner_image")
    return result


def _repository_evidence(value: Mapping[str, object], pair: Mapping[str, object]) -> dict[str, object]:
    result = dict(value)
    schema_version = result.get("schemaVersion")
    if type(schema_version) is not int or schema_version < 1:
        raise EngineeringError("readiness_schema_version")
    for field in (
        "migrationHash",
        "testSetHash",
        "implementationMapHash",
        "documentationHash",
        "sourceTreeHash",
        "qualificationProfileHash",
    ):
        _sha256(result.get(field), "readiness_" + field)
    if result.get("sourceTreeSha1") != pair["sourceTree"]:
        raise EngineeringError("readiness_source_tree_evidence_mismatch")
    return result


def _artifacts(values: Mapping[str, object]) -> dict[str, str]:
    if not values or len(values) > MAX_ARTIFACTS:
        raise EngineeringError("readiness_artifacts")
    result: dict[str, str] = {}
    for name, value in values.items():
        result[_identity(name, "readiness_artifact_name")] = _sha256(
            value,
            "readiness_artifact_digest",
        )
    return dict(sorted(result.items()))


def build_canonical_readiness_manifest(
    pair_receipt: Mapping[str, object],
    jobs_document: Mapping[str, object],
    runner_profile: Mapping[str, object],
    repository_evidence: Mapping[str, object],
    artifact_hashes: Mapping[str, object],
    *,
    workflow_sha: str,
    required_job_names: Sequence[str],
    acceptance_receipts: Iterable[ExternalAcceptanceReceipt] = (),
    custody_receipt: KeyCustodyContinuityReceipt | None = None,
    previous_custody_receipt: KeyCustodyContinuityReceipt | None = None,
    trust_store: SignatureTrustStore | None = None,
    exception_records: Sequence[Mapping[str, object]] = (),
    now_ns: int | None = None,
    evidence_ttl_ns: int = 30 * 24 * 60 * 60 * 1_000_000_000,
) -> dict[str, object]:
    """Build the sole readiness projection for one exact workflow attempt."""
    pair = _canonical_pair(pair_receipt)
    workflow_sha = _sha1(workflow_sha, "readiness_workflow_sha")
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise EngineeringError("invalid_time")
    if type(evidence_ttl_ns) is not int or evidence_ttl_ns <= 0:
        raise EngineeringError("readiness_evidence_ttl")

    job_ids, blockers = _jobs(
        jobs_document,
        pair=pair,
        workflow_sha=workflow_sha,
        required_job_names=required_job_names,
    )
    runner = _runner_profile(runner_profile)
    evidence = _repository_evidence(repository_evidence, pair)
    artifacts = _artifacts(artifact_hashes)

    if len(exception_records) > MAX_EXCEPTION_RECORDS:
        raise EngineeringError("readiness_exception_limit")
    exceptions: list[dict[str, object]] = []
    for row in exception_records:
        if not isinstance(row, Mapping):
            raise EngineeringError("readiness_exception_shape")
        record = dict(row)
        _identity(record.get("exceptionId"), "readiness_exception_id")
        _identity(record.get("reason"), "readiness_exception_reason")
        _sha256(record.get("receiptDigest"), "readiness_exception_digest")
        exceptions.append(record)
    if exceptions:
        blockers.append("exception_records_present")

    receipts = bounded_tuple(
        acceptance_receipts, MAX_ACCEPTANCE_RECEIPTS, "readiness_acceptance_limit"
    )
    external: dict[str, str] = {}
    acceptance_signers: dict[str, str] = {}
    expiry = now + evidence_ttl_ns
    if receipts:
        if trust_store is None:
            raise EngineeringError("readiness_acceptance_trust_store_required")
        signers: set[str] = set()
        for receipt in receipts:
            if not isinstance(receipt, ExternalAcceptanceReceipt):
                raise EngineeringError("readiness_acceptance_receipt_required")
            if receipt.kind in external:
                raise EngineeringError("readiness_duplicate_acceptance_kind")
            digest = verify_external_acceptance(
                receipt,
                trust_store,
                pair=pair,
                workflow_sha=workflow_sha,
                now_ns=now,
            )
            if receipt.signing_identity in signers:
                raise EngineeringError("readiness_acceptance_signer_collision")
            signers.add(receipt.signing_identity)
            external[receipt.kind] = digest
            acceptance_signers[receipt.kind] = receipt.signing_identity
            expiry = min(expiry, receipt.expires_unix_ns)

    custody_digest = None
    if custody_receipt is not None:
        if trust_store is None:
            raise EngineeringError("readiness_custody_trust_store_required")
        custody_digest = verify_key_custody_continuity(
            custody_receipt,
            trust_store,
            expected_repository=str(pair["repository"]),
            expected_source_sha=str(pair["sourceSha"]),
            expected_merge_sha=str(pair["mergeSha"]),
            previous_receipt=previous_custody_receipt,
            now_ns=now,
        )
        expiry = min(expiry, custody_receipt.expires_unix_ns)
        review_signer = acceptance_signers.get("independent_review")
        if review_signer is not None:
            current_reviewer = any(
                key.role == "independent_evaluator"
                and key.subject_signing_identity == review_signer
                for key in custody_receipt.current_keys
            )
            retiring_reviewer = (
                custody_receipt.rotation_state == "dual_window"
                and now < custody_receipt.dual_window_expires_unix_ns
                and any(
                    key.role == "independent_evaluator"
                    and key.subject_signing_identity == review_signer
                    for key in custody_receipt.retiring_keys
                )
            )
            if not current_reviewer and not retiring_reviewer:
                raise EngineeringError("readiness_review_custody_mismatch")
            if not current_reviewer:
                expiry = min(expiry, custody_receipt.dual_window_expires_unix_ns)

    internal_ready = not blockers
    independent = "independent_review" in external
    merge_ready = internal_ready and independent and not exceptions
    production_required = {
        "independent_review",
        "external_integration",
        "deployment_acceptance",
        "rollback_rehearsal",
        "external_audit_anchor",
    }
    production_qualified = (
        merge_ready
        and custody_digest is not None
        and production_required.issubset(external)
    )

    if not independent:
        blockers.append("independent_review_missing")
    for kind in sorted(production_required - set(external)):
        if kind != "independent_review":
            blockers.append(kind + "_missing")
    if custody_digest is None:
        blockers.append("key_custody_continuity_missing")

    manifest: dict[str, object] = {
        "schema": MANIFEST_SCHEMA,
        "source_head_sha": pair["sourceSha"],
        "merge_sha": pair["mergeSha"],
        "source_tree_sha1": pair["sourceTree"],
        "source_tree_hash": evidence["sourceTreeHash"],
        "merge_tree_sha1": pair["mergeTree"],
        "base_sha": pair["baseSha"],
        "workflow_sha": workflow_sha,
        "workflow_run_id": pair["runId"],
        "attempt_id": pair["runAttempt"],
        "pull_request_number": pair["pullRequestNumber"],
        "job_ids": job_ids,
        "runner_image_digest": runner["runnerImageDigest"],
        "toolchain_digest": runner["toolchainDigest"],
        "target_triple": runner["targetTriple"],
        "environment_allowlist_digest": runner["environmentAllowlistDigest"],
        "sbom_digest": runner["sbomDigest"],
        "isolation_profile_digest": runner["isolationProfileDigest"],
        "schema_version": evidence["schemaVersion"],
        "migration_hash": evidence["migrationHash"],
        "test_set_hash": evidence["testSetHash"],
        "qualification_profile_hash": evidence["qualificationProfileHash"],
        "implementation_map_hash": evidence["implementationMapHash"],
        "documentation_hash": evidence["documentationHash"],
        "artifact_hashes": artifacts,
        "required_check_results": {
            name: job_ids.get(name) for name in required_job_names
        },
        "required_job_names": list(required_job_names),
        "review_signatures": {
            "githubObservation": pair.get("githubReviewObservation"),
            "independentReceiptDigest": external.get("independent_review"),
        },
        "external_acceptance_receipts": dict(sorted(external.items())),
        "key_custody_continuity_digest": custody_digest,
        "exception_records": exceptions,
        "evidence_expiry": expiry,
        "internalEvidenceReady": internal_ready,
        "mergeReady": merge_ready,
        "productionQualified": production_qualified,
        "blockers": sorted(set(blockers)),
        "runtimeAuthority": False,
        "mergeAuthority": False,
        "activationAuthority": False,
        "promotionAuthority": False,
        "releaseAuthority": False,
        "externalEffectAuthority": False,
        "product_receipt_pair_digest": pair["pairDigest"],
    }
    manifest["manifest_digest"] = _digest(manifest)
    return manifest


def verify_canonical_readiness_manifest(
    value: Mapping[str, object], *, now_ns: int | None = None,
    expected_required_job_names: Sequence[str] | None = None,
) -> str:
    """Check retained projection consistency and expiry, not external authenticity.

    Authenticate the input artifact through its owner and rebuild from signed
    receipts when accepting external evidence. A recomputed JSON hash alone is
    not an acceptance signature. Consumers can pin their required job policy.
    """
    if not isinstance(value, Mapping) or value.get("schema") != MANIFEST_SCHEMA:
        raise EngineeringError("readiness_manifest_schema")
    for field in (
        "runtimeAuthority",
        "mergeAuthority",
        "activationAuthority",
        "promotionAuthority",
        "releaseAuthority",
        "externalEffectAuthority",
    ):
        if value.get(field) is not False:
            raise EngineeringError("readiness_manifest_authority_delta")
    digest = _sha256(value.get("manifest_digest"), "readiness_manifest_digest")
    unsigned = dict(value)
    unsigned.pop("manifest_digest", None)
    if digest != _digest(unsigned):
        raise EngineeringError("readiness_manifest_digest_mismatch")
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise EngineeringError("invalid_time")
    evidence_expiry = value.get("evidence_expiry")
    if type(evidence_expiry) is not int or now >= evidence_expiry:
        raise EngineeringError("readiness_manifest_expired")
    names = value.get("required_job_names")
    jobs = value.get("job_ids")
    checks = value.get("required_check_results")
    if (
        not isinstance(names, list) or not names or len(names) > MAX_REQUIRED_JOBS
        or any(not isinstance(name, str) for name in names)
        or len(set(names)) != len(names)
        or not isinstance(jobs, Mapping) or not isinstance(checks, Mapping)
        or set(checks) != set(names) or not set(jobs).issubset(names)
    ):
        raise EngineeringError("readiness_manifest_required_jobs")
    if expected_required_job_names is not None and list(expected_required_job_names) != names:
        raise EngineeringError("readiness_manifest_job_policy_mismatch")
    rows = []
    for name in names:
        _identity(name, "readiness_required_job_name")
        if checks[name] != jobs.get(name):
            raise EngineeringError("readiness_manifest_job_projection")
        row = jobs.get(name)
        if row is None:
            continue
        if not isinstance(row, Mapping):
            raise EngineeringError("readiness_manifest_job_projection")
        rows.append({"name": name, "id": row.get("jobId"),
                     "status": row.get("status"), "conclusion": row.get("conclusion")})
    _, job_blockers = _jobs(
        {"runId": value.get("workflow_run_id"), "runAttempt": value.get("attempt_id"),
         "workflowSha": value.get("workflow_sha"), "jobs": rows},
        pair={"runId": value.get("workflow_run_id"), "runAttempt": value.get("attempt_id")},
        workflow_sha=_sha1(value.get("workflow_sha"), "readiness_workflow_sha"),
        required_job_names=names,
    )
    blockers = value.get("blockers")
    if not isinstance(blockers, list) or any(not isinstance(row, str) for row in blockers):
        raise EngineeringError("readiness_manifest_blockers")
    for field in ("internalEvidenceReady", "mergeReady", "productionQualified"):
        if type(value.get(field)) is not bool:
            raise EngineeringError("readiness_manifest_projection_type")
    internal_ready = value.get("internalEvidenceReady") is True
    merge_ready = value.get("mergeReady") is True
    production = value.get("productionQualified") is True
    external = value.get("external_acceptance_receipts")
    if not isinstance(external, Mapping):
        raise EngineeringError("readiness_manifest_external_receipts")
    for kind, receipt_digest in external.items():
        if kind not in _ACCEPTANCE_ISSUERS:
            raise EngineeringError("readiness_manifest_external_receipts")
        _sha256(receipt_digest, "readiness_manifest_external_digest")
    exceptions = value.get("exception_records")
    if not isinstance(exceptions, list) or len(exceptions) > MAX_EXCEPTION_RECORDS:
        raise EngineeringError("readiness_manifest_exceptions")
    expected_job_blockers = set(job_blockers)
    if exceptions:
        expected_job_blockers.add("exception_records_present")
    observed_job_blockers = {
        row for row in blockers
        if row.startswith("required_job_") or row == "exception_records_present"
    }
    if observed_job_blockers != expected_job_blockers or internal_ready != (not expected_job_blockers):
        raise EngineeringError("readiness_manifest_internal_projection")
    expected_merge = (
        internal_ready
        and "independent_review" in external
        and not exceptions
    )
    if merge_ready != expected_merge:
        raise EngineeringError("readiness_manifest_merge_projection")
    custody = value.get("key_custody_continuity_digest")
    if custody is not None:
        _sha256(custody, "readiness_manifest_custody_digest")
    expected_production = (
        expected_merge
        and value.get("key_custody_continuity_digest") is not None
        and {
            "independent_review",
            "external_integration",
            "deployment_acceptance",
            "rollback_rehearsal",
            "external_audit_anchor",
        }.issubset(external)
    )
    if production != expected_production:
        raise EngineeringError("readiness_manifest_production_projection")
    return digest


def _hash_paths(root: Path, paths: Sequence[str]) -> str:
    output = run_git(root, "ls-tree", "-r", "--full-tree", "HEAD", "--", *paths)
    if not output:
        raise EngineeringError("readiness_evidence_paths_empty")
    return hashlib.sha256(output.encode("utf-8")).hexdigest()


def capture_repository_evidence(root: Path, *, source_tree_sha1: str) -> dict[str, object]:
    root = root.resolve()
    source_tree_sha1 = _sha1(source_tree_sha1, "readiness_source_tree_sha1")
    observed_tree = run_git(root, "rev-parse", "HEAD^{tree}")
    if observed_tree != source_tree_sha1:
        raise EngineeringError("readiness_source_tree_checkout_mismatch")
    module = "tools/hepta-engineering-control/control_engineering_v2"
    return {
        "schemaVersion": 10,
        "sourceTreeSha1": source_tree_sha1,
        "sourceTreeHash": hashlib.sha256(source_tree_sha1.encode("ascii")).hexdigest(),
        "migrationHash": _hash_paths(
            root,
            [f"{module}/SCHEMA.sql", f"{module}/control_plane.py"],
        ),
        "testSetHash": _hash_paths(
            root,
            ["tools/hepta-engineering-control", ".github/workflows/hepta-consolidated-source.yml"],
        ),
        "implementationMapHash": _hash_paths(
            root,
            [
                "docs/modules/control.engineering/IMPLEMENTATION_MAP.json",
                "docs/modules/control.engineering/TRACEABILITY.json",
                "docs/modules/control.engineering/COMPONENTS.json",
            ],
        ),
        "documentationHash": _hash_paths(
            root,
            ["docs/modules/control.engineering", "tools/hepta-engineering-control/INTEGRATION_HANDOFF.md"],
        ),
        "qualificationProfileHash": _hash_paths(
            root,
            [f"{module}/qualification_profile.py"],
        ),
    }


def _load(path: Path) -> dict[str, object]:
    with path.open("rb") as stream:
        encoded = stream.read(8 * 1024 * 1024 + 1)
    if len(encoded) > 8 * 1024 * 1024:
        raise EngineeringError("readiness_document_budget")
    document = json.loads(encoded)
    if not isinstance(document, dict):
        raise EngineeringError("readiness_document_shape")
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", required=True, type=Path)
    parser.add_argument("--jobs", required=True, type=Path)
    parser.add_argument("--runner-profile", required=True, type=Path)
    parser.add_argument("--artifact-hashes", required=True, type=Path)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--required-job", action="append", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--now-ns", type=int)
    parser.add_argument("--ttl-seconds", type=int, default=30 * 24 * 60 * 60)
    args = parser.parse_args(argv)
    pair = _canonical_pair(_load(args.pair))
    evidence = capture_repository_evidence(
        args.repository,
        source_tree_sha1=str(pair["sourceTree"]),
    )
    manifest = build_canonical_readiness_manifest(
        pair,
        _load(args.jobs),
        _load(args.runner_profile),
        evidence,
        _load(args.artifact_hashes),
        workflow_sha=args.workflow_sha,
        required_job_names=tuple(args.required_job),
        now_ns=args.now_ns,
        evidence_ttl_ns=args.ttl_seconds * 1_000_000_000,
    )
    verify_canonical_readiness_manifest(manifest, now_ns=args.now_ns)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
