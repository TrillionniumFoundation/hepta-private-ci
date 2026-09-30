#!/usr/bin/env python3
"""Bind six-subject aggregate validation to SBOM/provenance evidence."""

from __future__ import annotations

from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hepta_ui_native_evidence as evidence

CURRENT_WORKFLOW = ".github/workflows/ui-native-qualification.yml"
COMPILE_NEGATIVE = "compile_negative"
DIGEST = re.compile(r"[0-9a-f]{64}\Z")

evidence.WORKFLOW = CURRENT_WORKFLOW
if COMPILE_NEGATIVE not in evidence.REQUIRED:
    evidence.REQUIRED = (*evidence.REQUIRED, COMPILE_NEGATIVE)

import hepta_ui_native_aggregate as aggregate

aggregate.evidence.WORKFLOW = CURRENT_WORKFLOW
aggregate.evidence.REQUIRED = evidence.REQUIRED
_original_aggregate = aggregate.aggregate


def aggregate_with_supply_chain(
    bundles: Path,
    *,
    candidate: str,
    base: str,
    workflow_sha: str,
    workflow_digest: str,
    run_id: str,
    attempt: str,
    subjects: dict[str, dict[str, str]],
) -> dict:
    result = _original_aggregate(
        bundles,
        candidate=candidate,
        base=base,
        workflow_sha=workflow_sha,
        workflow_digest=workflow_digest,
        run_id=run_id,
        attempt=attempt,
        subjects=subjects,
    )
    summaries = []
    implementations = set()
    for profile in evidence.qualification_matrix()["include"]:
        name = (
            f"ui-native-qualification-{profile['runner']}-{profile['kind']}-"
            f"{candidate}-attempt-{attempt}"
        )
        bundle = bundles / name
        supply_root = bundle / "native-evidence/supply-chain"
        manifest_path = supply_root / "supply-chain.json"
        sbom_path = supply_root / "sbom.cdx.json"
        provenance_path = supply_root / "provenance.intoto.json"
        manifest = aggregate.read_json(manifest_path)
        receipt = aggregate.read_json(bundle / "native-evidence/qualification.json")
        expected = subjects[profile["kind"]]
        platform = {"Linux": "linux", "macOS": "macos", "Windows": "windows"}[
            profile["os"]
        ]
        for key, value in {
            "candidateSha": candidate,
            "baseSha": base,
            "sourceSha": expected["sourceSha"],
            "sourceTreeSha": expected["sourceTreeSha"],
            "sourceKind": profile["kind"],
            "platform": platform,
        }.items():
            if manifest.get(key) != value:
                raise ValueError(f"{name}: supply-chain {key} mismatch")
        implementation = manifest.get("implementationSourceSha")
        if not evidence.SHA.fullmatch(str(implementation)):
            raise ValueError(f"{name}: invalid implementation source")
        implementations.add(implementation)
        for key in (
            "productionSigningObserved",
            "physicalHostAcceptance",
            "productionQualified",
            "deploymentQualified",
            "releaseAuthorized",
        ):
            if manifest.get(key) is not False:
                raise ValueError(f"{name}: supply-chain evidence promoted {key}")
        for descriptor, path in (
            (manifest.get("sbom"), sbom_path),
            (manifest.get("provenance"), provenance_path),
        ):
            if (
                not isinstance(descriptor, dict)
                or descriptor.get("path") != path.name
                or not DIGEST.fullmatch(str(descriptor.get("sha256", "")))
                or aggregate.file_digest(path) != descriptor["sha256"]
            ):
                raise ValueError(f"{name}: missing or modified supply-chain artifact")
        supply_receipt = receipt.get("supplyChain")
        if (
            not isinstance(supply_receipt, dict)
            or supply_receipt.get("manifestSha256") != aggregate.file_digest(manifest_path)
            or supply_receipt.get("sbomSha256") != manifest["sbom"]["sha256"]
            or supply_receipt.get("provenanceSha256")
            != manifest["provenance"]["sha256"]
        ):
            raise ValueError(f"{name}: qualification receipt does not bind supply chain")
        summaries.append(
            {
                "runner": profile["runner"],
                "os": profile["os"],
                "kind": profile["kind"],
                "manifestSha256": aggregate.file_digest(manifest_path),
                "sbomSha256": manifest["sbom"]["sha256"],
                "provenanceSha256": manifest["provenance"]["sha256"],
            }
        )
    if len(implementations) != 1:
        raise ValueError("six subjects disagree on implementation source")
    result["implementationSourceSha"] = implementations.pop()
    result["supplyChainSubjects"] = summaries
    result["sbomGenerated"] = True
    result["provenanceGenerated"] = True
    result["productionSigningObserved"] = False
    result["productionQualified"] = False
    result["deploymentQualified"] = False
    result["releaseAuthorized"] = False
    return result


aggregate.aggregate = aggregate_with_supply_chain

if __name__ == "__main__":
    raise SystemExit(aggregate.main())
