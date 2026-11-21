"""Independent dense-oracle builder stopped before either exponential action."""

import hashlib
import json
from fractions import Fraction
from pathlib import Path


EXECUTION_ALLOWED = False
CHANNELS = 5
INTERIOR = 255
INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
METADATA_RELATIVE = "qualification/hcsn_n256_new_export/evidence/attempt001/METADATA.json"
METADATA_SHA256 = "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6"
CONTAINER_BYTES = 545171


def _spatial(mu, sigma, nodes):
    if len(nodes) != 257 or any(right <= left for left, right in zip(nodes, nodes[1:])):
        raise ValueError("oracle node geometry")
    rows = [[0.0] * INTERIOR for _ in range(INTERIOR)]
    lower = [0.0] * INTERIOR
    upper = [0.0] * INTERIOR
    gaps = [right - left for left, right in zip(nodes, nodes[1:])]
    for index in range(INTERIOR):
        left, right = gaps[index], gaps[index + 1]
        down = (sigma**2 - mu * right) / (left * (left + right))
        up = (sigma**2 + mu * left) / (right * (left + right))
        rows[index][index] = -(down + up)
        if index:
            rows[index][index - 1] = down
        else:
            lower[index] = down
        if index + 1 < INTERIOR:
            rows[index][index + 1] = up
        else:
            upper[index] = up
    return rows, lower, upper


def _reset(reset_position, nodes):
    right = next(index for index, value in enumerate(nodes) if value > reset_position)
    left = right - 1
    if not 1 <= left or right >= len(nodes) - 1:
        raise ValueError("oracle reset support")
    fraction = (reset_position - nodes[left]) / (nodes[right] - nodes[left])
    weights = [0.0] * INTERIOR
    weights[left - 1] = 1.0 - fraction
    weights[right - 1] = fraction
    return weights


def _payload(np, array, shape, name):
    if tuple(array.shape) != shape:
        raise ValueError(f"oracle shape: {name}")
    if array.dtype.str != "<f8" or not array.flags.c_contiguous:
        raise ValueError(f"oracle raw layout: {name}")
    if not np.isfinite(array).all():
        raise ValueError(f"oracle finite values: {name}")
    return array.tobytes(order="C")


def build_boundary(root):
    """Future admitted entry; this source-only stage never calls it."""
    import numpy as np

    from qualification.hcsn_currentstate_n256_boundary_container_contract.boundary_codec import (
        encode_boundary,
    )
    from qualification.hcsn_currentstate_n256_independent_oracle_v2_intent.adapter import (
        load_authentic_input,
    )

    root = Path(root)
    metadata_path = root / METADATA_RELATIVE
    if hashlib.sha256(metadata_path.read_bytes()).hexdigest() != METADATA_SHA256:
        raise ValueError("oracle metadata identity")
    metadata = json.loads(metadata_path.read_text())
    authentic = load_authentic_input(root)
    nodes = np.frombuffer(authentic.nodes_payload, dtype="<f8")
    spatial, lower, upper = _spatial(
        metadata["physics"]["mu"], metadata["physics"]["sigma"], nodes
    )
    reset = _reset(metadata["reset_distance"], nodes)
    parents = [item for item in authentic.phase_packets if item[1] == Fraction(0)]
    if len(parents) != 1:
        raise ValueError("oracle warm releasing-parent denominator")
    _identity, _start, _end, alpha_fraction = parents[0]
    rows = [[0.0] * 256 for _ in range(256)]
    for node, weight in enumerate(reset):
        rows[0][1 + node] = weight
    for row in range(INTERIOR):
        rows[1 + row][1 : 1 + INTERIOR] = spatial[row]
    generator = np.asarray(rows, dtype="<f8")
    extended = np.zeros((257, 257), dtype="<f8")
    extended[:-1, :-1] = generator
    extended[1:256, -1] = upper
    active = np.frombuffer(authentic.active_payload, dtype="<f8")
    content = np.frombuffer(authentic.signed_content_payload, dtype="<f8").reshape(257, 4)
    interior = np.column_stack((active[1:-1], content[1:-1])).T
    alpha = np.asarray(tuple(float(value) for value in alpha_fraction), dtype="<f8").reshape(5, 1)
    initial = np.concatenate((alpha, interior, np.zeros((5, 1), dtype="<f8")), axis=1)
    lower_selector = np.zeros((257, 1), dtype="<f8")
    lower_selector[1:256, 0] = lower
    discounted = np.zeros((257, 2), dtype="<f8")
    discounted[1:256, 0] = lower
    discounted[1:, 1] = 1.0
    sections = {
        "extended_generator": _payload(np, extended, (257, 257), "generator"),
        "initial": _payload(np, initial, (5, 257), "initial"),
        "lower_selector": _payload(np, lower_selector, (257, 1), "lower"),
        "discounted_selectors": _payload(np, discounted, (257, 2), "discounted"),
    }
    encoded = encode_boundary(sections)
    if len(encoded) != CONTAINER_BYTES:
        raise ValueError("oracle container length")
    return encoded
