#!/usr/bin/env python3
"""Build deterministic, target-specific seed corpora for cognitive.types fuzzing.

The corpus is derived only from checked-in qualification vectors.  It contains
no network input and creates no product authority.  Every seed filename is its
SHA-256, so duplicate bytes collapse naturally and campaign receipts can bind
the exact corpus independently of directory order.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
TARGETS: Final[tuple[str, ...]] = (
    "hnmf_base",
    "hnmf_learning",
    "shared_experience_v2",
    "consumer_handoff",
    "canonical_json_grammar",
)

BASE_CONTRACTS: Final = {
    "ModalitySpanRefV1",
    "MemoryEventV1",
    "CrossModalBindingV1",
}
LEARNING_CONTRACTS: Final = {
    "EngramNodeV1",
    "SynapseV1",
    "MemoryCueV1",
    "RecallPacketV1",
    "OutcomeSignalV1",
    "ReplaySelectionReceiptV1",
    "PlasticityBatchV1",
    "TopologyProposalV1",
    "ForgetPropagationReceiptV1",
}
SHARED_CONTRACTS: Final = {
    "SharedExperiencePublicationV2",
    "SharedExperienceSnapshotV2",
    "SharedExperienceUseReceiptV2",
    "SharedExperienceRevocationReceiptV2",
}
CONSUMER_CONTRACTS: Final = {
    "MemoryEventV1",
    "RecallPacketV1",
    "ForgetPropagationReceiptV1",
}


def _load_json(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: top-level JSON object required")
    return value


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _checked_wire(case: object, source: Path) -> tuple[str, bytes]:
    if not isinstance(case, dict):
        raise ValueError(f"{source}: vector case must be an object")
    contract = case.get("contract")
    wire = case.get("wire")
    if not isinstance(contract, str) or not contract:
        raise ValueError(f"{source}: case contract must be a non-empty string")
    if not isinstance(wire, str) or not wire:
        raise ValueError(f"{source}: case wire must be a non-empty string")
    wire_bytes = wire.encode("utf-8")
    if b"\0" in wire_bytes:
        raise ValueError(f"{source}: NUL is forbidden in corpus vectors")
    return contract, wire_bytes


def _targets_for(contract: str) -> set[str]:
    targets = {"canonical_json_grammar"}
    if contract in BASE_CONTRACTS:
        targets.add("hnmf_base")
    if contract in LEARNING_CONTRACTS:
        targets.add("hnmf_learning")
    if contract in SHARED_CONTRACTS:
        targets.add("shared_experience_v2")
    if contract in CONSUMER_CONTRACTS:
        targets.add("consumer_handoff")
    return targets


def _write_seed(directory: Path, data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()
    destination = directory / digest
    if destination.exists():
        if destination.is_symlink() or not destination.is_file():
            raise ValueError(f"unsafe corpus entry {destination}")
        if destination.read_bytes() != data:
            raise ValueError(f"digest collision at {destination}")
    else:
        destination.write_bytes(data)
    return digest


def _clean_target_directory(path: Path) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise ValueError(f"corpus target must be a real directory: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, mode=0o755)


def build(output: Path) -> dict[str, object]:
    if output.exists() and output.is_symlink():
        raise ValueError("output root may not be a symlink")
    output.mkdir(parents=True, exist_ok=True)
    target_dirs = {target: output / target for target in TARGETS}
    for directory in target_dirs.values():
        _clean_target_directory(directory)

    seeds: dict[str, list[str]] = {target: [] for target in TARGETS}

    bound_path = ROOT / "qualification/cognitive-types-v1/bound_vector.json"
    bound = _load_json(bound_path)
    contract = bound.get("contract")
    schema = bound.get("schema")
    schema_version = bound.get("schemaVersion")
    payload = bound.get("payload")
    if not isinstance(contract, str) or not isinstance(schema, str):
        raise ValueError(f"{bound_path}: contract and schema strings required")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ValueError(f"{bound_path}: integer schemaVersion required")
    valid_wire = _canonical_json(
        {
            "contract": contract,
            "payload": payload,
            "schema": schema,
            "schemaVersion": schema_version,
        }
    )
    for target in _targets_for(contract):
        seeds[target].append(_write_seed(target_dirs[target], valid_wire))

    vector_paths = (
        ROOT / "qualification/cognitive-types-v1/negative-vectors.json",
        ROOT / "qualification/cognitive-types-v2/negative-vectors.json",
    )
    for vector_path in vector_paths:
        vectors = _load_json(vector_path)
        cases = vectors.get("cases")
        if not isinstance(cases, list):
            raise ValueError(f"{vector_path}: cases array required")
        for case in cases:
            vector_contract, wire = _checked_wire(case, vector_path)
            for target in _targets_for(vector_contract):
                seeds[target].append(_write_seed(target_dirs[target], wire))

    # Grammar campaigns need malformed framing seeds in addition to semantic
    # negative vectors. These are constants, not generated mutations, so corpus
    # identity remains deterministic across hosts and Python versions.
    grammar_constants = (
        b"",
        b"{",
        b"[]",
        b"null",
        b"{\"contract\":\"ModalitySpanRefV1\"}",
        b"{\"contract\":\"ModalitySpanRefV1\",\"contract\":\"ModalitySpanRefV1\"}",
        b" {\"contract\":\"ModalitySpanRefV1\"}",
        b"{\"schemaVersion\":1.0}",
        b"{\"schemaVersion\":1e0}",
        b"{\"payload\":\"\\ud800\"}",
    )
    for seed in grammar_constants:
        seeds["canonical_json_grammar"].append(
            _write_seed(target_dirs["canonical_json_grammar"], seed)
        )

    manifest_targets: dict[str, object] = {}
    for target in TARGETS:
        directory = target_dirs[target]
        entries = sorted(path for path in directory.iterdir() if path.is_file())
        if any(path.is_symlink() for path in directory.iterdir()):
            raise ValueError(f"{target}: symlinked corpus entry forbidden")
        if not entries:
            raise ValueError(f"{target}: at least one deterministic seed required")
        corpus_hasher = hashlib.sha256()
        for entry in entries:
            data = entry.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if entry.name != digest:
                raise ValueError(f"{entry}: filename/digest mismatch")
            corpus_hasher.update(bytes.fromhex(digest))
            corpus_hasher.update(len(data).to_bytes(8, "big"))
        manifest_targets[target] = {
            "seedCount": len(entries),
            "corpusSha256": corpus_hasher.hexdigest(),
            "seedSha256s": [entry.name for entry in entries],
        }

    manifest: dict[str, object] = {
        "schema": "hepta.cognitive-types.fuzz-corpus.v1",
        "schemaVersion": 1,
        "targets": manifest_targets,
        "productionAuthority": False,
        "activationAuthority": False,
    }
    manifest_bytes = (_canonical_json(manifest) + b"\n")
    (output / "MANIFEST.json").write_bytes(manifest_bytes)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="destination directory for the five deterministic target corpora",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    # Refuse the repository itself or its qualification source directory. A
    # campaign may write only to an explicitly selected generated directory.
    if output == ROOT or output == (ROOT / "qualification/cognitive-types-v1"):
        raise SystemExit("refusing to replace a source directory")
    manifest = build(output)
    print(json.dumps(manifest, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
