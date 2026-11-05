"""Analytic adapter training reference; synthetic regression is not model efficacy.

Profile ``portfolio-adapter-synthetic-entropic-v1`` is a declared finite NDU
special case: U(x)=-c(a)+exp(-rate*duration)*G(y,target,p), followed by an
entropic root over the finite scenario distribution. Targets and preferences are
external immutable observations. This is not the repository's Q32 evaluator or
a trained text/image generator. Every gradient traverses a Cell low-rank adapter,
a generator low-rank adapter, and a resource-allocation head.
"""

from dataclasses import dataclass, fields
import hashlib
import math

import numpy as np


TRAINABLE = ("cell_down", "cell_up", "generator_down", "generator_up", "control_delta")


@dataclass(frozen=True)
class AdapterProfile:
    discount_rate: float = 0.05
    duration: float = 1.5
    risk_aversion: float = 0.4
    interaction: float = 0.3
    compute_cost: float = 0.01

    def __post_init__(self):
        values = tuple(getattr(self, f.name) for f in fields(self))
        if any(not math.isfinite(v) or v < 0 for v in values) or self.duration <= 0:
            raise ValueError("profile coefficients must be finite and nonnegative")


@dataclass(frozen=True)
class FrozenBundle:
    base_cell: np.ndarray
    base_generator: np.ndarray
    control_base: np.ndarray
    cell_down: np.ndarray
    cell_up: np.ndarray
    generator_down: np.ndarray
    generator_up: np.ndarray
    control_delta: np.ndarray

    def __post_init__(self):
        # Immutable bytes backing prevents setflags(write=True) on selected data.
        for field in fields(self):
            value = np.asarray(getattr(self, field.name), dtype=np.float64)
            if value.ndim != 2 or not np.all(np.isfinite(value)):
                raise ValueError("parameter tensors must be finite matrices")
            immutable = np.frombuffer(value.tobytes(), dtype=np.float64).reshape(value.shape)
            object.__setattr__(self, field.name, immutable)
        d, h = self.base_cell.shape
        if self.base_generator.shape != (h, 2) or self.control_base.shape != (h, 2):
            raise ValueError("reference requires two modality outputs")
        if self.cell_down.shape[0] != d or self.cell_up.shape != (self.cell_down.shape[1], h):
            raise ValueError("incompatible Cell adapter")
        if self.generator_down.shape[0] != h or self.generator_up.shape != (self.generator_down.shape[1], 2):
            raise ValueError("incompatible generator adapter")
        if self.control_delta.shape != self.control_base.shape:
            raise ValueError("incompatible control head")

    def digest(self):
        digest = hashlib.sha256()
        for field in fields(self):
            array = getattr(self, field.name)
            digest.update(f"{field.name}:{array.shape}:float64".encode())
            digest.update(array.astype("<f8").tobytes())
        return digest.hexdigest()

    def effective(self):
        return (self.base_cell + self.cell_down @ self.cell_up,
                self.base_generator + self.generator_down @ self.generator_up,
                self.control_base + self.control_delta)


def make_bundle(seed=11):
    rng = np.random.default_rng(seed)
    return FrozenBundle(rng.normal(0, 0.35, (5, 6)), rng.normal(0, 0.35, (6, 2)),
                        rng.normal(0, 0.15, (6, 2)), rng.normal(0, 0.2, (5, 2)),
                        np.zeros((2, 6)), rng.normal(0, 0.2, (6, 2)),
                        np.zeros((2, 2)), np.zeros((6, 2)))


def _softmax(values):
    exp = np.exp(values - np.max(values, axis=-1, keepdims=True))
    return exp / np.sum(exp, axis=-1, keepdims=True)


def _forward(bundle, features):
    x = np.asarray(features, dtype=np.float64)
    if x.ndim != 2 or x.shape[0] == 0 or x.shape[1] != bundle.base_cell.shape[0] or not np.all(np.isfinite(x)):
        raise ValueError("features must be a nonempty compatible finite matrix")
    wc, wg, wa = bundle.effective()
    hidden = np.tanh(x @ wc)
    raw = hidden @ wg
    allocation = _softmax(hidden @ wa)
    logits = raw * (0.5 + allocation)
    # Stable sigmoid without evaluating an overflowing inactive branch.
    probability = np.exp(-np.logaddexp(0.0, -logits))
    return x, hidden, raw, allocation, probability, (wc, wg, wa)


def predict(bundle, features):
    """Return two synthetic outcome probabilities and continuous allocation."""
    _, _, _, allocation, probability, _ = _forward(bundle, features)
    return probability, allocation


def objective_and_gradient(bundle, features, targets, preferences, profile=AdapterProfile()):
    """Return the exact finite-scenario objective and analytic ascent gradients."""
    x, hidden, raw, allocation, probability, (_, wg, wa) = _forward(bundle, features)
    target = np.asarray(targets, dtype=np.float64)
    pref = np.asarray(preferences, dtype=np.float64)
    if target.shape != probability.shape or pref.shape != target.shape:
        raise ValueError("targets/preferences must match sample and modality dimensions")
    if not np.all(np.isfinite(target)) or not np.all((target >= 0) & (target <= 1)):
        raise ValueError("targets must be independently supplied values in [0,1]")
    if not np.all(np.isfinite(pref)) or np.any(pref < 0) or not np.allclose(pref.sum(axis=1), 1, atol=1e-12, rtol=0):
        raise ValueError("preferences must be finite simplex rows")
    error = probability - target
    difference = error[:, 0] - error[:, 1]
    terminal = -np.sum(pref * error**2, axis=1) - profile.interaction * difference**2
    discount = math.exp(-profile.discount_rate * profile.duration)
    utility = -profile.compute_cost * np.sum(allocation**2, axis=1) + discount * terminal
    if profile.risk_aversion == 0:
        value, sensitivity = float(np.mean(utility)), np.full(len(x), 1 / len(x))
    else:
        mean = float(np.mean(utility))
        centered = -profile.risk_aversion * (utility - mean)
        if np.max(np.abs(centered)) < 1.0:
            # log1p/expm1 preserve the continuous risk-neutral limit.
            value = mean - float(np.log1p(np.mean(np.expm1(centered)))) / profile.risk_aversion
        else:
            anchor = np.max(centered)
            value = mean - float(anchor + np.log(np.mean(np.exp(centered-anchor)))) / profile.risk_aversion
        sensitivity = _softmax(centered[None, :])[0]
    dprob = -2 * pref * error
    dprob[:, 0] -= 2 * profile.interaction * difference
    dprob[:, 1] += 2 * profile.interaction * difference
    dlogits = sensitivity[:, None] * discount * dprob * probability * (1 - probability)
    draw = dlogits * (0.5 + allocation)
    da = dlogits * raw - sensitivity[:, None] * 2 * profile.compute_cost * allocation
    dcontrol = allocation * (da - np.sum(da * allocation, axis=1, keepdims=True))
    dhidden = (draw @ wg.T + dcontrol @ wa.T) * (1 - hidden**2)
    dwc, dwg = x.T @ dhidden, hidden.T @ draw
    gradients = {"cell_down": dwc @ bundle.cell_up.T,
                 "cell_up": bundle.cell_down.T @ dwc,
                 "generator_down": dwg @ bundle.generator_up.T,
                 "generator_up": bundle.generator_down.T @ dwg,
                 "control_delta": hidden.T @ dcontrol}
    return value, gradients


def _with_parameters(bundle, parameters):
    return FrozenBundle(**{f.name: parameters.get(f.name, getattr(bundle, f.name)) for f in fields(bundle)})


def check_gradients(bundle, features, targets, preferences, profile=AdapterProfile(), epsilon=1e-5):
    """Central differences independently verify every trainable scalar."""
    if not math.isfinite(epsilon) or epsilon <= 0:
        raise ValueError("positive finite difference step required")
    _, analytic = objective_and_gradient(bundle, features, targets, preferences, profile)
    result = {}
    for name in TRAINABLE:
        measured = np.zeros_like(getattr(bundle, name))
        for index in np.ndindex(measured.shape):
            plus, minus = getattr(bundle, name).copy(), getattr(bundle, name).copy()
            plus[index] += epsilon
            minus[index] -= epsilon
            upper = objective_and_gradient(_with_parameters(bundle, {name: plus}), features, targets, preferences, profile)[0]
            lower = objective_and_gradient(_with_parameters(bundle, {name: minus}), features, targets, preferences, profile)[0]
            measured[index] = (upper - lower) / (2 * epsilon)
        result[name] = float(np.max(np.abs(measured - analytic[name])))
    return {"max_absolute_error": max(result.values()), "per_tensor_absolute_error": result}


def train_candidate(selected, features, targets, preferences, *, steps=200, learning_rate=1.0,
                    trust_radius=1.5, profile=AdapterProfile()):
    """Create an immutable candidate; never promote or mutate selected weights.

    The trust region measures effective matrices, not gauge-dependent low-rank
    factor norms. Backtracking preserves both this bound and ascent of the fixed
    training objective. This reference uses full-batch gradient ascent, not AdamW.
    """
    if not isinstance(steps, int) or steps < 0 or not all(math.isfinite(v) and v > 0 for v in (learning_rate, trust_radius)):
        raise ValueError("invalid training limits")
    selected_digest, anchor = selected.digest(), selected.effective()
    candidate, trace = selected, []
    for step in range(steps):
        value, gradient = objective_and_gradient(candidate, features, targets, preferences, profile)
        norm = math.sqrt(sum(float(np.sum(g*g)) for g in gradient.values()))
        rate, accepted = learning_rate / max(norm, 1.0), False
        for _ in range(24):
            proposal = _with_parameters(candidate, {name: getattr(candidate, name) + rate * gradient[name] for name in TRAINABLE})
            distance = math.sqrt(sum(float(np.sum((a-b)**2)) for a, b in zip(proposal.effective(), anchor)))
            next_value = objective_and_gradient(proposal, features, targets, preferences, profile)[0]
            if distance <= trust_radius and next_value >= value:
                candidate, accepted = proposal, True
                break
            rate *= 0.5
        trace.append({"step": step, "objective": value, "gradient_norm": norm, "accepted": accepted})
        if not accepted or norm < 1e-10:
            break
    if selected.digest() != selected_digest:
        raise RuntimeError("selected parameters changed")
    return candidate, trace


def run_adapter_experiment(seed=17):
    """Runnable differentiation evidence; all real Phase 3 acceptance stays HOLD."""
    rng, selected = np.random.default_rng(seed), make_bundle(seed)
    teacher = rng.normal(0, 0.7, (5, 2))
    x = rng.normal(size=(384, 5))
    truth = np.exp(-np.logaddexp(0.0, -(x @ teacher)))
    target = (rng.random(truth.shape) < truth).astype(float)
    preferences = np.tile([0.55, 0.45], (len(x), 1))
    candidate, trace = train_candidate(selected, x[:192], target[:192], preferences[:192])
    # These are disjoint synthetic rows. Neither their target nor metrics enter updates.
    before, routes_before = predict(selected, x[192:])
    after, routes_after = predict(candidate, x[192:])
    per_before = np.mean((before - target[192:])**2, axis=0)
    per_after = np.mean((after - target[192:])**2, axis=0)
    old_x = rng.normal(size=(128, 5))
    old_targets = predict(selected, old_x)[0]
    old_after = predict(candidate, old_x)[0]
    retention_drift = float(np.mean((old_after-old_targets)**2))
    calibration = {}
    for name, forecast in (("before", before), ("after", after)):
        # Fixed bins are predeclared; calibration labels do not enter training.
        total, flat, label = 0.0, forecast.ravel(), target[192:].ravel()
        bins = np.minimum((flat * 10).astype(int), 9)
        for group in range(10):
            mask = bins == group
            if np.any(mask):
                total += np.mean(mask) * abs(float(np.mean(flat[mask])-np.mean(label[mask])))
        calibration[name] = float(total)
    initial = objective_and_gradient(selected, x[:192], target[:192], preferences[:192])[0]
    final = objective_and_gradient(candidate, x[:192], target[:192], preferences[:192])[0]
    check = check_gradients(candidate, x[192:196], target[192:196], preferences[192:196])
    gates = {"heldout_brier_improved": bool(np.mean(per_after) < np.mean(per_before)),
             "old_probe_brier_drift_at_most_0_02": retention_drift <= 0.02,
             "heldout_ece_degradation_at_most_0_02": calibration["after"] <= calibration["before"] + 0.02,
             "prediction_spread_retained": bool(np.mean(np.std(after, axis=0)) >= 0.8*np.mean(np.std(before, axis=0)))}
    return {"profile": "portfolio-adapter-synthetic-entropic-v1", "evidence_kind": "synthetic_differentiation_only",
            "real_stage_3": "HOLD", "real_stage_3_reason": "No real Cell/generator model, independently judged generation dataset or future-window retention trial.",
            "seed": seed, "train_rows": 192, "heldout_rows": 192, "old_probe_rows": 128,
            "selected_digest": selected.digest(), "candidate_digest": candidate.digest(),
            "selected_unchanged": True, "candidate_selected": False, "optimizer_steps": len(trace),
            "train_objective_before": initial, "train_objective_after": final,
            "heldout_brier_before": per_before.tolist(), "heldout_brier_after": per_after.tolist(),
            "old_probe_brier_drift": retention_drift, "synthetic_gates": gates,
            "synthetic_candidate_admission": "PASS" if all(gates.values()) else "REJECTED",
            "heldout_expected_calibration_error": calibration,
            "retention_check_kind": "old_base_prediction_drift_not_real_task_retention",
            "diversity_check_kind": "prediction_spread_proxy_not_semantic_diversity",
            "prediction_spread_before": np.std(before, axis=0).tolist(),
            "prediction_spread_after": np.std(after, axis=0).tolist(),
            "routing_entropy_before": float(np.mean(-np.sum(routes_before*np.log(routes_before), axis=1))),
            "routing_entropy_after": float(np.mean(-np.sum(routes_after*np.log(routes_after), axis=1))),
            "trainable_parameters": sum(getattr(selected, name).size for name in TRAINABLE),
            "gradient_check": check,
            "non_claims": ["text/image generation quality", "critic calibration", "semantic diversity", "real old-task retention", "production parameter selection"]}
