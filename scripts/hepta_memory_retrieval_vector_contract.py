#!/usr/bin/env python3
"""Validate the repository-contained memory.retrieval vector publication contract.

This verifier proves source and composition consistency only. It deliberately
refuses to establish a production encoder, durable publisher, deployed store,
target-host qualification, activation, or release.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_COMPOSITION = "qualification/memory-retrieval/product-composition.json"
VECTOR_SOURCE = "codex-rs/hepta-memory-retrieval/src/vector_publication_append.rs"
VECTOR_TEST = "codex-rs/hepta-memory-retrieval/tests/vector_publication_append_api.rs"
VECTOR_GUIDE = "docs/modules/memory.retrieval/VECTOR_OWNER.md"
LIB_SOURCE = "codex-rs/hepta-memory-retrieval/src/lib.rs"

REQUIRED_SOURCE_MARKERS = (
    "pub fn append_vector_publication_checked_v1",
    "CommitOutcomeUnknown",
    "CurrentPublicationMismatch",
    "InvalidGenesisSequence",
    ".validate_successor(next)",
    ".compare_and_publish(",
    ".load_current(",
)
REQUIRED_TEST_MARKERS = (
    "lost_acknowledgement_is_reconciled_without_a_second_write",
    "compare_failure_without_exact_current_is_outcome_unknown",
    "successful_publish_with_failed_confirmation_is_outcome_unknown",
    "stale_expected_parent_is_rejected_before_mutation",
    "successful_port_return_still_requires_exact_committed_object",
)
REQUIRED_GUIDE_MARKERS = (
    "`append_vector_publication_checked_v1`",
    "lost-acknowledgement",
    "never by blind republish",
    "does **not** establish a deployed durable backend",
)
REQUIRED_LIB_MARKERS = (
    "mod vector_publication_append;",
    "pub use vector_publication_append::DurableVectorPublicationAppendErrorV1;",
    "pub use vector_publication_append::append_vector_publication_checked_v1;",
)
REQUIRED_BLOCKERS = (
    "qualified text encoder identity is absent",
    "selected durable vector-index port backend and deployed store are absent",
)


class VectorContractError(ValueError):
    """The source-only vector publication contract is absent or weakened."""


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VectorContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) > 256 * 1024:
        raise VectorContractError(f"contract JSON exceeds 256 KiB: {path}")
    value = json.loads(data, object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise VectorContractError(f"contract JSON must be an object: {path}")
    return value


def _required_file(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.is_file():
        raise VectorContractError(f"required vector contract file is absent: {relative}")
    return path


def _require_markers(path: Path, markers: tuple[str, ...], label: str) -> None:
    text = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise VectorContractError(f"{label} marker missing: {marker}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(root: Path | str = REPOSITORY_ROOT) -> dict[str, Any]:
    root = Path(root)
    paths = {
        "composition": _required_file(root, PRODUCT_COMPOSITION),
        "source": _required_file(root, VECTOR_SOURCE),
        "test": _required_file(root, VECTOR_TEST),
        "guide": _required_file(root, VECTOR_GUIDE),
        "lib": _required_file(root, LIB_SOURCE),
    }

    composition = load_json(paths["composition"])
    if composition.get("schema") != "hepta.memory-retrieval.product-composition.v1":
        raise VectorContractError("unsupported product composition schema")
    if composition.get("module") != "memory.retrieval":
        raise VectorContractError("product composition targets the wrong module")
    if composition.get("sourceIdentityPolicy") != "runtime-exact-head-and-tree":
        raise VectorContractError("vector contract lost exact source identity policy")
    if composition.get("activationMode") != "compatibility":
        raise VectorContractError("vector contract cannot change activation mode")
    if composition.get("productionEnabled") is not False:
        raise VectorContractError("source-only vector contract cannot enable production")

    encoder = composition.get("encoder")
    if not isinstance(encoder, dict):
        raise VectorContractError("encoder contract is absent")
    expected_encoder = {
        "state": "not-established",
        "modelDigest": None,
        "dimensions": None,
        "normalization": None,
    }
    for field, expected in expected_encoder.items():
        if encoder.get(field) != expected:
            raise VectorContractError(f"encoder source-only boundary drifted: {field}")

    index = composition.get("index")
    if not isinstance(index, dict):
        raise VectorContractError("vector index contract is absent")
    expected_index = {
        "state": "not-product-qualified",
        "schema": "hepta.memory-retrieval.vector-index.v2",
        "version": 2,
        "writerFenceRequired": True,
        "staleWriterRejected": True,
        "checkedPublish": (
            "codex-hepta-memory-retrieval:append_vector_publication_checked_v1"
        ),
        "uncertainCommitPolicy": "reload-exact-current-no-blind-republish",
        "exactReplayIdempotent": True,
        "postCommitReloadRequired": True,
        "publisher": None,
        "durableStore": None,
    }
    for field, expected in expected_index.items():
        if index.get(field) != expected:
            raise VectorContractError(f"vector index contract drifted: {field}")

    blockers = composition.get("promotionBlockers")
    if not isinstance(blockers, list):
        raise VectorContractError("promotion blockers must be a list")
    for blocker in REQUIRED_BLOCKERS:
        if blocker not in blockers:
            raise VectorContractError(f"vector promotion blocker missing: {blocker}")

    _require_markers(paths["source"], REQUIRED_SOURCE_MARKERS, "vector source")
    _require_markers(paths["test"], REQUIRED_TEST_MARKERS, "vector test")
    _require_markers(paths["guide"], REQUIRED_GUIDE_MARKERS, "vector guide")
    _require_markers(paths["lib"], REQUIRED_LIB_MARKERS, "crate export")

    return {
        "schema": "hepta.memory-retrieval.vector-contract-observation.v1",
        "compositionPath": PRODUCT_COMPOSITION,
        "compositionSha256": _sha256(paths["composition"]),
        "sourcePath": VECTOR_SOURCE,
        "sourceSha256": _sha256(paths["source"]),
        "testPath": VECTOR_TEST,
        "testSha256": _sha256(paths["test"]),
        "guidePath": VECTOR_GUIDE,
        "guideSha256": _sha256(paths["guide"]),
        "libPath": LIB_SOURCE,
        "libSha256": _sha256(paths["lib"]),
        "checkedPublish": expected_index["checkedPublish"],
        "uncertainCommitPolicy": expected_index["uncertainCommitPolicy"],
        "productionImplementation": False,
        "productionEncoderEstablished": False,
        "durablePublisherEstablished": False,
        "durableStoreEstablished": False,
        "activation": False,
        "release": False,
    }


def main() -> int:
    try:
        print(json.dumps(validate(), indent=2, sort_keys=True))
    except (VectorContractError, OSError, TypeError, ValueError) as error:
        print(f"memory.retrieval vector contract refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
