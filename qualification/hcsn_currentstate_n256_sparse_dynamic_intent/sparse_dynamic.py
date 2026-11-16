"""Executable sparse N256 current-state candidate, frozen without execution.

NumPy and SciPy are imported only after fail-closed external admission.  This
module implements the same row-vector dynamics as the N128 dense reference,
including permanent upper escape, lower-hit flux, discounted occupation,
deterministic delay, resets, signed-content channels, and warm/coarse/cold
state forks.  It does not provide an independent oracle or serializer.
"""

import hashlib
import json
import math
from dataclasses import dataclass, replace
from fractions import Fraction as F

from qualification.hcsn_currentstate_n256_sparse_dynamic_intent.admission import (
    require_admission,
)


CHANNELS = 5
INTERIOR = 255
DISCOUNT = 0.15
DELAY = F(1, 5)
WARM = tuple(F(value) for value in ("0", ".001", ".02", ".16", ".2", ".201", ".28", ".36"))
COARSE = (F(0), F(1, 5), F(9, 25))
COLD = (F(201, 1000), F(7, 25), F(9, 25))
INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
ROSTER_IDENTITY = "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2"


@dataclass(frozen=True)
class Packet:
    source: str
    generation: int
    target: int
    origin: int
    start: F
    end: F
    operator: object
    alpha: tuple
    output: tuple

    @property
    def dimension(self):
        return self.operator.dimension


@dataclass
class DynamicState:
    active: object
    upper: object
    mass: object
    discounted_hit: object
    occupation: object

    def clone(self):
        return DynamicState(
            self.active.copy(),
            self.upper.copy(),
            self.mass.copy(),
            self.discounted_hit.copy(),
            self.occupation.copy(),
        )

    def coordinates(self):
        np, _ = _numeric_modules()
        return tuple(
            np.concatenate(
                (
                    self.active.ravel(),
                    self.upper.ravel(),
                    self.mass.ravel(),
                    self.discounted_hit.ravel(),
                    self.occupation.ravel(),
                )
            )
        )


@dataclass(frozen=True)
class Capsule:
    lane: str
    lane_order: int
    time: F
    state: tuple
    packets: tuple


@dataclass
class Counts:
    segments: int = 0
    expm_actions: int = 0
    scipy_imports: int = 0


def _numeric_modules():
    import numpy as np
    from scipy import sparse
    from scipy.sparse.linalg import expm_multiply

    return np, (sparse, expm_multiply)


def _csr(operator, sparse):
    return sparse.csr_matrix(
        (operator.data, operator.indices, operator.indptr),
        shape=(operator.dimension, operator.dimension),
        dtype="float64",
    )


def _extended(operator, upper_flow, sparse):
    core = _csr(operator, sparse)
    prefix = (0.0,) * (operator.dimension - INTERIOR)
    sink = sparse.csr_matrix(prefix + tuple(upper_flow), dtype="float64").T
    return sparse.bmat(
        ((core, sink), (None, sparse.csr_matrix((1, 1), dtype="float64"))),
        format="csr",
    )


def _action(matrix, initial, selectors, duration, discount, modules):
    np, (sparse, expm_multiply) = modules
    outputs = selectors.shape[1]
    shifted = matrix - discount * sparse.eye(matrix.shape[0], format="csr")
    augmented = sparse.bmat(
        (
            (shifted, sparse.csr_matrix(selectors)),
            (None, sparse.csr_matrix((outputs, outputs), dtype="float64")),
        ),
        format="csr",
    )
    seeded = np.concatenate(
        (initial, np.zeros((initial.shape[0], outputs), dtype="float64")), axis=1
    )
    evolved = expm_multiply((augmented.T * float(duration)), seeded.T).T
    return evolved[:, : matrix.shape[0]], evolved[:, matrix.shape[0] :]


def _template(packet, primitive):
    return primitive.Template(
        packet.source,
        packet.generation,
        packet.start,
        packet.end,
        packet.target,
        packet.origin,
        packet.operator,
        packet.output,
        (),
    )


def _initial_state(metadata, phase, arrays, primitive, bundle, np):
    original_active = np.asarray(arrays["active.npy"][1], dtype="float64")
    original_content = np.asarray(arrays["content.npy"][1], dtype="float64").reshape(257, 4)
    active = np.zeros((CHANNELS, 2, INTERIOR), dtype="float64")
    active[:, 0] = np.column_stack((original_active[1:-1], original_content[1:-1])).T
    upper = np.zeros((CHANNELS, 3), dtype="float64")
    upper[:, 0] = np.r_[original_active[-1], original_content[-1]]
    state = DynamicState(
        active,
        upper,
        np.zeros((CHANNELS, 2), dtype="float64"),
        np.zeros((CHANNELS, 2), dtype="float64"),
        np.zeros((CHANNELS, 3), dtype="float64"),
    )
    zero = primitive.CSR.from_rows(({},))
    packets = []
    for item in phase["packets"]:
        start, end = F(item["start"]), F(item["end"])
        width = end - start
        alpha = (float(F(item["mass"]) / width),) + tuple(
            float(F(value) / width) for value in item["content"]
        )
        source = primitive.source_identity(bundle, item["identity"], start, end, 1, 0, ())
        packets.append(Packet(source, 1, 1, 0, start, end, zero, alpha, (1.0,)))
    return state, tuple(packets)


def _advance(state, pending, time, right, primitive, spatial, lower, upper_flow, reset, bundle, modules, counts):
    np, (sparse, _) = modules
    releasing = tuple(packet for packet in pending if packet.start == time)
    fragments = {}
    emitted = []
    for origin, target in ((1, 2), (2, 3)):
        if origin == 2 and time < DELAY:
            continue
        parents = tuple(packet for packet in releasing if packet.target == origin)
        operator, output = primitive.block_operator(
            tuple(_template(packet, primitive) for packet in parents),
            spatial,
            lower,
            reset,
        )
        blocks = [np.asarray(packet.alpha, dtype="float64").reshape(CHANNELS, packet.dimension) for packet in parents]
        blocks.append(state.active[:, origin - 1])
        alpha = np.concatenate(blocks, axis=1)
        matrix = _extended(operator, upper_flow, sparse)
        initial = np.concatenate((alpha, state.upper[:, origin, None]), axis=1)
        lower_selector = np.zeros((matrix.shape[0], 1), dtype="float64")
        lower_selector[-INTERIOR - 1 : -1, 0] = lower
        final, lower_contribution = _action(matrix, initial, lower_selector, right - time, 0.0, modules)
        selectors = np.zeros((matrix.shape[0], 2), dtype="float64")
        selectors[-INTERIOR - 1 : -1, 0] = lower
        selectors[1:, 1] = 1.0
        _, discounted = _action(matrix, initial, selectors, right - time, DISCOUNT, modules)
        global_discount = math.exp(-DISCOUNT * float(time))
        offset = 0
        for parent in parents:
            stop = offset + parent.dimension
            if parent.end > right:
                fragments[parent.source] = replace(
                    parent,
                    start=right,
                    alpha=tuple(final[:, offset:stop].ravel()),
                )
            offset = stop
        state.active[:, origin - 1] = final[:, -INTERIOR - 1 : -1]
        state.upper[:, origin] = final[:, -1]
        state.mass[:, origin - 1] += lower_contribution[:, 0]
        state.discounted_hit[:, origin - 1] += global_discount * discounted[:, 0]
        state.occupation[:, origin] += global_discount * discounted[:, 1]
        source = primitive.source_identity(
            bundle,
            "lower-flux",
            time,
            right,
            target,
            origin,
            tuple(packet.source for packet in parents),
        )
        emitted.append(
            Packet(
                source,
                target,
                target,
                origin,
                time + DELAY,
                right + DELAY,
                operator,
                tuple(alpha.ravel()),
                output,
            )
        )
        counts.expm_actions += 2
    state.occupation[:, 0] += (
        math.exp(-DISCOUNT * float(time))
        * state.upper[:, 0]
        * (-math.expm1(-DISCOUNT * float(right - time)) / DISCOUNT)
    )
    retained = []
    for packet in pending:
        if packet.start != time:
            retained.append(packet)
        elif packet.source in fragments:
            retained.append(fragments[packet.source])
    retained.extend(emitted)
    counts.segments += 1
    return state, tuple(retained), right


def _run_lane(name, queries, state, pending, start, primitive, spatial, lower, upper_flow, reset, bundle, modules, counts):
    capsules = []
    time = start
    for lane_order, query in enumerate(queries):
        while time < query:
            boundaries = [query, time + DELAY]
            for packet in pending:
                boundaries.extend((packet.start, packet.end))
            right = min(value for value in boundaries if value > time)
            state, pending, time = _advance(
                state,
                pending,
                time,
                right,
                primitive,
                spatial,
                lower,
                upper_flow,
                reset,
                bundle,
                modules,
                counts,
            )
        capsules.append(Capsule(name, lane_order, time, state.coordinates(), pending))
    return tuple(capsules), state, pending


def _validate_roster(capsules, roster_dir, primitive):
    summary, published, expected_capsules, _ = primitive.roster_records(roster_dir)
    if summary["coordinate_identity_sha256"] != ROSTER_IDENTITY:
        raise ValueError("roster identity")
    by_capsule = {}
    for row in published:
        by_capsule.setdefault(row["capsule_order"], []).append(row)
    conceptual = 0
    for order, (capsule, expected) in enumerate(zip(capsules, expected_capsules)):
        if (
            capsule.lane,
            capsule.lane_order,
            [capsule.time.numerator, capsule.time.denominator],
            len(capsule.packets),
        ) != (
            expected["lane"],
            expected["lane_order"],
            expected["time"]["fraction"],
            expected["packets"],
        ):
            raise ValueError("capsule roster mismatch")
        rows = by_capsule[order]
        for packet, row in zip(capsule.packets, rows):
            actual = (
                packet.source,
                packet.generation,
                packet.dimension,
                packet.target,
                packet.origin,
                [packet.start.numerator, packet.start.denominator],
                [packet.end.numerator, packet.end.denominator],
            )
            target = (
                row["source"],
                row["generation"],
                row["dimension"],
                row["target"],
                row["origin"],
                row["start"]["fraction"],
                row["end"]["fraction"],
            )
            if actual != target:
                raise ValueError("packet roster mismatch")
        count = len(capsule.state) + sum(packet.dimension**2 + 6 * packet.dimension for packet in capsule.packets)
        if count != expected["coordinate_count"]:
            raise ValueError("coordinate denominator mismatch")
        conceptual += count
    if len(capsules) != 14 or conceptual != 18_225_028:
        raise ValueError("complete N256 denominator")


def run(request_path, admission_path, metadata_path, state_path, phase_path, npz_b64_path, roster_dir):
    """Execute only after an external, hash-bound resource amendment exists."""

    require_admission(request_path, admission_path)
    np, modules = _numeric_modules()
    from qualification.hcsn_currentstate_n256_engineering import candidate as primitive

    hashes, metadata, phase, arrays = primitive.load_inputs(
        metadata_path, state_path, phase_path, npz_b64_path
    )
    bundle = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if bundle != INPUT_BUNDLE_SHA256:
        raise ValueError("input bundle")
    spatial, lower, upper_flow, reset = primitive.spatial_operator(metadata, arrays["nodes.npy"][1])
    initial_state, initial_pending = _initial_state(metadata, phase, arrays, primitive, bundle, np)
    counts = Counts(scipy_imports=1)
    warm, warm_state, warm_pending = _run_lane(
        "warm", WARM, initial_state.clone(), tuple(initial_pending), F(0), primitive, spatial, lower, upper_flow, reset, bundle, modules, counts
    )
    saved = warm[5]
    saved_state = DynamicState(
        np.asarray(saved.state[: CHANNELS * 2 * INTERIOR], dtype="float64").reshape(CHANNELS, 2, INTERIOR),
        np.asarray(saved.state[CHANNELS * 2 * INTERIOR : CHANNELS * 2 * INTERIOR + CHANNELS * 3], dtype="float64").reshape(CHANNELS, 3),
        np.asarray(saved.state[CHANNELS * 2 * INTERIOR + CHANNELS * 3 : CHANNELS * 2 * INTERIOR + CHANNELS * 3 + CHANNELS * 2], dtype="float64").reshape(CHANNELS, 2),
        np.asarray(saved.state[CHANNELS * 2 * INTERIOR + CHANNELS * 3 + CHANNELS * 2 : CHANNELS * 2 * INTERIOR + CHANNELS * 3 + CHANNELS * 4], dtype="float64").reshape(CHANNELS, 2),
        np.asarray(saved.state[-CHANNELS * 3 :], dtype="float64").reshape(CHANNELS, 3),
    )
    coarse, _, _ = _run_lane(
        "coarse", COARSE, initial_state.clone(), tuple(initial_pending), F(0), primitive, spatial, lower, upper_flow, reset, bundle, modules, counts
    )
    cold, _, _ = _run_lane(
        "cold", COLD, saved_state, tuple(saved.packets), saved.time, primitive, spatial, lower, upper_flow, reset, bundle, modules, counts
    )
    capsules = warm + coarse + cold
    _validate_roster(capsules, roster_dir, primitive)
    return capsules, {
        "dynamic_segments": counts.segments,
        "sparse_expm_multiply_actions": counts.expm_actions,
        "scipy_imports": counts.scipy_imports,
        "conceptual_coordinates": 18_225_028,
        "oracle_calls": 0,
        "serializer_calls": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "qualification": False,
    }
