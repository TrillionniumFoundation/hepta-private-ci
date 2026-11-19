"""Independent dense warm-1 current-state oracle, frozen without execution.

The implementation does not import candidate, engineering, N128, or sparse
operator source. Numerical dependencies load only after a separately published
admission. The bounded target is exactly warm 0 -> 0.001.
"""

import hashlib
import json
import math
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path

from qualification.hcsn_currentstate_n256_firststep_dense_oracle_source.admission import (
    require_admission,
)
from qualification.hcsn_currentstate_n256_firststep_serializer_v2.serializer import (
    Block,
    Envelope,
    Packet,
    Tensor,
    coordinate_counts,
    publish_atomic,
)
from qualification.hcsn_currentstate_n256_independent_oracle_v2_intent.adapter import (
    load_authentic_input,
)


CHANNELS = 5
INTERIOR = 255
DELAY = Fraction(1, 5)
DISCOUNT = 0.15
RIGHT = Fraction(1, 1000)
INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
METADATA_RELATIVE = "qualification/hcsn_n256_new_export/evidence/attempt001/METADATA.json"
METADATA_SHA256 = "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6"
CAPSULE_IDENTITY = "af3119de18a4f2f9049fd4f33c2331448237cb1c90810f6cdf2f2bedaa5bf7c1"


@dataclass(frozen=True)
class DensePacket:
    identity: str
    generation: int
    origin: int
    target: int
    start: Fraction
    end: Fraction
    generator: object
    alpha: object
    output: object

    @property
    def dimension(self):
        return len(self.output)


@dataclass
class DenseState:
    active: object
    upper: object
    mass: object
    discounted_hit: object
    occupation: object


def _canonical(value):
    return json.dumps(
        value, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()


def _source_identity(kind, start, end, target, origin, parents):
    return hashlib.sha256(
        _canonical(
            {
                "bundle": INPUT_BUNDLE_SHA256,
                "kind": kind,
                "start": [start.numerator, start.denominator],
                "end": [end.numerator, end.denominator],
                "target": target,
                "origin": origin,
                "parents": sorted(parents),
            }
        )
    ).hexdigest()


def _numeric_modules():
    import numpy as np
    from scipy.linalg import expm

    return np, expm


def _spatial_coefficients(mu, sigma, nodes):
    if len(nodes) < 4 or any(right <= left for left, right in zip(nodes, nodes[1:])):
        raise ValueError("strict node geometry")
    interior = len(nodes) - 2
    rows = [[0.0] * interior for _ in range(interior)]
    lower = [0.0] * interior
    upper = [0.0] * interior
    gaps = [right - left for left, right in zip(nodes, nodes[1:])]
    for index in range(interior):
        left, right = gaps[index], gaps[index + 1]
        down = (sigma**2 - mu * right) / (left * (left + right))
        up = (sigma**2 + mu * left) / (right * (left + right))
        rows[index][index] = -(down + up)
        if index:
            rows[index][index - 1] = down
        else:
            lower[index] = down
        if index + 1 < interior:
            rows[index][index + 1] = up
        else:
            upper[index] = up
    return rows, lower, upper


def _reset_weights(reset_position, nodes):
    right = next(index for index, value in enumerate(nodes) if value > reset_position)
    left = right - 1
    if not 1 <= left or right >= len(nodes) - 1:
        raise ValueError("reset support is not interior")
    fraction = (reset_position - nodes[left]) / (nodes[right] - nodes[left])
    weights = [0.0] * (len(nodes) - 2)
    weights[left - 1] = 1.0 - fraction
    weights[right - 1] = fraction
    return weights


def _block_rows(parents, spatial, lower, reset):
    interior = len(spatial)
    dimension = interior + sum(parent.dimension for parent in parents)
    rows = [[0.0] * dimension for _ in range(dimension)]
    offset = 0
    for parent in parents:
        for row in range(parent.dimension):
            for column in range(parent.dimension):
                rows[offset + row][offset + column] = float(parent.generator[row][column])
            if parent.output[row] != 0:
                for node, weight in enumerate(reset):
                    rows[offset + row][dimension - interior + node] = (
                        float(parent.output[row]) * weight
                    )
        offset += parent.dimension
    for row in range(interior):
        rows[offset + row][offset : offset + interior] = spatial[row]
    output = [0.0] * (dimension - interior) + list(lower)
    return rows, output


def _phase_alpha(alpha):
    return tuple(float(value) for value in alpha)


def _stream_action(generator, initial, selectors, duration, discount, np, expm):
    outputs = selectors.shape[1]
    dimension = generator.shape[0]
    augmented = np.zeros((dimension + outputs, dimension + outputs), dtype="float64")
    augmented[:dimension, :dimension] = generator - discount * np.eye(dimension)
    augmented[:dimension, dimension:] = selectors
    seed = np.concatenate(
        (initial, np.zeros((initial.shape[0], outputs), dtype="float64")), axis=1
    )
    evolved = (expm(augmented.T * float(duration)) @ seed.T).T
    return evolved[:, :dimension], evolved[:, dimension:]


def _initial_state(authentic, np):
    active_original = np.frombuffer(authentic.active_payload, dtype="<f8")
    content_original = np.frombuffer(authentic.signed_content_payload, dtype="<f8").reshape(257, 4)
    active = np.zeros((CHANNELS, 2, INTERIOR), dtype="float64")
    active[:, 0] = np.column_stack((active_original[1:-1], content_original[1:-1])).T
    upper = np.zeros((CHANNELS, 3), dtype="float64")
    upper[:, 0] = np.r_[active_original[-1], content_original[-1]]
    return DenseState(
        active,
        upper,
        np.zeros((CHANNELS, 2), dtype="float64"),
        np.zeros((CHANNELS, 2), dtype="float64"),
        np.zeros((CHANNELS, 3), dtype="float64"),
    )


def _initial_packets(authentic, np):
    packets = []
    for identity, start, end, alpha in authentic.phase_packets:
        packets.append(
            DensePacket(
                _source_identity(identity, start, end, 1, 0, ()),
                1,
                0,
                1,
                start,
                end,
                np.zeros((1, 1), dtype="float64"),
                np.asarray(_phase_alpha(alpha), dtype="float64").reshape(CHANNELS, 1),
                np.ones(1, dtype="float64"),
            )
        )
    return tuple(packets)


def _advance_first(state, pending, spatial, lower, upper_flow, reset, np, expm):
    parents = tuple(packet for packet in pending if packet.start == 0 and packet.target == 1)
    if len(parents) != 1:
        raise ValueError("warm first-step releasing packet denominator")
    rows, output = _block_rows(parents, spatial, lower, reset)
    generator = np.asarray(rows, dtype="float64")
    alpha = np.concatenate(
        [np.asarray(packet.alpha).reshape(CHANNELS, packet.dimension) for packet in parents]
        + [state.active[:, 0]],
        axis=1,
    )
    extended = np.zeros((generator.shape[0] + 1, generator.shape[1] + 1), dtype="float64")
    extended[:-1, :-1] = generator
    extended[-INTERIOR - 1 : -1, -1] = upper_flow
    initial = np.concatenate((alpha, state.upper[:, 1, None]), axis=1)
    lower_selector = np.zeros((extended.shape[0], 1), dtype="float64")
    lower_selector[-INTERIOR - 1 : -1, 0] = lower
    final, hit = _stream_action(extended, initial, lower_selector, RIGHT, 0.0, np, expm)
    selectors = np.zeros((extended.shape[0], 2), dtype="float64")
    selectors[-INTERIOR - 1 : -1, 0] = lower
    selectors[1:, 1] = 1.0
    _, discounted = _stream_action(
        extended, initial, selectors, RIGHT, DISCOUNT, np, expm
    )
    parent = parents[0]
    fragment = replace(parent, start=RIGHT, alpha=final[:, : parent.dimension].copy())
    state.active[:, 0] = final[:, -INTERIOR - 1 : -1]
    state.upper[:, 1] = final[:, -1]
    state.mass[:, 0] += hit[:, 0]
    state.discounted_hit[:, 0] += discounted[:, 0]
    state.occupation[:, 1] += discounted[:, 1]
    state.occupation[:, 0] += state.upper[:, 0] * (
        -math.expm1(-DISCOUNT * float(RIGHT)) / DISCOUNT
    )
    emitted = DensePacket(
        _source_identity("lower-flux", Fraction(0), RIGHT, 2, 1, tuple(p.identity for p in parents)),
        2,
        1,
        2,
        DELAY,
        RIGHT + DELAY,
        generator,
        alpha,
        np.asarray(output, dtype="float64"),
    )
    retained = [packet for packet in pending if packet is not parent]
    retained.extend((fragment, emitted))
    return state, tuple(retained)


def _fraction(value):
    return f"{value.numerator}/{value.denominator}"


def _tensor(np, values):
    array = np.asarray(values, dtype="<f8", order="C")
    return Tensor("<f8", tuple(array.shape), array.tobytes(order="C"))


def _envelope(state, packets, np):
    blocks = tuple(
        Block(name, _tensor(np, values))
        for name, values in sorted(
            (
                ("active", state.active),
                ("upper", state.upper),
                ("mass", state.mass),
                ("discounted_hit", state.discounted_hit),
                ("occupation", state.occupation),
            )
        )
    )
    encoded_packets = tuple(
        Packet(
            identity=packet.identity,
            generation=packet.generation,
            origin=packet.origin,
            target=packet.target,
            start=_fraction(packet.start),
            end=_fraction(packet.end),
            alpha=_tensor(np, packet.alpha),
            generator=_tensor(np, packet.generator),
            output=_tensor(np, packet.output),
        )
        for packet in sorted(packets, key=lambda item: item.identity)
    )
    envelope = Envelope(
        {
            "capsule_identity": CAPSULE_IDENTITY,
            "input_bundle_sha256": INPUT_BUNDLE_SHA256,
            "lane": "warm",
            "lane_order": 1,
            "time": "1/1000",
        },
        blocks,
        encoded_packets,
    )
    if coordinate_counts(envelope) != {
        "state": 2600,
        "packet_alpha": 1320,
        "packet_generator": 65544,
        "packet_output": 264,
        "packet": 67128,
        "total": 69728,
    }:
        raise ValueError("warm first-step coordinate denominator")
    return envelope


def run_warm_first_step(root, request_path, admission_path, output_path):
    require_admission(request_path, admission_path, __file__)
    np, expm = _numeric_modules()
    root = Path(root)
    metadata_path = root / METADATA_RELATIVE
    if hashlib.sha256(metadata_path.read_bytes()).hexdigest() != METADATA_SHA256:
        raise ValueError("authentic metadata identity")
    metadata = json.loads(metadata_path.read_text())
    authentic = load_authentic_input(root)
    nodes = np.frombuffer(authentic.nodes_payload, dtype="<f8")
    spatial, lower, upper = _spatial_coefficients(
        metadata["physics"]["mu"], metadata["physics"]["sigma"], nodes
    )
    reset = _reset_weights(metadata["reset_distance"], nodes)
    state = _initial_state(authentic, np)
    packets = _initial_packets(authentic, np)
    state, packets = _advance_first(
        state, packets, spatial, lower, upper, reset, np, expm
    )
    envelope = _envelope(state, packets, np)
    payload_sha256 = publish_atomic(output_path, envelope)
    return {
        "payload_sha256": payload_sha256,
        "n256_serializer_calls": 1,
        "dynamic_steps": 1,
        "dense_expm_actions": 2,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "qualification": False,
    }
