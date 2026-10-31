"""Finite four-slot state/output contract; the v6 backend implements two slots.

The static task shares a logical event clock, not a fabricated media duration.
Presentation-clock anchors are reserved for future implemented media backends.
Validation binds state, requirements and alignment; it does not authenticate
observations, implement a decoder, or grant production-owner authority.
"""

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re


class Modality(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


MODALITIES = tuple(Modality)
IMPLEMENTED = (Modality.TEXT, Modality.IMAGE)
BITS = {modality: 1 << index for index, modality in enumerate(MODALITIES)}
PROFILE = {"schema": "hepta.ndu-v6.four-slot-state.v1",
           "slot_order": [modality.value for modality in MODALITIES],
           "encoder_capabilities": [modality.value for modality in IMPLEMENTED],
           "decoder_capabilities": [modality.value for modality in IMPLEMENTED],
           "clock_basis": "logical_event", "physical_media_sync_observed": False}


def modalities(values):
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError("Required modalities must be a nonempty list")
    try:
        parsed = tuple(Modality(value) for value in values)
    except (TypeError, ValueError) as error:
        raise ValueError("Unknown modality") from error
    if len(set(parsed)) != len(parsed):
        raise ValueError("Duplicate modality")
    return tuple(modality for modality in MODALITIES if modality in parsed)


def require_v6_capabilities(values):
    required = modalities(values)
    missing = [modality.value for modality in required if modality not in IMPLEMENTED]
    if missing:
        raise ValueError(f"Unimplemented required decoder: {', '.join(missing)}")
    if required != IMPLEMENTED:
        raise ValueError("This v6 task requires exactly text and image outputs")
    return required


def modality_mask(values):
    return sum(BITS[modality] for modality in modalities(values))


def _identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._:/-]{1,128}", value):
        raise ValueError("Invalid bounded clock/event identity")


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) or value == "0" * 64:
        raise ValueError("Invalid nonzero state/output digest")


def _integer(value, minimum=0, maximum=(1 << 63) - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Invalid bounded integer clock value")


@dataclass(frozen=True)
class MediaClock:
    clock_id: str
    basis: str
    ticks_per_second: int | None
    extent_ticks: int
    max_skew_ticks: int = 0

    def validate(self):
        _identity(self.clock_id)
        _integer(self.extent_ticks, 1)
        _integer(self.max_skew_ticks, maximum=self.extent_ticks)
        if self.basis == "logical_event":
            if self.ticks_per_second is not None:
                raise ValueError("Logical event ticks have no physical duration")
        elif self.basis == "presentation":
            _integer(self.ticks_per_second, 1, 10**12)
        else:
            raise ValueError("Unknown clock basis")


@dataclass(frozen=True)
class EventSpan:
    event_id: str
    clock_id: str
    start_tick: int
    end_tick: int

    def validate(self, clock):
        _identity(self.event_id)
        if self.clock_id != clock.clock_id:
            raise ValueError("Cross-clock event alignment")
        _integer(self.start_tick, maximum=clock.extent_ticks)
        _integer(self.end_tick, minimum=self.start_tick + 1, maximum=clock.extent_ticks)


@dataclass(frozen=True)
class ModalitySlot:
    modality: Modality
    status: str  # pending, complete, not_requested, or unsupported
    latent_sha256: str | None
    output_sha256: str | None
    anchors: tuple[EventSpan, ...]


@dataclass(frozen=True)
class JointState:
    snapshot_sha256: str
    state_sha256: str
    shared_latent_sha256: str
    required: tuple[Modality, ...]
    clock: MediaClock
    events: tuple[EventSpan, ...]
    slots: tuple[ModalitySlot, ModalitySlot, ModalitySlot, ModalitySlot]

    def validate(self, declared_mask, *, complete=True):
        if type(complete) is not bool:
            raise ValueError("Completion requirement must be boolean")
        for value in (self.snapshot_sha256, self.state_sha256, self.shared_latent_sha256):
            _digest(value)
        required = modalities(self.required)
        if type(declared_mask) is not int or declared_mask != modality_mask(required):
            raise ValueError("Declared mask differs from exact required outputs")
        self.clock.validate()
        if not isinstance(self.events, tuple) or not 1 <= len(self.events) <= 64:
            raise ValueError("Event cardinality exceeds the bounded contract")
        expected = {}
        for event in self.events:
            event.validate(self.clock)
            if event.event_id in expected:
                raise ValueError("Duplicate semantic event")
            expected[event.event_id] = event
        if not isinstance(self.slots, tuple) or tuple(slot.modality for slot in self.slots) != MODALITIES:
            raise ValueError("Joint state requires four ordered modality slots")
        produced = []
        for slot in self.slots:
            if not isinstance(slot.anchors, tuple) or len(slot.anchors) > 64:
                raise ValueError("Unbounded alignment anchors")
            if slot.status in {"unsupported", "not_requested"}:
                if slot.latent_sha256 is not None or slot.output_sha256 is not None or slot.anchors:
                    raise ValueError("Unavailable slot cannot contain fabricated state/output")
                if slot.modality in required:
                    raise ValueError("Required output is unavailable")
                continue
            if slot.modality not in required:
                raise ValueError("Output or pending state outside the required set")
            _digest(slot.latent_sha256)
            if slot.status == "pending":
                if complete or slot.output_sha256 is not None or slot.anchors:
                    raise ValueError("Pending output cannot complete the required bundle")
                continue
            if slot.status != "complete":
                raise ValueError("Unknown output state")
            _digest(slot.output_sha256)
            if slot.modality in (Modality.AUDIO, Modality.VIDEO) and self.clock.basis != "presentation":
                raise ValueError("Timed media require a presentation clock")
            if len(slot.anchors) != len(expected) or {a.event_id for a in slot.anchors} != set(expected):
                raise ValueError("Required semantic event coverage is incomplete")
            for anchor in slot.anchors:
                anchor.validate(self.clock)
                target = expected[anchor.event_id]
                if max(abs(anchor.start_tick - target.start_tick),
                       abs(anchor.end_tick - target.end_tick)) > self.clock.max_skew_ticks:
                    raise ValueError("Cross-modal synchronization skew exceeds its bound")
            produced.append(slot.modality)
        if complete and modality_mask(produced) != declared_mask:
            raise ValueError("Incomplete required output bundle")


def latent_digest(tensor):
    """Bind actual small runtime state; unsupported modalities have no tensor."""
    if not 0 < tensor.numel() <= 65536 or not tensor.isfinite().all():
        raise ValueError("Nonfinite or oversized latent state")
    value = tensor.detach().cpu().contiguous()
    identity = f"{value.dtype}:{tuple(value.shape)}:".encode() + value.numpy().tobytes()
    return hashlib.sha256(identity).hexdigest()


def bind_v6_output(required, snapshot_sha256, state_sha256, latents, outputs, event_id):
    """Bind re-read UTF-8/PNG digests to the actual decoder states and one event."""
    required = require_v6_capabilities(required)
    if set(outputs) != {modality.value for modality in required} or set(latents) != {"shared", "text", "image"}:
        raise ValueError("Output/latent set differs from the implemented required set")
    clock = MediaClock(f"event:{event_id}", "logical_event", None, 1)
    event = EventSpan(event_id, clock.clock_id, 0, 1)
    slots = tuple(ModalitySlot(modality, "complete", latents[modality.value],
                               outputs[modality.value], (event,)) if modality in IMPLEMENTED
                  else ModalitySlot(modality, "unsupported", None, None, ())
                  for modality in MODALITIES)
    state = JointState(snapshot_sha256, state_sha256, latents["shared"], required,
                       clock, (event,), slots)
    mask = modality_mask(required)
    state.validate(mask)
    # One JSON representation supports producer memory and persisted-row replay.
    return json.loads(json.dumps({"schema": PROFILE["schema"], "required_mask": mask,
                                  **asdict(state)}, allow_nan=False))
