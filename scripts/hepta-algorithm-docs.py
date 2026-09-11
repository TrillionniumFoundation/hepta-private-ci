#!/usr/bin/env python3
"""Closed-world verifier for Hepta adaptive algorithm specifications."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PLAN_ID = "HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN"
PLAN_VERSION = "8.0.0"
REGISTRY_PATH = "docs/learning/ALGORITHM_SPECS.json"
PAPER_PATH = "docs/learning/PAPER_TRACEABILITY.json"
STATUS_PATH = "docs/learning/ALGORITHM_STATUS.md"
LEARNING_README = "docs/learning/README.md"
MODULES_PATH = "docs/modules/MODULES.json"
CONTRACTS_PATH = "docs/contracts/CONTRACTS.json"
PROTOCOLS_PATH = "docs/contracts/PROTOCOL_SCHEMAS.json"
PROTOCOL_AUTHORITY_PATHS = (CONTRACTS_PATH, PROTOCOLS_PATH)
DATA_PATH = "docs/data/DATA_AUTHORITY.json"
WORK_PATH = "docs/delivery/WORK_PACKAGES.json"
DAG_PATHS = [
    "docs/delivery/DEVELOPMENT_DAG.json",
    "docs/delivery/ACTIVATION_DAG.json",
    "docs/delivery/EVIDENCE_DAG.json",
]
DOCUMENT_SYSTEM_PATH = "docs/governance/DOCUMENT_SYSTEM.json"
EXPERIMENTS_PATH = "docs/learning/EXPERIMENTS.json"
ARTIFACTS_PATH = "docs/learning/ARTIFACTS.json"
CLAIMS_PATH = "docs/evidence/CLAIMS.json"
GLOBAL_VERIFIER = "scripts/hepta-docs.py"
GLOBAL_WORKFLOW = ".github/workflows/hepta-development-docs.yml"
WORKFLOW_PATH = ".github/workflows/hepta-algorithm-docs.yml"
DOC_PACKAGE = "DOC-3D-ADAPTIVE-ALGORITHM-DOC-CLOSED-WORLD"
RECEIPT_SCHEMA = "hepta.algorithm-docs-execution-receipt.v2"

AUTHORITY_KEYS = [
    "runtimeAuthority",
    "productionCaller",
    "productionWriter",
    "modelInvocation",
    "providerDispatch",
    "toolExecution",
    "networkConnect",
    "externalFilesystemMutation",
    "secretOperation",
    "matrixSend",
    "externalEffect",
    "fleetMutation",
    "canonicalSelection",
    "merge",
    "operatorAcceptance",
    "promotion",
    "release",
]
HEADINGS = [
    "## 1. Scope, ownership and non-claims",
    "## 2. Symbols, dimensions, units and normalization",
    "## 3. Formal model and invariants",
    "## 4. Deterministic reference algorithm",
    "## 5. Trainable or estimated algorithm",
    "## 6. Data, protocol and lineage schema",
    "## 7. Numerical stability, complexity and resource bounds",
    "## 8. Failure detection, fallback and rollback",
    "## 9. Security, authority, privacy and unlearning",
    "## 10. Verification, golden vectors and property tests",
    "## 11. Quantitative acceptance gates",
    "## 12. Paper traceability and Hepta extensions",
    "## 13. Implementation sequence and completion rule",
]
TEMPORARY_PATHS = [
    ".github/hepta-doc-closure.part00",
    ".github/hepta-doc-closure.part01",
    ".github/hepta-doc-closure.part02",
    ".github/hepta-doc-closure.part03",
    ".github/workflows/paper-fingerprint-discovery.yml",
]


PAPER_SCHEMA = "hepta.paper-traceability.v2"
PAPER_ROW_KEYS = [
    "id",
    "title",
    "author",
    "dateWritten",
    "publication",
    "canonicalUrl",
    "fullTextUrl",
    "sourceClass",
    "claimsUsed",
    "nonClaims",
    "doi",
    "sourceLock",
    "claimAnchors",
    "nonClaimAnchors",
]
SOURCE_LOCK_KEYS = [
    "sourceArtifactId",
    "identityClass",
    "publisher",
    "recordId",
    "doi",
    "postedDate",
    "sourceKind",
    "sourceScope",
    "canonicalization",
    "contentDigestAlgorithm",
    "contentDigest",
    "contentLengthBytes",
    "contentDigestStatus",
    "pageCount",
    "canonicalUrl",
    "immutableUrl",
    "publisherRepository",
    "publisherCommit",
    "publisherGitBlobSha",
    "verifiedTitle",
    "verifiedAuthor",
    "verifiedDateWritten",
    "verificationStatus",
]
CLAIM_ANCHOR_KEYS = [
    "claim",
    "sourceArtifactId",
    "locator",
    "sourceTextDigestAlgorithm",
    "sourceTextDigest",
    "sourceTextLengthBytes",
    "claimScope",
    "verificationStatus",
]
LOCATOR_KEYS = [
    "kind",
    "section",
    "paragraphIndex",
    "sentenceIndex",
    "publicationPage",
    "pdfPage",
    "theoremOrEquation",
]
NONCLAIM_ANCHOR_KEYS = [
    "nonClaim",
    "basis",
    "sourceArtifactId",
    "locator",
    "sourceTextDigestAlgorithm",
    "sourceTextDigest",
    "sourceTextLengthBytes",
    "verificationStatus",
]
HEPTA_ONLY_PAPER_BOUNDARIES = {
    "quasi_uniform_sensor_geometry",
    "monotone_positive_reconstruction",
    "near_greedy_residual_scope",
}
EXPECTED_SOURCE_LOCKS = {
    "PAPER-NDU-FOUNDATIONS-2024": {
        "sourceArtifactId": "ssrn-5072524-abstract-nfkc-ws-v1",
        "identityClass": "publisher_abstract_sha256",
        "contentDigest": "735d842f690836752de0fac6c36bba2c5f8608361f17c90a0c580192707a16eb",
        "contentLengthBytes": 644,
        "sourceKind": "publisher_abstract",
        "sourceScope": "publisher_abstract_statement_only",
    },
    "PAPER-NDU-UPA-2025": {
        "sourceArtifactId": "ssrn-5125219-abstract-nfkc-ws-v1",
        "identityClass": "publisher_abstract_sha256",
        "contentDigest": "5716f408db9e2b98c53d7d508c3c2b20a3ce28f050e3ebc2cbd162feecc77dec",
        "contentLengthBytes": 866,
        "sourceKind": "publisher_abstract",
        "sourceScope": "publisher_abstract_statement_only",
    },
    "PAPER-NDU-EU-2025": {
        "sourceArtifactId": "ssrn-5267854-abstract-nfkc-ws-v1",
        "identityClass": "publisher_abstract_sha256",
        "contentDigest": "f72a1cab40a82c668711682e8909d83b5346759d24d8ba25654cd253d2196c1c",
        "contentLengthBytes": 831,
        "sourceKind": "publisher_abstract",
        "sourceScope": "publisher_abstract_statement_only",
    },
    "PAPER-HOLDER-Q-2026": {
        "sourceArtifactId": "pmlr-v336-qi26a-pdf-sha256-git-blob",
        "identityClass": "publisher_pdf_sha256_and_git_blob",
        "contentDigest": "19892c98ba43ba1c01e0d4d01859f0d1e3bce601808414543f182b630338f60a",
        "contentLengthBytes": 98363,
        "sourceKind": "publisher_extended_abstract_pdf",
        "sourceScope": "publisher_extended_abstract_statement_only",
        "pageCount": 2,
        "immutableUrl": "https://raw.githubusercontent.com/mlresearch/v336/a38f8ab26e793cff794c8017a29fb29a7c25c6b3/assets/qi26a/qi26a.pdf",
        "publisherRepository": "mlresearch/v336",
        "publisherCommit": "a38f8ab26e793cff794c8017a29fb29a7c25c6b3",
        "publisherGitBlobSha": "6ed0be8d3e49ca1ae32d0e9f601eb133cdc2de92",
    },
}
EXPECTED_CLAIM_ANCHORS = {
    "PAPER-NDU-FOUNDATIONS-2024": {
        "resource_constrained_subject": (
            2,
            "bdd5ede55b15ba28da08a2eeb1f402f7dfdb6301b81a68a79f50ccc2a65c2740",
            129,
        ),
        "endogenous_preference_state": (
            2,
            "bdd5ede55b15ba28da08a2eeb1f402f7dfdb6301b81a68a79f50ccc2a65c2740",
            129,
        ),
        "recursive_utility_framing": (
            1,
            "5c58e43d831c0ebd2ac5d73c0c115aec5998629a7c6bf6c0c72b88af920b2a39",
            144,
        ),
        "neural_parameterization_motivation": (
            1,
            "5c58e43d831c0ebd2ac5d73c0c115aec5998629a7c6bf6c0c72b88af920b2a39",
            144,
        ),
    },
    "PAPER-NDU-UPA-2025": {
        "continuous_time_fbsde_preference_process": (
            2,
            "109913c27bf17b1a4f7ac904a9a5885b108655807f32e343f9f849e348043bd7",
            240,
        ),
        "continuous_time_resnet_preference_parameterization": (
            2,
            "109913c27bf17b1a4f7ac904a9a5885b108655807f32e343f9f849e348043bd7",
            240,
        ),
        "resnet_aggregator_approximation": (
            3,
            "f1ca1c2d65f34ca4819da0906120ced5694746b6bca092ed19d66c0387355cc5",
            307,
        ),
        "weakly_compact_admissible_process_scope": (
            3,
            "f1ca1c2d65f34ca4819da0906120ced5694746b6bca092ed19d66c0387355cc5",
            307,
        ),
    },
    "PAPER-NDU-EU-2025": {
        "general_multidimensional_square_integrable_martingale": (
            1,
            "0e517302738db798a49dfc4836f86301f9d21c68d49762bca7c79f7c4f82b43e",
            185,
        ),
        "distinct_forward_and_backward_driver_components": (
            2,
            "d5af987b16fcda258bd8f796cb9a0eaf46fe9f742a9633ca4500b5cc83e59e9d",
            290,
        ),
        "forward_preference_state": (
            2,
            "d5af987b16fcda258bd8f796cb9a0eaf46fe9f742a9633ca4500b5cc83e59e9d",
            290,
        ),
        "backward_utility_aggregator": (
            2,
            "d5af987b16fcda258bd8f796cb9a0eaf46fe9f742a9633ca4500b5cc83e59e9d",
            290,
        ),
        "existence_and_uniqueness_require_explicit_conditions": (
            3,
            "d65636fb63fc0484f5e4f815882f47d421d1bb88ac116a05f4aa37d88ea02b60",
            98,
        ),
        "optimal_control_requires_regularity_growth_concavity_and_weak_to_strong_continuity": (
            5,
            "5336e30f4d1d176a49c0ed54ead6a570c846e79885ce065c1b9488e5be662f7d",
            170,
        ),
    },
    "PAPER-HOLDER-Q-2026": {
        "continuous_state_continuous_action_controlled_diffusion": (
            1,
            "bf531440a9a7e987fe4ea15189b9a07e1c37b849163019c347583f5ae0fd1396",
            124,
        ),
        "uniform_ellipticity": (
            2,
            "dbdd2ed9b141593a84b0946ee998cb77faa29d144e16a700a1e4973abee50898",
            244,
        ),
        "holder_regular_coefficients": (
            3,
            "7b3211f59d946cf03713fcb36793f0b52b77ce994663808f51326318c48e3bc6",
            253,
        ),
        "state_smoothing_action_lipschitz_anisotropy": (
            3,
            "7b3211f59d946cf03713fcb36793f0b52b77ce994663808f51326318c48e3bc6",
            253,
        ),
        "tensor_product_deeponet": (
            4,
            "411df267ec4168dd8200450fbb7d51e6860fb213553e78de35f8449064056e6b",
            159,
        ),
        "stiffness_complexity_tradeoff": (
            5,
            "0199dd83b5e85ef764d8c98f4926d39d78496ce5aa36a837b8fb9ccb4074b3c0",
            131,
        ),
    },
}


class DuplicateKey(ValueError):
    pass


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise DuplicateKey(key)
        result[key] = value
    return result


def die(message: str) -> None:
    raise SystemExit("FAIL_HEPTA_ALGORITHM_DOCS: " + message)


def need(condition: bool, message: str) -> None:
    if not condition:
        die(message)


def load(rel: str) -> dict[str, Any]:
    try:
        return json.loads(
            (ROOT / rel).read_text(encoding="utf-8"),
            object_pairs_hook=pairs,
        )
    except Exception as exc:
        die(f"{rel}: {exc}")


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode:
        die("git " + " ".join(args) + ": " + proc.stderr.strip())
    return proc.stdout.strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w.-]+\b", text))


def protocol_authority_boundary(text: str) -> bool:
    remaining = text
    for path in PROTOCOL_AUTHORITY_PATHS:
        token = f"`{path}`"
        if token not in remaining:
            return False
        remaining = remaining.replace(token, "")
    return not any(Path(path).name in remaining for path in PROTOCOL_AUTHORITY_PATHS)


def false_authority(value: Any, label: str) -> None:
    need(isinstance(value, dict), label + " authority object")
    need(list(value) == AUTHORITY_KEYS, label + " authority key closure/order")
    need(not any(bool(item) for item in value.values()), label + " positive authority")


def coverage(registry: dict[str, Any]) -> dict[str, list[str]]:
    result = {module: [] for module in registry["criticalModules"]}
    for document in registry["documents"]:
        for module in document["modules"]:
            need(module in result, document["id"] + " unknown module " + module)
            result[module].append(document["id"])
    return result


def status_text(registry: dict[str, Any], papers: dict[str, Any]) -> str:
    bound = coverage(registry)
    locked = sum(
        1
        for row in papers["papers"]
        if row["sourceLock"]["verificationStatus"] == "verified"
    )
    lines = [
        "# Hepta Adaptive Algorithm Documentation Status",
        "",
        "> Generated by `python3 scripts/hepta-algorithm-docs.py generate-status`. Do not edit by hand.",
        "",
        f"**Plan:** `{registry['planId']}` v{registry['planVersion']}",
        f"**Documentation gap state:** `{registry['documentationGapState']}`",
        f"**Global closure state:** `{registry['globalClosure']['state']}`",
        f"**Capability claim state:** `{registry['capabilityClaimState']}`",
        "",
        "## Closure summary",
        "",
        f"- Critical adaptive modules: **{len(registry['criticalModules'])}**",
        f"- Formal implementation specifications: **{len(registry['documents'])}**",
        f"- Mandatory closure gates: **{len(registry['closureGates'])}**",
        f"- Canonical adaptive protocols: **{len(registry['requiredProtocols'])}**",
        f"- Paper source locks: **{locked}/{len(papers['papers'])} verified; every used claim is locator- and SHA-256-bound**",
        f"- Global work package: **`{registry['globalClosure']['workPackageId']}`**",
        "- Specification identity: **exact Git blob bound**",
        "- Exact source and synthetic merge validation: **required in dedicated and global workflows**",
        "",
        "## Critical-module coverage",
        "",
        "| Module | Specifications |",
        "|---|---|",
    ]
    for module in registry["criticalModules"]:
        names = ", ".join(f"`{item}`" for item in bound[module])
        lines.append(f"| `{module}` | {names} |")
    lines.extend(
        [
            "",
            "## Truthful capability posture",
            "",
            "Documentation closure does not imply source implementation, activation, causal efficacy, functional biomimicry, selection, promotion or release. Capability levels remain governed by `docs/evidence/CLAIMS.json` and current exact evidence.",
            "",
            "Every authority flag in the algorithm and paper registries is present and false.",
            "",
        ]
    )
    return "\n".join(lines)


def validate_paper_sources(papers: dict[str, Any]) -> int:
    need(papers.get("schema") == PAPER_SCHEMA, "paper traceability schema")
    need(papers.get("schemaVersion") == 2, "paper traceability schema version")
    policy = papers.get("sourceLockPolicy")
    expected_policy = {
        "publisherIdentityRequired": True,
        "contentDigestRequiredForEveryCitedArtifact": True,
        "claimSpecificTextDigestRequired": True,
        "exactLocatorRequiredForEveryClaim": True,
        "abstractOnlyScopeMaySupportTheoremOrEquation": False,
        "htmlChallengeOrAccessDeniedBodyMaySatisfyContentDigest": False,
        "mutableUrlWithoutContentLockMaySatisfyClaim": False,
        "retrievalFailureMayAdvanceClaim": False,
        "unsupportedPaperAttributionMayRemainInClaimsUsed": False,
        "paperReferenceMayAdvanceRuntimeClaim": False,
    }
    need(policy == expected_policy, "paper source lock policy closure")
    rules = papers.get("rules")
    for key in (
        "claimAnchorDigestRequired",
        "exactLocatorRequiredForEveryUsedClaim",
        "unsupportedPaperAttributionForbidden",
        "sourceArtifactSubstitutionForbidden",
    ):
        need(rules.get(key) is True, "paper rule " + key)
    need(
        rules.get("abstractStatementMaySatisfyTheoremOrEquationClaim") is False,
        "abstract theorem rule",
    )
    need(
        rules.get("heptaExtensionsMayBeAttributedToPaper") is False,
        "Hepta attribution rule",
    )

    rows = papers.get("papers")
    need(isinstance(rows, list) and len(rows) == 4, "paper source count")
    ids = [row.get("id") for row in rows]
    need(ids == list(EXPECTED_SOURCE_LOCKS), "paper source order/identity")
    need(len(ids) == len(set(ids)), "duplicate paper ID")
    source_artifact_ids: set[str] = set()
    attributed_claims: set[str] = set()

    for row in rows:
        paper_id = row["id"]
        need(list(row) == PAPER_ROW_KEYS, paper_id + " paper key closure/order")
        lock = row.get("sourceLock")
        need(isinstance(lock, dict), paper_id + " source lock")
        need(
            list(lock) == SOURCE_LOCK_KEYS, paper_id + " source-lock key closure/order"
        )
        expected_lock = EXPECTED_SOURCE_LOCKS[paper_id]
        for key, expected in expected_lock.items():
            need(lock.get(key) == expected, paper_id + " source lock " + key)
        source_artifact_id = lock["sourceArtifactId"]
        need(
            source_artifact_id not in source_artifact_ids,
            paper_id + " duplicate source artifact",
        )
        source_artifact_ids.add(source_artifact_id)
        need(
            lock.get("verificationStatus") == "verified",
            paper_id + " source verification",
        )
        need(lock.get("verifiedTitle") == row["title"], paper_id + " title lock")
        need(lock.get("verifiedAuthor") == row["author"], paper_id + " author lock")
        need(
            lock.get("verifiedDateWritten") == row["dateWritten"],
            paper_id + " date lock",
        )
        need(
            str(lock.get("canonicalUrl", "")).startswith("https://"),
            paper_id + " canonical URL",
        )
        need(
            lock.get("contentDigestAlgorithm") == "sha256",
            paper_id + " digest algorithm",
        )
        need(
            re.fullmatch(r"[0-9a-f]{64}", str(lock.get("contentDigest"))) is not None,
            paper_id + " digest",
        )
        need(lock.get("contentLengthBytes", 0) > 0, paper_id + " content length")
        need(lock.get("contentDigestStatus") == "verified", paper_id + " digest status")
        need(
            lock.get("sourceKind")
            in {"publisher_abstract", "publisher_extended_abstract_pdf"},
            paper_id + " source kind",
        )
        need(
            "challenge" not in lock.get("sourceKind", "").casefold(),
            paper_id + " challenge substitution",
        )
        need(
            "access_denied" not in lock.get("sourceKind", "").casefold(),
            paper_id + " access-denied substitution",
        )
        if lock["sourceKind"] == "publisher_abstract":
            need(
                str(lock.get("doi", "")).startswith("10.2139/ssrn."),
                paper_id + " SSRN DOI",
            )
            need(
                lock.get("canonicalization") == "unicode_nfkc_whitespace_collapse_v1",
                paper_id + " abstract canonicalization",
            )
            need(lock.get("immutableUrl") is None, paper_id + " false immutable URL")
            need(
                lock.get("publisherRepository") is None, paper_id + " false repository"
            )
            need(
                lock.get("publisherCommit") is None,
                paper_id + " false publisher commit",
            )
            need(
                lock.get("publisherGitBlobSha") is None,
                paper_id + " false publisher blob",
            )
        else:
            need(
                lock.get("canonicalization") == "raw_bytes",
                paper_id + " PDF canonicalization",
            )
            need(
                str(lock.get("immutableUrl", "")).startswith("https://"),
                paper_id + " immutable PDF URL",
            )
            need(
                re.fullmatch(r"[0-9a-f]{40}", str(lock.get("publisherCommit")))
                is not None,
                paper_id + " publisher commit",
            )
            need(
                re.fullmatch(r"[0-9a-f]{40}", str(lock.get("publisherGitBlobSha")))
                is not None,
                paper_id + " publisher blob",
            )

        expected_anchors = EXPECTED_CLAIM_ANCHORS[paper_id]
        claims = row.get("claimsUsed")
        need(
            isinstance(claims, list) and claims == list(expected_anchors),
            paper_id + " claim identity/order",
        )
        need(
            not (set(claims) & HEPTA_ONLY_PAPER_BOUNDARIES),
            paper_id + " Hepta extension attributed to paper",
        )
        attributed_claims.update(claims)
        claim_anchors = row.get("claimAnchors")
        need(
            isinstance(claim_anchors, list) and len(claim_anchors) == len(claims),
            paper_id + " claim anchor closure",
        )
        need(
            [item.get("claim") for item in claim_anchors] == claims,
            paper_id + " claim anchor order",
        )
        for anchor in claim_anchors:
            claim = anchor["claim"]
            need(
                list(anchor) == CLAIM_ANCHOR_KEYS,
                paper_id + " claim-anchor key closure " + claim,
            )
            need(
                anchor.get("sourceArtifactId") == source_artifact_id,
                paper_id + " source artifact substitution " + claim,
            )
            locator = anchor.get("locator")
            need(
                isinstance(locator, dict) and list(locator) == LOCATOR_KEYS,
                paper_id + " locator closure " + claim,
            )
            need(
                locator.get("section") == "Abstract",
                paper_id + " source section " + claim,
            )
            need(
                locator.get("paragraphIndex") == 1,
                paper_id + " paragraph locator " + claim,
            )
            need(
                isinstance(locator.get("sentenceIndex"), int)
                and locator["sentenceIndex"] > 0,
                paper_id + " sentence locator " + claim,
            )
            need(
                locator.get("theoremOrEquation") is None,
                paper_id + " abstract promoted to theorem/equation " + claim,
            )
            expected_sentence, expected_digest, expected_bytes = expected_anchors[claim]
            need(
                locator.get("sentenceIndex") == expected_sentence,
                paper_id + " sentence identity " + claim,
            )
            need(
                anchor.get("sourceTextDigestAlgorithm") == "sha256",
                paper_id + " claim digest algorithm " + claim,
            )
            need(
                anchor.get("sourceTextDigest") == expected_digest,
                paper_id + " claim text digest " + claim,
            )
            need(
                anchor.get("sourceTextLengthBytes") == expected_bytes,
                paper_id + " claim text length " + claim,
            )
            need(
                anchor.get("claimScope") == lock["sourceScope"],
                paper_id + " claim scope " + claim,
            )
            need(
                anchor.get("verificationStatus") == "verified",
                paper_id + " claim verification " + claim,
            )
            if lock["sourceKind"] == "publisher_abstract":
                need(
                    locator.get("publicationPage") is None
                    and locator.get("pdfPage") is None,
                    paper_id + " false page locator " + claim,
                )
            else:
                need(
                    locator.get("publicationPage") == 5397
                    and locator.get("pdfPage") == 1,
                    paper_id + " PDF page locator " + claim,
                )

        nonclaims = row.get("nonClaims")
        nonclaim_anchors = row.get("nonClaimAnchors")
        need(
            isinstance(nonclaims, list) and len(nonclaims) == len(set(nonclaims)),
            paper_id + " nonclaim identity",
        )
        need(
            isinstance(nonclaim_anchors, list)
            and len(nonclaim_anchors) == len(nonclaims),
            paper_id + " nonclaim anchor closure",
        )
        need(
            [item.get("nonClaim") for item in nonclaim_anchors] == nonclaims,
            paper_id + " nonclaim anchor order",
        )
        for anchor in nonclaim_anchors:
            nonclaim = anchor["nonClaim"]
            need(
                list(anchor) == NONCLAIM_ANCHOR_KEYS,
                paper_id + " nonclaim-anchor key closure " + nonclaim,
            )
            need(
                anchor.get("verificationStatus") == "verified",
                paper_id + " nonclaim verification " + nonclaim,
            )
            if anchor.get("sourceArtifactId") is None:
                need(
                    anchor.get("basis")
                    == "explicit_engineering_non_substitution_boundary",
                    paper_id + " nonclaim basis " + nonclaim,
                )
                need(
                    anchor.get("locator") is None,
                    paper_id + " false nonclaim locator " + nonclaim,
                )
                need(
                    anchor.get("sourceTextDigestAlgorithm") is None,
                    paper_id + " false nonclaim algorithm " + nonclaim,
                )
                need(
                    anchor.get("sourceTextDigest") is None,
                    paper_id + " false nonclaim digest " + nonclaim,
                )
                need(
                    anchor.get("sourceTextLengthBytes") is None,
                    paper_id + " false nonclaim length " + nonclaim,
                )
            else:
                need(
                    anchor.get("sourceArtifactId") == source_artifact_id,
                    paper_id + " nonclaim source substitution " + nonclaim,
                )
                need(
                    nonclaim == "no_full_sampled_dqn_convergence_theorem",
                    paper_id + " unexpected sourced nonclaim",
                )
                need(
                    anchor.get("basis")
                    == "explicit_publisher_extended_abstract_nonclaim",
                    paper_id + " sourced nonclaim basis",
                )
                locator = anchor.get("locator")
                need(
                    isinstance(locator, dict) and list(locator) == LOCATOR_KEYS,
                    paper_id + " sourced nonclaim locator",
                )
                need(
                    locator.get("sentenceIndex") == 6
                    and locator.get("theoremOrEquation") is None,
                    paper_id + " sourced nonclaim location",
                )
                need(
                    anchor.get("sourceTextDigestAlgorithm") == "sha256",
                    paper_id + " sourced nonclaim algorithm",
                )
                need(
                    anchor.get("sourceTextDigest")
                    == "6bc394a19d18f298335ab050f5f08d7603a1f2f6a78244e604fda66494e71853",
                    paper_id + " sourced nonclaim digest",
                )
                need(
                    anchor.get("sourceTextLengthBytes") == 188,
                    paper_id + " sourced nonclaim length",
                )

    extensions = papers.get("heptaExtensions")
    need(
        isinstance(extensions, list) and len(extensions) == len(set(extensions)),
        "Hepta extension identity",
    )
    need(
        HEPTA_ONLY_PAPER_BOUNDARIES.issubset(set(extensions)),
        "Hepta-only paper boundaries missing",
    )
    need(
        not (HEPTA_ONLY_PAPER_BOUNDARIES & attributed_claims),
        "Hepta-only boundary paper attribution",
    )
    return len(rows)


def verify_sources() -> int:
    count = validate_paper_sources(load(PAPER_PATH))
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_PAPER_SOURCE_LOCKS_V2",
                "papers": count,
                "claimAnchors": sum(
                    len(row) for row in EXPECTED_CLAIM_ANCHORS.values()
                ),
                "hostileSubstitutionPolicy": "fail_closed",
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0


def verify() -> int:
    registry = load(REGISTRY_PATH)
    papers = load(PAPER_PATH)
    modules = load(MODULES_PATH)
    contracts = load(CONTRACTS_PATH)
    protocols = load(PROTOCOLS_PATH)
    data = load(DATA_PATH)
    work = load(WORK_PATH)
    document_system = load(DOCUMENT_SYSTEM_PATH)
    experiments = load(EXPERIMENTS_PATH)
    artifacts = load(ARTIFACTS_PATH)
    claims = load(CLAIMS_PATH)

    need(
        registry.get("schema") == "hepta.algorithm-spec-registry.v1", "algorithm schema"
    )
    need(papers.get("schema") == PAPER_SCHEMA, "paper schema")
    for label, value in (("algorithm", registry), ("paper", papers)):
        need(value.get("planId") == PLAN_ID, label + " plan ID")
        need(value.get("planVersion") == PLAN_VERSION, label + " plan version")
        false_authority(value.get("authorityFlags"), label)

    need(registry.get("documentationGapState") == "closed", "documentation gap state")
    need(
        registry.get("globalClosure", {}).get("state") == "closed",
        "global closure state",
    )
    need(
        registry.get("capabilityClaimState")
        == "unchanged_and_governed_by_docs/evidence/CLAIMS.json",
        "capability truth state",
    )
    need(registry.get("paperTraceabilityPath") == PAPER_PATH, "paper path")
    need(
        git("hash-object", PAPER_PATH) == registry.get("paperTraceabilityBlobSha"),
        "paper traceability blob identity",
    )

    module_ids = [row.get("id") for row in modules.get("modules", [])]
    need(
        len(module_ids) == 40 and len(module_ids) == len(set(module_ids)),
        "module registry closure",
    )
    critical = registry.get("criticalModules")
    need(isinstance(critical, list) and len(critical) == 14, "critical module count")
    need(set(critical).issubset(set(module_ids)), "unknown critical module")

    gates = registry.get("closureGates")
    need(isinstance(gates, list) and len(gates) == 13, "closure gate count")
    need(
        [row.get("id") for row in gates]
        == [f"ACG-{index:02d}" for index in range(1, 14)],
        "closure gate IDs",
    )
    need(all(row.get("required") is True for row in gates), "optional closure gate")

    rules = registry.get("rules")
    for key in (
        "allCriticalModulesCovered",
        "allRequiredProtocolsRegistered",
        "allRequiredDataDomainsOwned",
        "globalCanonicalPathClosureRequired",
        "globalVerifierMustInvokeAlgorithmVerifier",
        "paperSourceLockAndClaimAnchorsRequired",
        "temporaryInstallersForbidden",
        "dedicatedAndGlobalWorkflowsReadOnly",
    ):
        need(rules.get(key) is True, "algorithm rule " + key)

    documents = registry.get("documents")
    need(isinstance(documents, list) and len(documents) == 6, "specification count")
    ids = [row.get("id") for row in documents]
    need(len(ids) == len(set(ids)), "duplicate specification ID")
    bound = coverage(registry)
    unresolved = re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b", re.IGNORECASE)
    common_terms = [
        "deterministic reference",
        "golden vector",
        "rollback",
        "unlearning",
        "acceptance gate",
        "non-claims",
        "implementation sequence",
    ]
    for row in documents:
        doc_id = row["id"]
        path = row["path"]
        target = ROOT / path
        need(target.is_file(), doc_id + " missing")
        text = target.read_text(encoding="utf-8")
        need(row.get("documentationState") == "closed", doc_id + " documentation state")
        need(
            row.get("implementationState") == "not_implied",
            doc_id + " implementation state",
        )
        need(
            len(text.encode("utf-8")) >= int(rules["minimumDocumentBytes"]),
            doc_id + " byte floor",
        )
        need(
            word_count(text) >= int(rules["minimumDocumentWords"]),
            doc_id + " word floor",
        )
        need(git("hash-object", path) == row.get("blobSha"), doc_id + " blob identity")
        need(not unresolved.search(text), doc_id + " unresolved marker")
        positions = [text.find(heading) for heading in HEADINGS]
        need(all(position >= 0 for position in positions), doc_id + " missing section")
        need(positions == sorted(positions), doc_id + " section order")
        need("**Documentation state:** `closed`" in text, doc_id + " closure marker")
        need(
            "**Implementation state:** not implied" in text,
            doc_id + " implementation marker",
        )
        need(
            protocol_authority_boundary(text),
            doc_id + " protocol authority boundary",
        )
        for module in row["modules"]:
            need(module in text, doc_id + " missing module " + module)
        for paper_id in row.get("paperIds", []):
            need(
                paper_id in {item["id"] for item in papers["papers"]},
                doc_id + " unknown paper",
            )
            need(paper_id in text, doc_id + " missing paper " + paper_id)
        for term in common_terms:
            need(term.casefold() in text.casefold(), doc_id + " missing term " + term)
    need(
        all(bound[module] for module in critical),
        "critical module without specification",
    )

    contract_ids = {row["id"] for row in contracts["contracts"]}
    protocol_ids = {row["id"] for row in protocols["protocols"]}
    domain_ids = {row["id"] for row in data["domains"]}
    required_protocols = registry.get("requiredProtocols")
    required_domains = registry.get("requiredDataDomains")
    need(
        isinstance(required_protocols, list) and len(required_protocols) >= 20,
        "protocol closure size",
    )
    need(set(required_protocols).issubset(contract_ids), "required contract missing")
    need(
        set(required_protocols).issubset(protocol_ids),
        "required protocol schema missing",
    )
    need(
        set(required_domains).issubset(domain_ids),
        "required data authority domain missing",
    )
    protocol_rows = {row["id"]: row for row in protocols["protocols"]}
    for protocol_id in required_protocols:
        row = protocol_rows[protocol_id]
        need(row["contractId"] == protocol_id, protocol_id + " contract identity")
        need(
            row["denyUnknownCriticalFields"] is True,
            protocol_id + " unknown-field policy",
        )
        need(row["maximumEncodedBytes"] > 0 and row["fields"], protocol_id + " bounds")
        names = [item["name"] for item in row["fields"]]
        need(len(names) == len(set(names)), protocol_id + " duplicate field")

    canonical = set(document_system["canonicalPaths"])
    required_paths = {
        REGISTRY_PATH,
        PAPER_PATH,
        STATUS_PATH,
        LEARNING_README,
        WORKFLOW_PATH,
        GLOBAL_WORKFLOW,
        GLOBAL_VERIFIER,
        *[row["path"] for row in documents],
    }
    need(required_paths.issubset(canonical), "global canonical adaptive path closure")
    for path in TEMPORARY_PATHS:
        need(not (ROOT / path).exists(), "temporary installer present " + path)

    packages = {row["id"]: row for row in work["packages"]}
    need(DOC_PACKAGE in packages, "adaptive work package")
    package = packages[DOC_PACKAGE]
    need(package["state"] == "source_implemented", "adaptive package state")
    need(package["authorityDelta"] == "none", "adaptive package authority")
    need(package["sourceMutationAllowed"] is True, "adaptive package mutation")
    need(
        DOC_PACKAGE in packages["DOC-2-DEFAULT-BRANCH-SELECTION"]["developmentAfter"],
        "default selection dependency",
    )
    for dag_path in DAG_PATHS:
        dag = load(dag_path)
        need(DOC_PACKAGE in dag["nodes"], dag_path + " node")
        edges = {(row["from"], row["to"]) for row in dag["edges"]}
        need(
            ("DOC-3C-MODULE-DOC-CLOSED-WORLD", DOC_PACKAGE) in edges,
            dag_path + " predecessor edge",
        )
        need(
            (DOC_PACKAGE, "DOC-2-DEFAULT-BRANCH-SELECTION") in edges,
            dag_path + " selection edge",
        )

    profiles = {row["id"]: row for row in experiments.get("quantitativeProfiles", [])}
    need("adaptive_longitudinal_v1" in profiles, "quantitative profile")
    profile = profiles["adaptive_longitudinal_v1"]
    need(profile["minimumEffectiveSampleSize"] >= 400, "ESS floor")
    need(profile["bootstrapReplicates"] >= 2000, "bootstrap floor")
    need(profile["minimumFutureWindows"] >= 2, "future window floor")
    need(profile["minimumIndependentSnapshots"] >= 3, "snapshot floor")
    need(profile["deletionNonResurrectionCount"] == 0, "deletion floor")

    lifecycle = artifacts.get("lifecycleStateMachine")
    need(isinstance(lifecycle, dict), "artifact lifecycle state machine")
    need(lifecycle["bytesImmutable"] is True, "artifact immutability")
    need(lifecycle["currentRunReplacementAllowed"] is False, "current run replacement")
    need(
        lifecycle["selectionDistinctFromAcceptance"] is True,
        "selection/acceptance separation",
    )

    claim_current = {row["id"]: row["current"] for row in claims["ladders"]}
    need(claim_current["systemLearning"] == "L0_STATIC", "learning claim advanced")
    need(claim_current["ndu"] == "D0_SPECIFIED_ONLY", "NDU claim advanced")
    need(claim_current["neuron"] == "N0_METAPHORICAL", "neuron claim advanced")
    need(claim_current["selfIteration"] == "SI0_NONE", "self-iteration claim advanced")

    verify_sources()

    for rel in (
        LEARNING_README,
        "README.md",
        "docs/modules/README.md",
        WORKFLOW_PATH,
        GLOBAL_WORKFLOW,
        GLOBAL_VERIFIER,
        STATUS_PATH,
    ):
        need((ROOT / rel).is_file(), rel + " missing")
    learning_readme = (ROOT / LEARNING_README).read_text(encoding="utf-8")
    for row in documents:
        need(
            Path(row["path"]).name in learning_readme,
            "learning index missing " + row["id"],
        )
    need("ALGORITHM_SPECS.json" in learning_readme, "learning index algorithm registry")
    need("PAPER_TRACEABILITY.json" in learning_readme, "learning index paper registry")
    need(
        (ROOT / STATUS_PATH).read_text(encoding="utf-8")
        == status_text(registry, papers),
        "algorithm status drift",
    )

    dedicated_workflow = (ROOT / WORKFLOW_PATH).read_text(encoding="utf-8")
    global_workflow = (ROOT / GLOBAL_WORKFLOW).read_text(encoding="utf-8")
    global_verifier = (ROOT / GLOBAL_VERIFIER).read_text(encoding="utf-8")
    for workflow, label in (
        (dedicated_workflow, "dedicated workflow"),
        (global_workflow, "global workflow"),
    ):
        need("permissions:\n  contents: read" in workflow, label + " permissions")
        for forbidden in (
            "contents: write",
            "git push",
            "update-ref",
            "persist-credentials: true",
        ):
            need(forbidden not in workflow, label + " mutation " + forbidden)
        need("git merge-tree --write-tree" in workflow, label + " synthetic merge")
    for token in (
        "python3 scripts/hepta-algorithm-docs.py self-test",
        "python3 scripts/hepta-algorithm-docs.py verify-sources",
        "python3 scripts/hepta-algorithm-docs.py verify",
        "python3 scripts/hepta-algorithm-docs.py generate-status",
    ):
        need(token in dedicated_workflow, "dedicated workflow token " + token)
        # Global verification owns the subordinate verify call; self-tests and
        # source checks remain separate commands.
        if token != "python3 scripts/hepta-algorithm-docs.py verify":
            need(token in global_workflow, "global workflow token " + token)

    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_ALGORITHM_DOCS_CLOSED_WORLD_V2",
                "criticalModules": len(critical),
                "specifications": len(documents),
                "closureGates": len(gates),
                "protocols": len(required_protocols),
                "papers": len(papers["papers"]),
                "documentationGapState": "closed",
                "globalClosureState": "closed",
                "capabilityClaimsAdvanced": False,
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0


def self_test() -> int:
    need(len(AUTHORITY_KEYS) == 17, "authority fixture")
    need(len(HEADINGS) == 13, "heading fixture")
    authority_fixture = (
        "Canonical production protocols remain owned by "
        f"`{CONTRACTS_PATH}` and `{PROTOCOLS_PATH}`."
    )
    need(
        protocol_authority_boundary(authority_fixture),
        "canonical protocol authority fixture",
    )
    hostile_authority_cases: list[str] = []

    def rejected_authority(name: str, candidate: str) -> None:
        need(
            not protocol_authority_boundary(candidate),
            "hostile protocol authority fixture accepted: " + name,
        )
        hostile_authority_cases.append(name)

    rejected_authority(
        "abbreviated_protocol_schema",
        authority_fixture.replace(PROTOCOLS_PATH, Path(PROTOCOLS_PATH).name),
    )
    rejected_authority(
        "abbreviated_contract_registry",
        authority_fixture.replace(CONTRACTS_PATH, Path(CONTRACTS_PATH).name),
    )
    rejected_authority(
        "wrong_protocol_directory",
        authority_fixture.replace(
            PROTOCOLS_PATH, "docs/learning/PROTOCOL_SCHEMAS.json"
        ),
    )
    rejected_authority(
        "unquoted_canonical_protocol_path",
        authority_fixture.replace(f"`{PROTOCOLS_PATH}`", PROTOCOLS_PATH),
    )
    rejected_authority(
        "canonical_pair_plus_abbreviated_reference",
        authority_fixture + " Alias `PROTOCOL_SCHEMAS.json` is forbidden.",
    )
    need(
        len(hostile_authority_cases) == 5,
        "hostile protocol authority fixture count",
    )
    try:
        json.loads('{"x":1,"x":2}', object_pairs_hook=pairs)
        raise AssertionError("duplicate key accepted")
    except DuplicateKey:
        pass
    fixture = {
        "criticalModules": ["a"],
        "documents": [{"id": "s", "modules": ["a"]}],
        "planId": PLAN_ID,
        "planVersion": PLAN_VERSION,
        "documentationGapState": "closed",
        "globalClosure": {"state": "closed", "workPackageId": DOC_PACKAGE},
        "capabilityClaimState": "unchanged",
        "closureGates": [],
        "requiredProtocols": ["p"],
    }
    papers = load(PAPER_PATH)
    need("| `a` | `s` |" in status_text(fixture, papers), "status fixture")
    validate_paper_sources(papers)
    hostile_cases: list[str] = []

    def rejected(name: str, mutate: Any) -> None:
        candidate = copy.deepcopy(papers)
        mutate(candidate)
        try:
            validate_paper_sources(candidate)
        except SystemExit:
            hostile_cases.append(name)
            return
        raise AssertionError("hostile paper-source case accepted: " + name)

    rejected(
        "missing_source_digest",
        lambda value: value["papers"][0]["sourceLock"].__setitem__(
            "contentDigest", None
        ),
    )
    rejected(
        "wrong_source_digest",
        lambda value: value["papers"][3]["sourceLock"].__setitem__(
            "contentDigest", "0" * 64
        ),
    )
    rejected(
        "challenge_body_substitution",
        lambda value: value["papers"][0]["sourceLock"].__setitem__(
            "sourceKind", "html_challenge"
        ),
    )
    rejected(
        "missing_exact_locator",
        lambda value: value["papers"][0]["claimAnchors"][0].__setitem__(
            "locator", None
        ),
    )
    rejected(
        "claim_text_substitution",
        lambda value: value["papers"][1]["claimAnchors"][0].__setitem__(
            "sourceTextDigest", "f" * 64
        ),
    )
    rejected(
        "source_artifact_substitution",
        lambda value: value["papers"][2]["claimAnchors"][0].__setitem__(
            "sourceArtifactId", "other-artifact"
        ),
    )
    rejected(
        "abstract_promoted_to_theorem",
        lambda value: value["papers"][0]["claimAnchors"][0]["locator"].__setitem__(
            "theoremOrEquation", "Theorem 1"
        ),
    )

    def add_unsupported_attribution(value: dict[str, Any]) -> None:
        row = value["papers"][3]
        row["claimsUsed"].append("quasi_uniform_sensor_geometry")
        anchor = copy.deepcopy(row["claimAnchors"][-1])
        anchor["claim"] = "quasi_uniform_sensor_geometry"
        row["claimAnchors"].append(anchor)

    rejected("Hepta_extension_attributed_to_paper", add_unsupported_attribution)
    need(len(hostile_cases) == 8, "hostile paper-source fixture count")
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_ALGORITHM_DOCS_SELF_TEST_V4",
                "hostilePaperSourceCases": hostile_cases,
                "hostileProtocolAuthorityCases": hostile_authority_cases,
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0


def generate_status(check: bool) -> int:
    registry = load(REGISTRY_PATH)
    papers = load(PAPER_PATH)
    text = status_text(registry, papers)
    target = ROOT / STATUS_PATH
    if check:
        need(target.read_text(encoding="utf-8") == text, "algorithm status drift")
        print(
            json.dumps({"status": "PASS_HEPTA_ALGORITHM_STATUS_CHECK"}, sort_keys=True)
        )
        return 0
    target.write_text(text, encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_ALGORITHM_STATUS_GENERATED",
                "sha256": sha256_text(text),
            },
            sort_keys=True,
        )
    )
    return 0


def receipt(expected_sha: str, output: str) -> int:
    verify()
    need(re.fullmatch(r"[0-9a-f]{40}", expected_sha) is not None, "expected SHA")
    need(git("rev-parse", "HEAD") == expected_sha, "receipt head")
    registry = load(REGISTRY_PATH)
    papers = load(PAPER_PATH)
    value = {
        "schema": RECEIPT_SCHEMA,
        "expectedSha": expected_sha,
        "headSha": git("rev-parse", "HEAD"),
        "treeSha": git("rev-parse", "HEAD^{tree}"),
        "algorithmRegistryBlobSha": git("hash-object", REGISTRY_PATH),
        "paperTraceabilityBlobSha": registry["paperTraceabilityBlobSha"],
        "paperSourceLockSha256": sha256_text(
            json.dumps(
                [row["sourceLock"] for row in papers["papers"]],
                sort_keys=True,
                separators=(",", ":"),
            )
        ),
        "specificationBlobShas": {
            row["id"]: row["blobSha"] for row in registry["documents"]
        },
        "requiredProtocolIds": registry["requiredProtocols"],
        "documentationGapState": registry["documentationGapState"],
        "globalClosureState": registry["globalClosure"]["state"],
        "capabilityClaimsAdvanced": False,
        "authorityGranted": False,
        "observedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    target = Path(output)
    if not target.is_absolute():
        target = ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"status": "PASS_HEPTA_ALGORITHM_RECEIPT_V2", "path": str(target)},
            sort_keys=True,
        )
    )
    return 0


def receipt_verify(input_path: str, expected_sha: str) -> int:
    target = Path(input_path)
    if not target.is_absolute():
        target = ROOT / target
    try:
        value = json.loads(target.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except Exception as exc:
        die("receipt input: " + str(exc))
    need(value.get("schema") == RECEIPT_SCHEMA, "receipt schema")
    need(value.get("expectedSha") == expected_sha, "receipt expected SHA")
    need(
        value.get("headSha") == git("rev-parse", "HEAD") == expected_sha,
        "receipt current head",
    )
    need(value.get("treeSha") == git("rev-parse", "HEAD^{tree}"), "receipt tree")
    need(
        value.get("algorithmRegistryBlobSha") == git("hash-object", REGISTRY_PATH),
        "receipt registry",
    )
    need(value.get("documentationGapState") == "closed", "receipt closure")
    need(value.get("globalClosureState") == "closed", "receipt global closure")
    need(value.get("capabilityClaimsAdvanced") is False, "receipt capability")
    need(value.get("authorityGranted") is False, "receipt authority")
    print(
        json.dumps({"status": "PASS_HEPTA_ALGORITHM_RECEIPT_VERIFY_V2"}, sort_keys=True)
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    sub.add_parser("verify")
    sub.add_parser("verify-sources")
    generate = sub.add_parser("generate-status")
    generate.add_argument("--check", action="store_true")
    create = sub.add_parser("receipt")
    create.add_argument("--expected-sha", required=True)
    create.add_argument("--output", required=True)
    check = sub.add_parser("receipt-verify")
    check.add_argument("--input", required=True)
    check.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    if args.command == "self-test":
        return self_test()
    if args.command == "verify":
        return verify()
    if args.command == "verify-sources":
        return verify_sources()
    if args.command == "generate-status":
        return generate_status(args.check)
    if args.command == "receipt":
        return receipt(args.expected_sha, args.output)
    if args.command == "receipt-verify":
        return receipt_verify(args.input, args.expected_sha)
    die("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
