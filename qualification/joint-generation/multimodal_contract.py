"""Bounded media transport mapped to the canonical Hepta HNMF modality types.

This is a qualification adapter, not a new cognitive contract or runtime authority.
AV payload admission and backend generation capability are separate decisions.
"""

from dataclasses import dataclass
from enum import Enum
import json
import re

import numpy as np

from contracts import Budget, ContractError, RunSpec


SCHEMA = "hepta.joint-generation.media-envelope.v1"
CANONICAL_TYPES = "codex-rs/hepta-cognitive-types/src/hnmf.rs"


class Modality(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    CODE_AST = "code_ast"
    GUI_STATE = "gui_state"
    TOOL_TRAJECTORY = "tool_trajectory"
    STRUCTURED_DATA = "structured_data"
    SENSOR = "sensor"


class UnknownModality(ContractError):
    pass


class UnsupportedCapability(ContractError):
    pass


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ContractError("missing or unknown fields")


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ContractError("integer outside bounds")
    return value


def _identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,127}", value):
        raise ContractError("invalid identity")
    return value


def _modality(value):
    try:
        return Modality(value)
    except (ValueError, TypeError) as error:
        raise UnknownModality("unknown canonical modality") from error


def _shape(value, limits):
    if isinstance(value, np.ndarray):
        shape = value.shape
        if len(shape) != len(limits) or any(not 1 <= n <= cap for n, cap in zip(shape, limits)):
            raise ContractError("tensor shape exceeds profile")
        return shape
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= limits[0]:
        raise ContractError("tensor shape exceeds profile")
    if len(limits) == 1:
        if any(isinstance(item, (list, tuple, np.ndarray)) for item in value):
            raise ContractError("invalid tensor rank")
        return (len(value),)
    children = [_shape(item, limits[1:]) for item in value]
    if any(child != children[0] for child in children):
        raise ContractError("ragged tensor")
    return (len(value), *children[0])


def _tensor(value, limits, low, high):
    _shape(value, limits)  # Bound advertised geometry before allocating a float tensor.
    array = np.asarray(value)
    if array.dtype.kind not in "fiu" or not np.isfinite(array).all() or np.any(array < low) or np.any(array > high):
        raise ContractError("invalid finite tensor values")
    array = np.array(array, dtype=np.float32, copy=True)
    array.flags.writeable = False
    return array


@dataclass(frozen=True)
class Timing:
    clock_id: str
    sync_group: str
    start_ns: int
    end_ns: int

    @classmethod
    def parse(cls, value):
        _keys(value, ("clock_id", "sync_group", "start_ns", "end_ns"))
        start, end = (_integer(value[key], 0, 2**63 - 1) for key in ("start_ns", "end_ns"))
        if end <= start:
            raise ContractError("empty or reversed media interval")
        return cls(_identity(value["clock_id"]), _identity(value["sync_group"]), start, end)


@dataclass(frozen=True)
class TextPayload:
    text: str

    @property
    def nbytes(self):
        return len(self.text.encode("utf-8"))


@dataclass(frozen=True)
class ImagePayload:
    pixels: np.ndarray

    @property
    def nbytes(self):
        return self.pixels.nbytes


@dataclass(frozen=True)
class AudioPayload:
    samples: np.ndarray
    sample_rate_hz: int
    channels: int

    @property
    def nbytes(self):
        return self.samples.nbytes


@dataclass(frozen=True)
class VideoPayload:
    frames: np.ndarray
    fps_num: int
    fps_den: int
    timestamps_ns: tuple

    @property
    def nbytes(self):
        return self.frames.nbytes + 8 * len(self.timestamps_ns)


def _payload(mode, value, timing):
    if mode == Modality.TEXT:
        _keys(value, ("encoding", "text"))
        if value["encoding"] != "utf-8" or not isinstance(value["text"], str):
            raise ContractError("expected UTF-8 text")
        try:
            encoded = value["text"].encode("utf-8")
        except UnicodeError as error:
            raise ContractError("invalid UTF-8 text") from error
        if not 1 <= len(encoded) <= 4096:
            raise ContractError("text byte bound exceeded")
        return TextPayload(value["text"])
    if mode == Modality.IMAGE:
        _keys(value, ("dtype", "color_space", "pixels"))
        if value["dtype"] != "float32" or value["color_space"] != "RGB":
            raise ContractError("expected float32 RGB")
        pixels = _tensor(value["pixels"], (64, 64, 3), 0, 1)
        if pixels.shape[-1] != 3:
            raise ContractError("expected three RGB channels")
        return ImagePayload(pixels)
    if mode == Modality.AUDIO:
        _keys(value, ("dtype", "sample_rate_hz", "channels", "samples"))
        rate = _integer(value["sample_rate_hz"], 8000, 192000)
        channels = _integer(value["channels"], 1, 8)
        if value["dtype"] != "float32":
            raise ContractError("expected normalized float32 audio")
        samples = _tensor(value["samples"], (192000, 8), -1, 1)
        duration = (len(samples) * 10**9 + rate - 1) // rate
        if samples.shape[1] != channels or timing.end_ns - timing.start_ns != duration:
            raise ContractError("audio channels or sample-clock duration mismatch")
        return AudioPayload(samples, rate, channels)
    if mode == Modality.VIDEO:
        _keys(value, ("dtype", "color_space", "fps_num", "fps_den", "timestamps_ns", "frames"))
        num, den = (_integer(value[key], 1, 100000) for key in ("fps_num", "fps_den"))
        if value["dtype"] != "float32" or value["color_space"] != "RGB" or not 1 <= num / den <= 240:
            raise ContractError("unsupported RGB frame-rate profile")
        frames = _tensor(value["frames"], (64, 64, 64, 3), 0, 1)
        timestamps = value["timestamps_ns"]
        if not isinstance(timestamps, (list, tuple)) or len(timestamps) != len(frames):
            raise ContractError("video timestamp count mismatch")
        timestamps = tuple(_integer(t, 0, 2**63 - 1) for t in timestamps)
        expected = tuple(timing.start_ns + i * 10**9 * den // num for i in range(len(frames)))
        duration = (len(frames) * 10**9 * den + num - 1) // num
        if frames.shape[-1] != 3 or timestamps != expected or timing.end_ns - timing.start_ns != duration:
            raise ContractError("video RGB geometry or frame-clock mismatch")
        return VideoPayload(frames, num, den, timestamps)
    raise UnsupportedCapability("canonical modality has no payload adapter in this media profile: " + mode.value)


@dataclass(frozen=True)
class MediaStream:
    stream_id: str
    modality: Modality
    timing: Timing
    payload: TextPayload | ImagePayload | AudioPayload | VideoPayload

    def canonical_range(self):
        """Project admitted coordinates into HNMF SpanRangeV1; not an asset grant."""
        p = self.payload
        if self.modality == Modality.TEXT:
            return {"kind": "byte_range", "start": 0, "end": p.nbytes}
        if self.modality == Modality.IMAGE:
            return {"kind": "pixel_rect", "x": 0, "y": 0, "width": p.pixels.shape[1], "height": p.pixels.shape[0]}
        if self.modality == Modality.AUDIO:
            return {"kind": "sample_range", "start": 0, "end": len(p.samples), "sampleRateHz": p.sample_rate_hz}
        return {"kind": "frame_range", "start": 0, "end": len(p.frames), "timebaseNum": p.fps_den, "timebaseDen": p.fps_num}


@dataclass(frozen=True)
class MediaEnvelope:
    objective_id: str
    run_id: str
    artifact_sha256: str
    budget: Budget
    input_bytes: int
    deadline_ns: int
    decoding_mode: str
    decoding_seed: int
    outputs: tuple
    streams: tuple
    sync_tolerance_ns: int

    @classmethod
    def from_json(cls, raw, *, now_ns):
        if type(raw) is not bytes or not 1 <= len(raw) <= 16 * 2**20:
            raise ContractError("wire JSON byte bound exceeded")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError) as error:
            raise ContractError("invalid wire JSON") from error
        return cls.parse(value, now_ns=now_ns)

    @classmethod
    def parse(cls, value, *, now_ns):
        _keys(value, ("schema", "objective_id", "run_id", "artifact_sha256", "budget", "deadline_ns", "decoding", "outputs", "streams", "sync_tolerance_ns"))
        if value["schema"] != SCHEMA:
            raise ContractError("unsupported media envelope version")
        _keys(value["budget"], ("compute_units", "input_bytes", "output_bytes"))
        budget = Budget(_integer(value["budget"]["compute_units"], 1, 10**9), _integer(value["budget"]["output_bytes"], 1, 2**20))
        input_bytes = _integer(value["budget"]["input_bytes"], 1, 8 * 2**20)
        _keys(value["decoding"], ("mode", "seed"))
        mode = value["decoding"]["mode"]
        if mode not in ("sample", "greedy"):
            raise ContractError("unsupported decoding mode")
        seed = _integer(value["decoding"]["seed"], 0, 2**63 - 1)
        digest = value["artifact_sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ContractError("invalid selected artifact")
        deadline = _integer(value["deadline_ns"], 1, 2**63 - 1)
        if deadline <= _integer(now_ns, 0, 2**63 - 1):
            raise ContractError("deadline expired")
        if not isinstance(value["outputs"], (list, tuple)) or not 1 <= len(value["outputs"]) <= 9:
            raise ContractError("invalid output modalities")
        outputs = tuple(_modality(item) for item in value["outputs"])
        if len(set(outputs)) != len(outputs):
            raise ContractError("duplicate output modality")
        if not isinstance(value["streams"], (list, tuple)) or not 1 <= len(value["streams"]) <= 8:
            raise ContractError("stream count outside bound")
        streams, total, groups, ids = [], 0, {}, set()
        tolerance = _integer(value["sync_tolerance_ns"], 0, 10**9)
        for stream in value["streams"]:
            _keys(stream, ("stream_id", "modality", "timing", "payload"))
            sid, modality = _identity(stream["stream_id"]), _modality(stream["modality"])
            if sid in ids:
                raise ContractError("duplicate stream identity")
            ids.add(sid)
            timing = Timing.parse(stream["timing"])
            payload = _payload(modality, stream["payload"], timing)
            total += payload.nbytes
            if total > input_bytes:
                raise ContractError("aggregate input byte budget exceeded")
            groups.setdefault(timing.sync_group, []).append(timing)
            streams.append(MediaStream(sid, modality, timing, payload))
        for timings in groups.values():
            if (len({t.clock_id for t in timings}) != 1
                    or max(t.start_ns for t in timings) - min(t.start_ns for t in timings) > tolerance
                    or max(t.end_ns for t in timings) - min(t.end_ns for t in timings) > tolerance):
                raise ContractError("incompatible clock or synchronization interval")
        return cls(_identity(value["objective_id"]), _identity(value["run_id"]), digest, budget, input_bytes,
                   deadline, mode, seed, outputs, tuple(streams), tolerance)


@dataclass(frozen=True)
class BackendCapabilities:
    profile_id: str
    input_modalities: frozenset
    output_modalities: frozenset

    def require(self, envelope):
        inputs = frozenset(stream.modality for stream in envelope.streams)
        if inputs != self.input_modalities or frozenset(envelope.outputs) != self.output_modalities:
            raise UnsupportedCapability("known modalities unsupported by backend profile " + self.profile_id)


RGB8_CAPABILITIES = BackendCapabilities("rgb8-instruction10-v1", frozenset((Modality.TEXT, Modality.IMAGE)),
                                        frozenset((Modality.TEXT, Modality.IMAGE)))


def to_legacy_request(envelope, *, expected_artifact_sha256, now_ns):
    """Validate backend admission and preserve the frozen RunSpec/budget binding."""
    RGB8_CAPABILITIES.require(envelope)
    if envelope.artifact_sha256 != expected_artifact_sha256:
        raise ContractError("selected backend artifact mismatch")
    if len(envelope.streams) != 2:
        raise UnsupportedCapability("RGB8 backend requires one instruction and one image")
    streams = {stream.modality: stream for stream in envelope.streams}
    image, text = streams[Modality.IMAGE].payload, streams[Modality.TEXT].payload
    if image.pixels.shape != (8, 8, 3):
        raise UnsupportedCapability("RGB8 backend requires an 8x8 image")
    words = text.text.split()
    if len(words) != 3:
        raise UnsupportedCapability("RGB8 instruction requires color, shape and position")
    RunSpec.parse({"objective_id": envelope.objective_id, "run_id": envelope.run_id,
                   "artifact_sha256": envelope.artifact_sha256, "modalities": [m.value for m in envelope.outputs],
                   "budget": vars(envelope.budget), "deadline_ns": envelope.deadline_ns}, now_ns=now_ns)
    request = {"objective_id": envelope.objective_id, "run_id": envelope.run_id,
               "image": image.pixels.tolist(), "instruction": dict(zip(("color", "shape", "position"), words)),
               "decoding": {"mode": envelope.decoding_mode, "seed": envelope.decoding_seed},
               "budget": vars(envelope.budget), "deadline_ns": envelope.deadline_ns}
    from serve import encode_request
    encode_request(request)
    return request


def dispatch(envelope, backend, *, expected_artifact_sha256, now_ns):
    request = to_legacy_request(envelope, expected_artifact_sha256=expected_artifact_sha256, now_ns=now_ns)
    return backend(request)
