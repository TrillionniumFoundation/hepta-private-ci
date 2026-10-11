"""Unsigned, shadow-only affine Torch Head -> compact Hepta Q24 tensor export.

No model install, authoritative receipt, cross-scope sharing or production release.
Quantization admission uses calibration vectors, never held-out/future outcomes.
"""
import hashlib
import json
import math
from pathlib import Path

Q24 = 1 << 24
LIMIT = 8 * Q24
KINDS = {"linear", "film", "rank8", "rank16"}


def to_q24(value):
    value = float(value)
    if not math.isfinite(value) or abs(value) > 8:
        raise ValueError("Q24 scalar outside representable [-8, 8] range")
    return round(value * Q24)


def round_q48(value):
    quotient, remainder = divmod(value, Q24)
    if remainder * 2 > Q24 or (remainder * 2 == Q24 and quotient % 2):
        quotient += 1
    if abs(quotient) > LIMIT:
        raise ValueError("Q24 inference output outside range")
    return quotient


def affine_head(torch, head, kind):
    if kind not in KINDS:
        raise ValueError("nonaffine Head requires a native registered operator")
    head.eval()
    with torch.no_grad():
        if kind == "linear":
            w = head.weight.detach().float()
            b = head.bias.detach().float()
        elif kind == "film":
            source = head.readout.weight.detach().float()
            w = source * head.gamma.detach().float().unsqueeze(0)
            b = head.readout.bias.detach().float() + source @ head.beta.detach().float()
        else:
            w = head[1].weight.detach().float() @ head[0].weight.detach().float()
            b = head[1].bias.detach().float()
    return w.cpu(), b.cpu()


def tensor_digest(width, classes, tensors):
    hasher = hashlib.sha256(b"hepta.cpu-gated-head.v1")
    hasher.update(width.to_bytes(8, "big"))
    hasher.update(classes.to_bytes(8, "big"))
    for values in tensors:
        hasher.update(len(values).to_bytes(8, "big"))
        for number in values:
            hasher.update(number.to_bytes(8, "big", signed=True))
    return hasher.hexdigest()


def bundle_digest(encoder_digest, head_digest):
    if len(encoder_digest) != 64 or any(c not in "0123456789abcdef" for c in encoder_digest):
        raise ValueError("encoder must have a pinned lowercase 64-hex digest")
    return hashlib.sha256(
        b"hepta.cpu-gated-bundle.v1"
        + encoder_digest.encode("ascii")
        + (1).to_bytes(8, "big")
        + head_digest.encode("ascii")
    ).hexdigest()


def native_logits(artifact, vector):
    width = artifact["input_width"]
    classes = artifact["output_width"]
    if len(vector) != width:
        raise ValueError("native input feature width mismatch")
    inputs = [to_q24(v) for v in vector]
    outputs = []
    for row in range(classes):
        acc = artifact["drive_bias_q24"][row] * Q24
        offset = row * width
        for index, value in enumerate(inputs):
            acc += value * artifact["drive_weights_q24"][offset + index]
        outputs.append(round_q48(acc) / Q24)
    return outputs


def build_candidate(torch, head, kind, encoder_digest, calibration_features,
                    *, max_abs_error=0.02):
    weights, bias = affine_head(torch, head, kind)
    if weights.ndim != 2 or bias.shape != (weights.shape[0],):
        raise ValueError("invalid affine Head shape")
    classes, width = weights.shape
    if not (1 <= width <= 512 and 1 <= classes <= 512):
        raise ValueError("native Neuron V1 input width <=512; projection required")
    drive = [to_q24(v) for v in weights.reshape(-1).tolist()]
    drive_bias = [to_q24(v) for v in bias.tolist()]
    # Canonical constant-zero prediction and gate weight matrices.
    prediction, gate = [], []
    prediction_bias, gate_bias = [0] * classes, [Q24] * classes
    tensors = (drive, prediction, gate, drive_bias, prediction_bias, gate_bias)
    head_digest = tensor_digest(width, classes, tensors)
    artifact = {
        "schema": "hepta.stem.q24-cpu-head-candidate.v1",
        "shadow_only": True,
        "production_authorized": False,
        "source_head_kind": kind,
        "encoder_digest": encoder_digest,
        "input_width": width,
        "output_width": classes,
        "drive_weights_q24": drive,
        "prediction_weights_q24": prediction,
        "gate_weights_q24": gate,
        "drive_bias_q24": drive_bias,
        "prediction_bias_q24": prediction_bias,
        "gate_bias_q24": gate_bias,
        "head_digest": head_digest,
        "weights_digest": bundle_digest(encoder_digest, head_digest),
        "native_stored_coefficients": sum(len(t) for t in tensors),
        "native_stored_tensor_bytes": 8 * sum(len(t) for t in tensors),
    }
    if not calibration_features:
        raise ValueError("disjoint calibration vectors required")
    largest = 0.0
    mismatches = 0
    with torch.inference_mode():
        for feature in calibration_features:
            expected = head(feature.reshape(1, -1)).flatten().cpu().tolist()
            actual = native_logits(artifact, feature.flatten().cpu().tolist())
            largest = max(largest, *(abs(a-b) for a,b in zip(expected, actual)))
            if max(range(classes), key=lambda i: expected[i]) != max(range(classes), key=lambda i: actual[i]):
                mismatches += 1
    if largest > max_abs_error or mismatches or not math.isfinite(largest):
        raise ValueError("Q24 calibration parity failure: no export")
    artifact.update({
        "calibration_vector_count": len(calibration_features),
        "calibration_max_abs_logit_error": largest,
        "calibration_argmax_mismatch_count": mismatches,
        "parity_limit": max_abs_error,
    })
    return artifact


def write_candidate(path, artifact):
    content = json.dumps(artifact, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    with Path(path).open("x", encoding="utf-8") as handle:
        handle.write(content)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# Research-only bytes for the existing signed Artifact CAS. A candidate is not
# a selection, proof of owner freshness, independent NDU or production grant.
HEAD_BANK_SCHEMA = "hepta.stem.q24-cpu-head-bank-candidate.v1"
HEAD_BANK_MAX_BYTES = 16 * 1024 * 1024
HEAD_BANK_MAX_CELLS = 32
HEAD_TENSOR_NAMES = (
    "drive_weights_q24", "prediction_weights_q24", "gate_weights_q24",
    "drive_bias_q24", "prediction_bias_q24", "gate_bias_q24",
)
HEAD_FIELDS = ("input_width", "output_width") + HEAD_TENSOR_NAMES


def bundle_digest_many(encoder_digest, head_digests):
    """Same sorted Q24 Head-bank digest as CpuGatedHeadDriver in Rust."""
    if (type(encoder_digest) is not str or len(encoder_digest) != 64 or
            any(c not in "0123456789abcdef" for c in encoder_digest)):
        raise ValueError("invalid fixed Encoder digest")
    if (type(head_digests) not in (tuple, list)
            or not 1 <= len(head_digests) <= HEAD_BANK_MAX_CELLS):
        raise ValueError("Head-bank size out of bounds")
    hashes = sorted(head_digests)
    if any(type(h) is not str or len(h) != 64 or
           any(c not in "0123456789abcdef" for c in h) for h in hashes):
        raise ValueError("invalid Head digest")
    if any(a == b for a, b in zip(hashes, hashes[1:])):
        raise ValueError("duplicate Cell Head is not a distinct bank member")
    content = (b"hepta.cpu-gated-bundle.v1" + encoder_digest.encode("ascii")
               + len(hashes).to_bytes(8, "big")
               + b"".join(h.encode("ascii") for h in hashes))
    return hashlib.sha256(content).hexdigest()


def encode_cpu_head_bank_candidate(artifacts):
    """Convert audited compact Q24 training candidates to canonical CAS bytes.

    Head content, member ordering and bundle weights are verified before
    serialization. This is shadow-only and supplies no producer, selector or
    final-use signature.
    """
    if type(artifacts) not in (list, tuple) or not 1 <= len(artifacts) <= HEAD_BANK_MAX_CELLS:
        raise ValueError("Head bank must contain 1..32 bounded members")
    heads = []
    encoder = None
    for candidate in artifacts:
        if (type(candidate) is not dict or
                candidate.get("schema") != "hepta.stem.q24-cpu-head-candidate.v1"
                or candidate.get("shadow_only") is not True
                or candidate.get("production_authorized") is not False):
            raise ValueError("non-shadow or unknown Head candidate")
        if encoder is None:
            encoder = candidate.get("encoder_digest")
        if candidate.get("encoder_digest") != encoder:
            raise ValueError("mixed Encoder bank")
        head = {k: candidate.get(k) for k in HEAD_FIELDS}
        width, classes = head["input_width"], head["output_width"]
        if (type(width) is not int or type(classes) is not int
                or not 1 <= width <= 512 or not 1 <= classes <= 512):
            raise ValueError("unsupported Q24 Head dimensions")
        n = width * classes
        for name, expected in (
            ("drive_weights_q24", (n,)),
            ("prediction_weights_q24", (0, n)),
            ("gate_weights_q24", (0, n)),
            ("drive_bias_q24", (classes,)),
            ("prediction_bias_q24", (classes,)),
            ("gate_bias_q24", (classes,)),
        ):
            values = head[name]
            if (type(values) is not list or len(values) not in expected
                    or any(type(v) is not int or not -LIMIT <= v <= LIMIT for v in values)):
                raise ValueError("invalid Head matrix or Q24 scalar")
        digest = tensor_digest(width, classes, [head[n] for n in HEAD_TENSOR_NAMES])
        if candidate.get("head_digest") != digest or (
                candidate.get("weights_digest") != bundle_digest(encoder, digest)):
            raise ValueError("Head digest does not match actual Q24 weights")
        heads.append((digest, head))
    heads.sort(key=lambda pair: pair[0])
    digests = [d for d, _ in heads]
    weight_digest = bundle_digest_many(encoder, digests)
    raw = (json.dumps({
        "encoder_digest": encoder,
        "heads": [item for _, item in heads],
        "schema": HEAD_BANK_SCHEMA,
        "weights_digest": weight_digest,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
           + "\n").encode("ascii")
    if len(raw) > HEAD_BANK_MAX_BYTES:
        raise ValueError("Head bank exceeds exact CAS size bound")
    return raw


def write_cpu_head_bank_candidate(path, artifacts):
    """Create-only candidate payload. Real CAS publication is a separate owner."""
    raw = encode_cpu_head_bank_candidate(artifacts)
    with Path(path).open("xb") as handle:
        handle.write(raw)
    return hashlib.sha256(raw).hexdigest()


# Stable research names for the optional model-runner hook.
build_q24_head_candidate = build_candidate
write_q24_head_candidate = write_candidate
_native_logits = native_logits
_round_q48 = round_q48
