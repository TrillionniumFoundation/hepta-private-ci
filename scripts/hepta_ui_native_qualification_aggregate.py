#!/usr/bin/env python3
"""Bind six-subject aggregate validation to SBOM/provenance evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

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

LOCK_PATHS = {
    "apps/hepta-native/Cargo.lock": "application",
    "codex-rs/Cargo.lock": "owner",
}


def source_dependency_inventory(
    repository: Path, subject: dict[str, str]
) -> tuple[dict[str, str], list[dict]]:
    """Reconstruct inventory from immutable Git blobs, independently of SBOM claims."""
    source_sha = subject["sourceSha"]
    if not evidence.SHA.fullmatch(source_sha) or source_sha == "0" * 40:
        raise ValueError("invalid dependency inventory source identity")
    if evidence.git(repository, "rev-parse", f"{source_sha}^{{tree}}") != subject["sourceTreeSha"]:
        raise ValueError("dependency inventory source tree mismatch")
    locks, components = {}, []
    for path, label in LOCK_PATHS.items():
        blob = subprocess.check_output(
            ["git", "show", f"{source_sha}:{path}"], cwd=repository
        )
        if len(blob) > 8 * 1024 * 1024:
            raise ValueError(f"oversized source dependency lock: {path}")
        locks[path] = evidence.sha256(blob)
        packages = tomllib.loads(blob.decode("utf-8")).get("package")
        if not isinstance(packages, list):
            raise ValueError(f"source dependency lock lacks packages: {path}")
        for package in packages:
            if not isinstance(package, dict) or any(
                not isinstance(package.get(key), str) or not package[key]
                for key in ("name", "version")
            ):
                raise ValueError(f"invalid source dependency package: {path}")
            name, version = package["name"], package["version"]
            component = {
                "type": "library",
                "name": name,
                "version": version,
                "bom-ref": f"pkg:cargo/{name}@{version}?lock={label}",
                "purl": f"pkg:cargo/{name}@{version}",
                "properties": [{"name": "hepta:lockfile", "value": label}],
            }
            if "checksum" in package:
                checksum = package["checksum"]
                if not isinstance(checksum, str) or not DIGEST.fullmatch(checksum):
                    raise ValueError(f"invalid source dependency checksum: {path}")
                component["hashes"] = [{"alg": "SHA-256", "content": checksum}]
            if "source" in package:
                package_source = package["source"]
                if not isinstance(package_source, str) or not package_source:
                    raise ValueError(f"invalid source dependency origin: {path}")
                component["properties"].append(
                    {"name": "hepta:cargo-source", "value": package_source}
                )
            components.append(component)
    components.sort(key=lambda item: (item["name"], item["version"], item["bom-ref"]))
    return locks, components


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
    implementation: str | None = None,
    repository: Path = Path(__file__).resolve().parents[1],
) -> dict:
    if implementation is None:
        raise ValueError(
            "frozen implementation source is required for supply-chain validation"
        )
    result = _original_aggregate(
        bundles,
        candidate=candidate,
        base=base,
        workflow_sha=workflow_sha,
        workflow_digest=workflow_digest,
        run_id=run_id,
        attempt=attempt,
        subjects=subjects,
        implementation=implementation,
    )
    summaries = []
    implementations = set()
    inventories = {
        kind: source_dependency_inventory(repository, subject)
        for kind, subject in subjects.items()
    }
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
        if manifest.get("schema") != "hepta.ui-native-supply-chain.v1":
            raise ValueError(f"{name}: unexpected supply-chain schema")
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
        if manifest.get("implementationSourceSha") != implementation:
            raise ValueError(f"{name}: foreign frozen implementation source")
        implementations.add(implementation)
        package_receipt = aggregate.read_json(
            bundle / "native-package/package-receipt.json"
        )
        package_name = manifest.get("packageArchive")
        package_digest = manifest.get("packageSha256")
        if (
            package_receipt.get("schema") != "hepta.ui-native-package-receipt.v1"
            or package_receipt.get("archive") != package_name
            or package_receipt.get("archiveSha256") != package_digest
            or not any(
                artifact.get("name") == package_name
                and artifact.get("sha256") == package_digest
                for artifact in receipt.get("artifacts", [])
            )
        ):
            raise ValueError(f"{name}: supply chain does not bind the retained package")
        if (
            manifest.get("applicationCargoLockSha256")
            != receipt["dependencyLocks"]["apps/hepta-native/Cargo.lock"]
            or manifest.get("ownerCargoLockSha256")
            != receipt["dependencyLocks"]["codex-rs/Cargo.lock"]
        ):
            raise ValueError(
                f"{name}: supply-chain dependency locks differ from executed source"
            )
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
        provenance = aggregate.read_json(provenance_path)
        sbom = aggregate.read_json(sbom_path)
        expected_locks, expected_components = inventories[profile["kind"]]
        if (
            receipt.get("dependencyLocks") != expected_locks
            or sbom.get("components") != expected_components
            or sbom.get("metadata", {}).get("properties")
            != [
                {"name": "hepta:application-lock-sha256", "value": expected_locks["apps/hepta-native/Cargo.lock"]},
                {"name": "hepta:owner-lock-sha256", "value": expected_locks["codex-rs/Cargo.lock"]},
            ]
        ):
            raise ValueError(f"{name}: SBOM dependency inventory differs from exact source locks")
        sbom_component = sbom.get("metadata", {}).get("component", {})
        sbom_properties = {
            item.get("name"): item.get("value")
            for item in sbom_component.get("properties", [])
            if isinstance(item, dict)
        }
        if (
            sbom.get("bomFormat") != "CycloneDX"
            or sbom.get("specVersion") != "1.6"
            or sbom_component.get("hashes")
            != [{"alg": "SHA-256", "content": package_digest}]
            or any(
                sbom_properties.get(key) != value
                for key, value in {
                    "hepta:candidate-sha": candidate,
                    "hepta:base-sha": base,
                    "hepta:implementation-source-sha": implementation,
                    "hepta:subject-source-sha": expected["sourceSha"],
                    "hepta:subject-source-tree": expected["sourceTreeSha"],
                    "hepta:source-kind": profile["kind"],
                    "hepta:platform": platform,
                    "hepta:production-qualified": "false",
                    "hepta:release-authorized": "false",
                }.items()
            )
        ):
            raise ValueError(f"{name}: SBOM package/source identity mismatch")
        definition = provenance.get("predicate", {}).get("buildDefinition", {})
        provenance_subjects = provenance.get("subject")
        parameters = {
            "candidateSha": candidate,
            "baseSha": base,
            "implementationSourceSha": implementation,
            "subjectSourceSha": expected["sourceSha"],
            "subjectSourceTree": expected["sourceTreeSha"],
            "sourceKind": profile["kind"],
            "platform": platform,
        }
        internal = definition.get("internalParameters", {})
        if (
            provenance.get("_type") != "https://in-toto.io/Statement/v1"
            or provenance.get("predicateType") != "https://slsa.dev/provenance/v1"
            or provenance_subjects
            != [{"name": package_name, "digest": {"sha256": package_digest}}]
            or definition.get("externalParameters") != parameters
            or internal.get("runId") != run_id
            or internal.get("runAttempt") != attempt
        ):
            raise ValueError(f"{name}: provenance subject/source/run identity mismatch")
        supply_receipt = receipt.get("supplyChain")
        if (
            not isinstance(supply_receipt, dict)
            or supply_receipt.get("manifestSha256")
            != aggregate.file_digest(manifest_path)
            or supply_receipt.get("sbomSha256") != manifest["sbom"]["sha256"]
            or supply_receipt.get("provenanceSha256")
            != manifest["provenance"]["sha256"]
        ):
            raise ValueError(
                f"{name}: qualification receipt does not bind supply chain"
            )
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


def main() -> int:
    # Pass the selected checkout into independent Git-blob validation as well
    # as deterministic subject construction; the working tree is never input.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--bundles", type=Path, required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        candidate_state = json.loads(evidence.git(
            args.root, "show", f"{args.candidate}:apps/hepta-native/CANDIDATE.json"
        ))
        workflow = subprocess.check_output(
            ["git", "show", f"{args.workflow_sha}:{evidence.WORKFLOW}"], cwd=args.root
        )
        result = aggregate_with_supply_chain(
            args.bundles,
            candidate=args.candidate,
            base=args.base,
            workflow_sha=args.workflow_sha,
            workflow_digest=evidence.sha256(workflow),
            run_id=os.environ.get("GITHUB_RUN_ID", ""),
            attempt=os.environ.get("GITHUB_RUN_ATTEMPT", ""),
            subjects=aggregate.deterministic_subjects(args.root, args.candidate, args.base),
            implementation=candidate_state["implementationSourceSha"],
            repository=args.root,
        )
        evidence.write_json(args.out, result)
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as error:
        print(f"ui.native aggregate refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
