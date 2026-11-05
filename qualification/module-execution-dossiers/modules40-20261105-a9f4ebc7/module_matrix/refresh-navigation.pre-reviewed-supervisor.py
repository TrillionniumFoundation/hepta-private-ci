#!/usr/bin/env python3
"""Refresh source navigation through the repository's existing strict verifier.

This integration helper preserves every original sourceBase and every execution
claim. If a legacy path-only anchor has drifted, it uses the already-supported
exact_blob mode with a new, explicitly current source observation. Historical
candidate records are immutable. Run outside the target checkout; commit the
result and run the original qualification verifier separately.
"""

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


LEGACY_EXECUTION_CLAIMS = {
    "productExecutionComplete",
    "deploymentQualificationComplete",
    "independentAcceptanceComplete",
    "targetHostQualified",
    "requestLocalReadOnlyProductExecutionProved",
    "authenticatedProductionProductExecutionProved",
    "productionWriterActivated",
    "independentDecisionEvidenceProved",
    "namedHostQualificationReceiptProved",
}


def semantic_view(row):
    """Remove only current navigation fields; historical provenance stays."""
    result = copy.deepcopy(row)
    for key in (
        "sourceObjects",
        "observedAtHead",
        "observedSourcePaths",
        "mappingSourceIdentityMode",
    ):
        result.pop(key, None)
    for operation in result.get("operations", []):
        operation.pop("sourceBlob", None)
    for caller in result.get("productCallers", []):
        caller.pop("blobSha", None)
    evidence = result.get("exactSourceEvidence")
    if isinstance(evidence, dict) and evidence.get("kind") == "path_blob_manifest_v1":
        for entry in evidence.get("entries", []):
            entry.pop("blobSha", None)
    return result


def refresh(verifier, *, expected_sha, expected_tree, ledger, apply):
    root = verifier.ROOT
    candidate = verifier.current_source_base()
    expected = {"commit": expected_sha, "tree": expected_tree}
    if candidate != expected:
        raise ValueError(f"candidate identity mismatch: expected {expected}, got {candidate}")
    if not LEGACY_EXECUTION_CLAIMS.issubset(verifier.EXECUTION_CLAIMS):
        raise ValueError("install the legacy execution claim protection before rebinding")
    if not callable(getattr(verifier, "verify_explicit_source_pins", None)):
        raise ValueError("install the original source pin protection before rebinding")
    verifier.require_clean_candidate(candidate)
    modules = verifier.load("docs/modules/MODULES.json")["modules"]
    identities = [module["id"] for module in modules]
    if not modules or len(set(identities)) != len(identities):
        raise ValueError("module registry must be nonempty and have unique identities")
    lanes = verifier.lane_by_module()
    ledger_path = verifier.checked_source_path(root, ledger)
    if ledger_path.exists():
        raise ValueError("rebind ledger already exists; historical records are immutable")
    pending = []
    records = []
    checked_paths = set()
    for module in sorted(modules, key=lambda entry: entry["id"]):
        mid = module["id"]
        relative = f"docs/modules/{mid}/IMPLEMENTATION_MAP.json"
        path = verifier.checked_source_path(root, relative)
        before_bytes = path.read_bytes()
        row = verifier.load(relative)
        if row.get("module") != mid or row.get("schemaVersion") != 3:
            raise ValueError(f"{mid}: expected its canonical v3 map")
        anchor = verifier.checked_identity(row.get("sourceBase"), candidate)
        roots = verifier.resolve_source_roots(root, module)
        # Original executable evidence must already match. Do not clear a claim
        # or manufacture a source observation to make old execution seem current.
        if verifier.validate_claim_types(row):
            verifier.verify_source_identity(row, roots, candidate, check_checkout=False)
            verifier.verify_explicit_source_pins(row, candidate)
        migrated = verifier.migrate_map(copy.deepcopy(row), module, lanes, anchor)
        if "observedAtHead" in row:
            migrated["observedAtHead"] = copy.deepcopy(row["observedAtHead"])
        try:
            paths = verifier.verify_source_identity(
                migrated, roots, candidate, check_checkout=False
            )
        except verifier.SourceDrift:
            observed = row.get("observedAtHead", {})
            if not isinstance(observed, dict) or set(observed) - {"commit", "tree"}:
                raise ValueError(f"{mid}: observation has fields requiring explicit review")
            stronger = copy.deepcopy(row)
            stronger["mappingSourceIdentityMode"] = "exact_blob"
            migrated = verifier.migrate_map(stronger, module, lanes, anchor)
            migrated["observedAtHead"] = copy.deepcopy(candidate)
            observed_paths = set(migrated.get("observedSourcePaths", [])) | set(roots)
            if any(path == "codex-rs" or path.startswith("codex-rs/") for path in roots):
                observed_paths.update({"codex-rs/Cargo.toml", "codex-rs/Cargo.lock"})
            migrated["observedSourcePaths"] = sorted(observed_paths)
            paths = verifier.verify_source_identity(
                migrated, roots, candidate, check_checkout=False
            )
        if migrated["sourceBase"] != row["sourceBase"]:
            raise ValueError(f"{mid}: historical sourceBase changed")
        verifier.verify_explicit_source_pins(migrated, candidate)
        if semantic_view(migrated) != semantic_view(row):
            raise ValueError(f"{mid}: migration changed non-navigation metadata")
        old_observed = set(row.get("observedSourcePaths", []))
        if not old_observed.issubset(migrated.get("observedSourcePaths", [])):
            raise ValueError(f"{mid}: observation coverage narrowed")
        if "sourceObjects" in migrated:
            if migrated["sourceObjects"] != verifier.current_source_objects(migrated):
                raise ValueError(f"{mid}: source object manifest does not match HEAD")
            old_objects = {entry["path"] for entry in row.get("sourceObjects", [])}
            new_objects = {entry["path"] for entry in migrated["sourceObjects"]}
            if not old_objects.issubset(new_objects):
                raise ValueError(f"{mid}: source object evidence removed")
        checked_paths.update(paths)
        if migrated == row:
            continue
        rendered = json.dumps(migrated, ensure_ascii=False, indent=2) + "\n"
        records.append(
            {
                "module": mid,
                "mapPath": relative,
                "previousMap": {
                    **candidate,
                    "blob": verifier.git("rev-parse", f"{expected_sha}:{relative}"),
                    "sha256": hashlib.sha256(before_bytes).hexdigest(),
                    "bytes": len(before_bytes),
                },
                "previousSourceBase": row["sourceBase"],
                "previousObservedAtHead": row.get("observedAtHead"),
                "replacementSourceBase": migrated["sourceBase"],
                "replacementObservedAtHead": migrated.get("observedAtHead"),
                "previousClaimBoundary": row.get("claimBoundary"),
                "mappingSourceIdentityMode": migrated.get("mappingSourceIdentityMode", "path_only"),
                "withdrawnClaims": [],
                "historicalCandidateRecordsModified": False,
                "replacementSha256": hashlib.sha256(rendered.encode()).hexdigest(),
            }
        )
        pending.append((path, rendered))
    verifier.require_clean_candidate(candidate, sorted(checked_paths))
    if verifier.current_source_base() != candidate:
        raise ValueError("candidate changed during refresh preparation")
    report = {
        "schema": "hepta.source-navigation-observation-rebind.v1",
        "schemaVersion": 1,
        "sourceCandidate": candidate,
        "scope": "source_navigation_only",
        "executionEvidenceTransferred": False,
        "qualificationRulesModified": False,
        "historicalSourceBasesModified": False,
        "historicalExecutionRecordsModified": False,
        "qualificationAfterCommitRequired": True,
        "priorRecordRecovery": "git cat-file blob <previousMap.blob>; verify SHA-256 and byte count",
        "records": records,
    }
    if apply and pending:
        for path, rendered in pending:
            path.write_text(rendered, encoding="utf-8")
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return {
        "candidateSource": candidate,
        "modules": len(modules),
        "changedMaps": len(pending),
        "maps": [str(path.relative_to(root)) for path, _ in pending],
        "written": bool(apply and pending),
        "ledger": str(ledger_path.relative_to(root)) if pending else None,
        "scope": report["scope"],
        "executionEvidenceTransferred": False,
        "historicalSourceBasesModified": False,
        "qualificationAfterCommitRequired": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-tree", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "exact_candidate_implementation_maps", root / "scripts/hepta-implementation-maps.py"
    )
    if spec is None or spec.loader is None:
        raise ValueError("repository implementation-map verifier is unavailable")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    print(json.dumps(refresh(verifier, expected_sha=args.expected_sha,
                             expected_tree=args.expected_tree, ledger=args.ledger,
                             apply=args.apply), sort_keys=True))


if __name__ == "__main__":
    main()
