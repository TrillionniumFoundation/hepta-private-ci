"""Portable numerical DDE state; preserves flux history, never replays time zero.

Newton coefficients are exported from SciPy BDF dense polynomials, projected
onto lower-hit flux. Their evaluator is independent of SciPy object pickling.
The hash binds bytes and exact local operator sources, not external authority.
"""

from dataclasses import asdict
import hashlib
import inspect
import json
from pathlib import Path

import numpy as np


def _canonical(value):
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def _binding(model):
    root = Path(__file__).resolve().parents[2]
    paths = ["hcsn_joint_dde/model.py", "hcsn_joint_dde/state_io.py",
             "hcsn_boundary_audit/spatial_generator.py",
             "hcsn_boundary_audit/refractory_transport.py"]
    for cls in (type(model), type(model.spatial)):
        source = Path(inspect.getfile(cls)).resolve().relative_to(root / "qualification")
        paths.append(str(source))
    return {"physics": json.loads(_canonical(asdict(model))),
            "types": [cls.__module__ + "." + cls.__qualname__ for cls in (type(model), type(model.spatial))],
            "sources": {
        name: hashlib.sha256((root / "qualification" / name).read_bytes()).hexdigest()
        for name in paths}}


def flux_pieces(solution, channels, size, lower):
    """Export the actual accepted BDF step polynomials, without resampling."""
    pieces = []
    for dense in solution.interpolants:
        order = dense.order
        if not 1 <= order <= 5:
            raise ArithmeticError("unsupported BDF dense polynomial order")
        coefficients = dense.D.reshape(order + 1, channels, size)[..., :len(lower)] @ lower
        pieces.append({"left": float(dense.t_old), "right": float(dense.t),
                       "shift": dense.t_shift.tolist(), "denom": dense.denom.tolist(),
                       "coefficients": coefficients.tolist()})
    return pieces


def evaluate_flux(piece, time):
    products = np.cumprod((time - np.asarray(piece["shift"])) / piece["denom"])
    coefficients = np.asarray(piece["coefficients"])
    return coefficients[0] + products @ coefficients[1:]


def encode_state(model, *, time, state, history, uniform, atoms, source_knots,
                 initial_totals, internal_steps):
    """Serialize the post-release state and only the required recent history."""
    payload = {"schema": "hcsn-dde-state-v1", "binding": _binding(model),
               "time": float(time), "state": np.asarray(state).tolist(),
               "history": [p for p in history if p["right"] > time - model.delay],
               "uniform": [[lo, hi, value.tolist()] for lo, hi, value in uniform if hi > time],
               "atoms": [[at, value.tolist()] for at, value in sorted(atoms.items()) if at > time],
               "source_knots": sorted(set(source_knots)),
               "initial_totals": np.asarray(initial_totals).tolist(),
               "internal_steps": internal_steps}
    raw = _canonical(payload)
    envelope = _canonical({"sha256": hashlib.sha256(raw).hexdigest(), "payload": payload})
    # Decode our own output through the same bounded validation as cold restore.
    decode_state(model, envelope)
    return envelope


def decode_state(model, raw):
    """Reject changed physics/source, omitted history, malformed or huge state."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 16 * 1024 * 1024:
        raise ValueError("bounded checkpoint bytes required")

    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate checkpoint key")
            result[key] = value
        return result

    envelope = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(envelope, dict) or set(envelope) != {"sha256", "payload"}:
        raise ValueError("checkpoint envelope mismatch")
    payload = envelope["payload"]
    if hashlib.sha256(_canonical(payload)).hexdigest() != envelope["sha256"]:
        raise ValueError("checkpoint digest mismatch")
    if (not isinstance(payload, dict) or payload.get("schema") != "hcsn-dde-state-v1" or payload.get("binding") != _binding(model)
            or set(payload) != {"schema", "binding", "time", "state", "history", "uniform",
                               "atoms", "source_knots", "initial_totals", "internal_steps"}):
        raise ValueError("checkpoint schema or exact operator binding mismatch")
    time = payload["time"]
    state = np.asarray(payload["state"], dtype=float)
    size = model.spatial.intervals - 1 + 6
    if (type(time) not in (int, float) or not 0 <= time <= 8
            or state.ndim != 2 or not 2 <= state.shape[0] <= 17 or state.shape[1] != size
            or not np.isfinite(state).all() or min(state[0, :size-4]) < -1e-8
            or type(payload["internal_steps"]) is not int or not 0 <= payload["internal_steps"] <= 10**7):
        raise ValueError("invalid checkpoint clock, state or step count")
    channels = len(state)
    totals = np.asarray(payload["initial_totals"], dtype=float)
    if (totals.shape != (channels,) or not np.isfinite(totals).all()
            or not np.allclose(state[:, :size-4].sum(1), totals, rtol=1e-7, atol=1e-8)):
        raise ValueError("checkpoint conservation mismatch")
    history = payload["history"]
    if not isinstance(history, list) or len(history) > 65536:
        raise ValueError("checkpoint history budget exceeded")
    previous = None
    for piece in history:
        if set(piece) != {"left", "right", "shift", "denom", "coefficients"}:
            raise ValueError("invalid history polynomial fields")
        lo, hi = piece["left"], piece["right"]
        shifts, denominators = np.asarray(piece["shift"]), np.asarray(piece["denom"])
        coefficients = np.asarray(piece["coefficients"])
        order = len(shifts)
        if (not 0 <= lo < hi <= time or (previous is not None and lo != previous)
                or shifts.shape != (order,) or not 1 <= order <= 5
                or denominators.shape != (order,) or np.any(denominators <= 0)
                or coefficients.shape != (order+1, channels)
                or not all(np.isfinite(a).all() for a in (shifts, denominators, coefficients))):
            raise ValueError("history polynomial or continuity mismatch")
        previous = hi
    if time > 0 and (not history or history[0]["left"] > max(0, time-model.delay)
                     or previous != time):
        raise ValueError("required delay history is absent")
    for key in ("uniform", "atoms", "source_knots"):
        if not isinstance(payload[key], list) or len(payload[key]) > 8193:
            raise ValueError("checkpoint source budget exceeded")
    for lo, hi, vector in payload["uniform"]:
        if not 0 <= lo < hi <= model.delay or hi <= time or len(vector) != channels:
            raise ValueError("invalid remaining initial uniform source")
        if not np.isfinite(vector).all() or vector[0] < 0:
            raise ValueError("nonfinite uniform source")
    for at, vector in payload["atoms"]:
        if not time < at <= model.delay or len(vector) != channels or not np.isfinite(vector).all() or vector[0] < 0:
            raise ValueError("invalid remaining atom source")
    atom_times = [at for at, _ in payload["atoms"]]
    if atom_times != sorted(set(atom_times)):
        raise ValueError("atom deadlines must be strictly increasing")
    knots = payload["source_knots"]
    if (not knots or knots != sorted(set(knots)) or knots[0] != 0
            or not np.isfinite(knots).all() or knots[-1] > model.delay):
        raise ValueError("invalid source discontinuity schedule")
    required_knots = {at for at, _ in payload["atoms"]}
    required_knots.update(x for lo, hi, _ in payload["uniform"] for x in (lo, hi))
    if not required_knots.issubset(knots):
        raise ValueError("pending source deadline absent from discontinuity schedule")
    # A mass total and one age moment do not authenticate the pending release
    # law. Reconstruct both from actual recent flux plus unreleased originals.
    pending, discounted = np.zeros(channels), np.zeros(channels)
    for lo, hi, vector in payload["uniform"]:
        left = max(time, lo)
        vector = np.asarray(vector)
        pending += (hi-left) * vector
        discounted += np.exp(-model.discount*(left-time)) * -np.expm1(-model.discount*(hi-left)) / model.discount * vector
    for at, vector in payload["atoms"]:
        pending += vector
        discounted += np.exp(-model.discount*(at-time)) * np.asarray(vector)
    nodes, weights = np.polynomial.legendre.leggauss(16)
    for piece in history:
        lo, hi = max(0, time-model.delay, piece["left"]), piece["right"]
        if hi <= lo:
            continue
        for node, weight in zip(nodes, weights):
            at = (lo+hi)/2 + (hi-lo)*node/2
            flow = weight*(hi-lo)/2 * evaluate_flux(piece, at)
            pending += flow
            discounted += np.exp(-model.discount*(model.delay+at-time)) * flow
    if (not np.allclose(pending, state[:, size-5], rtol=1e-7, atol=1e-8)
            or not np.allclose(discounted, state[:, size-1], rtol=1e-7, atol=1e-8)):
        raise ValueError("pending phase mass/moment do not match retained release law")
    return payload
