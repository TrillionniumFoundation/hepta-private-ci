"""Bounded snapshots of real shared features, with separate source provenance.

Tensor bytes are copied once into private CPU storage; readers receive copies.
Digests establish local integrity, not independent model or source attestation.
Pooled features never acquire invented region, timestamp or token annotations.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import re

import torch

MODALITIES = ("text", "image", "audio", "video", "ui_event")
MAX_BATCH = 512
MAX_WIDTH = 4096
MAX_TOKENS = 4096
MAX_ELEMENTS = 2_097_152
MAX_BYTES = 16 * 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
NAME = re.compile(r"[a-zA-Z0-9_.:-]{1,128}\Z")


class FeatureBundleError(ValueError):
    pass


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class FeatureIdentityV1:
    """Effective checkpoint and complete preprocessing identity for one scope.

The preprocessing digest must include tokenizer, task prefix, normalization,
precision, truncation and media sampling/cropping when applicable. Revocation
epochs are supplied by the owner; this object does not authorize cache reads.
    """

    encoder_sha256: str
    checkpoint_revision: str
    preprocess_sha256: str
    generation: int = 1
    scope_id: str = "research-local"
    purpose: str = "research"
    revocation_epoch: int = 0

    def __post_init__(self):
        if (any(type(v) is not str or SHA256.fullmatch(v) is None
                for v in (self.encoder_sha256, self.preprocess_sha256))
                or type(self.checkpoint_revision) is not str
                or SHA40.fullmatch(self.checkpoint_revision) is None
                or type(self.generation) is not int or self.generation < 1
                or type(self.revocation_epoch) is not int or self.revocation_epoch < 0
                or any(type(v) is not str or NAME.fullmatch(v) is None
                       for v in (self.scope_id, self.purpose))):
            raise FeatureBundleError("invalid checkpoint/preprocessing/scope identity")


def _tensor_record(value: torch.Tensor) -> dict:
    payload = value.contiguous().view(torch.uint8).numpy().tobytes()
    return {"shape": list(value.shape), "dtype": str(value.dtype),
            "bytes_sha256": hashlib.sha256(payload).hexdigest()}


class FeatureBundleV1:
    """One ordered batch, reusable by many Cells without exposing its storage."""

    __slots__ = ("_identity", "_sources", "_tensors", "_manifest", "_digest", "_cache_key")

    @classmethod
    def from_tensors(cls, *, global_features: torch.Tensor,
                     source_record_digests: tuple[str, ...], identity: FeatureIdentityV1,
                     missing_mask: torch.Tensor, token_features: torch.Tensor | None = None,
                     token_valid: torch.Tensor | None = None,
                     modality_ids: torch.Tensor | None = None,
                     region_boxes: torch.Tensor | None = None,
                     region_valid: torch.Tensor | None = None,
                     time_spans: torch.Tensor | None = None,
                     time_valid: torch.Tensor | None = None):
        if type(identity) is not FeatureIdentityV1:
            raise FeatureBundleError("a validated feature identity is required")
        if (not isinstance(global_features, torch.Tensor) or global_features.ndim != 2
                or not 1 <= global_features.shape[0] <= MAX_BATCH
                or not 1 <= global_features.shape[1] <= MAX_WIDTH):
            raise FeatureBundleError("global feature batch/width outside bounds")
        batch = global_features.shape[0]
        if (not isinstance(source_record_digests, tuple)
                or len(source_record_digests) != batch
                or any(type(v) is not str or SHA256.fullmatch(v) is None
                       for v in source_record_digests)):
            raise FeatureBundleError("one ordered source digest is required per row")
        values = {"global_features": global_features, "missing_mask": missing_mask,
                  "token_features": token_features, "token_valid": token_valid,
                  "modality_ids": modality_ids, "region_boxes": region_boxes,
                  "region_valid": region_valid, "time_spans": time_spans,
                  "time_valid": time_valid}
        if token_features is None:
            if any(v is not None for k, v in values.items()
                   if k not in ("global_features", "missing_mask", "token_features")):
                raise FeatureBundleError("pooled-only features have no token/region/time view")
        elif (not isinstance(token_features, torch.Tensor) or token_features.ndim != 3
              or token_features.shape[0] != batch
              or not 1 <= token_features.shape[1] <= MAX_TOKENS
              or not 1 <= token_features.shape[2] <= MAX_WIDTH):
            raise FeatureBundleError("token feature shape outside bounds")
        present = {k: v for k, v in values.items() if v is not None}
        elements = byte_count = 0
        for name, value in present.items():
            if (not isinstance(value, torch.Tensor) or value.is_meta
                    or value.layout != torch.strided or value.requires_grad
                    or value.grad_fn is not None):
                raise FeatureBundleError(f"{name}: detached materialized tensor required")
            elements += value.numel()
            byte_count += value.numel() * value.element_size()
        if elements > MAX_ELEMENTS or byte_count > MAX_BYTES:
            raise FeatureBundleError("combined feature snapshot budget exceeded")
        # Normalize layout/device, but preserve the dtype whose bytes are bound.
        frozen = {k: v.detach().to(device="cpu").contiguous().clone()
                  for k, v in present.items()}
        for name in ("global_features", "token_features", "region_boxes", "time_spans"):
            value = frozen.get(name)
            if value is not None and (value.dtype not in (torch.float32, torch.bfloat16)
                                      or not bool(torch.isfinite(value).all())):
                raise FeatureBundleError(f"{name}: finite float32/BF16 features required")
        missing = frozen.get("missing_mask")
        if (missing is None or missing.dtype != torch.bool
                or missing.shape != (batch, len(MODALITIES))
                or bool(missing.all(dim=1).any())):
            raise FeatureBundleError("invalid per-row modality presence")
        if token_features is not None:
            cls._validate_tokens(frozen, missing, token_features.shape[:2])
        obj = cls()
        obj._identity = identity
        obj._sources = tuple(source_record_digests)
        obj._tensors = frozen
        obj._manifest = {
            "schema": "hepta.feature-bundle.v1", "identity": asdict(identity),
            "source_record_digests": list(obj._sources), "modalities": list(MODALITIES),
            "views": {k: _tensor_record(v) for k, v in frozen.items()},
            "source_independently_attested": False, "authority": "DENY_ALL",
        }
        obj._digest = _digest(obj._manifest)
        # Same effective request may have only one output; differing bundle
        # digests at this key are a conflict, not a cache replacement.
        obj._cache_key = _digest({"schema": "hepta.feature-request.v1",
                                 "identity": asdict(identity),
                                 "source_record_digests": list(obj._sources)})
        return obj

    @staticmethod
    def _validate_tokens(values, missing, shape):
        valid, modalities = values.get("token_valid"), values.get("modality_ids")
        if (valid is None or valid.dtype != torch.bool or valid.shape != shape
                or not bool(valid.any(dim=1).all()) or modalities is None
                or modalities.dtype != torch.int64 or modalities.shape != shape
                or bool(((modalities[valid] < 0) | (modalities[valid] >= len(MODALITIES))).any())
                or bool((modalities[~valid] != -1).any())):
            raise FeatureBundleError("invalid token validity/modality mapping")
        if bool(missing.gather(1, modalities.clamp(min=0))[valid].any()):
            raise FeatureBundleError("token refers to a missing modality")
        for name, mask_name, width in (("region_boxes", "region_valid", 4),
                                       ("time_spans", "time_valid", 2)):
            view, mask = values.get(name), values.get(mask_name)
            if view is None and mask is None:
                continue
            if (view is None or mask is None or view.shape != (*shape, width)
                    or mask.dtype != torch.bool or mask.shape != shape
                    or bool((mask & ~valid).any()) or bool((view[~mask] != 0).any())):
                raise FeatureBundleError(f"unbound or noncanonical {name}")
            selected = view[mask].float()
            if name == "region_boxes":
                if (bool(((selected < 0) | (selected > 1)).any())
                        or bool((selected[:, 2:] <= selected[:, :2]).any())
                        or not bool(torch.isin(modalities[mask], torch.tensor([1, 3])).all())):
                    raise FeatureBundleError("invalid normalized image/video regions")
            elif (bool(((selected < 0) | (selected > 1e9)).any())
                  or bool((selected[:, 1] < selected[:, 0]).any())):
                raise FeatureBundleError("invalid source time spans in seconds")

    @property
    def identity(self):
        return self._identity

    @property
    def source_record_digests(self):
        return self._sources

    @property
    def bundle_digest(self):
        return self._digest

    @property
    def cache_key(self):
        return self._cache_key

    def read_global(self):
        return self._tensors["global_features"].clone()

    def read_tokens(self):
        value = self._tensors.get("token_features")
        return None if value is None else value.clone()

    def snapshot(self):
        """Read independently mutable tensor views; never alias sealed storage."""
        return {k: v.clone() for k, v in self._tensors.items()}

    def manifest(self):
        return json.loads(json.dumps(self._manifest))

    def verify_integrity(self):
        current = self.manifest()
        current["identity"] = asdict(self._identity)
        current["source_record_digests"] = list(self._sources)
        current["views"] = {k: _tensor_record(v) for k, v in self._tensors.items()}
        if _digest(current) != self._digest:
            raise FeatureBundleError("feature bundle bytes changed")

    def require_identity(self, expected: FeatureIdentityV1):
        if self._identity != expected:
            raise FeatureBundleError("encoder/preprocessing/generation/scope mismatch")
        self.verify_integrity()

    def q24_global(self, row: int = 0):
        """Explicit global-only conversion, not nonlinear-Head export/parity.

The receipt uses SHA256 locally. Native Rust wire digests must still be
computed by their existing canonical encoder, never copied from this receipt.
        """
        self.verify_integrity()
        features = self.read_global()
        if type(row) is not int or not 0 <= row < features.shape[0]:
            raise FeatureBundleError("invalid Q24 source row")
        values = features[row].float().tolist()
        if any(abs(value) > 8 for value in values):
            raise FeatureBundleError("Q24 global view exceeds legacy [-8,8] bounds")
        statement = {"schema": "hepta.feature-global-q24-conversion.v1",
                     "numeric_profile": "signed-q24-nearest-ties-even-v1",
                     "source_bundle_sha256": self.bundle_digest,
                     "source_record_digest": self._sources[row], "row": row,
                     "feature_vector_q24": [round(v * (1 << 24)) for v in values],
                     "authority": "DENY_ALL", "legacy_head_parity_qualified": False}
        return {**statement, "conversion_sha256": _digest(statement)}
