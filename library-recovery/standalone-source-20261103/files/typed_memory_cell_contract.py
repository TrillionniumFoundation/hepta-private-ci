#!/usr/bin/env python3
"""Typed MemoryCell lineage contract, qualification only.

This deterministic standard-library artifact models episodic, semantic,
procedural and working memory as immutable compressed payloads attached to a
Cell contract. Cells can split under a bounded budget, expose rollback
lineage, and expire through a retention watermark. Tombstones are
authoritative: deletion removes retrieval support and cannot be undone by add,
split, rollback, or correction.

The protocol is intentionally fail-closed: ``mode = SHADOW_ONLY`` and
``authority = DENY_ALL``. No provider, model, filesystem or production memory
service is called.
"""
from __future__ import annotations

from dataclasses import dataclass
import argparse
import hashlib
import json
import zlib
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

MEMORY_TYPES = ("episodic", "semantic", "procedural", "working")
MODE = "SHADOW_ONLY"
PROTOCOL_MODE = MODE
AUTHORITY = "DENY_ALL"
ZERO_DIGEST = "0" * 64


class MemoryContractError(ValueError):
    """A contract, digest, authority, budget, or lineage invariant failed."""


class MemoryTypeError(MemoryContractError):
    """A memory type is unsupported or a typed read is mismatched."""


class WrongMemoryType(MemoryTypeError):
    """A Cell was consumed as another supported memory type."""


class TombstonedMemoryError(MemoryContractError):
    """A deleted or expired Cell cannot be read or resurrected."""


class LineageError(MemoryContractError):
    """A parent, child, or rollback lineage invariant failed."""


class RetrievalDenied(MemoryContractError):
    """Retrieval support, authority, or mode is not fail-closed."""


def _canonical_bytes(payload: str) -> bytes:
    if not isinstance(payload, str):
        raise MemoryContractError("payload must be a string")
    return payload.encode("utf-8")


def digest_payload(memory_type: str, payload: str, parent_digest: str = "") -> str:
    """Return a deterministic SHA-256 digest bound to type, parent and payload."""
    if memory_type not in MEMORY_TYPES:
        raise MemoryTypeError(memory_type)
    raw = _canonical_bytes(payload)
    compressed = zlib.compress(raw, level=9)
    return hashlib.sha256(
        b"typed-memory-payload-v2|"
        + memory_type.encode("utf-8")
        + b"|"
        + parent_digest.encode("utf-8")
        + b"|"
        + hashlib.sha256(raw).digest()
        + b"|"
        + hashlib.sha256(compressed).digest()
    ).hexdigest()


@dataclass(frozen=True)
class CompressedPayload:
    """Immutable zlib bytes plus raw/compressed integrity digests."""

    raw_digest: str
    compressed_digest: str
    compressed: bytes
    raw_size: int
    compressed_size: int
    codec: str = "zlib"

    @classmethod
    def from_text(cls, payload: str) -> "CompressedPayload":
        raw = _canonical_bytes(payload)
        compressed = zlib.compress(raw, level=9)
        return cls(
            raw_digest=hashlib.sha256(raw).hexdigest(),
            compressed_digest=hashlib.sha256(compressed).hexdigest(),
            compressed=bytes(compressed),
            raw_size=len(raw),
            compressed_size=len(compressed),
        )

    def decode(self) -> str:
        if hashlib.sha256(self.compressed).hexdigest() != self.compressed_digest:
            raise MemoryContractError("compressed payload digest drift")
        raw = zlib.decompress(self.compressed)
        if hashlib.sha256(raw).hexdigest() != self.raw_digest:
            raise MemoryContractError("raw payload digest drift")
        return raw.decode("utf-8")


@dataclass(frozen=True)
class MemorySnapshot:
    artifact_digest: str
    contract_digest: str
    payload_digest: str
    compressed_digest: str
    predecessor_digest: str
    revision: int
    cell_id: str
    memory_type: str
    mode: str = MODE
    authority: str = AUTHORITY

    def as_dict(self) -> Dict[str, object]:
        return {
            "artifact_digest": self.artifact_digest,
            "contract_digest": self.contract_digest,
            "payload_digest": self.payload_digest,
            "compressed_digest": self.compressed_digest,
            "predecessor_digest": self.predecessor_digest,
            "revision": self.revision,
            "cell_id": self.cell_id,
            "memory_type": self.memory_type,
            "mode": self.mode,
            "authority": self.authority,
        }


@dataclass(frozen=True)
class MemoryCell:
    """Immutable typed Cell; the first seven fields preserve the old API."""

    cell_id: str
    memory_type: str
    payload_digest: str
    compressed_bytes: int
    parent_digest: str
    budget_flops: int
    retention_until: int
    tombstoned: bool = False
    mode: str = MODE
    authority: str = AUTHORITY
    compressed_digest: str = ""
    predecessor_digest: str = ZERO_DIGEST
    revision: int = 1
    raw_digest: str = ""
    payload_text: str = ""

    def validate(self) -> None:
        if self.memory_type not in MEMORY_TYPES:
            raise MemoryTypeError(self.memory_type)
        if not self.cell_id or len(self.payload_digest) != 64:
            raise MemoryContractError("invalid cell identity or payload digest")
        if any(char not in "0123456789abcdef" for char in self.payload_digest):
            raise MemoryContractError("payload digest must be lowercase sha256")
        if self.compressed_bytes <= 0 or self.budget_flops <= 0:
            raise MemoryContractError("compressed size and budget must be positive")
        if self.retention_until < 0 or self.revision < 1:
            raise MemoryContractError("retention and revision must be non-negative/positive")
        if self.mode != MODE or self.authority != AUTHORITY:
            raise MemoryContractError("memory cell cannot claim production authority")
        for label, value in (("parent_digest", self.parent_digest), ("predecessor_digest", self.predecessor_digest)):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise MemoryContractError(f"invalid {label}")
        if self.compressed_digest and (
            len(self.compressed_digest) != 64
            or any(char not in "0123456789abcdef" for char in self.compressed_digest)
        ):
            raise MemoryContractError("invalid compressed digest")
        if self.payload_text:
            payload = CompressedPayload.from_text(self.payload_text)
            if payload.compressed_size != self.compressed_bytes:
                raise MemoryContractError("compressed byte count drift")
            if self.raw_digest and self.raw_digest != payload.raw_digest:
                raise MemoryContractError("raw payload digest drift")
            if self.compressed_digest and self.compressed_digest != payload.compressed_digest:
                raise MemoryContractError("compressed payload digest drift")

    @property
    def digest(self) -> str:
        self.validate()
        payload = {
            "cell_id": self.cell_id,
            "memory_type": self.memory_type,
            "payload_digest": self.payload_digest,
            "compressed_bytes": self.compressed_bytes,
            "compressed_digest": self.compressed_digest,
            "parent_digest": self.parent_digest,
            "budget_flops": self.budget_flops,
            "retention_until": self.retention_until,
            "tombstoned": self.tombstoned,
            "mode": self.mode,
            "authority": self.authority,
            "predecessor_digest": self.predecessor_digest,
            "revision": self.revision,
            "raw_digest": self.raw_digest,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @property
    def artifact_digest(self) -> str:
        return self.digest

    def decode(self, requested_type: Optional[str] = None) -> str:
        self.validate()
        if requested_type is not None:
            if requested_type not in MEMORY_TYPES:
                raise MemoryTypeError(requested_type)
            if requested_type != self.memory_type:
                raise WrongMemoryType(f"Cell {self.cell_id} stores {self.memory_type}, requested {requested_type}")
        if not self.payload_text:
            raise MemoryContractError("payload bytes are unavailable for legacy digest-only Cell")
        return CompressedPayload.from_text(self.payload_text).decode()


# A contract alias makes the immutable MemoryCell schema discoverable to
# callers that use the more explicit name.
MemoryContract = MemoryCell


@dataclass(frozen=True)
class Tombstone:
    cell_id: str
    target_digest: str
    reason: str
    tombstone_digest: str
    sequence: int
    correction_of: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {
            "cell_id": self.cell_id,
            "target_digest": self.target_digest,
            "reason": self.reason,
            "tombstone_digest": self.tombstone_digest,
            "sequence": self.sequence,
            "correction_of": self.correction_of,
        }


class MemoryRegistry:
    """Mutable shadow registry around immutable typed Cells."""

    def __init__(self) -> None:
        self.cells: Dict[str, MemoryCell] = {}
        self.tombstones: Dict[str, str] = {}
        self.tombstone_records: Dict[str, Tombstone] = {}
        self._children: Dict[str, List[str]] = {}
        self._lineage: Dict[str, Tuple[MemorySnapshot, ...]] = {}
        self._sequence = 0
        self._watermark = 0

    def _snapshot(self, cell: MemoryCell, predecessor: str) -> MemorySnapshot:
        artifact = hashlib.sha256(
            ("typed-memory-artifact-v2|" + cell.digest + "|" + predecessor + "|" + str(cell.revision)).encode()
        ).hexdigest()
        return MemorySnapshot(
            artifact_digest=artifact,
            contract_digest=cell.digest,
            payload_digest=cell.payload_digest,
            compressed_digest=cell.compressed_digest,
            predecessor_digest=predecessor,
            revision=cell.revision,
            cell_id=cell.cell_id,
            memory_type=cell.memory_type,
            mode=cell.mode,
            authority=cell.authority,
        )

    def add(self, cell: MemoryCell) -> None:
        cell.validate()
        if cell.cell_id in self.cells or cell.cell_id in self.tombstones:
            raise MemoryContractError("cell id is already used or tombstoned")
        if cell.parent_digest != ZERO_DIGEST and not any(item.digest == cell.parent_digest for item in self.cells.values()):
            if not any(snapshot.artifact_digest == cell.parent_digest for snapshots in self._lineage.values() for snapshot in snapshots):
                raise LineageError("parent digest is not present in active lineage")
        self.cells[cell.cell_id] = cell
        self._children.setdefault(cell.cell_id, [])
        initial = self._snapshot(cell, cell.predecessor_digest)
        candidate = self._snapshot(cell, initial.artifact_digest)
        self._lineage[cell.cell_id] = (initial, candidate)

    def split(
        self,
        parent_id: str,
        parts: Iterable[Tuple[str, str]],
        *,
        memory_type: Optional[str] = None,
    ) -> List[MemoryCell]:
        parent = self.get(parent_id)
        parts_list = list(parts)
        if not parts_list:
            raise MemoryContractError("split requires at least one child")
        child_type = parent.memory_type if memory_type is None else memory_type
        if child_type not in MEMORY_TYPES:
            raise MemoryTypeError(child_type)
        existing_budget = sum(self.cells[child_id].budget_flops for child_id in self._children.get(parent_id, []))
        child_budget = parent.budget_flops // len(parts_list)
        if child_budget <= 0 or existing_budget + child_budget * len(parts_list) > parent.budget_flops:
            raise MemoryContractError("split budget exceeds parent budget")
        proposed_ids = [f"{parent.cell_id}:{suffix}" for suffix, _ in parts_list]
        if len(set(proposed_ids)) != len(proposed_ids) or any(
            child_id in self.cells or child_id in self.tombstones for child_id in proposed_ids
        ):
            raise MemoryContractError("child id is already used or tombstoned")
        children: List[MemoryCell] = []
        for suffix, payload_text in parts_list:
            child_id = f"{parent.cell_id}:{suffix}"
            compressed = CompressedPayload.from_text(payload_text)
            child = MemoryCell(
                cell_id=child_id,
                memory_type=child_type,
                payload_digest=digest_payload(child_type, payload_text, parent.digest),
                compressed_bytes=compressed.compressed_size,
                parent_digest=parent.digest,
                budget_flops=child_budget,
                retention_until=parent.retention_until,
                compressed_digest=compressed.compressed_digest,
                predecessor_digest=parent.digest,
                revision=1,
                raw_digest=compressed.raw_digest,
                payload_text=payload_text,
            )
            self.add(child)
            self._children.setdefault(parent_id, []).append(child_id)
            children.append(child)
        return children

    def tombstone(self, cell_id: str, reason: str) -> Tombstone:
        if cell_id in self.tombstones:
            prior = self.tombstone_records[cell_id]
            self._sequence += 1
            corrected = Tombstone(
                cell_id=cell_id,
                target_digest=prior.target_digest,
                reason=reason,
                tombstone_digest=hashlib.sha256(
                    ("typed-memory-tombstone-correction|" + prior.tombstone_digest + "|" + reason + "|" + str(self._sequence)).encode()
                ).hexdigest(),
                sequence=self._sequence,
                correction_of=prior.tombstone_digest,
            )
            self.tombstone_records[cell_id] = corrected
            self.tombstones[cell_id] = reason
            return corrected
        cell = self.get(cell_id)
        self._sequence += 1
        tombstone = Tombstone(
            cell_id=cell_id,
            target_digest=cell.digest,
            reason=reason,
            tombstone_digest=hashlib.sha256(
                ("typed-memory-tombstone-v2|" + cell_id + "|" + cell.digest + "|" + reason + "|" + str(self._sequence)).encode()
            ).hexdigest(),
            sequence=self._sequence,
        )
        self.tombstone_records[cell_id] = tombstone
        self.tombstones[cell_id] = reason
        del self.cells[cell_id]
        return tombstone

    def advance(self, watermark: int) -> Tuple[Tombstone, ...]:
        if watermark < self._watermark:
            raise MemoryContractError("retention watermark cannot move backwards")
        self._watermark = watermark
        expired: List[Tombstone] = []
        for cell in tuple(self.cells.values()):
            if cell.retention_until > 0 and cell.retention_until <= watermark:
                expired.append(self.tombstone(cell.cell_id, "retention_expired"))
        return tuple(expired)

    def get(self, cell_id: str) -> MemoryCell:
        if cell_id in self.tombstones:
            raise TombstonedMemoryError(cell_id)
        try:
            return self.cells[cell_id]
        except KeyError as exc:
            raise MemoryContractError("unknown memory cell") from exc

    def rollback(self, cell_id: str, artifact_digest: str) -> MemorySnapshot:
        if cell_id in self.tombstones:
            raise TombstonedMemoryError(cell_id)
        if cell_id not in self._lineage:
            raise LineageError("unknown Cell lineage")
        for snapshot in self._lineage[cell_id]:
            if snapshot.artifact_digest == artifact_digest:
                return snapshot
        raise LineageError("rollback target is not in Cell lineage")

    def restore(self, cell_id: str, artifact_digest: str) -> None:
        if cell_id in self.tombstones:
            raise TombstonedMemoryError(cell_id)
        raise MemoryContractError("restore is not a permitted shadow operation")

    def children_of(self, parent_id: str) -> Tuple[MemoryCell, ...]:
        if parent_id not in self._children:
            raise LineageError("unknown parent Cell")
        return tuple(self.cells[child_id] for child_id in self._children[parent_id] if child_id in self.cells)

    def retrieve(
        self,
        memory_type: str,
        query_digest: str = ZERO_DIGEST,
        *,
        capability: Sequence[str] = ("retrieve",),
        authority: str = AUTHORITY,
        mode: str = MODE,
    ) -> List[MemoryCell]:
        if memory_type not in MEMORY_TYPES:
            raise MemoryTypeError(memory_type)
        if authority != AUTHORITY or mode != MODE:
            raise RetrievalDenied("retrieval authority is fail-closed")
        if "retrieve" not in capability and f"retrieve:{memory_type}" not in capability:
            raise RetrievalDenied("retrieval support is not declared")
        if not query_digest or len(query_digest) != 64 or any(char not in "0123456789abcdef" for char in query_digest):
            raise MemoryContractError("query digest must be a lowercase sha256 digest")
        return [
            cell
            for cell in self.cells.values()
            if cell.memory_type == memory_type
            and not cell.tombstoned
            and (cell.payload_digest == query_digest or query_digest == ZERO_DIGEST)
        ]


def run(seed: int = 17) -> dict:
    registry = MemoryRegistry()
    parent_payload = f"knowledge:{seed}"
    parent_compressed = CompressedPayload.from_text(parent_payload)
    parent = MemoryCell(
        cell_id=f"memory:{seed}:root",
        memory_type="semantic",
        payload_digest=digest_payload("semantic", parent_payload),
        compressed_bytes=parent_compressed.compressed_size,
        parent_digest=ZERO_DIGEST,
        budget_flops=4096,
        retention_until=100,
        compressed_digest=parent_compressed.compressed_digest,
        raw_digest=parent_compressed.raw_digest,
        payload_text=parent_payload,
    )
    registry.add(parent)
    children = registry.split(parent.cell_id, (("facts", "fact-a"), ("relations", "fact-b")))
    tombstone = registry.tombstone(children[1].cell_id, "deletion-test")
    rollback = registry.rollback(parent.cell_id, registry._lineage[parent.cell_id][0].artifact_digest)
    return {
        "seed": seed,
        "mode": MODE,
        "authority": AUTHORITY,
        "parent": parent.__dict__,
        "children": [child.__dict__ for child in children],
        "active_cells": sorted(registry.cells),
        "tombstones": dict(registry.tombstones),
        "tombstone_records": {key: value.as_dict() for key, value in registry.tombstone_records.items()},
        "non_resurrection": children[1].cell_id not in registry.cells,
        "rollback_snapshot": rollback.as_dict(),
        "protocol": {
            "compression_is_digest_only": True,
            "immutable_compressed_payload": True,
            "retrieval_fail_closed": True,
            "model_invocation": False,
            "provider_dispatch": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    print(json.dumps(run(args.seed), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
