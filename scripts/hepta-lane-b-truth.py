#!/usr/bin/env python3
"""Verify Lane B v3 after an exact, provenance-preserving convergence rebase."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = Path(__file__).with_name("hepta-lane-b-truth-core-v3.py")
REBASE = ROOT / "qualification/lane-b/LANE_B_CONVERGENCE_REBASE.json"
SPEC = importlib.util.spec_from_file_location("hepta_lane_b_truth_core_v3", CORE_PATH)
if SPEC is None or SPEC.loader is None:
    raise SystemExit("FAIL_HEPTA_LANE_B_REPOSITORY_CLOSURE: cannot load v3 core")
CORE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CORE
SPEC.loader.exec_module(CORE)
globals().update({name: getattr(CORE, name) for name in dir(CORE) if not name.startswith("__")})


def parents(commit: str) -> list[str]:
    values = CORE.git("rev-list", "--parents", "-n", "1", commit).split()
    CORE.need(values and values[0] == commit, f"cannot resolve parents: {commit}")
    return values[1:]


def source_commit(head: str) -> str:
    values = parents(head)
    if len(values) == 1:
        return head
    if len(values) == 2:
        return values[1]  # synthetic merge order is base, source
    raise CORE.Invalid("HEAD is neither a linear source nor a synthetic merge")


def hex40(value: Any, label: str) -> str:
    CORE.need(isinstance(value, str) and bool(CORE.HEX40.fullmatch(value)), label)
    return value


def verify_manifest(manifest: dict[str, Any]) -> tuple[str, str, list[str]]:
    CORE.need(manifest.get("schema") == "hepta.lane-b-candidate-manifest.v3", "manifest schema")
    CORE.need(manifest.get("schemaVersion") == 3, "manifest version")
    CORE.need(manifest.get("repository") == "TrillionniumFoundation/hepta-private-ci", "repository")
    CORE.need(manifest.get("laneId") == "LANE-B-RUNTIME", "lane")
    CORE.need(manifest.get("requiredModuleGuides") == CORE.MODULES, "module order")
    CORE.need(manifest.get("requiredOperationCount") == 39, "operation count")
    CORE.need("candidateHead" not in manifest, "self-referential candidateHead")

    anchor = manifest.get("lineageAnchor")
    CORE.need(isinstance(anchor, dict), "lineage anchor")
    anchor_commit = hex40(anchor.get("commit"), "anchor commit")
    anchor_tree = hex40(anchor.get("tree"), "anchor tree")
    CORE.need(CORE.git("rev-parse", f"{anchor_commit}^{{tree}}") == anchor_tree, "anchor tree mismatch")

    identity = manifest.get("sourceIdentity")
    history = manifest.get("historyPolicy")
    CORE.need(isinstance(identity, dict) and isinstance(history, dict), "lineage policy")
    for item, key, expected in (
        (identity, "lineageAnchorMustBeAncestor", False),
        (identity, "originalLineageAnchorIsProvenanceOnly", True),
        (identity, "verifiedConvergenceRebaseRequired", True),
        (identity, "convergenceBaseMustBeDirectParent", True),
        (history, "lineageAnchorMustBeAncestor", False),
        (history, "originalLineageAnchorIsProvenanceOnly", True),
        (history, "unrelatedCommitGraftsForbidden", True),
        (history, "mergeCommitsForbiddenInSourceLineage", True),
        (history, "candidateControlledMutationForbidden", True),
        (history, "workflowWritePermissionsForbidden", True),
    ):
        CORE.need(item.get(key) is expected, f"lineage policy: {key}")

    CORE.need(
        manifest.get("convergenceRebaseReceipt")
        == "qualification/lane-b/LANE_B_CONVERGENCE_REBASE.json",
        "rebase receipt path",
    )
    receipt = CORE.load(REBASE)
    CORE.need(receipt.get("schema") == "hepta.lane-b-convergence-rebase.v1", "rebase schema")
    CORE.need(receipt.get("schemaVersion") == 1, "rebase version")
    CORE.need(receipt.get("repository") == manifest["repository"], "rebase repository")
    CORE.need(receipt.get("laneId") == manifest["laneId"], "rebase lane")

    original = receipt.get("sourceCandidate")
    base = receipt.get("convergenceBase")
    policy = receipt.get("policy")
    CORE.need(isinstance(original, dict) and isinstance(base, dict), "rebase identities")
    CORE.need(isinstance(policy, dict), "rebase policy")
    CORE.need(original.get("originalBaseCommit") == anchor_commit, "original base commit")
    CORE.need(original.get("originalBaseTree") == anchor_tree, "original base tree")
    original_commit = hex40(original.get("commit"), "source candidate commit")
    original_tree = hex40(original.get("tree"), "source candidate tree")
    base_commit = hex40(base.get("commit"), "convergence base commit")
    base_tree = hex40(base.get("tree"), "convergence base tree")
    CORE.need(CORE.git("rev-parse", f"{original_commit}^{{tree}}") == original_tree, "source candidate tree")
    CORE.need(CORE.git("rev-parse", f"{base_commit}^{{tree}}") == base_tree, "convergence base tree")
    for key in (
        "sourceCandidateMustBeDirectChildOfConvergenceBase",
        "importedBlobsMustMatchSourceCandidate",
        "expectedChangedPathSetMustMatch",
        "mergeCommitsForbiddenInSourceLineage",
    ):
        CORE.need(policy.get(key) is True, f"missing rebase policy: {key}")
    for key in (
        "authorityGranted",
        "externalEvidenceAdvanced",
        "independentAcceptanceAdvanced",
        "promotionOrReleaseAdvanced",
    ):
        CORE.need(policy.get(key) is False, f"unsupported rebase claim: {key}")

    source = source_commit(CORE.current_head())
    CORE.need(parents(source) == [base_commit], "convergence base is not direct parent")
    imported = receipt.get("importedBlobs")
    CORE.need(isinstance(imported, list) and imported, "imported blobs")
    targets: list[str] = []
    for row in imported:
        CORE.need(isinstance(row, dict), "imported blob record")
        source_path = row.get("sourcePath")
        target_path = row.get("targetPath")
        blob = hex40(row.get("sha"), "imported blob sha")
        CORE.need(isinstance(source_path, str) and source_path, "source path")
        CORE.need(isinstance(target_path, str) and target_path, "target path")
        CORE.need(
            CORE.git("rev-parse", f"{original_commit}:{source_path}") == blob,
            f"source blob drift: {source_path}",
        )
        CORE.need(
            CORE.git("rev-parse", f"{source}:{target_path}") == blob,
            f"rebased blob drift: {target_path}",
        )
        targets.append(target_path)
    CORE.need(len(targets) == len(set(targets)), "duplicate imported target")

    changed = [
        value for value in CORE.git(
            "diff", "--name-only", "--diff-filter=ACDMRTUXB", f"{base_commit}..{source}"
        ).splitlines() if value
    ]
    expected = receipt.get("expectedChangedPaths")
    CORE.need(isinstance(expected, list) and changed == sorted(expected), "changed-path set")
    prefixes = manifest.get("allowedPathPrefixes")
    CORE.need(isinstance(prefixes, list) and prefixes, "path envelope")
    denied = [path for path in changed if not any(path.startswith(prefix) for prefix in prefixes)]
    CORE.need(not denied, "path outside Lane B envelope: " + ", ".join(denied))
    for path in changed:
        if path.startswith(".github/workflows/hepta-lane-b-"):
            text = (ROOT / path).read_text(encoding="utf-8").lower()
            for forbidden in CORE.FORBIDDEN_WORKFLOW:
                CORE.need(forbidden not in text, f"{path}: forbidden capability {forbidden}")
            CORE.need("persist-credentials: false" in text, f"{path}: credentials persist")

    claims = manifest.get("claimBoundary")
    CORE.need(isinstance(claims, dict), "claim boundary")
    CORE.need(
        claims.get("repositoryControlledDocumentationAndMappingMayBeCertified") is True,
        "repository claim",
    )
    for key, value in claims.items():
        if key.endswith("MayBeSelfCertified"):
            CORE.need(value is False, f"unsupported self-certification: {key}")
    return base_commit, base_tree, changed


CORE.verify_manifest = verify_manifest
if __name__ == "__main__":
    raise SystemExit(CORE.main())
