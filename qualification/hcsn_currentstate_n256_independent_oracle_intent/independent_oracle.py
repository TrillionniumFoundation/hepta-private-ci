"""Independent streaming N256 oracle source, frozen without numerical execution.

This implementation shares no Python imports with the sparse candidate. It
reconstructs row-vector birth/death/reset dynamics, delayed lower-hit release,
permanent upper escape, discounted hit, and occupation coordinates from the
authentic input bundle. NumPy and SciPy load only after exact admission.
"""

import hashlib
import json
import math
import zipfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from qualification.hcsn_currentstate_n256_independent_oracle_intent.admission import require_admission

INTERIOR = 255
CHANNELS = 5
DELAY = Fraction(1, 5)
DISCOUNT = 0.15
INPUT_BUNDLE_SHA256 = "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95"
ROSTER_IDENTITY = "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2"
WARM_TIMES = tuple(Fraction(value) for value in ("0", ".001", ".02", ".16", ".2", ".201", ".28", ".36"))
COARSE_TIMES = (Fraction(0), Fraction(1, 5), Fraction(9, 25))
COLD_TIMES = (Fraction(201, 1000), Fraction(7, 25), Fraction(9, 25))


@dataclass(frozen=True)
class OraclePacket:
    identity: str
    generation: int
    origin: int
    target: int
    start: Fraction
    end: Fraction
    operator: object
    alpha: object


@dataclass
class OracleState:
    active: object
    escaped_upper: object
    lower_hit: object
    discounted_hit: object
    occupation: object

    def clone(self):
        return OracleState(self.active.copy(), self.escaped_upper.copy(), self.lower_hit.copy(), self.discounted_hit.copy(), self.occupation.copy())


@dataclass
class OracleCounts:
    numerical_imports: int = 0
    matrix_actions: int = 0
    segments: int = 0
    oracle_runs: int = 0
    serialized_coordinates: int = 0


def _numeric_modules():
    import numpy as np
    from scipy import sparse
    from scipy.sparse.linalg import expm_multiply

    return np, sparse, expm_multiply


def _bundle_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_bundle(path, np):
    members = {}
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if name.endswith(".json"):
                members[name] = json.loads(archive.read(name))
            elif name.endswith(".npy"):
                with archive.open(name) as stream:
                    members[name] = np.load(stream, allow_pickle=False)
    return members


def _birth_death_operator(nodes, drift, volatility, reset_rate, reset_target, sparse, np):
    nodes = np.asarray(nodes, dtype="float64")
    if nodes.shape != (INTERIOR + 2,) or not np.all(np.diff(nodes) > 0):
        raise ValueError("N256 node geometry")
    rows, columns, values = [], [], []
    lower_flow = np.zeros(INTERIOR, dtype="float64")
    upper_flow = np.zeros(INTERIOR, dtype="float64")
    reset_index = int(np.argmin(np.abs(nodes[1:-1] - reset_target)))
    variance = volatility * volatility
    for index in range(INTERIOR):
        left = nodes[index + 1] - nodes[index]
        right = nodes[index + 2] - nodes[index + 1]
        left_rate = max(0.0, variance / (left * (left + right)) - drift / (left + right))
        right_rate = max(0.0, variance / (right * (left + right)) + drift / (left + right))
        rows.append(index); columns.append(index); values.append(-(left_rate + right_rate + reset_rate))
        if index:
            rows.append(index); columns.append(index - 1); values.append(left_rate)
        else:
            lower_flow[index] = left_rate
        if index + 1 < INTERIOR:
            rows.append(index); columns.append(index + 1); values.append(right_rate)
        else:
            upper_flow[index] = right_rate
        rows.append(index); columns.append(reset_index); values.append(reset_rate)
    matrix = sparse.csr_matrix((values, (rows, columns)), shape=(INTERIOR, INTERIOR), dtype="float64")
    return matrix, lower_flow, upper_flow


def _extended_generator(core, upper_flow, sparse, np):
    sink = sparse.csr_matrix(np.asarray(upper_flow, dtype="float64")[:, None])
    return sparse.bmat(((core, sink), (None, sparse.csr_matrix((1, 1)))), format="csr")


def _stream_action(generator, initial, selectors, duration, discount, sparse, expm_multiply, np):
    outputs = selectors.shape[1]
    shifted = generator - discount * sparse.eye(generator.shape[0], format="csr")
    augmented = sparse.bmat(((shifted, sparse.csr_matrix(selectors)), (None, sparse.csr_matrix((outputs, outputs)))), format="csr")
    seed = np.concatenate((initial, np.zeros((initial.shape[0], outputs))), axis=1)
    evolved = expm_multiply((augmented.T * float(duration)), seed.T).T
    return evolved[:, : generator.shape[0]], evolved[:, generator.shape[0] :]


def _seed_state(active, content, np):
    active = np.asarray(active, dtype="float64")
    content = np.asarray(content, dtype="float64").reshape(INTERIOR + 2, CHANNELS - 1)
    state = np.zeros((CHANNELS, 2, INTERIOR), dtype="float64")
    state[:, 0] = np.column_stack((active[1:-1], content[1:-1])).T
    escaped = np.zeros((CHANNELS, 3), dtype="float64")
    escaped[:, 0] = np.r_[active[-1], content[-1]]
    return OracleState(state, escaped, np.zeros((CHANNELS, 2)), np.zeros((CHANNELS, 2)), np.zeros((CHANNELS, 3)))


def _advance_segment(state, left, right, generator, lower_flow, upper_flow, modules, counts):
    np, sparse, expm_multiply = modules
    extended = _extended_generator(generator, upper_flow, sparse, np)
    lower_selector = np.zeros((INTERIOR + 1, 1), dtype="float64")
    lower_selector[:INTERIOR, 0] = lower_flow
    selectors = np.zeros((INTERIOR + 1, 2), dtype="float64")
    selectors[:INTERIOR, 0] = lower_flow
    selectors[:, 1] = 1.0
    for phase in range(2):
        initial = np.concatenate((state.active[:, phase], state.escaped_upper[:, phase + 1, None]), axis=1)
        final, hit = _stream_action(extended, initial, lower_selector, right - left, 0.0, sparse, expm_multiply, np)
        _, discounted = _stream_action(extended, initial, selectors, right - left, DISCOUNT, sparse, expm_multiply, np)
        state.active[:, phase] = final[:, :INTERIOR]
        state.escaped_upper[:, phase + 1] = final[:, INTERIOR]
        state.lower_hit[:, phase] += hit[:, 0]
        factor = math.exp(-DISCOUNT * float(left))
        state.discounted_hit[:, phase] += factor * discounted[:, 0]
        state.occupation[:, phase + 1] += factor * discounted[:, 1]
        counts.matrix_actions += 2
    counts.segments += 1


def _coordinate_stream(lane, time, state):
    for block, values in (("active", state.active), ("escaped_upper", state.escaped_upper), ("lower_hit", state.lower_hit), ("discounted_hit", state.discounted_hit), ("occupation", state.occupation)):
        for index, value in enumerate(values.ravel(order="C")):
            yield {"lane": lane, "time": str(time), "block": block, "index": index, "value_hex": float(value).hex()}


def _run_lane(lane, times, initial, generator, lower_flow, upper_flow, modules, counts):
    state = initial.clone()
    previous = times[0]
    for time in times:
        if time > previous:
            _advance_segment(state, previous, time, generator, lower_flow, upper_flow, modules, counts)
        yield from _coordinate_stream(lane, time, state)
        previous = time


def run_oracle(bundle_path, request_path, admission_path, output_path):
    require_admission(request_path, admission_path)
    if _bundle_sha256(bundle_path) != INPUT_BUNDLE_SHA256:
        raise ValueError("authentic input bundle SHA-256 mismatch")
    np, sparse, expm_multiply = _numeric_modules()
    counts = OracleCounts(numerical_imports=2, oracle_runs=1)
    members = _read_bundle(bundle_path, np)
    manifest = members["MANIFEST.json"]
    state = _seed_state(members[manifest["active_member"]], members[manifest["content_member"]], np)
    generator, lower_flow, upper_flow = _birth_death_operator(members[manifest["nodes_member"]], float(manifest["drift"]), float(manifest["volatility"]), float(manifest["reset_rate"]), float(manifest["reset_target"]), sparse, np)
    modules = np, sparse, expm_multiply
    with Path(output_path).open("w") as stream:
        for lane, times in (("warm", WARM_TIMES), ("coarse", COARSE_TIMES), ("cold", COLD_TIMES)):
            for row in _run_lane(lane, times, state, generator, lower_flow, upper_flow, modules, counts):
                stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
                counts.serialized_coordinates += 1
    return counts
