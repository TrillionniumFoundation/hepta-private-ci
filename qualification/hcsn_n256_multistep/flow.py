"""Two-cycle finite N256 flow, explicitly forked from the v3 sparse intent.

New identity: correct active occupation and preserve event-time reset snapshots.
The old protected entry point is never invoked and its admission is unchanged.
This primitive accepts caller-owned finite state; the separately frozen study
binds authentic inputs, runtime and limits. Two active generations are supported
only through time < 2*DELAY. No continuum or autograd claim is made.
"""

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from fractions import Fraction as F



CHANNELS = 5
INTERIOR = 255
DISCOUNT = 0.15
DELAY = F(1, 5)
WARM = tuple(F(value) for value in ("0", ".001", ".02", ".16", ".2", ".201", ".28", ".36"))
COARSE = (F(0), F(1, 5), F(9, 25))
COLD = (F(201, 1000), F(7, 25), F(9, 25))
INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
ROSTER_IDENTITY = "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2"
PHASE_SHA256 = "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548"


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
    reset: tuple

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
    actions: list = field(default_factory=list)


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
    sink = sparse.csr_matrix([prefix + tuple(upper_flow)], dtype="float64").T
    return sparse.bmat(
        ((core, sink), (None, sparse.csr_matrix((1, 1), dtype="float64"))),
        format="csr",
    )


def _action(matrix, initial, selectors, duration, discount, modules, counts):
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
    import time
    scaled = augmented.T.tocsr() * float(duration)
    if scaled.shape[0] > 514:
        raise ValueError("frozen matrix order cap")
    started, cpu = time.perf_counter(), time.process_time()
    evolved = expm_multiply(scaled, seeded.T, traceA=float(scaled.diagonal().sum())).T
    counts.actions.append({"order": scaled.shape[0], "nnz": scaled.nnz,
        "duration": str(duration), "discount": discount,
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "csr_bytes": scaled.data.nbytes + scaled.indices.nbytes + scaled.indptr.nbytes})
    if not np.isfinite(evolved).all():
        raise ValueError("nonfinite action")
    return evolved[:, : matrix.shape[0]], evolved[:, matrix.shape[0] :]


def _block_operator(parents, spatial, lower, primitive):
    """Snapshot-aware injection; parent coordinates are signal realizations."""
    dimension = INTERIOR + sum(parent.dimension for parent in parents)
    rows = [dict() for _ in range(dimension)]
    offset = 0
    for parent in parents:
        if len(parent.reset) != INTERIOR:
            raise ValueError("packet reset dimension")
        for row in range(parent.dimension):
            for index in range(parent.operator.indptr[row], parent.operator.indptr[row + 1]):
                rows[offset + row][offset + parent.operator.indices[index]] = parent.operator.data[index]
            for node, weight in enumerate(parent.reset):
                if parent.output[row] != 0 and weight != 0:
                    rows[offset + row][dimension - INTERIOR + node] = parent.output[row] * weight
        offset += parent.dimension
    for row in range(INTERIOR):
        for index in range(spatial.indptr[row], spatial.indptr[row + 1]):
            rows[offset + row][offset + spatial.indices[index]] = spatial.data[index]
    return primitive.CSR.from_rows(rows), (0.0,) * (dimension - INTERIOR) + tuple(lower)


def _phase_packet_alpha(item):
    """Map one authentic phase packet to five ambient FP64 amplitudes.

    The historical v1 source read a nonexistent ``content`` field.  This v2
    candidate accepts only the frozen ``signed_content`` schema and does not
    silently alias, normalize, or repair legacy records.
    """

    if set(item) != {"end", "identity", "mass", "signed_content", "start"}:
        raise ValueError("authentic phase packet field set")
    signed_content = item["signed_content"]
    if not isinstance(signed_content, list) or len(signed_content) != CHANNELS - 1:
        raise ValueError("authentic signed-content channel count")
    start, end = F(item["start"]), F(item["end"])
    width = end - start
    if width <= 0:
        raise ValueError("authentic phase packet width")
    return (float(F(item["mass"]) / width),) + tuple(
        float(F(value) / width) for value in signed_content
    )


def _initial_state(metadata, phase, arrays, primitive, bundle, reset, np):
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
        alpha = _phase_packet_alpha(item)
        source = primitive.source_identity(bundle, item["identity"], start, end, 1, 0, ())
        packets.append(Packet(source, 1, 1, 0, start, end, zero, alpha, (1.0,), tuple(reset)))
    return state, tuple(packets)


def _advance(state, pending, time, right, primitive, spatial, lower, upper_flow, reset, bundle, modules, counts):
    np, (sparse, _) = modules
    if not F(0) <= time < right < 2 * DELAY:
        raise ValueError("two-cycle interval must end before 2*delay")
    if len(pending) > 22:
        raise ValueError("frozen packet cap")
    releasing = tuple(packet for packet in pending if packet.start == time)
    fragments = {}
    emitted = []
    for origin, target in ((1, 2), (2, 3)):
        if origin == 2 and time < DELAY:
            continue
        parents = tuple(packet for packet in releasing if packet.target == origin)
        operator, output = _block_operator(parents, spatial, lower, primitive)
        blocks = [np.asarray(packet.alpha, dtype="float64").reshape(CHANNELS, packet.dimension) for packet in parents]
        blocks.append(state.active[:, origin - 1])
        alpha = np.concatenate(blocks, axis=1)
        matrix = _extended(operator, upper_flow, sparse)
        initial = np.concatenate((alpha, state.upper[:, origin, None]), axis=1)
        lower_selector = np.zeros((matrix.shape[0], 1), dtype="float64")
        lower_selector[-INTERIOR - 1 : -1, 0] = lower
        final, lower_contribution = _action(matrix, initial, lower_selector, right - time, 0.0, modules, counts)
        selectors = np.zeros((matrix.shape[0], 2), dtype="float64")
        selectors[-INTERIOR - 1 : -1, 0] = lower
        # Signal realizations in the parent prefix are not active cell mass.
        # With no parent, the first active node must be included too.
        selectors[-INTERIOR - 1 :, 1] = 1.0
        _, discounted = _action(matrix, initial, selectors, right - time, DISCOUNT, modules, counts)
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
                tuple(float(value) for value in reset),
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
