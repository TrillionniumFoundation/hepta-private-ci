"""Read-only reference for the native Rust Q24 gated Cell Head arithmetic.

This module is an exact numeric comparator, NOT a selected model, signed CAS
receipt, grant, inference owner, native backend, or measured accelerator.
Production applications must verify artifact selection, scope/fence and CURRENT.
"""

from native_bridge import LIMIT, Q24, tensor_digest

KEYS = frozenset(
    (
        "input_width",
        "output_width",
        "drive_weights_q24",
        "prediction_weights_q24",
        "gate_weights_q24",
        "drive_bias_q24",
        "prediction_bias_q24",
        "gate_bias_q24",
    )
)
TENSORS = (
    "drive_weights_q24",
    "prediction_weights_q24",
    "gate_weights_q24",
    "drive_bias_q24",
    "prediction_bias_q24",
    "gate_bias_q24",
)


def _q24_integer(value):
    if type(value) is not int or not -LIMIT <= value <= LIMIT:
        raise ValueError("invalid signed Q24 value")
    return value


def _round_q48(value):
    floor, remainder = divmod(value, Q24)
    if remainder * 2 > Q24 or (remainder * 2 == Q24 and floor % 2):
        floor += 1
    return _q24_integer(floor)


def _gate_q24(preactivation):
    """Exact hard-sigmoid clamp with round-to-nearest, ties-to-even."""
    numerator = min(2 * Q24, max(0, preactivation + Q24))
    half, remainder = divmod(numerator, 2)
    return half + int(remainder == 1 and half % 2 == 1)


def _validated_head(head):
    if type(head) is not dict or set(head) != KEYS:
        raise ValueError("unregistered gated Head schema")
    width, outputs = head["input_width"], head["output_width"]
    if type(width) is not int or type(outputs) is not int:
        raise ValueError("invalid Head dimensions")
    if not (1 <= width <= 512 and 1 <= outputs <= 512):
        raise ValueError("invalid Head dimensions")
    count = width * outputs
    tensors = []
    for name in TENSORS:
        values = head[name]
        if type(values) is not list or any(type(v) is not int for v in values):
            raise ValueError("noncanonical Head coefficients")
        if name == "drive_weights_q24":
            allowed_lengths = (count,)
        elif name in ("prediction_weights_q24", "gate_weights_q24"):
            allowed_lengths = (0, count)
        else:
            allowed_lengths = (outputs,)
        if len(values) not in allowed_lengths:
            raise ValueError("Head tensor shape mismatch")
        for number in values:
            _q24_integer(number)
        tensors.append(values)
    return width, outputs, tensors


def gated_head_digest(head):
    """Same digest bytes as CpuGatedHead::digest; not an authority signature."""
    width, outputs, tensors = _validated_head(head)
    return tensor_digest(width, outputs, tensors)


def infer_gated_q24(head, features_q24):
    """Compute exact Q24 (drive, prediction) vectors; never truncate or clamp
    overflow. A terminal numerical failure rejects the whole Head invocation.
    """
    width, outputs, tensors = _validated_head(head)
    if type(features_q24) not in (tuple, list) or len(features_q24) != width:
        raise ValueError("Q24 input width mismatch")
    features = [_q24_integer(value) for value in features_q24]
    drive_w, prediction_w, gate_w, drive_b, prediction_b, gate_b = tensors

    def dot(weights, bias, row):
        if not weights:
            return bias
        start = row * width
        total = bias * Q24
        total += sum(
            weight * value for weight, value in zip(weights[start : start + width], features)
        )
        return _round_q48(total)

    drive, prediction = [], []
    for row in range(outputs):
        gate = _gate_q24(dot(gate_w, gate_b[row], row))
        drive.append(_round_q48(dot(drive_w, drive_b[row], row) * gate))
        prediction.append(_round_q48(dot(prediction_w, prediction_b[row], row) * gate))
    return tuple(drive), tuple(prediction)
