"""CSR action for one warm interval, assembled independently of the dense oracle.

Numerical imports are lazy. The authentic entry point checks the new warm-1
admission before loading its immutable input or importing numerical libraries.
No original full-roster candidate, protected advance, or dense solver is used.
"""

import hashlib
import json
import math
import time
from fractions import Fraction
from pathlib import Path

from qualification.hcsn_currentstate_n256_firststep_serializer_v2 import serializer as wire
from qualification.hcsn_currentstate_n256_independent_oracle_v2_intent import adapter


RIGHT = Fraction(1, 1000)
DELAY = Fraction(1, 5)
DISCOUNT = 0.15
CAPSULE = "af3119de18a4f2f9049fd4f33c2331448237cb1c90810f6cdf2f2bedaa5bf7c1"
COUNTS = {"state": 2600, "packet_alpha": 1320, "packet_generator": 65544,
          "packet_output": 264, "packet": 67128, "total": 69728}


def source_id(kind, start, end, target, origin, parents=()):
    record = {"bundle": adapter.INPUT_BUNDLE_SHA256, "kind": kind,
              "start": [start.numerator, start.denominator],
              "end": [end.numerator, end.denominator], "target": target,
              "origin": origin, "parents": sorted(parents)}
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def calculate(nodes, active, upper, parent, mu, sigma, reset_position,
              duration, discount):
    """Two exponential actions, including signed channels and upper occupation.

This primitive also supports tiny synthetic controls. It returns the emitted
packet's *initial* alpha and generator, preserving its future output function.
There is no positivity clipping and no dense exponential fallback.
"""
    import numpy as np
    from scipy.sparse import bmat, csr_matrix, diags, eye
    from scipy.sparse.linalg import expm_multiply

    nodes = np.asarray(nodes, dtype="float64")
    n = len(nodes) - 2
    gaps = np.diff(nodes)
    if not 2 <= n <= 255 or np.any(gaps <= 0) or not np.isfinite(nodes).all():
        raise ValueError("bounded strict node geometry")
    if duration <= 0 or discount <= 0 or sigma <= 0:
        raise ValueError("positive interval, discount, and diffusion required")
    active, upper, parent = (np.asarray(x, dtype="float64") for x in (active, upper, parent))
    if active.ndim != 2 or active.shape[1] != n or upper.shape != parent.shape or upper.shape != (len(active),):
        raise ValueError("channel layout")
    if not all(np.isfinite(x).all() for x in (active, upper, parent)):
        raise ValueError("finite input")
    down = (sigma**2 - mu * gaps[1:]) / (gaps[:-1] * (gaps[:-1] + gaps[1:]))
    up = (sigma**2 + mu * gaps[:-1]) / (gaps[1:] * (gaps[:-1] + gaps[1:]))
    if np.any(down < 0) or np.any(up < 0):
        raise ValueError("negative CTMC transition rate")
    q = diags((down[1:], -(down + up), up[:-1]), (-1, 0, 1), format="csr")
    j = int(np.searchsorted(nodes, reset_position, side="right"))
    if not 2 <= j <= n:
        raise ValueError("interior reset support")
    theta = (reset_position - nodes[j - 1]) / (nodes[j] - nodes[j - 1])
    reset = csr_matrix(([1 - theta, theta], ([0, 0], [j - 2, j - 1])), shape=(1, n))
    generator = bmat([[csr_matrix((1, 1)), reset], [csr_matrix((n, 1)), q]], format="csr")
    escape = csr_matrix(([up[-1]], ([n], [0])), shape=(n + 1, 1))
    extended = bmat([[generator, escape], [csr_matrix((1, n + 1)), csr_matrix((1, 1))]], format="csr")
    lower = np.zeros(n + 2)
    lower[1] = down[0]
    occupation = np.ones(n + 2)
    occupation[0] = 0.0
    alpha = np.column_stack((parent, active))
    initial = np.column_stack((alpha, np.zeros(len(active))))
    actions = []

    def action(selectors, rate):
        selectors = np.asarray(selectors).T
        outputs = selectors.shape[1]
        augmented = bmat([[extended - rate * eye(n + 2, format="csr"), csr_matrix(selectors)],
                          [csr_matrix((outputs, n + 2)), csr_matrix((outputs, outputs))]], format="csr")
        scaled = augmented.T.tocsr() * duration
        seed = np.column_stack((initial, np.zeros((len(active), outputs))))
        wall, cpu = time.perf_counter(), time.process_time()
        evolved = expm_multiply(scaled, seed.T, traceA=float(scaled.diagonal().sum())).T
        actions.append({"order": scaled.shape[0], "nnz": scaled.nnz,
                        "csr_bytes": scaled.data.nbytes + scaled.indices.nbytes + scaled.indptr.nbytes,
                        "wall_seconds": time.perf_counter() - wall,
                        "cpu_seconds": time.process_time() - cpu})
        if not np.isfinite(evolved).all():
            raise ValueError("nonfinite sparse result")
        return evolved[:, :n + 2], evolved[:, n + 2:]

    final, hit = action([lower], 0.0)
    _, discounted = action([lower, occupation], discount)
    state = {"active": np.zeros((len(active), 2, n)), "upper": np.zeros((len(active), 3)),
             "mass": np.zeros((len(active), 2)), "discounted_hit": np.zeros((len(active), 2)),
             "occupation": np.zeros((len(active), 3))}
    state["active"][:, 0] = final[:, 1:-1]
    state["upper"][:, 0], state["upper"][:, 1] = upper, final[:, -1]
    state["mass"][:, 0], state["discounted_hit"][:, 0] = hit[:, 0], discounted[:, 0]
    state["occupation"][:, 0] = upper * (-math.expm1(-discount * duration) / discount)
    state["occupation"][:, 1] = discounted[:, 1]
    balances = [math.fsum(final[c, 1:]) + hit[c, 0] - math.fsum(active[c]) - parent[c] * duration
                for c in range(len(active))]
    return state, generator, alpha, lower[:-1], final[:, :1], actions, balances


def run_warm1(root, admission_path, output_path):
    from qualification.hcsn_currentstate_n256_warm1_sparse.runner import verify_child

    verify_child(admission_path)
    import numpy as np

    root = Path(root)
    authentic = adapter.load_authentic_input(root)
    metadata = json.loads((root / adapter.RELATIVE["metadata"]).read_text())
    nodes = np.frombuffer(authentic.nodes_payload, dtype="<f8")
    initial = np.column_stack((np.frombuffer(authentic.active_payload, dtype="<f8"),
                               np.frombuffer(authentic.signed_content_payload, dtype="<f8").reshape(257, 4))).T
    releasing = [packet for packet in authentic.phase_packets if packet[1] == 0 and packet[2] >= RIGHT]
    if len(releasing) != 1 or len(nodes) != 257 or metadata["physics"]["discount"] != DISCOUNT:
        raise ValueError("frozen warm-1 scope")
    source, start, end, rates = releasing[0]
    parent = np.asarray([float(x) for x in rates])
    state, generator, alpha, output, residual, actions, balances = calculate(
        nodes, initial[:, 1:-1], initial[:, -1], parent, metadata["physics"]["mu"],
        metadata["physics"]["sigma"], metadata["reset_distance"], float(RIGHT), DISCOUNT)

    def tensor(values):
        values = np.asarray(values, dtype="<f8", order="C")
        return wire.Tensor("<f8", values.shape, values.tobytes(order="C"))

    def fraction(value):
        return f"{value.numerator}/{value.denominator}"

    packets = []
    for identity, begin, finish, rates in authentic.phase_packets:
        packet_alpha = residual if begin == 0 else np.asarray([float(x) for x in rates])[:, None]
        packets.append(wire.Packet(source_id(identity, begin, finish, 1, 0), 1, 0, 1,
                                   fraction(RIGHT if begin == 0 else begin), fraction(finish),
                                   tensor(packet_alpha), tensor(np.zeros((1, 1))), tensor(np.ones(1))))
    identity = source_id("lower-flux", Fraction(0), RIGHT, 2, 1, (source_id(source, start, end, 1, 0),))
    packets.append(wire.Packet(identity, 2, 1, 2, fraction(DELAY), fraction(DELAY + RIGHT),
                               tensor(alpha), tensor(generator.toarray()), tensor(output)))
    envelope = wire.Envelope({"capsule_identity": CAPSULE, "input_bundle_sha256": adapter.INPUT_BUNDLE_SHA256,
                              "lane": "warm", "lane_order": 1, "time": "1/1000"},
                             tuple(wire.Block(name, tensor(value)) for name, value in sorted(state.items())),
                             tuple(sorted(packets, key=lambda x: x.identity)))
    if wire.coordinate_counts(envelope) != COUNTS or len(packets) != 9:
        raise ValueError("complete warm-1 coordinate denominator")
    return {"payload_sha256": wire.publish_atomic(output_path, envelope), "dynamic_steps": 1,
            "sparse_exponential_actions": len(actions), "dense_expm_actions": 0,
            "authentic_input_loads": 1, "actions": actions, "channel_balance_residuals": balances,
            "probability_active_minimum": float(state["active"][0].min()),
            "serialized_bytes": Path(output_path).stat().st_size, "packet_count": len(packets),
            "coordinate_counts": COUNTS, "torch_calls": 0, "optimizer_steps": 0,
            "full_roster_qualification": False, "largegrid_qualification": False, "all_closed": False}
