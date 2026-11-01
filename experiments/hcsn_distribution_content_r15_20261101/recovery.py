"""Paid, causal reset/replay interventions on an actual content-model state.

The trusted raw-event cache and public alarm are explicit service assumptions.
Labels are used only for evaluator returns and offline selector fitting.
"""

import copy
import hashlib
import json
import time
from dataclasses import asdict, dataclass

import numpy as np
import torch


ACTIONS = ("none", "reset_only", "replay_only", "reset_replay")


@dataclass(frozen=True)
class RecoveryPrices:
    """Synthetic task tariffs; measured process CPU is reported separately."""

    initial_read: float = .0025
    physical_time: float = .0005
    monitor: float = .001
    cached_byte: float = 1e-8
    reset: float = .005
    replay_read: float = .0025
    replay_process: float = .00025
    replay_service_seconds: float = .05
    reset_service_seconds: float = .1

    def __post_init__(self):
        if any(not np.isfinite(v) or v < 0 for v in asdict(self).values()):
            raise ValueError("Recovery prices must be finite and nonnegative")


def _clone(state):
    if isinstance(state, torch.Tensor):
        return state.detach().clone()
    return {name: value.detach().clone() for name, value in state.items()}


class StatefulContent:
    """Causal adapter for the shared encoder and explicit-state recurrent cores."""

    def __init__(self, model, x, dt):
        if any(not hasattr(model.core, name) for name in
               ("initial_state", "step", "observe", "read_state")):
            raise TypeError("Recovery requires the complete distribution-core state interface")
        self.model, self.x, self.dt = model, x, dt
        self.elapsed = dt.cumsum(1)
        self.consumed_frames = 0

    def initial(self):
        core = self.model.core
        return core.initial_state(len(self.x), device=self.x.device, dtype=self.x.dtype)

    def consume(self, state, start, end, clock="source"):
        # Each cache access re-encodes the paid raw event. Original source clocks
        # are replay metadata, not a claim that physical time runs backwards.
        for t in range(start, end):
            previous = self.x[:, t - 1] if t else torch.zeros_like(self.x[:, 0])
            clocks = torch.stack((self.dt[:, t].log1p(), self.elapsed[:, t].log1p()), -1)
            features = torch.cat((self.x[:, t], previous, clocks), -1)
            encoded = self.model.encoder.net(features)
            if clock == "source":
                result = self.model.core.step(encoded, state, self.dt[:, t:t + 1])
                state = result[1] if isinstance(result, tuple) else result
            elif clock == "observation_only" and hasattr(self.model.core, "observe"):
                state = self.model.core.observe(state, encoded)
            else:
                raise ValueError("Observation-only replay requires core.observe")
            self.consumed_frames += len(self.x)
        return state

    def logits(self, state):
        core = self.model.core
        feature = core.read_state(state) if hasattr(core, "read_state") else state
        return self.model.readout(feature)


def corrupt_content(state, alarm, fault_kind):
    """Only stored content is corrupted; probability, cache and model survive."""
    if fault_kind not in ("none", "zero", "sign"):
        raise ValueError("Unknown registered fault kind")
    state = _clone(state)
    target = state["content_moment"] if isinstance(state, dict) else state
    if fault_kind == "zero":
        target[alarm] = 0
    elif fault_kind == "sign":
        target[alarm] *= -1
    return state


def prefix_features(logits, alarm, dt, cut, prices, cache_bytes):
    probability = logits.softmax(-1)
    if probability.shape[-1] > 3:
        raise ValueError("The frozen recovery feature contract supports 2/3 classes")
    padded = torch.nn.functional.pad(probability, (0, 3 - probability.shape[-1]))
    entropy = -(probability * probability.clamp_min(1e-8).log()).sum(-1)
    largest = probability.topk(2, dim=-1).values
    replay_price = cut * (prices.replay_read + prices.replay_process
                          + prices.physical_time * prices.replay_service_seconds)
    constants = logits.new_tensor([cut / dt.shape[1], replay_price, prices.reset,
                                   cache_bytes / 4096]).expand(len(dt), -1)
    return torch.cat((alarm[:, None].to(logits.dtype), padded,
                      entropy[:, None], (largest[:, 0] - largest[:, 1])[:, None],
                      dt[:, :cut].sum(1, keepdim=True) / 32,
                      dt[:, cut:].sum(1, keepdim=True) / 32, constants), -1)


@torch.inference_mode()
def paired_recovery(model, x, dt, labels, *, fault_kind="sign", fault_probability=.5,
                    seed=151901, cut=None, prices=None, groups=None):
    """Four real actions from one identical prefix and one damaged-state copy.

    The model completes the same suffix in each arm. No action sees labels or
    unpaid future payloads. ``cut`` counts original paid frames before the fault.
    This is a read-all recovery profile, not the STOP controller's policy value.
    """
    prices = prices or RecoveryPrices()
    if not 0 <= fault_probability <= 1 or not np.isfinite(fault_probability):
        raise ValueError("fault_probability must be in [0,1]")
    if x.ndim != 3 or dt.shape != x.shape[:2] or len(x) == 0:
        raise ValueError("Expected a nonempty batch with matching clocks")
    if not torch.isfinite(x).all() or not torch.isfinite(dt).all() or (dt < 0).any():
        raise ValueError("Finite raw events and nonnegative clocks required")
    cut = max(1, x.shape[1] - 2) if cut is None else cut
    if type(cut) is not int or not 1 <= cut <= x.shape[1]:
        raise ValueError("The intervention must follow a nonempty paid prefix")
    if labels.shape != (len(x),):
        raise ValueError("One evaluator label per episode required")
    groups = np.arange(len(x)) if groups is None else np.asarray(groups)
    if groups.shape != (len(x),):
        raise ValueError("One group identity per episode required")
    unique, inverse = np.unique(groups, return_inverse=True)
    alarm_np = np.random.default_rng(seed).random(len(unique))[inverse] < fault_probability
    if fault_kind == "none":
        alarm_np[:] = False
    alarm = torch.as_tensor(alarm_np, device=x.device)
    model.eval()
    total_cpu, total_wall = time.process_time(), time.perf_counter()
    adapter = StatefulContent(model, x, dt)
    started = time.process_time()
    prefix = adapter.consume(adapter.initial(), 0, cut)
    common_prefix_cpu = time.process_time() - started
    damaged = corrupt_content(prefix, alarm, fault_kind)
    cache_bytes = cut * (x.shape[-1] * x.element_size() + dt.element_size())
    feature = prefix_features(adapter.logits(damaged), alarm, dt, cut, prices, cache_bytes)
    prediction, action_cpu, processed = [], {}, {}
    initial_fee = prices.initial_read * dt.shape[1] + prices.physical_time * dt.double().sum(1)
    shared_fee = initial_fee + prices.monitor + prices.cached_byte * cache_bytes
    fees = []
    for action in ACTIONS:
        begin = time.process_time()
        before = adapter.consumed_frames
        state = adapter.initial() if action in ("reset_only", "reset_replay") else _clone(damaged)
        extra = 0.
        if action in ("reset_only", "reset_replay"):
            extra += prices.reset + prices.physical_time * prices.reset_service_seconds
        if action in ("replay_only", "reset_replay"):
            replay_clock = "observation_only" if action == "replay_only" else "source"
            state = adapter.consume(state, 0, cut, clock=replay_clock)
            extra += cut * (prices.replay_read + prices.replay_process
                            + prices.physical_time * prices.replay_service_seconds)
        state = adapter.consume(state, cut, dt.shape[1])
        prediction.append(adapter.logits(state).argmax(-1))
        fees.append(shared_fee + extra)
        action_cpu[action] = time.process_time() - begin
        processed[action] = adapter.consumed_frames - before
    clean_started = time.process_time()
    clean = adapter.logits(adapter.consume(_clone(prefix), cut, dt.shape[1])).argmax(-1)
    clean_diagnostic_cpu = time.process_time() - clean_started
    predictions, fee = torch.stack(prediction, -1), torch.stack(fees, -1)
    correct = (predictions == labels[:, None]).to(x.dtype)
    return {
        "actions": ACTIONS, "features": feature.cpu().numpy(),
        "alarm": alarm.cpu().numpy(), "group": groups,
        "predictions": predictions.cpu().numpy(), "correct": correct.cpu().numpy(),
        "fee": fee.cpu().numpy(), "utility": (correct - fee).cpu().numpy(),
        "clean_prediction": clean.cpu().numpy(),
        "clean_correct": (clean == labels).cpu().numpy(),
        "unprotected_fee": initial_fee.cpu().numpy(),
        "metadata": {"fault_kind": fault_kind, "fault_probability": fault_probability,
                     "seed": seed, "cut": cut, "length": x.shape[1], "episodes": len(x),
                     "prices": asdict(prices), "cached_bytes_per_episode": cache_bytes,
                     "model_parameters": sum(p.numel() for p in model.parameters()),
                     "operational_original_frame_reads_per_arm": len(x) * x.shape[1],
                     "replay_frame_reads_per_replay_arm": len(x) * cut,
                     "actual_encoder_core_frames_in_experiment": adapter.consumed_frames,
                     "post_prefix_processed_frames": processed,
                     "common_prefix_cpu_seconds": common_prefix_cpu,
                     "post_prefix_cpu_seconds": action_cpu,
                     "clean_diagnostic_cpu_seconds": clean_diagnostic_cpu,
                     "experiment_cpu_seconds": time.process_time() - total_cpu,
                     "experiment_wall_seconds": time.perf_counter() - total_wall,
                     "cpu_scope": "actual batch process CPU; shared prefix counted once in experiment",
                     "price_scope": "synthetic task tariffs, not physical energy or provider billing"}}


def merge_cases(cases):
    """Pool prespecified fault cohorts without confusing them with fit seeds."""
    names = ("features", "alarm", "group", "predictions", "correct", "fee", "utility",
             "clean_prediction", "clean_correct", "unprotected_fee")
    return {**{name: np.concatenate([c[name] for c in cases]) for name in names},
            "actions": ACTIONS, "metadata": [c["metadata"] for c in cases]}


def select_actions(policy, features):
    """Frozen deployment rule: prefix features only, never labels or outcomes."""
    features = np.asarray(features, dtype=np.float64)
    alarm = features[:, 0] > .5
    if policy["kind"] == "fixed":
        chosen = np.full(len(features), ACTIONS.index(policy["action"]), dtype=np.int64)
    elif policy["kind"] == "ridge":
        scaled = (features - np.asarray(policy["mean"])) / np.asarray(policy["scale"])
        design = np.column_stack((np.ones(len(features)), scaled))
        chosen = (design @ np.asarray(policy["coefficients"])).argmax(-1)
    else:
        raise ValueError("Unknown recovery policy")
    # Monitoring is paid even here. No-alarm means no intervention in this
    # explicitly diagnosed-fault profile; spontaneous faults are not covered.
    return np.where(alarm, chosen, 0)


def apply_selector(policy, result):
    begin = time.process_time()
    actions = select_actions(policy, result["features"])
    selection_cpu = time.process_time() - begin
    rows = np.arange(len(actions))
    out = {name: result[name][rows, actions] for name in
           ("predictions", "correct", "fee", "utility")}
    out.update(actions=actions, selection_cpu_seconds=selection_cpu)
    out["utility_gain_vs_none"] = out["utility"] - result["utility"][:, 0]
    out["utility_gain_vs_unprotected_none"] = out["utility"] - (
        result["correct"][:, 0] - result["unprotected_fee"])
    return out


def fit_selector(training, validation, ridge_values=(.1, 1., 10.)):
    """Fit on actual training returns, select by held-out validation utility."""
    features = np.asarray(training["features"], dtype=np.float64)
    targets = np.asarray(training["utility"], dtype=np.float64)
    mean, scale = features.mean(0), features.std(0)
    scale[scale < 1e-8] = 1.
    design = np.column_stack((np.ones(len(features)), (features - mean) / scale))
    candidates = [dict(kind="fixed", action=a, no_alarm_action="none") for a in ACTIONS]
    for strength in ridge_values:
        penalty = np.eye(design.shape[1]) * strength
        penalty[0, 0] = 0
        weights = np.linalg.solve(design.T @ design + penalty, design.T @ targets)
        candidates.append(dict(kind="ridge", strength=strength, mean=mean.tolist(),
                               scale=scale.tolist(), coefficients=weights.tolist(),
                               no_alarm_action="none"))
    scores = [float(apply_selector(p, validation)["utility"].mean()) for p in candidates]
    chosen = int(np.argmax(scores))  # earliest tie; no-recovery candidate first
    policy = copy.deepcopy(candidates[chosen])
    payload = json.dumps(policy, sort_keys=True, separators=(",", ":"))
    return {"policy": policy, "sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "selected_index": chosen, "validation_utility": scores[chosen],
            "candidates": [{"kind": p["kind"], "action": p.get("action"),
                            "strength": p.get("strength"), "validation_utility": s}
                           for p, s in zip(candidates, scores)],
            "training_episodes": len(features), "validation_episodes": len(validation["features"]),
            "heldout_opened": False}


def summarize(result, policy=None):
    summary = {"episodes": len(result["alarm"]), "alarms": int(result["alarm"].sum()),
               "clean_accuracy": float(result["clean_correct"].mean()), "arms": {}}
    for j, name in enumerate(ACTIONS):
        summary["arms"][name] = {"accuracy": float(result["correct"][:, j].mean()),
                                  "utility": float(result["utility"][:, j].mean()),
                                  "fee": float(result["fee"][:, j].mean()),
                                  "prediction_changes_vs_none": int(np.count_nonzero(
                                      result["predictions"][:, j] != result["predictions"][:, 0]))}
    if policy is not None:
        selected = apply_selector(policy, result)
        summary["selected"] = {"accuracy": float(selected["correct"].mean()),
                               "utility": float(selected["utility"].mean()),
                               "fee": float(selected["fee"].mean()),
                               "gain_vs_none": float(selected["utility_gain_vs_none"].mean()),
                               "gain_vs_unprotected_none": float(selected["utility_gain_vs_unprotected_none"].mean()),
                               "action_counts": {a: int(np.count_nonzero(selected["actions"] == j))
                                                 for j, a in enumerate(ACTIONS)}}
    return summary
