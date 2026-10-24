"""Offline public-state forecasts and source-disjoint residual calibration.

The terminal law uses two public-prediction strata when each has >=30 distinct
calibration pairs, otherwise the global residual profile. These empirical laws
have no conditional coverage guarantee and are not a general NDU/FBSDE model.
Offline observer labels never enter the inference backend. Calls are counted.
"""

from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import time
from threading import Lock, get_ident

import torch
from torch import nn

from .control import entropic_value
from .data import make_batch, render_tokens
from .neural import ACTIONS, parameter_hash
from .observer import METRIC_DIGEST, observe_tensors


class RidgeHead(nn.Module):
    """Frozen standardized linear predictor with an unpenalized intercept."""

    def __init__(self, features, outputs):
        super().__init__()
        self.register_buffer("mean", torch.zeros(features, dtype=torch.float64))
        self.register_buffer("scale", torch.ones(features, dtype=torch.float64))
        self.register_buffer("weight", torch.zeros(features + 1, outputs, dtype=torch.float64))

    def forward(self, features):
        x = (features.to(dtype=torch.float64, device="cpu") - self.mean) / self.scale
        return torch.cat((x, torch.ones(len(x), 1, dtype=x.dtype)), dim=1) @ self.weight

    @classmethod
    @torch.no_grad()
    def fit(cls, features, targets, ridge=4.0):
        x, y = features.double(), targets.double()
        if y.ndim == 1:
            y = y[:, None]
        if len(x) != len(y) or len(x) < 2 or not math.isfinite(ridge) or ridge <= 0:
            raise ValueError("Invalid ridge fitting dimensions or regularization")
        if not torch.isfinite(x).all() or not torch.isfinite(y).all():
            raise ValueError("Nonfinite forecast training data")
        head = cls(x.shape[1], y.shape[1])
        head.mean.copy_(x.mean(0))
        head.scale.copy_(x.std(0, unbiased=False).clamp_min(1e-4))
        z = (x - head.mean) / head.scale
        z = torch.cat((z, torch.ones(len(z), 1, dtype=z.dtype)), dim=1)
        regularizer = torch.eye(z.shape[1], dtype=z.dtype) * ridge
        regularizer[-1, -1] = 0
        head.weight.copy_(torch.linalg.solve(z.T @ z + regularizer, z.T @ y))
        return head.eval().requires_grad_(False)


class ForecastBundle:
    """Data-only checkpoint: frozen forecast/router heads and residual support."""

    def __init__(self, utility_head, action_head, residuals, snapshot_digest,
                 static_sequence, metric_digest=METRIC_DIGEST, threshold=None, profiles=None):
        self.utility_head = deepcopy(utility_head).eval().requires_grad_(False)
        self.action_head = deepcopy(action_head).eval().requires_grad_(False)
        self.residuals = residuals.detach().cpu().double().clone().reshape(-1)
        self.snapshot_digest, self.metric_digest = snapshot_digest, metric_digest
        self.static_sequence = tuple(static_sequence)
        self.threshold, self.profiles = threshold, deepcopy(profiles or {})
        if not len(self.residuals) or not torch.isfinite(self.residuals).all():
            raise ValueError("Finite nonempty residual support required")
        if self.residuals.abs().max() > 2:
            raise ValueError("Invalid bounded residuals")
        if any(a not in ACTIONS for a in self.static_sequence):
            raise ValueError("Unknown action in fixed sequence")
        if self.utility_head.weight.shape[1] != 1 or self.action_head.weight.shape[1] != len(ACTIONS):
            raise ValueError("Forecast/router head output dimensions do not match")
        if self.utility_head.mean.shape != self.action_head.mean.shape:
            raise ValueError("Forecast/router public feature dimensions differ")
        for head in (self.utility_head, self.action_head):
            if any(not torch.isfinite(tensor).all() for tensor in head.buffers()) or torch.any(head.scale <= 0):
                raise ValueError("Forecast head contains nonfinite parameters or invalid scales")
        if threshold is not None and not math.isfinite(threshold):
            raise ValueError("Invalid public forecast partition threshold")
        for name, profile in self.profiles.items():
            r, p = profile["residuals"], profile["probabilities"]
            if (name not in {"low", "high"} or threshold is None or profile["groups"] < 30
                    or r.ndim != 1 or r.shape != p.shape or not len(r)
                    or not torch.isfinite(r).all() or r.abs().max() > 2
                    or not torch.isfinite(p).all() or torch.any(p <= 0) or abs(p.sum().item() - 1) > 1e-10):
                raise ValueError("Invalid source-balanced conditional residual profile")
        self.fingerprint = self._digest()

    def _digest(self):
        digest = hashlib.sha256(json.dumps({
            "snapshot": self.snapshot_digest, "metric": self.metric_digest,
            "sequence": self.static_sequence, "scope": "stratified_empirical_residuals_dual_init_v1", "threshold": self.threshold,
        }, sort_keys=True).encode())
        digest.update(parameter_hash(self.utility_head).encode())
        digest.update(parameter_hash(self.action_head).encode())
        digest.update(self.residuals.numpy().tobytes())
        for name, profile in sorted(self.profiles.items()):
            digest.update(f"{name}:{profile['groups']}".encode())
            digest.update(profile["residuals"].numpy().tobytes())
            digest.update(profile["probabilities"].numpy().tobytes())
        return digest.hexdigest()

    def profile(self, mean):
        name = "low" if self.threshold is not None and mean < self.threshold else "high"
        if name in self.profiles:
            return self.profiles[name]["residuals"], self.profiles[name]["probabilities"]
        return self.residuals, torch.full_like(self.residuals, 1 / len(self.residuals))

    def verify_integrity(self):
        if self._digest() != self.fingerprint:
            raise RuntimeError("Frozen forecast parameters or calibration profile changed")
        return self.fingerprint

    def backend(self, snapshot, context_id):
        return ForecastBackend(snapshot, self, context_id)

    def save(self, path):
        self.verify_integrity()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": "hepta.ndu-v6.forecast.v1", "features": len(self.utility_head.mean),
            "utility": self.utility_head.state_dict(), "actions": self.action_head.state_dict(),
            "residuals": self.residuals, "snapshot_digest": self.snapshot_digest,
            "metric_digest": self.metric_digest, "static_sequence": list(self.static_sequence),
            "threshold": self.threshold, "profiles": self.profiles,
            "fingerprint": self.fingerprint,
        }
        temporary = path.with_suffix(path.suffix + ".tmp")
        torch.save(record, temporary)
        temporary.replace(path)
        return self.fingerprint

    @classmethod
    def load(cls, path):
        record = torch.load(Path(path), map_location="cpu", weights_only=True)
        if record.get("schema") != "hepta.ndu-v6.forecast.v1":
            raise ValueError("Unsupported forecast checkpoint schema")
        utility, actions = RidgeHead(record["features"], 1), RidgeHead(record["features"], len(ACTIONS))
        utility.load_state_dict(record["utility"], strict=True)
        actions.load_state_dict(record["actions"], strict=True)
        bundle = cls(utility, actions, record["residuals"], record["snapshot_digest"],
                     record["static_sequence"], record["metric_digest"], record["threshold"], record["profiles"])
        if bundle.fingerprint != record["fingerprint"]:
            raise ValueError("Forecast checkpoint fingerprint mismatch")
        return bundle


class ForecastBackend:
    """Controller port containing only snapshots, fitted heads and public IDs."""

    def __init__(self, snapshot, forecast, context_id):
        snapshot.verify_integrity()
        forecast.verify_integrity()
        if snapshot.fingerprint != forecast.snapshot_digest or not isinstance(context_id, str) or not context_id:
            raise ValueError("Forecast snapshot mismatch or missing public context ID")
        if forecast.metric_digest != METRIC_DIGEST:
            raise ValueError("Forecast objective differs from the active metric contract")
        self.snapshot, self.forecast, self.context_id = snapshot, forecast, context_id
        self._guard_owner, self._guard_lock = None, Lock()

    def _guard_active(self):
        if self._guard_owner is not None and self._guard_owner != get_ident():
            raise RuntimeError("Inference backend is guarded by another thread")
        return self._guard_owner is not None

    @contextmanager
    def inference_guard(self):
        """Verify immutable artifacts around one synchronous inference episode.

        Only repeated model hashes are skipped inside this owning thread. The
        forecast and public-state checks remain active. No result may be
        published before context exit. Concurrent writers are unsupported.
        """
        if not self._guard_lock.acquire(blocking=False):
            raise RuntimeError("Nested or concurrent inference guards are unsupported")
        self._guard_owner = get_ident()
        try:
            try:
                self.snapshot.verify_integrity()
            finally:
                self.forecast.verify_integrity()
            try:
                yield self
            finally:
                try:
                    self.snapshot.verify_integrity()
                finally:
                    self.forecast.verify_integrity()
        finally:
            self._guard_owner = None
            self._guard_lock.release()

    def actions(self, state, content_control):
        self._guard_active()
        return ACTIONS if content_control else ("refine_image", "refine_text")

    def transition(self, state, action):
        self._guard_active()
        return self.snapshot.step(state, action)

    @torch.inference_mode()
    def predict(self, state):
        self._guard_active()
        self.forecast.verify_integrity()
        features = self.snapshot.state_features(state)
        if len(features) != 1:
            raise ValueError("A controller episode requires one public input")
        mean = self.forecast.utility_head(features).squeeze().clamp(-1, 1)
        residuals, probabilities = self.forecast.profile(mean.item())
        return (mean + residuals).clamp(-1, 1).tolist(), probabilities.tolist()

    @torch.inference_mode()
    def router(self, state, admissible_actions):
        self._guard_active()
        self.forecast.verify_integrity()
        features = self.snapshot.state_features(state)
        if len(features) != 1 or any(a not in ACTIONS for a in admissible_actions):
            raise ValueError("Invalid public routing state or action")
        gains = self.forecast.action_head(features)[0].tolist()
        candidates = [(gains[ACTIONS.index(a)], a) for a in admissible_actions]
        gain, action = max(candidates, default=(0.0, None), key=lambda item: item[0])
        return action if gain > 0 else None

    def action_cost(self, state, action):
        self._guard_active()
        if action not in ACTIONS:
            raise ValueError("Unknown neural action")
        return 1.0

    def prediction_cost(self, state):
        self._guard_active()
        return 0.25

    def state_key(self, state):
        self._guard_active()
        return self.snapshot.state_key(state)

    def identity(self, state):
        if not self._guard_active():
            self.snapshot.verify_integrity()
        self.forecast.verify_integrity()
        context = self.snapshot.observation_identity(state)
        return ":".join((self.context_id, self.snapshot.fingerprint, self.forecast.fingerprint, context))


def _observe(snapshot, state, batch, observer_model, counts):
    output = snapshot.decode(state)
    pixels = (output.image_logits.sigmoid() * 255).round() / 255
    captions = [render_tokens(tokens) for tokens in output.token_ids]
    rows = observe_tensors(observer_model, pixels, captions, batch.target.pixels, batch.target.labels)
    for key in ("decode", "observer"):
        counts[key + "_batch_calls"] += 1
        counts[key + "_case_calls"] += len(pixels)
    utility = torch.tensor([row["utility"] for row in rows], dtype=torch.float64)
    if not torch.isfinite(utility).all() or utility.abs().max() > 1:
        raise ValueError("Observer utility is outside declared [-1,1] bounds")
    return snapshot.state_features(state).double(), utility


def _collect(snapshot, batch, observer_model, seed, horizon, counts, content_control=True):
    actions = ACTIONS if content_control else ("refine_image", "refine_text")
    state = initial = snapshot.encode(batch.observation, noise_seed=seed, content_control=content_control)
    counts["encode_batch_calls"] += 1
    counts["encode_case_calls"] += len(batch.source_ids)
    features, utility = _observe(snapshot, state, batch, observer_model, counts)
    xs, ys, router_x, router_y = [features], [utility], [], []
    for depth in range(horizon):
        children, observations = [], []
        for action in actions:
            child = snapshot.step(state, action)
            counts["transition_batch_calls"] += 1
            counts["transition_case_calls"] += len(batch.source_ids)
            observed = _observe(snapshot, child, batch, observer_model, counts)
            children.append(child)
            observations.append(observed)
            xs.append(observed[0])
            ys.append(observed[1])
        if content_control:
            router_x.append(features)
            router_y.append(torch.stack([row[1] - utility for row in observations], dim=1))
        continuation = (seed + depth) % len(actions)
        state, (features, utility) = children[continuation], observations[continuation]
    return (torch.cat(xs), torch.cat(ys), torch.cat(router_x) if router_x else None,
            torch.cat(router_y) if router_y else None, initial)


def _calibration_profiles(means, utilities, groups, threshold):
    residuals = utilities - means
    profiles, evidence = {}, {}
    for name, mask in (("low", means < threshold), ("high", means >= threshold)):
        frequencies = torch.bincount(groups[mask], minlength=int(groups.max()) + 1)
        support = int((frequencies > 0).sum())
        active = support >= 30
        evidence[name] = {"distinct_source_pairs": support, "rows": int(mask.sum()), "active": active}
        if active:
            probabilities = 1 / (support * frequencies[groups[mask]].double())
            profiles[name] = {"residuals": residuals[mask].clone(), "probabilities": probabilities, "groups": support}
            order = residuals[mask].argsort()
            bounds = residuals[mask][order][torch.searchsorted(probabilities[order].cumsum(0),
                                            torch.tensor([.05, .95], dtype=torch.float64))]
            covered = (utilities[mask] >= (means[mask] + bounds[0]).clamp(-1, 1)) & (utilities[mask] <= (means[mask] + bounds[1]).clamp(-1, 1))
            evidence[name]["empirical_calibration_90pct_coverage"] = float((covered * probabilities).sum())
    return profiles, evidence


@torch.inference_mode()
def fit_forecast(snapshot, corpus, observer_model, seed, fit_pairs=128,
                 calibration_pairs=64, dev_pairs=64, horizon=3, action_cost_penalty=.002):
    """Fit on validation-fit; calibrate and tune on separate source identities."""
    if (any(not isinstance(n, int) or isinstance(n, bool) or n < 2 for n in (fit_pairs, calibration_pairs, dev_pairs))
            or not isinstance(horizon, int) or isinstance(horizon, bool) or horizon < 1):
        raise ValueError("Positive horizon and at least two pairs per forecast partition required")
    if not math.isfinite(action_cost_penalty) or action_cost_penalty < 0:
        raise ValueError("Fixed-policy action cost penalty must be finite and nonnegative")
    source = corpus.splits["validation"]
    if 2 * (fit_pairs + calibration_pairs + dev_pairs) > len(source):
        raise ValueError("Insufficient source-disjoint validation pairs for forecast fitting")
    snapshot.verify_integrity()
    observer_digest = parameter_hash(observer_model)
    started = time.perf_counter_ns()
    counts = {f"{operation}_{unit}_calls": 0 for operation in ("encode", "transition", "decode", "observer")
              for unit in ("batch", "case")}
    collected, partitions, seen_ids, seen_pixels = {}, {}, set(), set()
    offset = 0
    for index, (name, count) in enumerate((("fit", fit_pairs), ("calibration", calibration_pairs), ("dev", dev_pairs))):
        part_start = time.perf_counter_ns()
        batch = make_batch(corpus, "validation", count, seed + index, offset=offset)
        ids = [identity for pair in batch.source_ids for identity in pair]
        pixels = list(source.pixel_hashes[2 * offset:2 * (offset + count)])
        if len(set(ids)) != len(ids) or len(set(pixels)) != len(pixels) or seen_ids.intersection(ids) or seen_pixels.intersection(pixels):
            raise ValueError("Source identity/pixel leakage across forecast partitions")
        seen_ids.update(ids)
        seen_pixels.update(pixels)
        full = _collect(snapshot, batch, observer_model, seed + index, horizon, counts)
        allocation = _collect(snapshot, batch, observer_model, seed + index, horizon, counts, False)
        collected[name] = (torch.cat((full[0], allocation[0])), torch.cat((full[1], allocation[1])),
                           full[2], full[3], full[4], batch)
        partitions[name] = {"pair_offset": offset, "pairs": count, "source_ids": ids, "pixel_hashes": pixels,
                            "identity_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(),
                            "pixel_set_sha256": hashlib.sha256("\n".join(sorted(pixels)).encode()).hexdigest(),
                            "rollout_rows": len(collected[name][1]),
                            "rollout_rows_by_initialization": {"full": len(full[1]), "allocation": len(allocation[1])},
                            "wall_ns": time.perf_counter_ns() - part_start}
        offset += count
    fit_x, fit_y, fit_rx, fit_ry, _, _ = collected["fit"]
    fitting_started = time.perf_counter_ns()
    utility_head, action_head = RidgeHead.fit(fit_x, fit_y), RidgeHead.fit(fit_rx, fit_ry)
    fitting_ns = time.perf_counter_ns() - fitting_started
    cal_x, cal_y = collected["calibration"][:2]
    cal_mean = utility_head(cal_x).squeeze(1).clamp(-1, 1)
    residuals = cal_y - cal_mean
    threshold = utility_head(fit_x).squeeze(1).clamp(-1, 1).median().item()
    groups = torch.arange(calibration_pairs).repeat(2 + (len(ACTIONS) + 2) * horizon)
    profiles, profile_evidence = _calibration_profiles(cal_mean, cal_y, groups, threshold)
    dev_x, dev_y, _, dev_gains, initial, dev_batch = collected["dev"]
    dev_mean = utility_head(dev_x).squeeze(1).clamp(-1, 1)
    sequences = [tuple([action] * horizon) for action in ACTIONS]
    sequences += [tuple(ACTIONS[(start + i) % len(ACTIONS)] for i in range(horizon)) for start in range(4)]
    sequences += [tuple(("refine_image", "refine_text")[(start + i) % 2] for i in range(horizon)) for start in range(2)]
    sequence_scores = []
    tuning_started = time.perf_counter_ns()
    candidates = sorted({sequence[:length] for sequence in sequences for length in range(horizon + 1)},
                        key=lambda sequence: (len(sequence), sequence))
    for sequence in candidates:
        state = initial
        for action in sequence:
            state = snapshot.step(state, action)
            counts["transition_batch_calls"] += 1
            counts["transition_case_calls"] += dev_pairs
        _, utility = _observe(snapshot, state, dev_batch, observer_model, counts)
        mean, cost = utility.mean().item(), action_cost_penalty * len(sequence)
        sequence_scores.append({"sequence": list(sequence), "mean_external_utility": mean,
                                "selection_score": mean - cost, "action_cost": cost,
                                "dev_empirical_entropic_utility_gamma2": entropic_value(utility.tolist(), [1 / dev_pairs] * dev_pairs, 2)})
    selected = max(sequence_scores, key=lambda row: row["selection_score"])["sequence"]
    bundle = ForecastBundle(utility_head, action_head, residuals, snapshot.fingerprint, selected,
                            threshold=threshold, profiles=profiles)
    predicted_gain = action_head(collected["dev"][2])
    chosen = predicted_gain.argmax(1)
    achieved = dev_gains.gather(1, chosen[:, None]).squeeze(1)
    achieved = torch.where(predicted_gain.max(1).values > 0, achieved, torch.zeros_like(achieved))
    low, high = torch.quantile(residuals, torch.tensor([.05, .95], dtype=torch.float64))
    covered = (dev_y >= (dev_mean + low).clamp(-1, 1)) & (dev_y <= (dev_mean + high).clamp(-1, 1))
    actual_covered = torch.zeros_like(covered)
    for name, mask in (("low", dev_mean < threshold), ("high", dev_mean >= threshold)):
        r, p = bundle.profile(threshold - 1 if name == "low" else threshold)
        order = r.argsort()
        bounds = r[order][torch.searchsorted(p[order].cumsum(0), torch.tensor([.05, .95], dtype=torch.float64))]
        actual_covered[mask] = (dev_y[mask] >= (dev_mean[mask] + bounds[0]).clamp(-1, 1)) & (dev_y[mask] <= (dev_mean[mask] + bounds[1]).clamp(-1, 1))
        profile_evidence[name]["dev_rows"] = int(mask.sum())
        profile_evidence[name]["dev_90pct_coverage"] = actual_covered[mask].double().mean().item() if mask.any() else None
    if parameter_hash(observer_model) != observer_digest:
        raise RuntimeError("Independent observer changed during forecast labeling")
    snapshot.verify_integrity()
    evidence = {
        "schema": "hepta.ndu-v6.forecast-evidence.v1", "seed": seed, "horizon": horizon,
        "snapshot_sha256": snapshot.fingerprint, "forecast_sha256": bundle.fingerprint,
        "observer_sha256": observer_digest, "metric_sha256": METRIC_DIGEST,
        "source_manifest_sha256": corpus.manifest["manifest_sha256"], "partitions": partitions,
        "ridge_regularization": 4.0, "head_fit_wall_ns": fitting_ns,
        "fixed_sequence_tuning_wall_ns": time.perf_counter_ns() - tuning_started,
        "wall_ns": time.perf_counter_ns() - started, "offline_calls": counts,
        "offline_initial_plan_work_units": getattr(snapshot, "initial_plan_cost", 0) * counts["encode_case_calls"],
        "offline_learned_head_batch_calls": 4, "offline_learned_head_case_calls": len(fit_x) + len(cal_x) + len(dev_x) + len(collected["dev"][2]),
        "calibration_scope": "two public-utility strata; source-balanced residuals when supported, otherwise global; no conditional coverage guarantee",
        "calibration_partition_rule": {"threshold": threshold, "selected_from": "fit predicted utility median", "minimum_distinct_pairs": 30},
        "conditional_profiles": profile_evidence,
        "residual_scenarios": len(residuals), "residual_probabilities": "uniform empirical row mass; equal routes per source pair",
        "calibration_source_pairs": calibration_pairs, "residual_dependence": "multiple correlated endpoints per source pair",
        "rollout_design": "paired full init/four-action routes and allocation init/image-text routes; continuation=(partition_seed+depth)%action_count",
        "source_pair_weighting": "both initialization families share source-pair identity; never counted as independent pairs",
        "fixed_sequence_initialization": "full only",
        "fixed_sequence_selection": {"objective": "mean external utility minus penalty times continuation action work", "action_cost_penalty": action_cost_penalty,
                                     "stopping": "empty sequence and every prefix; shortest wins exact ties", "initial_cost": "common across candidates"},
        "residual_mean": residuals.mean().item(), "residual_std": residuals.std(unbiased=False).item(),
        "dev_mean_absolute_error": (dev_mean - dev_y).abs().mean().item(),
        "dev_global_90pct_interval_coverage": covered.double().mean().item(),
        "dev_used_profile_90pct_interval_coverage": actual_covered.double().mean().item(),
        "global_empirical_calibration_90pct_coverage": ((cal_y >= (cal_mean + low).clamp(-1, 1)) & (cal_y <= (cal_mean + high).clamp(-1, 1))).double().mean().item(),
        "dev_router_mean_observed_gain": achieved.mean().item(),
        "dev_router_oracle_gain": dev_gains.max(1).values.clamp_min(0).mean().item(),
        "fixed_sequence_candidates": sequence_scores, "static_sequence": selected,
        "raw_output_labeling": "autoregressive emitted captions; sigmoid pixels rounded to 8-bit before observer",
        "transition_work_units": 1.0, "forecast_work_units": .25,
        "claims": {"source_disjoint_fit_calibration_dev": True, "test_used_for_selection": False,
                   "conditional_calibration": False, "global_policy_optimality": False},
    }
    return bundle, evidence
