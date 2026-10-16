"""Research-only deterministic f32 magnitude scaling for E0 public CPU diagnosis.

The *rule* is frozen: use the smallest nonnegative power-of-two shift
placing the largest absolute f32 feature at most 4. Never clip. The shift
is chosen per input; this is NOT a trained, selected, invertible or
production-qualified normalizer.
"""
from __future__ import annotations

import hashlib
import math
import struct

MAX_WIDTH = 8192
MAX_SHIFT = 126
TARGET_ABS = 4.0
Q = 1 << 24
POLICY_DOMAIN = b"hepta.neuron.e0.f32-dyadic-bound.v1"
BINDING_DOMAIN = b"hepta.neuron.e0.f32-dyadic-source-binding.v1"
POLICY_DIGEST = hashlib.sha256(POLICY_DOMAIN).hexdigest()


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def normalize_feature_bytes(raw: bytes) -> tuple[bytes, dict]:
    _require(type(raw) is bytes and len(raw) % 4 == 0 and
             1 <= len(raw) // 4 <= MAX_WIDTH, "invalid raw f32 geometry")
    count = len(raw) // 4
    values = struct.unpack(f">{count}f", raw)
    _require(all(math.isfinite(v) for v in values), "nonfinite raw f32 model output")
    magnitude = max(abs(v) for v in values)
    shift = 0
    while math.ldexp(magnitude, -shift) > TARGET_ABS:
        shift += 1
        _require(shift <= MAX_SHIFT, "raw features exceed diagnostic scaling envelope")
    normalized = struct.pack(f">{count}f", *(math.ldexp(v, -shift) for v in values))
    _require(all(math.isfinite(v) and abs(v) <= TARGET_ABS
                 for v in struct.unpack(f">{count}f", normalized)),
             "normalized f32 outside diagnostic envelope")
    raw_sha = hashlib.sha256(raw).hexdigest()
    normalized_sha = hashlib.sha256(normalized).hexdigest()
    binding = hashlib.sha256(BINDING_DOMAIN + shift.to_bytes(8, "big") +
                             bytes.fromhex(raw_sha) + bytes.fromhex(normalized_sha)).hexdigest()
    return normalized, {
        "schema": "hepta.neuron.e0-f32-dyadic-observation.v1",
        "policy_digest": POLICY_DIGEST,
        "raw_sha256": raw_sha,
        "normalized_sha256": normalized_sha,
        "shift": shift,
        "binding_digest": binding,
        "raw_max_abs": magnitude,
        "per_input_exponent": True,
        "no_silent_clipping": True,
        "lossless_or_semantically_neutral": False,
        "production_authorized": False,
    }


def choose_diagnostic_tail_index(normalized: bytes, head_width: int) -> int:
    """Pick one observable tail coordinate; diagnostic, never Cell selection."""
    _require(type(normalized) is bytes and len(normalized) % 4 == 0,
             "invalid normalized f32 buffer")
    n = len(normalized) // 4
    _require(type(head_width) is int and 0 < head_width < n <= MAX_WIDTH,
             "diagnostic projector requires source tail")
    values = struct.unpack(f">{n}f", normalized)
    index = max(range(head_width, n), key=lambda j: abs(values[j]))
    _require(math.isfinite(values[index]) and abs(values[index]) <= TARGET_ABS,
             "invalid diagnostic source tail")
    _require(round(values[index] * Q) != 0,
             "no Q24-representable diagnostic source tail")
    return index
