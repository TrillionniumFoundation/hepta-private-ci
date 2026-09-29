"""Render exact-candidate platform.types documentation evidence."""

from pathlib import Path
from typing import Any
import json
import shutil

from platform_types_candidate_support import (
    CandidateBundleError, ROOT, exact_identity, identity_sha256, sha256_file,
    utc_now, write_object,
)

DOCS = (
    "docs/modules/platform.types/TECHNICAL.md",
    "docs/modules/platform.types/TECHNICAL_CURRENT_AMENDMENT_V2.md",
    "docs/modules/platform.types/CURRENT_IMPLEMENTATION.md",
    "docs/modules/platform.types/PROTOCOL_AND_QUALIFICATION_V1.md",
    "docs/modules/platform.types/DEEP_QUALIFICATION_V1.md",
    "docs/modules/platform.types/NORMATIVE_PROTOCOL_SOURCE_V2.md",
    "docs/modules/platform.types/PUBLIC_API_INVENTORY_V1.json",
    "docs/modules/platform.types/IMPLEMENTATION_MAP.json",
    "docs/lane-a-foundation/platform.types/TRUTH_MATRIX_V1.json",
    "docs/lane-a-foundation/platform.types/CURRENT_IMPLEMENTATION.md",
    "qualification/module-execution-dossiers/detail/platform.types.md",
)
PROVENANCE = DOCS + (
    "codex-rs/hepta-types/MANIFEST_V1_CONFORMANCE.json",
    "codex-rs/hepta-types/PLATFORM_TYPES_WIRE_CONFORMANCE_V1.json",
    "codex-rs/hepta-types/CONSUMER_QUALIFICATION_V1.json",
    "codex-rs/hepta-types/src/lib.rs",
    "codex-rs/hepta-types/src/registry.rs",
    "codex-rs/hepta-types/src/registry_tests.rs",
    "codex-rs/hepta-types/src/topology.rs",
    "codex-rs/hepta-types/src/manifests.rs",
    "codex-rs/hepta-types/src/numeric_conversion.rs",
    "codex-rs/hepta-types/src/numeric_registry_v2.rs",
    "codex-rs/hepta-types/src/prompt_delivery.rs",
    "codex-rs/hepta-types/src/prompt_delivery_v2.rs",
    "codex-rs/hepta-types/src/protocol_catalog_v2.rs",
    "codex-rs/hepta-types/src/bin/platform-types-protocol-codegen.rs",
    "codex-rs/hepta-types/src/bin/platform-types-registry-bench.rs",
    "codex-rs/hepta-types/fuzz/fuzz_targets/canonical_validate.rs",
    "codex-rs/hepta-wire/src/lib.rs",
    "codex-rs/hepta-wire/src/platform_types_json.rs",
    "codex-rs/hepta-wire/src/platform_manifest_json.rs",
    "codex-rs/hepta-wire/fuzz/fuzz_targets/platform_types_json.rs",
    "codex-rs/hepta-ndu/src/random_stream_owner.rs",
    "codex-rs/hepta-supervisor/src/platform_manifest_admission.rs",
    "scripts/platform_types_public_api.py",
    "scripts/platform_types_implementation_map.py",
    "scripts/platform_types_property_checks.py",
    "scripts/platform_types_provenance.py",
    "scripts/platform_types_rustdoc_api.py",
    "scripts/test_platform_types_rustdoc_api.py",
    "scripts/platform_types_rama_lock_guard.py",
    "scripts/test_platform_types_rama_lock_guard.py",
    "scripts/platform_types_prepare_stable_rama.py",
    "scripts/platform_types_apply_closure_repair.py",
    "scripts/platform_types_candidate_bundle.py",
    "scripts/platform_types_candidate_evidence.py",
    "scripts/platform_types_candidate_render.py",
    "scripts/platform_types_independent_review.py",
    "scripts/test_platform_types_independent_review.py",
    "scripts/verify_platform_types_consumers.py",
    "scripts/run_platform_types_consumer_qualification.sh",
    "scripts/run_platform_types_coverage_fuzz.sh",
    "scripts/run_platform_types_deep_qualification.sh",
    ".github/workflows/platform-types-convergence-repair.yml",
    ".github/workflows/platform-types-deep-qualification.yml",
    ".github/workflows/platform-types-independent-review.yml",
    ".github/workflows/platform-types-lock-refresh.yml",
    ".github/workflows/blocking-ci.yml",
)
GENERATED = ("protocol-catalog.json", "protocol-catalog.md")


def _file(relative: str) -> Path:
    path = ROOT / relative
    if not path.is_file():
        raise CandidateBundleError(f"missing candidate provenance file: {relative}")
    return path


def render_bundle(args: Any) -> None:
    identity = exact_identity(args)
    output: Path = args.output_dir
    candidate_root = output.parent
    if output.exists():
        shutil.rmtree(output)
    rendered = output / "rendered-documents"
    generated_output = output / "generated-projections"
    rendered.mkdir(parents=True)
    generated_output.mkdir(parents=True)
    identity_json = json.dumps(identity, indent=2, sort_keys=True)
    rows = []
    for relative in DOCS:
        source = _file(relative)
        text = source.read_text(encoding="utf-8")
        target = rendered / f"{relative.replace('/', '__')}.candidate-bound.md"
        target.write_text(
            "# Exact-candidate projection\n\n"
            f"Source: `{relative}`  \nCandidate: `{identity['candidateSha']}`  \n"
            f"Tree: `{identity['candidateTree']}`  \nKind: `{identity['kind']}`  \n"
            f"Source SHA-256: `{sha256_file(source)}`  \n"
            "Authoritative qualification: `false`\n\n"
            "No production activation, external acceptance, promotion, or release is granted.\n\n"
            f"``````json\n{identity_json}\n``````\n\n``````text\n{text}"
            f"{'' if text.endswith(chr(10)) else chr(10)}``````\n",
            encoding="utf-8",
        )
        rows.append({
            "sourcePath": relative,
            "sourceSha256": sha256_file(source),
            "sourceBytes": source.stat().st_size,
            "renderedPath": str(target.relative_to(output)),
            "renderedSha256": sha256_file(target),
            "renderedBytes": target.stat().st_size,
        })
    generated_rows = []
    for name in GENERATED:
        source = candidate_root / name
        if not source.is_file():
            raise CandidateBundleError(f"missing generated protocol projection: {source}")
        target = generated_output / name
        shutil.copyfile(source, target)
        generated_rows.append({
            "sourcePath": str(source.relative_to(ROOT)),
            "sourceSha256": sha256_file(source),
            "sourceBytes": source.stat().st_size,
            "renderedPath": str(target.relative_to(output)),
            "renderedSha256": sha256_file(target),
            "renderedBytes": target.stat().st_size,
        })
    provenance = {
        name: {"sha256": sha256_file(_file(name)), "bytes": _file(name).stat().st_size}
        for name in PROVENANCE
    }
    write_object(output / "manifest.json", {
        "schema": "hepta.platform-types.candidate-document-bundle.v2",
        "schemaVersion": 2,
        "module": "platform.types",
        "candidateKind": identity["kind"],
        "candidateIdentity": identity,
        "candidateIdentitySha256": identity_sha256(identity),
        "generatedAtUtc": utc_now(),
        "documentCount": len(rows),
        "documents": rows,
        "generatedProjectionCount": len(generated_rows),
        "generatedProjections": generated_rows,
        "provenanceFiles": provenance,
        "authoritativeQualification": False,
        "nonClaims": {
            "productionActivation": "not_claimed",
            "externalAcceptance": "not_claimed",
            "promotion": "not_claimed",
            "release": "not_claimed",
        },
    })
