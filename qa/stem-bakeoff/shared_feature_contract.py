"""Versioned event views over the existing immutable shared feature bundle.

Source times describe the supplied event, not inferred token alignment. Digests
bind local bytes and declared provenance; they do not authenticate a publisher.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
from math import prod

import torch

from feature_bundle import FeatureBundleV1, FeatureIdentityV1, MAX_BYTES, MAX_ELEMENTS, SHA256

SCHEMA = "hepta.shared-event-features.v1"
DTYPE_BYTES = {"torch.float32": 4, "torch.bfloat16": 2, "torch.int64": 8, "torch.bool": 1}


class SharedFeatureError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class SourceEvent:
    """Declared revision; Unix observation nanoseconds and source media milliseconds."""

    source_id: str
    source_version: str
    observed_at_ns: int | None = None
    time_start_ms: int | None = None
    time_end_ms: int | None = None

    def __post_init__(self):
        for name in ("source_id", "source_version"):
            value = getattr(self, name)
            if (type(value) is not str or not value.strip()
                    or len(value.encode()) > 512 or any(ord(c) < 32 for c in value)):
                raise SharedFeatureError("bounded source identity/revision required")
        for name in ("observed_at_ns", "time_start_ms", "time_end_ms"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or not 0 <= value < 2**63):
                raise SharedFeatureError("source times must be nonnegative integer units")
        if ((self.time_start_ms is None) != (self.time_end_ms is None)
                or (self.time_start_ms is not None and self.time_end_ms < self.time_start_ms)):
            raise SharedFeatureError("source time interval must be complete and ordered")


class SharedFeatureBatch:
    """Immutable event-bound views of an existing owner's feature bundle."""

    __slots__ = ("_bundle", "_events", "_locations", "_manifest", "_digest",
                 "_feature_identity_digest", "_cache_key")

    @classmethod
    def seal(cls, bundle, events, *, extractor_sha256, char_spans=None, char_valid=None):
        if type(bundle) is not FeatureBundleV1:
            raise SharedFeatureError("existing shared FeatureBundleV1 required")
        bundle.verify_integrity()
        base_views = bundle.manifest()["views"]
        if (not isinstance(events, (list, tuple))
                or len(events) != len(bundle.source_record_digests)
                or any(type(event) is not SourceEvent for event in events)
                or type(extractor_sha256) is not str
                or SHA256.fullmatch(extractor_sha256) is None):
            raise SharedFeatureError("one typed event per row and extractor digest required")
        locations = {}
        if char_spans is not None or char_valid is not None:
            tokens = base_views.get("token_features")
            if (tokens is None or not isinstance(char_spans, torch.Tensor)
                    or not isinstance(char_valid, torch.Tensor)
                    or char_spans.dtype != torch.int64 or char_valid.dtype != torch.bool
                    or any(v.is_meta or v.layout != torch.strided
                           for v in (char_spans, char_valid))
                    or tuple(char_spans.shape) != (*tokens["shape"][:2], 2)
                    or list(char_valid.shape) != tokens["shape"][:2]):
                raise SharedFeatureError("character locations require matching native tokens")
            snapshot = bundle.snapshot()
            valid = char_valid.detach().to("cpu").contiguous().clone()
            spans = char_spans.detach().to("cpu").contiguous().clone()
            selected = spans[valid]
            if (bool((valid & ~snapshot["token_valid"]).any())
                    or bool((snapshot["modality_ids"][valid] != 0).any())
                    or bool((spans[~valid] != 0).any())
                    or bool((selected[:, 0] < 0).any())
                    or bool((selected[:, 1] <= selected[:, 0]).any())):
                raise SharedFeatureError("invalid source-text character locations")
            locations = {"char_spans": spans, "char_valid": valid}
        elements = sum(prod(v["shape"]) for v in base_views.values())
        byte_count = sum(prod(v["shape"]) * DTYPE_BYTES[v["dtype"]] for v in base_views.values())
        elements += sum(v.numel() for v in locations.values())
        byte_count += sum(v.numel() * v.element_size() for v in locations.values())
        if elements > MAX_ELEMENTS or byte_count > MAX_BYTES:
            raise SharedFeatureError("event feature and location budget exceeded")
        obj = cls()
        obj._bundle, obj._events, obj._locations = bundle, tuple(events), locations
        feature_identity = {"schema": SCHEMA, "encoder": asdict(bundle.identity),
                            "extractor_sha256": extractor_sha256}
        obj._feature_identity_digest = digest(feature_identity)
        obj._manifest = {
            **feature_identity, "feature_identity_sha256": obj._feature_identity_digest,
            "feature_bundle_sha256": bundle.bundle_digest,
            "events": [asdict(event) for event in events],
            "source_record_digests": list(bundle.source_record_digests),
            "retention": "tokens" if "token_features" in base_views else "global",
            "retained_tensor_bytes": byte_count,
            "locations": obj._location_records(),
            "character_unit": "original-text-python-codepoint",
            "observed_time_unit": "unix-nanoseconds", "source_interval_unit": "milliseconds",
            "token_time_alignment": "owner-provided" if "time_spans" in base_views else "absent",
            "token_time_unit": "seconds", "source_authentication": "not-established",
            "authority": "DENY_ALL",
        }
        obj._digest = digest(obj._manifest)
        obj._cache_key = digest({"feature_request": bundle.cache_key,
                                 "feature_identity": feature_identity,
                                 "events": obj._manifest["events"],
                                 "retention": obj._manifest["retention"]})
        return obj

    def _location_records(self):
        return {name: {"shape": list(value.shape), "dtype": str(value.dtype),
                       "sha256": hashlib.sha256(value.numpy().tobytes()).hexdigest()}
                for name, value in self._locations.items()}

    @property
    def bundle(self):
        """Compatibility view for existing Cell heads; integrity is still checked."""
        self.verify_integrity()
        return self._bundle

    @property
    def identity(self):
        return self._bundle.identity

    @property
    def events(self):
        return self._events

    @property
    def source_record_digests(self):
        return self._bundle.source_record_digests

    @property
    def feature_identity_digest(self):
        return self._feature_identity_digest

    @property
    def bundle_digest(self):
        return self._digest

    @property
    def cache_key(self):
        return self._cache_key

    @property
    def retained_tensor_bytes(self):
        return self._manifest["retained_tensor_bytes"]

    def verify_integrity(self):
        self._bundle.verify_integrity()
        manifest = self.manifest()
        manifest["encoder"] = asdict(self._bundle.identity)
        manifest["source_record_digests"] = list(self._bundle.source_record_digests)
        manifest["feature_identity_sha256"] = self._feature_identity_digest
        manifest["events"] = [asdict(event) for event in self._events]
        manifest["feature_bundle_sha256"] = self._bundle.bundle_digest
        manifest["locations"] = self._location_records()
        if digest(manifest) != self._digest:
            raise SharedFeatureError("event feature snapshot changed")

    def require_identity(self, expected: FeatureIdentityV1):
        self._bundle.require_identity(expected)
        self.verify_integrity()

    def read_global(self):
        self.verify_integrity()
        return self._bundle.read_global()

    def read_tokens(self):
        self.verify_integrity()
        return self._bundle.read_tokens()

    def read_locations(self):
        self.verify_integrity()
        return {name: value.clone() for name, value in self._locations.items()}

    def snapshot(self):
        """Independent tensor copies including masks, modalities and actual locations."""
        self.verify_integrity()
        return {**self._bundle.snapshot(), **self.read_locations()}

    def manifest(self):
        return json.loads(json.dumps(self._manifest))
