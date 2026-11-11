"""Exact Python encoding of the existing native CellCompatibilityBundleV1.

This is a producer-side compatibility check, not selection or execution authority.
The native state owner remains responsible for cutover and authenticated readback.
"""

import hashlib
import re
from dataclasses import asdict, dataclass, replace


REQUIRED = (
    "base",
    "heads",
    "composition",
    "encoder",
    "tokenizer",
    "normalizer",
    "calibration",
    "numeric_profile",
    "output_schema",
    "state_schema",
    "state_semantics",
)
OPTIONAL = ("organ_adapter", "cell_adapter")
LINEAGE = ("source_bundle", "dataset", "update_rule", "evaluation_profile")


def digest_bytes(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("digest must be 32 lowercase hex bytes")
    raw = bytes.fromhex(value)
    if not any(raw):
        raise ValueError("zero digest is not a commitment")
    return raw


def stable_id_bytes(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value):
        raise ValueError("invalid native StableId")
    raw = value.encode("ascii")
    return len(raw).to_bytes(4, "big") + raw


@dataclass(frozen=True)
class Bundle:
    artifact_id: str
    generation: int
    components: dict
    training_lineage: dict | None = None
    rollback_predecessor: str | None = None

    def canonical_bytes(self):
        if type(self.generation) is not int or not 1 <= self.generation < 2**64:
            raise ValueError("generation must be a positive native u64")
        if set(self.components) != set(REQUIRED + OPTIONAL):
            raise ValueError("component fields differ from native bundle")
        if (self.training_lineage is None) != (self.rollback_predecessor is None):
            raise ValueError("lineage and predecessor must be present together")
        raw = bytearray(b"hepta.cell.compatibility-bundle.v1\0")
        raw.extend(stable_id_bytes(self.artifact_id))
        raw.extend(self.generation.to_bytes(8, "big"))
        for name in REQUIRED:
            raw.extend(digest_bytes(self.components[name]))
        for value in (
            self.components["organ_adapter"],
            self.components["cell_adapter"],
            self.rollback_predecessor,
        ):
            raw.append(int(value is not None))
            if value is not None:
                raw.extend(digest_bytes(value))
        if self.training_lineage is not None:
            if set(self.training_lineage) != set(LINEAGE):
                raise ValueError("lineage fields differ from native bundle")
            if self.training_lineage["source_bundle"] != self.rollback_predecessor:
                raise ValueError("lineage names a different predecessor")
            for name in LINEAGE:
                raw.extend(digest_bytes(self.training_lineage[name]))
        return bytes(raw)

    def digest(self):
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def record(self):
        self.canonical_bytes()
        return asdict(self)

    def successor(
        self, artifact_id, components, dataset, update_rule, evaluation_profile
    ):
        predecessor = self.digest()
        candidate = replace(
            self,
            artifact_id=artifact_id,
            generation=self.generation + 1,
            components=dict(components),
            rollback_predecessor=predecessor,
            training_lineage=dict(
                source_bundle=predecessor,
                dataset=dataset,
                update_rule=update_rule,
                evaluation_profile=evaluation_profile,
            ),
        )
        candidate.canonical_bytes()
        return candidate


def validate_local_update(family, source, candidate, trainable="heads"):
    """Mirror the native local-update restriction; no adoption is performed."""
    source_digest = source.digest()
    candidate.digest()
    if family not in ("shared_semantic", "stateful_temporal"):
        raise ValueError("deterministic components do not have neural updates")
    if (
        candidate.rollback_predecessor != source_digest
        or candidate.generation != source.generation + 1
    ):
        raise ValueError("candidate is not the immediate successor")
    if family == "shared_semantic":
        if trainable not in ("heads", "cell_adapter_and_heads"):
            raise ValueError("invalid local trainable part")
        allowed = {"heads"}
        if trainable == "cell_adapter_and_heads":
            allowed.add("cell_adapter")
    else:
        if trainable != "kernel_and_heads":
            raise ValueError("temporal update must name kernel_and_heads")
        allowed = {"base", "heads"}
    changed = {
        key
        for key in source.components
        if source.components[key] != candidate.components[key]
    }
    if not changed or not changed <= allowed:
        raise ValueError("update changed frozen components or contains no change")
    return candidate.digest()


def reset_cutover_digest(
    operation_id,
    state_owner,
    partition,
    source,
    candidate,
    initializer,
    target_checkpoint,
):
    """Exact native Reset plan bytes; this digest does not execute the plan."""
    names = ("principal_id", "agent_id", "cell_id", "run_id")
    if set(partition) != set(names):
        raise ValueError("partition differs from native CellStatePartitionV1")
    previous = source.digest()
    successor = candidate.digest()
    if (
        candidate.rollback_predecessor != previous
        or candidate.generation <= source.generation
    ):
        raise ValueError("invalid cutover lineage")
    partition_bytes = b"hepta.cell.state-partition.v1\0" + b"".join(
        stable_id_bytes(partition[name]) for name in names
    )
    raw = (
        b"hepta.cell.bundle-cutover.v1\0"
        + stable_id_bytes(operation_id)
        + stable_id_bytes(state_owner)
        + hashlib.sha256(partition_bytes).digest()
        + digest_bytes(previous)
        + digest_bytes(successor)
        + candidate.generation.to_bytes(8, "big")
        + b"\x01"
        + digest_bytes(initializer)
        + digest_bytes(target_checkpoint)
    )
    return hashlib.sha256(raw).hexdigest()
