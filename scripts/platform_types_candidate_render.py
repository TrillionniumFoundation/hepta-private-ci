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
    "docs/modules/platform.types/PROTOCOL_AND_QUALIFICATION_V1.md",
    "docs/modules/platform.types/DEEP_QUALIFICATION_V1.md",
    "docs/modules/platform.types/PUBLIC_API_INVENTORY_V1.json",
    "docs/modules/platform.types/IMPLEMENTATION_MAP.json",
    "docs/lane-a-foundation/platform.types/TRUTH_MATRIX_V1.json",
    "docs/lane-a-foundation/platform.types/CURRENT_IMPLEMENTATION.md",
    "qualification/module-execution-dossiers/detail/platform.types.md",
)
PROVENANCE = DOCS + (
    "codex-rs/hepta-types/MANIFEST_V1_CONFORMANCE.json",
    "codex-rs/hepta-types/CONSUMER_QUALIFICATION_V1.json",
    "codex-rs/hepta-types/src/topology.rs",
    "codex-rs/hepta-types/src/manifests.rs",
    "codex-rs/hepta-types/src/numeric_conversion.rs",
    "scripts/platform_types_public_api.py",
    "scripts/platform_types_implementation_map.py",
    "scripts/platform_types_property_checks.py",
    "scripts/platform_types_candidate_bundle.py",
    "scripts/platform_types_candidate_evidence.py",
    "scripts/run_platform_types_deep_qualification.sh",
    ".github/workflows/platform-types-deep-qualification.yml",
)


def _file(relative: str) -> Path:
    path = ROOT / relative
    if not path.is_file():
        raise CandidateBundleError(f"missing candidate provenance file: {relative}")
    return path


def render_bundle(args: Any) -> None:
    identity = exact_identity(args)
    output: Path = args.output_dir
    if output.exists():
        shutil.rmtree(output)
    rendered = output / "rendered-documents"
    rendered.mkdir(parents=True)
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
    provenance = {
        name: {"sha256": sha256_file(_file(name)), "bytes": _file(name).stat().st_size}
        for name in PROVENANCE
    }
    write_object(output / "manifest.json", {
        "schema": "hepta.platform-types.candidate-document-bundle.v1",
        "schemaVersion": 1,
        "module": "platform.types",
        "candidateKind": identity["kind"],
        "candidateIdentity": identity,
        "candidateIdentitySha256": identity_sha256(identity),
        "generatedAtUtc": utc_now(),
        "documentCount": len(rows),
        "documents": rows,
        "provenanceFiles": provenance,
        "authoritativeQualification": False,
        "nonClaims": {
            "productionActivation": "not_claimed",
            "externalAcceptance": "not_claimed",
            "promotion": "not_claimed",
            "release": "not_claimed",
        },
    })
