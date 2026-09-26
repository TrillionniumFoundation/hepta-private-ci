"""Write exact-candidate diagnostics and qualification receipts."""

import os
from typing import Any

from lane_a_foundation_lib import canonical
from platform_types_candidate_support import (
    CandidateBundleError, evidence_records, exact_identity, identity_sha256,
    parse_named_values, read_object, require_outcome_set, resolve_record_path,
    sha256_bytes, utc_now, write_object,
)


def _github() -> dict[str, str | None]:
    return {
        "runId": os.environ.get("GITHUB_RUN_ID"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "job": os.environ.get("GITHUB_JOB"),
        "workflow": os.environ.get("GITHUB_WORKFLOW"),
    }


def _nonclaims() -> dict[str, str]:
    return {
        "productionActivation": "not_claimed",
        "externalAcceptance": "not_claimed",
        "promotion": "not_claimed",
        "release": "not_claimed",
    }


def _outcomes(args: Any) -> dict[str, str]:
    value = parse_named_values(args.outcome, outcomes=True)
    require_outcome_set(value)
    return value


def write_diagnostics(args: Any) -> None:
    identity = exact_identity(args)
    outcomes = _outcomes(args)
    write_object(args.output, {
        "schema": "hepta.platform-types.deep-diagnostics.v1",
        "schemaVersion": 1,
        "module": "platform.types",
        "candidateKind": identity["kind"],
        "candidateIdentity": identity,
        "candidateIdentitySha256": identity_sha256(identity),
        "generatedAtUtc": utc_now(),
        "outcomes": outcomes,
        "allRequiredChecksPassed": all(item == "success" for item in outcomes.values()),
        "evidence": evidence_records(args.evidence, require_existing=False),
        "authoritativeQualification": False,
        "github": _github(),
        "nonClaims": _nonclaims(),
    })


def _object(evidence: dict[str, Any], name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    record = evidence.get(name)
    if not isinstance(record, dict) or record.get("exists") is not True:
        raise CandidateBundleError(f"required evidence is absent: {name}")
    return record, read_object(resolve_record_path(record))


def write_receipt(args: Any) -> None:
    identity = exact_identity(args)
    outcomes = _outcomes(args)
    failed = sorted(name for name, value in outcomes.items() if value != "success")
    if failed:
        raise CandidateBundleError(f"non-success receipt outcomes: {failed}")
    evidence = evidence_records(args.evidence, require_existing=True)
    bundle_record, bundle = _object(evidence, "bundle-manifest")
    property_record, properties = _object(evidence, "property-report")
    map_record, generated_map = _object(evidence, "generated-map")

    if bundle.get("candidateIdentity") != identity:
        raise CandidateBundleError("document bundle candidate mismatch")
    if bundle.get("authoritativeQualification") is not False:
        raise CandidateBundleError("document bundle overclaims qualification")
    if properties.get("status") != "passed":
        raise CandidateBundleError("property report did not pass")
    if generated_map.get("schema") != "hepta.platform-types.generated-implementation-map.v1":
        raise CandidateBundleError("generated implementation map schema mismatch")
    if generated_map.get("module") != "platform.types":
        raise CandidateBundleError("generated implementation map module mismatch")
    if generated_map.get("exportCount") != properties.get("generatedMapExportCount"):
        raise CandidateBundleError("generated implementation map export mismatch")
    if generated_map.get("operationCount") != properties.get("generatedMapOperationCount"):
        raise CandidateBundleError("generated implementation map operation mismatch")
    if sha256_bytes(canonical(generated_map)) != properties.get("generatedImplementationMapSha256"):
        raise CandidateBundleError("generated implementation map digest mismatch")

    write_object(args.output, {
        "schema": "hepta.platform-types.deep-qualification-receipt.v1",
        "schemaVersion": 1,
        "module": "platform.types",
        "candidateKind": identity["kind"],
        "candidateIdentity": identity,
        "candidateIdentitySha256": identity_sha256(identity),
        "generatedAtUtc": utc_now(),
        "outcomes": outcomes,
        "toolchains": {"msrv": args.msrv_toolchain, "miri": args.miri_toolchain},
        "evidence": evidence,
        "documentBundleSha256": bundle_record["sha256"],
        "propertyReportSha256": property_record["sha256"],
        "generatedImplementationMapSha256": map_record["sha256"],
        "status": "passed_in_current_job",
        "scope": "exact source, generated map, properties, MSRV, native tests, Miri, and bound docs",
        **_nonclaims(),
        "github": _github(),
    })
