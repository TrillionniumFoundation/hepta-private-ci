"""Write exact-candidate diagnostics and qualification receipts."""

import os
from typing import Any

from lane_a_foundation_lib import canonical
from platform_types_candidate_support import (
    ROOT,
    CandidateBundleError,
    evidence_records,
    exact_identity,
    identity_sha256,
    parse_named_values,
    read_object,
    require_outcome_set,
    resolve_record_path,
    sha256_bytes,
    sha256_file,
    utc_now,
    write_object,
)
from platform_types_fuzz_evidence import validate_fuzz_summary

PUBLIC_API_INVENTORY = ROOT / "docs/modules/platform.types/PUBLIC_API_INVENTORY_V1.json"
DETAILED_IMPLEMENTATION_MAP = (
    ROOT / "docs/modules/platform.types/IMPLEMENTATION_MAP.json"
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
    write_object(
        args.output,
        {
            "schema": "hepta.platform-types.deep-diagnostics.v2",
            "schemaVersion": 2,
            "module": "platform.types",
            "candidateKind": identity["kind"],
            "candidateIdentity": identity,
            "candidateIdentitySha256": identity_sha256(identity),
            "generatedAtUtc": utc_now(),
            "outcomes": outcomes,
            "allRequiredChecksPassed": all(
                item == "success" for item in outcomes.values()
            ),
            "evidence": evidence_records(args.evidence, require_existing=False),
            "authoritativeQualification": False,
            "github": _github(),
            "nonClaims": _nonclaims(),
        },
    )


def _object(
    evidence: dict[str, Any], name: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    record = evidence.get(name)
    if not isinstance(record, dict) or record.get("exists") is not True:
        raise CandidateBundleError(f"required evidence is absent: {name}")
    return record, read_object(resolve_record_path(record))


def _nonnegative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_coverage_fuzz(value: dict[str, Any], record: dict[str, Any]) -> None:
    try:
        validate_fuzz_summary(value, resolve_record_path(record).parent)
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise CandidateBundleError(
            f"coverage-guided fuzz evidence is invalid: {error}"
        ) from error


def _validate_registry_benchmark(value: dict[str, Any]) -> None:
    if (
        value.get("schema") != "hepta.platform-types.registry-lookup-benchmark.v1"
        or value.get("schemaVersion") != 1
        or not _nonnegative_integer(value.get("iterationsPerLookup"))
        or value.get("iterationsPerLookup") == 0
        or value.get("acceptanceThreshold") is not None
    ):
        raise CandidateBundleError("registry workload evidence header is invalid")
    cases = value.get("cases")
    if not isinstance(cases, list) or [
        case.get("entryCount") for case in cases if isinstance(case, dict)
    ] != [8, 256]:
        raise CandidateBundleError(
            "registry workload matrix must contain exact 8 and 256 entry cases"
        )
    fields = (
        "constructionElapsedNs",
        "constructionNsPerEntry",
        "identityElapsedNs",
        "identityNsPerLookup",
        "digestElapsedNs",
        "digestNsPerLookup",
        "registryIdentityElapsedNs",
        "registryIdentityNsPerLookup",
    )
    for case in cases:
        if not isinstance(case, dict) or any(
            not _nonnegative_integer(case.get(field)) for field in fields
        ):
            raise CandidateBundleError(
                "registry workload case is incomplete or non-numeric"
            )


def _validate_generated_map_binding(
    generated_map: dict[str, Any],
    properties: dict[str, Any],
    identity: dict[str, Any],
) -> dict[str, str]:
    binding = generated_map.get("candidateBinding")
    expected = {
        "policy": "runtime_exact_git_candidate_v1",
        "commit": identity["candidateSha"],
        "tree": identity["candidateTree"],
        "publicApiInventorySha256": sha256_file(PUBLIC_API_INVENTORY),
        "detailedImplementationMapSha256": sha256_file(DETAILED_IMPLEMENTATION_MAP),
    }
    if binding != expected:
        raise CandidateBundleError(
            "generated implementation map is not bound to this exact candidate"
        )
    property_binding = {
        "commit": properties.get("generatedMapCandidateCommit"),
        "tree": properties.get("generatedMapCandidateTree"),
        "publicApiInventorySha256": properties.get(
            "generatedMapPublicApiInventorySha256"
        ),
        "detailedImplementationMapSha256": properties.get(
            "generatedMapDetailedImplementationMapSha256"
        ),
    }
    expected_property_binding = {
        key: expected[key]
        for key in (
            "commit",
            "tree",
            "publicApiInventorySha256",
            "detailedImplementationMapSha256",
        )
    }
    if property_binding != expected_property_binding:
        raise CandidateBundleError(
            "property report candidate binding differs from generated map"
        )
    return expected


def write_receipt(args: Any) -> None:
    identity = exact_identity(args)
    outcomes = _outcomes(args)
    failed = sorted(name for name, value in outcomes.items() if value != "success")
    if failed:
        raise CandidateBundleError(f"non-success receipt outcomes: {failed}")
    evidence = evidence_records(args.evidence, require_existing=True)
    bundle_record, bundle = _object(evidence, "bundle-manifest")
    property_record, properties = _object(evidence, "property-report")
    benchmark_record, registry_benchmark = _object(evidence, "registry-benchmark")
    map_record, generated_map = _object(evidence, "generated-map")
    provenance_record, provenance = _object(evidence, "provenance")
    api_record, api_diff = _object(evidence, "rustdoc-diff")
    fuzz_record, fuzz = _object(evidence, "fuzz-summary")
    catalog_record, catalog = _object(evidence, "protocol-catalog")

    if bundle.get("candidateIdentity") != identity:
        raise CandidateBundleError("document bundle candidate mismatch")
    if bundle.get("authoritativeQualification") is not False:
        raise CandidateBundleError("document bundle overclaims qualification")
    if properties.get("status") != "passed":
        raise CandidateBundleError("property report did not pass")
    _validate_registry_benchmark(registry_benchmark)
    if (
        provenance.get("status") != "passed"
        or provenance.get("candidateIdentity") != identity
    ):
        raise CandidateBundleError("Git provenance did not pass for this candidate")
    if api_diff.get("status") != "passed" or api_diff.get("breaking") is not False:
        raise CandidateBundleError("rustdoc public API semver gate did not pass")
    _validate_coverage_fuzz(fuzz, fuzz_record)
    if (
        catalog.get("schema") != "hepta.platform-types.protocol-catalog.v2"
        or catalog.get("schemaVersion") != 2
        or catalog.get("normativeSource")
        != "codex-rs/hepta-types/src/protocol_catalog_v2.rs"
        or not isinstance(catalog.get("protocolCount"), int)
        or catalog["protocolCount"] < 7
    ):
        raise CandidateBundleError("Rust-generated protocol catalog is invalid")
    if (
        generated_map.get("schema")
        != "hepta.platform-types.generated-implementation-map.v1"
    ):
        raise CandidateBundleError("generated implementation map schema mismatch")
    if generated_map.get("module") != "platform.types":
        raise CandidateBundleError("generated implementation map module mismatch")
    if generated_map.get("exportCount") != properties.get("generatedMapExportCount"):
        raise CandidateBundleError("generated implementation map export mismatch")
    if generated_map.get("operationCount") != properties.get(
        "generatedMapOperationCount"
    ):
        raise CandidateBundleError("generated implementation map operation mismatch")
    if sha256_bytes(canonical(generated_map)) != properties.get(
        "generatedImplementationMapSha256"
    ):
        raise CandidateBundleError("generated implementation map digest mismatch")
    map_binding = _validate_generated_map_binding(generated_map, properties, identity)

    write_object(
        args.output,
        {
            "schema": "hepta.platform-types.deep-qualification-receipt.v4",
            "schemaVersion": 4,
            "module": "platform.types",
            "candidateKind": identity["kind"],
            "candidateIdentity": identity,
            "candidateIdentitySha256": identity_sha256(identity),
            "generatedAtUtc": utc_now(),
            "outcomes": outcomes,
            "toolchains": {
                "msrv": args.msrv_toolchain,
                "miri": args.miri_toolchain,
                "fuzz": fuzz.get("toolchain"),
                "cargoFuzz": fuzz.get("cargoFuzzVersion"),
            },
            "evidence": evidence,
            "documentBundleSha256": bundle_record["sha256"],
            "propertyReportSha256": property_record["sha256"],
            "registryBenchmarkSha256": benchmark_record["sha256"],
            "generatedImplementationMapSha256": map_record["sha256"],
            "generatedImplementationMapCandidateBinding": map_binding,
            "generatedImplementationMapCandidateBindingSha256": sha256_bytes(
                canonical(map_binding)
            ),
            "gitProvenanceSha256": provenance_record["sha256"],
            "rustdocSemverDiffSha256": api_record["sha256"],
            "coverageFuzzSha256": fuzz_record["sha256"],
            "protocolCatalogSha256": catalog_record["sha256"],
            "performanceAcceptance": (
                "same_candidate_measurement_only_no_target_threshold"
            ),
            "status": "passed_in_current_job",
            "scope": (
                "exact Git identity, exact candidate-bound implementation map, "
                "Rust-generated protocol catalog, rustdoc API compatibility, "
                "deterministic properties, bounded registry workload measurement, "
                "coverage-guided fuzz, MSRV, native tests, Miri, consumers, and "
                "bound docs"
            ),
            **_nonclaims(),
            "github": _github(),
        },
    )
