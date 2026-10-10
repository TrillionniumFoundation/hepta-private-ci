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
