"""Four continuation heads on actual v6 states; STOP is the zero reference.

Labels use the same parent state and a declared, fixed suffix. For gamma > 0
they are exp(-gamma R_STOP) - exp(-gamma R_action), NOT CE differences. A
positive conditional mean has the direction of entropic improvement. gamma=0
is a separately identified mean-return objective. No optimal Q is claimed.
Inference never receives Target or a scorer. These heads require a separate
cost/quality admission gate; fitting or passing the support check grants none.
"""

from collections import Counter
from copy import deepcopy
from dataclasses import astuple, dataclass
import hashlib
import json
import math
from pathlib import Path
import time

import torch

from .conditioned import ConditionedSnapshot
from .data import Observation, VOCAB
from .forecast import ForecastBackend, RidgeHead
from .neural import ACTIONS, NeuralSnapshot, NeuralState
from .observer import METRIC_DIGEST
from .plan_training import ControlledSnapshot, ControlledState


SCHEMA = "hepta.ndu-v6.continuation-head.v1"
PAIR_SCHEMA = "hepta.ndu-v6.continuation-pair.v1"
FEATURE_SCHEMA = "h,image,text,context;plan[-1,0,1,2,3];resources.v1"
RESOURCE_FIELDS = ("remaining_work", "stop_reserve", "step_index", "steps_remaining",
                   "elapsed_seconds", "spent_cost", "resident_bytes",
                   "observation_version", "reuse_count")


def _digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _sha(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Expected a lowercase SHA-256 identity")
    return value


@dataclass(frozen=True)
class DecisionContext:
    remaining_work: float
    stop_reserve: float
    step_index: int
    steps_remaining: int
    elapsed_seconds: float = 0.0
    spent_cost: float = 0.0
    resident_bytes: int = 0
    observation_version: int = 0
    reuse_count: int = 0

    def __post_init__(self):
        for name, value in zip(RESOURCE_FIELDS, astuple(self)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("Invalid nonnegative public resource context")
            if name in RESOURCE_FIELDS[2:4] + RESOURCE_FIELDS[6:] and type(value) is not int:
                raise ValueError("Public counters must be integers")
        if self.stop_reserve > self.remaining_work:
            raise ValueError("Remaining work must preserve delivery reserve")


def snapshot_binding(snapshot):
    """Also bind legacy configuration, which its parameter digest omits."""
    if type(snapshot) not in (NeuralSnapshot, ConditionedSnapshot, ControlledSnapshot):
        raise TypeError("Unsupported v6 snapshot")
    snapshot.verify_integrity()
    base = snapshot._base if type(snapshot) is ControlledSnapshot else snapshot
    if type(base) not in (NeuralSnapshot, ConditionedSnapshot):
        raise TypeError("Unsupported controlled base")
    if (base.config != base._model.config or base._model.hidden != base.config["hidden"]
            or base._model.noise_scale != base.config["noise_scale"]):
        raise RuntimeError("Frozen base configuration changed")
    return _digest({"type": type(snapshot).__name__, "snapshot": snapshot.fingerprint,
                    "base": base.fingerprint, "config": snapshot.config})


def validate_observation(observation, required_modalities=("text", "image")):
    """Reject unsupported syntax/profile; this is not semantic OOD detection."""
    if type(observation) is not Observation or tuple(required_modalities) != ("text", "image"):
        raise ValueError("Only the declared public text/image observation is supported")
    p, m, t = observation.pixels, observation.mask, observation.text_tokens
    if (any(not isinstance(x, torch.Tensor) or x.device.type != "cpu" for x in (p, m, t))
            or p.shape != (1, 1, 28, 56) or m.shape != p.shape or t.shape != (1, 8)
            or p.dtype != torch.float32 or m.dtype != torch.float32 or t.dtype != torch.long
            or not torch.isfinite(p).all() or not torch.isfinite(m).all()
            or p.min() < 0 or p.max() > 1 or not ((m == 0) | (m == 1)).all()
            or ((p != 0) & (m == 0)).any()):
        raise ValueError("Unsupported or nonfinite public observation")
    ids = t[0].tolist()
    if (ids[0] != 1 or ids[1] not in (9, 10) or ids[2] != 12 or ids[4] != 13
            or ids[6:] != [2, 0] or any(i != 11 and not 14 <= i < len(VOCAB) for i in (ids[3], ids[5]))):
        raise ValueError("Unknown public command or hint token grammar")


@torch.inference_mode()
def encoder_only(snapshot, observation, noise_seed=0):
    """Return (base, state) with zero transitions, bypassing the two-step plan.

    The returned base identity is explicit; the state is never relabeled as a
    ControlledState. Encoding, decoding and delivery still require metering.
    """
    validate_observation(observation)
    if type(noise_seed) is not int or noise_seed < 0:
        raise ValueError("An explicit nonnegative encoding seed is required")
    before = snapshot_binding(snapshot)
    base = snapshot._base if type(snapshot) is ControlledSnapshot else snapshot
    state = base.encode(observation, noise_seed=noise_seed)
    if snapshot_binding(snapshot) != before:
        raise RuntimeError("Snapshot changed during encoding")
    return base, state


@torch.inference_mode()
def public_features(snapshot, state, context):
    if type(context) is not DecisionContext:
        raise TypeError("An explicit public DecisionContext is required")
    snapshot_binding(snapshot)
    snapshot.state_features(state)  # Existing foreign-state admission checks.
    controlled = type(snapshot) is ControlledSnapshot
    if type(state) is not (ControlledState if controlled else NeuralState):
        raise TypeError("Unsupported state type")
    neural = state.neural if controlled else state
    blocks = [getattr(neural, name) for name in ("h", "image", "text", "context")]
    if any(x.shape != (1, snapshot.config["hidden"]) or x.device.type != "cpu"
           or not x.is_floating_point() or not torch.isfinite(x).all() for x in blocks):
        raise ValueError("Incomplete, batched or nonfinite public state")
    plan = torch.zeros(1, 5, dtype=torch.float64)
    if controlled:
        if context.step_index < snapshot.initial_plan_cost:
            raise ValueError("Controlled initialization already executed two transitions")
        plan[0, state.plan_indices[0] + 1] = 1
    resources = torch.tensor([astuple(context)], dtype=torch.float64)
    return torch.cat([x.detach().double() for x in blocks] + [plan, resources], dim=1)


def _contract(suffix, cost_profile_digest, gamma, return_bounds):
    suffix = tuple(suffix)
    if len(suffix) > 4 or any(a not in ACTIONS for a in suffix):
        raise ValueError("Unknown or unbounded fixed suffix")
    if (isinstance(gamma, bool) or not math.isfinite(gamma) or gamma < 0
            or len(return_bounds) != 2 or not all(math.isfinite(v) for v in return_bounds)
            or not return_bounds[0] < return_bounds[1]
            or not math.isfinite(return_bounds[1] - return_bounds[0])
            or gamma * max(abs(v) for v in return_bounds) > 80):
        raise ValueError("Invalid risk/return bounds; clipping is not permitted")
    return {"suffix": list(suffix), "cost_profile_digest": _sha(cost_profile_digest),
            "gamma": float(gamma), "return_bounds": list(return_bounds),
            "target": "mean_return_difference" if gamma == 0 else "exponential_moment_improvement"}


def paired_record(backend, state, context, *, source_ids, suffix, cost_profile_digest,
                  evaluate, pair_seed=0, gamma=2.0, return_bounds=(-4.0, 1.0)):
    """Offline same-prefix continuations through the real ForecastBackend.

    evaluate(state, path, seed, transition_measurement) must actually decode and
    score outputs, returning utility, actual_cost and output_sha256. Its cost
    includes the measured transitions and all subsequent work under the bound
    profile, excluding common sunk prefix cost. Only this offline API sees the
    evaluator. Outer collection work is separately retained, not called free.
    """
    if not isinstance(backend, ForecastBackend) or type(pair_seed) is not int or pair_seed < 0:
        raise ValueError("A real v6 backend and explicit paired randomness are required")
    contract = _contract(suffix, cost_profile_digest, gamma, return_bounds)
    pixels = tuple(sorted(_sha(s.rsplit(":", 1)[-1]) for s in source_ids))
    if len(pixels) != 2 or len(set(pixels)) != 2:
        raise ValueError("Two distinct original source pixel identities required")
    if context.steps_remaining < len(suffix) + 1:
        raise ValueError("Fixed continuation exceeds remaining decision horizon")
    wall, cpu = time.perf_counter(), time.process_time()
    binding, origin = snapshot_binding(backend.snapshot), backend.state_key(state)
    identity = backend.identity(state)
    features = public_features(backend.snapshot, state, context)[0].tolist()
    outcomes = []
    for first in (None, *ACTIONS):
        path = () if first is None else (first, *suffix)
        candidate, work = state, context.remaining_work - context.stop_reserve
        start_wall, start_cpu = time.perf_counter(), time.process_time()
        for action in path:
            charge = float(backend.action_cost(candidate, action))
            if not math.isfinite(charge) or charge <= 0 or charge > work:
                raise ValueError("Paired path exceeds the declared work envelope")
            work -= charge
            candidate = backend.transition(candidate, action)
        measurement = {"transition_cpu_seconds": time.process_time() - start_cpu,
                       "transition_wall_seconds": time.perf_counter() - start_wall}
        key = backend.state_key(candidate)
        outcome = dict(evaluate(candidate, path, pair_seed, dict(measurement)))
        utility, cost = float(outcome["utility"]), float(outcome["actual_cost"])
        result = utility - cost
        if (not math.isfinite(utility) or not math.isfinite(cost) or cost < 0
                or not return_bounds[0] <= result <= return_bounds[1]):
            raise ValueError("Actual return is outside the frozen declared support")
        if (backend.state_key(candidate) != key or backend.state_key(state) != origin
                or backend.identity(state) != identity or snapshot_binding(backend.snapshot) != binding):
            raise RuntimeError("Scoring/continuation mutated a frozen parent or model")
        outcomes.append({"path": list(path), "net_return": result, "utility": utility,
                         "actual_cost": cost, "output_sha256": _sha(outcome["output_sha256"]),
                         **measurement})
    record = {"schema": PAIR_SCHEMA, "snapshot_digest": backend.snapshot.fingerprint,
              "snapshot_binding": binding, "metric_digest": METRIC_DIGEST, **contract,
              "source_pixels": list(pixels), "parent_state": origin, "pair_seed": pair_seed,
              "features": features, "outcomes": outcomes,
              "collection_cpu_seconds": time.process_time() - cpu,
              "collection_wall_seconds": time.perf_counter() - wall}
    return {**record, "sha256": _digest(record)}


class ContinuationHead:
    """Data-only ridge head; identity and empirical support fail closed."""

    def __init__(self, record):
        payload = deepcopy(record)
        expected = payload.pop("sha256")
        if _digest(payload) != expected or payload.get("schema") != SCHEMA or payload.get("actions") != list(ACTIONS):
            raise ValueError("Continuation artifact identity/schema mismatch")
        if payload.get("feature_schema") != FEATURE_SCHEMA or payload.get("metric_digest") != METRIC_DIGEST:
            raise ValueError("Unsupported feature/metric contract")
        contract = _contract(payload["suffix"], payload["cost_profile_digest"], payload["gamma"], payload["return_bounds"])
        if any(payload[k] != v for k, v in contract.items()):
            raise ValueError("Unsupported continuation objective")
        n = len(payload["mean"])
        self._head = RidgeHead(n, len(ACTIONS))
        for name in ("mean", "scale", "weight"):
            tensor = torch.tensor(payload.pop(name), dtype=torch.float64)
            if tensor.shape != getattr(self._head, name).shape or not torch.isfinite(tensor).all():
                raise ValueError("Invalid continuation head dimensions or values")
            getattr(self._head, name).copy_(tensor)
        if (n < 78 or (n - 14) % 4 or (self._head.scale <= 0).any()
                or len(payload["support_min"]) != n or len(payload["support_max"]) != n
                or any(not math.isfinite(a) or not math.isfinite(b) or a > b
                       for a, b in zip(payload["support_min"], payload["support_max"]))):
            raise ValueError("Invalid scaling or state coverage support")
        for key in ("snapshot_digest", "snapshot_binding", "fit_input_sha256"):
            _sha(payload[key])
        self._metadata, self.fingerprint = payload, expected
        self._head.requires_grad_(False).eval()

    def to_record(self):
        record = {**deepcopy(self._metadata), **{name: getattr(self._head, name).tolist()
                  for name in ("mean", "scale", "weight")}}
        if _digest(record) != self.fingerprint:
            raise RuntimeError("Frozen continuation artifact changed")
        return {**record, "sha256": self.fingerprint}

    @classmethod
    def fit(cls, snapshot, records, ridge=4.0):
        """Pair-balanced fitting; repeated prefixes are not independent sources."""
        binding = snapshot_binding(snapshot)
        rows = list(records)
        if len(rows) < 2 or not math.isfinite(ridge) or ridge <= 0:
            raise ValueError("At least two paired records and positive ridge required")
        protocol = {k: rows[0][k] for k in ("suffix", "cost_profile_digest", "gamma", "return_bounds", "target")}
        _contract(protocol["suffix"], protocol["cost_profile_digest"], protocol["gamma"], protocol["return_bounds"])
        features, targets, groups, keys = [], [], [], set()
        for row in rows:
            if (row.get("schema") != PAIR_SCHEMA or row.get("sha256") != _digest({k: v for k, v in row.items() if k != "sha256"})
                    or row.get("snapshot_binding") != binding or row.get("snapshot_digest") != snapshot.fingerprint
                    or row.get("metric_digest") != METRIC_DIGEST or any(row[k] != v for k, v in protocol.items())):
                raise ValueError("Mismatched/corrupt paired training record")
            group = tuple(sorted(row["source_pixels"]))
            if len(group) != 2 or len(set(group)) != 2:
                raise ValueError("Invalid original source pair")
            for pixel in group:
                _sha(pixel)
            key = _digest([group, row["parent_state"], row["pair_seed"], row["features"]])
            if key in keys:
                raise ValueError("Duplicate paired training observation")
            keys.add(key)
            outcomes = row["outcomes"]
            paths = [[]] + [[a, *protocol["suffix"]] for a in ACTIONS]
            if [o["path"] for o in outcomes] != paths:
                raise ValueError("Training targets do not use the registered fixed suffix")
            returns = [o["utility"] - o["actual_cost"] for o in outcomes]
            lo, hi = protocol["return_bounds"]
            if any(not math.isfinite(r) or not lo <= r <= hi or r != o["net_return"] or o["actual_cost"] < 0
                   for r, o in zip(returns, outcomes)):
                raise ValueError("Malformed actual paired returns")
            gamma = protocol["gamma"]
            targets.append([r - returns[0] if gamma == 0 else
                            -math.exp(-gamma * returns[0]) * math.expm1(-gamma * (r - returns[0]))
                            if r >= returns[0] else
                            math.exp(-gamma * r) * math.expm1(gamma * (r - returns[0]))
                            for r in returns[1:]])
            features.append(row["features"])
            groups.append(group)
        if len(set(groups)) < 2:
            raise ValueError("At least two original source pairs required")
        x, y = torch.tensor(features, dtype=torch.float64), torch.tensor(targets, dtype=torch.float64)
        if x.ndim != 2 or x.shape[1] != 4 * snapshot.config["hidden"] + 14 or not torch.isfinite(x).all():
            raise ValueError("Incomplete/nonfinite public training state")
        counts = Counter(groups)
        w = torch.tensor([1 / counts[g] for g in groups], dtype=torch.float64)
        w *= len(w) / w.sum()
        head = RidgeHead(x.shape[1], len(ACTIONS))
        head.mean.copy_((w[:, None] * x).sum(0) / w.sum())
        head.scale.copy_(((w[:, None] * (x - head.mean).square()).sum(0) / w.sum()).sqrt().clamp_min(1e-4))
        z = torch.cat(((x - head.mean) / head.scale, torch.ones(len(x), 1, dtype=x.dtype)), 1)
        penalty = torch.eye(z.shape[1], dtype=z.dtype) * ridge
        penalty[-1, -1] = 0
        head.weight.copy_(torch.linalg.solve(z.T @ (w[:, None] * z) + penalty, z.T @ (w[:, None] * y)))
        record = {"schema": SCHEMA, "actions": list(ACTIONS), "feature_schema": FEATURE_SCHEMA,
                  "snapshot_digest": snapshot.fingerprint, "snapshot_binding": binding,
                  "metric_digest": METRIC_DIGEST, **protocol,
                  "fit_source_pixels": sorted({p for g in groups for p in g}),
                  "fit_pairs": len(counts), "fit_samples": len(rows), "ridge": ridge,
                  "fit_input_sha256": _digest([r["sha256"] for r in rows]),
                  "support_min": x.min(0).values.tolist(), "support_max": x.max(0).values.tolist(),
                  **{name: getattr(head, name).tolist() for name in ("mean", "scale", "weight")}}
        return cls({**record, "sha256": _digest(record)})

    @torch.inference_mode()
    def predict(self, backend, state, context, *, cost_profile_digest):
        """Four scores, without action selection or a learned STOP coordinate."""
        record = self.to_record()
        if (not isinstance(backend, ForecastBackend) or snapshot_binding(backend.snapshot) != record["snapshot_binding"]
                or cost_profile_digest != record["cost_profile_digest"]):
            raise ValueError("Snapshot or actual-cost profile differs from fitted head")
        backend.identity(state)
        x = public_features(backend.snapshot, state, context)
        if ((x < torch.tensor(record["support_min"], dtype=x.dtype)).any()
                or (x > torch.tensor(record["support_max"], dtype=x.dtype)).any()):
            raise ValueError("Public state is outside empirical feature coverage")
        scores = self._head(x)[0]
        if not torch.isfinite(scores).all():
            raise ValueError("Nonfinite continuation prediction")
        return scores

    def infer(self, backend, state, context, *, cost_profile_digest):
        scores = self.predict(backend, state, context, cost_profile_digest=cost_profile_digest)
        return {"STOP": 0.0, **dict(zip(ACTIONS, scores.tolist()))}

    def save(self, path):
        raw = json.dumps(self.to_record(), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(raw)
        temporary.replace(path)
        return hashlib.sha256(raw).hexdigest()

    @classmethod
    def load(cls, path, *, expected_file_sha256):
        raw = Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != _sha(expected_file_sha256):
            raise ValueError("Continuation file SHA-256 mismatch")
        return cls(json.loads(raw))
