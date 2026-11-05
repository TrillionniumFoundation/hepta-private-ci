"""Causal multimodal I/O for research: bytes and state, never quality admission.

Source/session identities are administrative provenance, not learned entity labels.
No value in this module attests capture authenticity or historical completeness.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path


MODALITIES = ("text", "audio", "video", "image")
STATUSES = ("ok", "missing", "corrupt", "unsupported", "ood", "denied", "unknown", "timeout")


class BoundaryError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def identity(value):
    if not isinstance(value, str) or not 1 <= len(value.encode("utf-8")) <= 256:
        raise BoundaryError("Identity requires 1..256 UTF-8 bytes")
    return value


def sha256(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise BoundaryError("Malformed SHA256")
    return value


def integer(value, minimum=0):
    if type(value) is not int or value < minimum or value > 2**63-1:
        raise BoundaryError("Expected a bounded nonnegative integer")
    return value


@dataclass(frozen=True)
class Packet:
    source_id: str
    modality: str
    source_sha256: str
    encoder_sha256: str
    clock_id: str
    start_ns: int
    end_ns: int
    sample_times_ns: tuple
    features: tuple
    content: str
    status: str = "ok"

    def __post_init__(self):
        identity(self.source_id); identity(self.clock_id)
        sha256(self.source_sha256); sha256(self.encoder_sha256)
        if self.modality not in MODALITIES or self.status not in STATUSES:
            raise BoundaryError("Unknown modality or observation status")
        integer(self.start_ns); integer(self.end_ns)
        if self.end_ns <= self.start_ns:
            raise BoundaryError("Observation interval must advance")
        times = tuple(self.sample_times_ns)
        for t in times:
            integer(t)
            if not self.start_ns <= t <= self.end_ns:
                raise BoundaryError("Payload sample outside the acquired source window")
        if list(times) != sorted(set(times)):
            raise BoundaryError("Sample timestamps must strictly increase")
        values = tuple(self.features)
        if any(type(x) not in (float, int) or not math.isfinite(x) for x in values):
            raise BoundaryError("Nonfinite or untyped encoder features")
        if not isinstance(self.content, str):
            raise BoundaryError("Content must be UTF-8 text, never an evaluator object")
        if self.status == "ok":
            if not times or not values:
                raise BoundaryError("Observed content needs sample times and features")
        elif times or values or self.content:
            raise BoundaryError("Missing/failed observations cannot smuggle content or features")
        object.__setattr__(self, "sample_times_ns", times)
        object.__setattr__(self, "features", values)

    def document(self):
        return asdict(self)


class FrozenInput:
    """Bind sources and encoder schemas before use; confirmation stays blocked.

    A trusted capture/encoder adapter must independently verify raw media and
    execute the frozen encoder. Hash equality is identity, not proof of quality.
    """

    def __init__(self, document):
        self._bytes = canonical(document)
        doc = json.loads(self._bytes)
        if doc.get("schema") != "hcsn-v14-frozen-input.v1":
            raise BoundaryError("Unsupported input schema")
        if doc.get("role") != "development":
            raise BoundaryError("Independent confirmation requires unavailable original custody evidence")
        identity(doc["arrival_clock_id"])
        sources = doc.get("sources")
        if not isinstance(sources, list) or not sources:
            raise BoundaryError("Missing source inventory")
        self._sources = {}
        for source in sources:
            for key in ("source_id", "family_id", "session_id", "world_id", "clock_id"):
                identity(source[key])
            if source["source_id"] in self._sources:
                raise BoundaryError("Repeated source identity")
            sha256(source["sha256"])
            integer(source["max_end_ns"], 1)
            integer(source["sync_uncertainty_ns"])
            integer(source["release_offset_ns"])
            if source.get("origin") not in ("recorded", "recorded_features", "fixture", "authored_text"):
                raise BoundaryError("Unknown capture origin")
            encoders = source.get("encoders", {})
            if not encoders or any(k not in MODALITIES for k in encoders):
                raise BoundaryError("Missing/unknown frozen encoder")
            for spec in encoders.values():
                sha256(spec["sha256"]); integer(spec["width"], 1)
                if spec["width"] > 16384:
                    raise BoundaryError("Feature dimension exceeds research boundary")
            self._sources[source["source_id"]] = source
        self.sha256 = hashlib.sha256(self._bytes).hexdigest()
        self.arrival_clock_id = doc["arrival_clock_id"]

    @property
    def sources(self):
        return json.loads(canonical(self._sources))

    def verify(self, packet):
        if type(packet) is not Packet:
            raise BoundaryError("Expected an immutable Packet, not an overriding adapter object")
        source = self._sources.get(packet.source_id)
        if source is None:
            raise BoundaryError("Unfrozen source")
        encoder = source["encoders"].get(packet.modality)
        if (encoder is None or packet.source_sha256 != source["sha256"]
                or packet.clock_id != source["clock_id"] or packet.encoder_sha256 != encoder["sha256"]):
            raise BoundaryError("Source, clock or encoder identity mismatch")
        if packet.end_ns > source["max_end_ns"]:
            raise BoundaryError("Packet exceeds frozen recording")
        if packet.status == "ok" and len(packet.features) != encoder["width"]:
            raise BoundaryError("Encoder dimension differs from frozen schema")
        return json.loads(canonical(source))

    def read_bytes(self, root, relative_path, source_id, max_bytes=67108864):
        """Check actual source bytes at use; returned bytes are the verified copy.

        This does not perform a causal crop or encoder inference. A frontend
        must crop native samples before any normalization/contextual encoding.
        """
        integer(max_bytes, 1)
        root, relative = Path(root).resolve(), Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise BoundaryError("Source path must stay inside the declared root")
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root):
            raise BoundaryError("Resolved source escapes the declared root")
        source = self._sources.get(source_id)
        if source is None:
            raise BoundaryError("Source is absent from the freeze")
        with path.open("rb") as stream:
            data = stream.read(max_bytes+1)
        if len(data) > max_bytes:
            raise BoundaryError("Source exceeds the bounded reader")
        if hashlib.sha256(data).hexdigest() != source["sha256"]:
            raise BoundaryError("Actual source bytes changed after input freeze")
        return data

    def aligned(self, a, b, tolerance_ns):
        """Administrative time compatibility, never a learned identity verdict."""
        integer(tolerance_ns)
        sa, sb = self.verify(a), self.verify(b)
        if (sa["session_id"] != sb["session_id"] or sa["clock_id"] != sb["clock_id"]
                or sa["family_id"] != sb["family_id"] or sa["world_id"] != sb["world_id"]):
            return False
        uncertainty = sa["sync_uncertainty_ns"] + sb["sync_uncertainty_ns"]
        return (a.status == b.status == "ok" and uncertainty <= tolerance_ns
                and abs(a.start_ns-b.start_ns)+uncertainty <= tolerance_ns
                and abs(a.end_ns-b.end_ns)+uncertainty <= tolerance_ns)

    def claims(self):
        return {"input_sha256": self.sha256, "role": "development",
                "history_completeness_verified": False, "independent_confirmation": False,
                "pretraining_contamination_excluded": False, "production_activation": False}


def historical_overlap(candidate, histories):
    """Derived byte hashes do not erase source-family/session/world overlap."""
    fields = ("sha256", "family_id", "session_id", "world_id")
    if not histories:
        return {"status": "UNKNOWN", "overlaps": {}, "independence_established": False}
    prior = {key: {s[key] for h in histories for s in h.sources.values()} for key in fields}
    overlaps = {key: sorted({s[key] for s in candidate.sources.values()} & prior[key]) for key in fields}
    return {"status": "OVERLAP" if any(overlaps.values()) else "NO_DECLARED_OVERLAP",
            "overlaps": overlaps, "independence_established": False}
