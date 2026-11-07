"""A common, addressable public-state contract for every factorial arm.

The representation declares whether ``encoding`` describes an already public
output, an internal joint-content latent, or imported V3 latents. ``available``
means that the slot has a valid current value; it never asserts delivery.
Progress is an observable work cursor, never a target-derived quality label.
Prefixes record an existing owner's receipt; this module cannot commit output.
The explicit V3 migration preserves latent values, not semantic qualification.
"""

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping

import numpy as np


SCHEMA = "hepta.public-text-image-state.v1"
FEATURE_SCHEMA = "hepta.named-output-features.v1"
MODALITIES = ("text", "image")
PREPARATION = ("not_required", "pending", "ready")
REPRESENTATIONS = ("public_output_encoding", "joint_content_latent", "legacy_v3_latent")
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
MAX_VERSION = 2**31 - 1


def exact_fields(value, fields, label):
    if not isinstance(value, Mapping) or set(value) != set(fields):
        raise ValueError(f"{label}: expected exactly {sorted(fields)}")


def sha256_value(value, label):
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError(f"{label}: expected lowercase SHA256")
    return value


def integer(value, label, maximum=MAX_VERSION):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{label}: expected integer in [0, {maximum}]")
    return value


def matrix(value, label, shape=None):
    raw = np.asarray(value)
    if raw.dtype.kind not in "fi" or raw.ndim != 2 or min(raw.shape) < 1:
        raise ValueError(f"{label}: expected nonempty real matrix")
    if shape is not None and raw.shape != shape:
        raise ValueError(f"{label}: shape differs from shared state")
    result = np.array(raw, dtype=np.float64, copy=True)
    if not np.isfinite(result).all():
        raise ValueError(f"{label}: nonfinite value")
    return np.frombuffer(result.tobytes(), dtype=result.dtype).reshape(result.shape)


def vector(value, count, label, upper=None):
    raw = np.asarray(value)
    if raw.dtype.kind not in "fi" or raw.shape != (count,):
        raise ValueError(f"{label}: expected one real number per row")
    result = np.array(raw, dtype=np.float64, copy=True)
    if (
        not np.isfinite(result).all()
        or (result < 0).any()
        or (upper is not None and (result > upper).any())
    ):
        raise ValueError(f"{label}: out of range or nonfinite")
    return np.frombuffer(result.tobytes(), dtype=result.dtype).reshape(result.shape)


@dataclass(frozen=True)
class Prefix:
    sha256: str
    byte_count: int
    content_version: int

    def __post_init__(self):
        sha256_value(self.sha256, "prefix sha256")
        integer(self.byte_count, "prefix byte_count", 2**53 - 1)
        integer(self.content_version, "prefix content_version")
        if self.byte_count == 0 and (
            self.sha256 != EMPTY_SHA256 or self.content_version != 0
        ):
            raise ValueError("Empty prefix must retain the canonical empty receipt")

    @classmethod
    def parse(cls, value):
        exact_fields(
            value, ("sha256", "byte_count", "content_version"), "committed prefix"
        )
        return cls(value["sha256"], value["byte_count"], value["content_version"])

    def matches(self, value):
        return (
            isinstance(value, bytes)
            and len(value) == self.byte_count
            and hashlib.sha256(value).hexdigest() == self.sha256
        )


@dataclass(frozen=True)
class Slot:
    modality: str
    encoding: np.ndarray
    available: tuple
    progress: np.ndarray
    preparation: tuple
    version: tuple
    committed_prefix: tuple

    def __post_init__(self):
        if self.modality not in MODALITIES:
            raise ValueError("Unknown modality")
        encoding = matrix(self.encoding, "slot encoding")
        count = encoding.shape[0]
        for name in ("available", "preparation", "version", "committed_prefix"):
            value = getattr(self, name)
            if not isinstance(value, (list, tuple)) or len(value) != count:
                raise ValueError(f"slot {name}: expected one entry per row")
            object.__setattr__(self, name, tuple(value))
        if any(type(item) is not bool for item in self.available):
            raise ValueError("Availability must be explicit booleans")
        if any(item not in PREPARATION for item in self.preparation):
            raise ValueError("Unknown preparation state")
        for value in self.version:
            integer(value, "version")
        object.__setattr__(self, "encoding", encoding)
        object.__setattr__(
            self, "progress", vector(self.progress, count, "progress", 1.0)
        )
        for row, prefix in enumerate(self.committed_prefix):
            if type(prefix) is not Prefix or prefix.content_version > self.version[row]:
                raise ValueError(
                    "Invalid prefix type or version exceeds current content"
                )
            if not self.available[row] and (
                np.any(self.encoding[row] != 0)
                or self.progress[row] != 0
                or self.version[row] != 0
                or prefix.byte_count != 0
            ):
                raise ValueError(
                    "Missing outputs require zero encoding/progress/version and an empty prefix"
                )

    @classmethod
    def parse(cls, value, shape):
        exact_fields(
            value,
            (
                "modality",
                "encoding",
                "available",
                "progress",
                "preparation",
                "version",
                "committed_prefix",
            ),
            "slot",
        )
        if not isinstance(value["committed_prefix"], (list, tuple)):
            raise ValueError("Expected a committed-prefix list")
        return cls(
            value["modality"],
            matrix(value["encoding"], "slot encoding", shape),
            value["available"],
            value["progress"],
            value["preparation"],
            value["version"],
            tuple(Prefix.parse(x) for x in value["committed_prefix"]),
        )

    def metadata(self):
        return np.array(
            [
                [
                    float(self.available[i]),
                    self.progress[i],
                    *[float(self.preparation[i] == label) for label in PREPARATION],
                    np.log1p(self.version[i]),
                    np.log1p(prefix.byte_count),
                    np.log1p(prefix.content_version),
                    float(prefix.byte_count > 0),
                ]
                for i, prefix in enumerate(self.committed_prefix)
            ],
            dtype=np.float64,
        )


@dataclass(frozen=True)
class SemanticState:
    shared: np.ndarray
    slots: tuple
    remaining_budget: np.ndarray
    elapsed_seconds: np.ndarray
    representation: str

    def __post_init__(self):
        if self.representation not in REPRESENTATIONS:
            raise ValueError("Unknown state representation")
        shared = matrix(self.shared, "shared state")
        if (
            not isinstance(self.slots, (list, tuple))
            or len(self.slots) != len(MODALITIES)
            or any(type(slot) is not Slot for slot in self.slots)
            or tuple(slot.modality for slot in self.slots) != MODALITIES
        ):
            raise ValueError(
                "State slots must have canonical text/image identities and order"
            )
        if any(slot.encoding.shape != shared.shape for slot in self.slots):
            raise ValueError("Slot shape differs from shared state")
        object.__setattr__(self, "shared", shared)
        object.__setattr__(self, "slots", tuple(self.slots))
        object.__setattr__(
            self,
            "remaining_budget",
            vector(self.remaining_budget, shared.shape[0], "remaining budget"),
        )
        object.__setattr__(
            self,
            "elapsed_seconds",
            vector(self.elapsed_seconds, shared.shape[0], "elapsed seconds"),
        )

    @classmethod
    def from_payload(cls, value):
        exact_fields(
            value,
            (
                "schema",
                "representation",
                "shared",
                "slots",
                "remaining_budget",
                "elapsed_seconds",
            ),
            "state",
        )
        if value["schema"] != SCHEMA or value["representation"] not in REPRESENTATIONS:
            raise ValueError("Unknown state schema or representation")
        shared = matrix(value["shared"], "shared state")
        if not isinstance(value["slots"], (list, tuple)) or len(value["slots"]) != len(
            MODALITIES
        ):
            raise ValueError("Exactly one text slot and one image slot are required")
        slots = [Slot.parse(slot, shared.shape) for slot in value["slots"]]
        by_name = {slot.modality: slot for slot in slots}
        if set(by_name) != set(MODALITIES):
            raise ValueError("Duplicate or missing slot identity")
        return cls(
            shared,
            tuple(by_name[name] for name in MODALITIES),
            vector(value["remaining_budget"], shared.shape[0], "remaining budget"),
            vector(value["elapsed_seconds"], shared.shape[0], "elapsed seconds"),
            value["representation"],
        )

    @property
    def width(self):
        return self.shared.shape[1]

    def features(self):
        columns = [self.shared]
        for slot in self.slots:
            columns.extend((slot.encoding, slot.metadata()))
        columns.append(
            np.stack(
                (np.log1p(self.remaining_budget), np.log1p(self.elapsed_seconds)),
                axis=-1,
            )
        )
        return np.concatenate(columns, axis=-1)

    def feature_names(self):
        names = [f"shared.{i}" for i in range(self.width)]
        for name in MODALITIES:
            names.extend(f"{name}.encoding.{i}" for i in range(self.width))
            names.extend(
                f"{name}.{field}"
                for field in (
                    "available",
                    "progress",
                    "preparation.not_required",
                    "preparation.pending",
                    "preparation.ready",
                    "log1p_version",
                    "log1p_prefix_bytes",
                    "log1p_prefix_version",
                    "has_committed_prefix",
                )
            )
        return tuple(names + ["log1p_remaining_budget", "log1p_elapsed_seconds"])


def from_public_encodings(
    shared, encodings, metadata, *, representation="public_output_encoding"
):
    """Build the same named schema for all cores/controllers; no arm argument exists."""
    exact_fields(encodings, MODALITIES, "output encodings")
    exact_fields(
        metadata, ("slots", "remaining_budget", "elapsed_seconds"), "public metadata"
    )
    exact_fields(metadata["slots"], MODALITIES, "slot metadata")
    slots = []
    for name in MODALITIES:
        item = metadata["slots"][name]
        exact_fields(
            item,
            ("available", "progress", "preparation", "version", "committed_prefix"),
            "slot public metadata",
        )
        slots.append({"modality": name, "encoding": encodings[name], **item})
    return SemanticState.from_payload(
        {
            "schema": SCHEMA,
            "representation": representation,
            "shared": shared,
            "slots": slots,
            "remaining_budget": metadata["remaining_budget"],
            "elapsed_seconds": metadata["elapsed_seconds"],
        }
    )


def actor_binding(state):
    contract = {
        "state_schema": SCHEMA,
        "features_schema": FEATURE_SCHEMA,
        "representation": state.representation,
        "features": list(state.feature_names()),
        "slot_order": [slot.modality for slot in state.slots],
    }
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    return {**contract, "sha256": hashlib.sha256(encoded).hexdigest()}


def check_actor_binding(binding, state):
    if binding != actor_binding(state):
        raise ValueError(
            "Actor feature binding differs; old V3 actors require new training and cannot be loaded"
        )


def check_transition(previous, current, prefix_bytes=None):
    """Validate immutable prefix extension using actual bytes, without writing them.

    Changed receipts require witnesses ``{modality: [(before_bytes, after_bytes), ...]}``.
    A digest alone cannot prove that a longer prefix extends the previous one.
    """
    if (
        actor_binding(previous) != actor_binding(current)
        or previous.shared.shape != current.shared.shape
    ):
        raise ValueError("State identity or batch shape changed")
    if (current.elapsed_seconds < previous.elapsed_seconds).any() or (
        current.remaining_budget > previous.remaining_budget
    ).any():
        raise ValueError("Elapsed time or remaining budget moved backwards")
    prefix_bytes = {} if prefix_bytes is None else prefix_bytes
    if not isinstance(prefix_bytes, Mapping) or not set(prefix_bytes) <= set(
        MODALITIES
    ):
        raise ValueError("Unknown prefix witness modality")
    for witnesses in prefix_bytes.values():
        if (
            not isinstance(witnesses, (tuple, list))
            or len(witnesses) != previous.shared.shape[0]
        ):
            raise ValueError("Provided prefix witnesses must have one pair per row")
        for pair in witnesses:
            if (
                not isinstance(pair, (tuple, list))
                or len(pair) != 2
                or any(not isinstance(value, bytes) for value in pair)
            ):
                raise ValueError("Invalid prefix byte witness")
    for old_slot, new_slot in zip(previous.slots, current.slots, strict=True):
        for i, (before, after) in enumerate(
            zip(old_slot.committed_prefix, new_slot.committed_prefix, strict=True)
        ):
            if new_slot.version[i] < old_slot.version[i]:
                raise ValueError("Content version moved backwards")
            if new_slot.version[i] == old_slot.version[i] and not np.array_equal(
                old_slot.encoding[i], new_slot.encoding[i]
            ):
                raise ValueError(
                    "Changed output encoding requires a new content version"
                )
            witnesses = prefix_bytes.get(old_slot.modality)
            if witnesses is None and before == after:
                continue
            if witnesses is None:
                raise ValueError(
                    "Changed committed prefix requires actual byte witnesses"
                )
            a, b = witnesses[i]
            if not before.matches(a) or not after.matches(b):
                raise ValueError(
                    "Provided bytes differ from a committed-prefix receipt"
                )
            if before == after:
                if a != b:
                    raise ValueError(
                        "Unchanged prefix receipt cannot describe changed bytes"
                    )
                continue
            if (
                not b.startswith(a)
                or len(b) <= len(a)
                or after.content_version < before.content_version
            ):
                raise ValueError("Committed prefix was changed, truncated, or rebound")


def migrate_v3_latents(shared, slots, metadata):
    """Explicitly import V3 [image,audio,video,text] latents, never its actor.

    Audio/video are deliberately outside this new two-output profile. The old
    checkpoint remains the authority for them; no old qualification is migrated.
    """
    original_shared = np.asarray(shared)
    common = matrix(original_shared, "legacy shared")
    old = np.asarray(slots)
    if (
        old.shape != (common.shape[0], 4, common.shape[1])
        or old.dtype.kind not in "fi"
        or not np.isfinite(old).all()
    ):
        raise ValueError(
            "V3 slots must have shape [batch, 4, width] and finite real values"
        )
    encoded = {"text": old[:, 3, :], "image": old[:, 0, :]}
    state = from_public_encodings(
        common, encoded, metadata, representation="legacy_v3_latent"
    )
    h = hashlib.sha256()
    for value in (original_shared, old):
        arr = np.ascontiguousarray(value)
        h.update(str((str(arr.dtype), arr.shape)).encode())
        h.update(arr.tobytes())
    receipt = {
        "source_schema": "hepta.joint-generation.initial-stop.v3",
        "target_schema": SCHEMA,
        "source_values_sha256": h.hexdigest(),
        "old_slot_order": ["image", "audio", "video", "text"],
        "new_slot_order": list(MODALITIES),
        "old_actor_features": 2 * state.width + 5,
        "new_actor_features": len(state.feature_names()),
        "old_actor_compatible": False,
        "semantic_qualification_migrated": False,
        "omitted_modalities": ["audio", "video"],
        "state_binding": actor_binding(state),
    }
    return state, receipt
