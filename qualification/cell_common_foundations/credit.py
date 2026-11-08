"""Bounded FP64 delayed-credit reference for the common Cell research panel.

The tanh recurrence is a diagnostic model, not the native Q24 Cell runtime or a
replication of e-prop/PNAS. Local eligibility differentiates each unit's own
recurrence and omits cross-unit paths. Execution weights and row-stochastic
credit transport are independent artifacts. Proposals never mutate a model.
"""

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import platform
import time

import numpy as np

try:
    from .protocol import canonical_digest, source_inventory
except ImportError:
    from protocol import canonical_digest, source_inventory

METHODS = (
    "bptt",
    "tbptt",
    "three_factor",
    "type_specific",
    "diffusion",
    "shuffled_diffusion",
)
LAYERS = ("input", "recurrent", "bias")
CELL_TYPES = (
    "perception",
    "memory",
    "prediction",
    "decision",
    "verification",
    "action",
    "evaluation",
)
_SOURCE_ROOT = Path(__file__).resolve().parent
_SOURCE_FILES = ("credit.py", "protocol.py")
_IMPORTED_SOURCE = source_inventory(_SOURCE_ROOT, _SOURCE_FILES)
_THREE_FACTOR_DEFINITION = (
    "uniform arithmetic mean of all seven declared group-map rows, including "
    "unused rows, broadcast to the available feedback locations"
)
_THREE_FACTOR_LIMIT = (
    "signed group rows can cancel and reduce magnitude; this fixed untuned "
    "baseline is not claimed to be an optimal or fully tuned three-factor rule"
)


def _array(value, ndim, name):
    out = np.array(value, dtype=np.float64, copy=True)
    if out.ndim != ndim or not np.isfinite(out).all():
        raise ValueError(name + ": wrong dimension or nonfinite value")
    return out


def _norm_components(value):
    """Return max scale, scaled L2 and representable L2 without squaring scale."""
    array = np.asarray(value, dtype=np.float64).ravel()
    if not np.isfinite(array).all():
        raise ArithmeticError("nonfinite norm input; candidate refused")
    scale = float(np.max(np.abs(array), initial=0.0))
    if scale == 0:
        return 0.0, 1.0, 0.0
    scaled = array / scale
    unit_norm = math.sqrt(float(scaled @ scaled))
    if scale > np.finfo(np.float64).max / unit_norm:
        raise ArithmeticError("L2 norm is not representable in FP64; candidate refused")
    norm = scale * unit_norm
    if not math.isfinite(norm):
        raise ArithmeticError("L2 norm is not representable in FP64; candidate refused")
    return scale, unit_norm, norm


def _safe_l2(value):
    return _norm_components(value)[2]


def _relative_l2(value, baseline):
    """Compare scaled components, including actual changes to a zero baseline."""
    scale, unit, _ = _norm_components(value)
    base_scale, base_unit, _ = _norm_components(baseline)
    if base_scale == 0:
        if scale != 0:
            raise ArithmeticError("nonzero rounded change to a zero-norm baseline")
        return 0.0
    ratio = (scale / base_scale) * (unit / base_unit)
    if not math.isfinite(ratio) or (scale != 0 and ratio == 0):
        raise ArithmeticError("relative L2 norm is not representable in FP64")
    return ratio


def _digest(arrays):
    value = hashlib.sha256(b"hepta.cell-credit.fp64.v1\0")
    for name, array in sorted(arrays.items()):
        array = np.asarray(array, dtype="<f8")
        value.update(name.encode() + b"\0")
        value.update(str(array.shape).encode() + b"\0")
        value.update(array.tobytes())
    return value.hexdigest()


@dataclass(frozen=True)
class Model:
    """Frozen selected model; head is shared and untrained in this panel."""

    input: np.ndarray
    recurrent: np.ndarray
    bias: np.ndarray
    head: np.ndarray
    cell_types: tuple

    def __post_init__(self):
        values = {
            name: _array(getattr(self, name), 1 if name == "bias" else 2, name)
            for name in (*LAYERS, "head")
        }
        width, inputs = values["input"].shape
        if not 1 <= width <= 256 or not 1 <= inputs <= 256:
            raise ValueError("model dimensions outside pilot bounds")
        if values["recurrent"].shape != (width, width) or values["bias"].shape != (
            width,
        ):
            raise ValueError("recurrent/bias shape mismatch")
        if values["head"].shape[1] != width or not 1 <= values["head"].shape[0] <= 8:
            raise ValueError("head dimension must be 1..8")
        types = tuple(self.cell_types)
        if len(types) != width or any(
            type(t) is not int or not 0 <= t < 7 for t in types
        ):
            raise ValueError("one registered Cell type is required per unit")
        for name, array in values.items():
            if np.any(np.abs(array) > 8):
                raise ValueError("reference model parameter absolute bound is 8")
            array.setflags(write=False)
            object.__setattr__(self, name, array)
        object.__setattr__(self, "cell_types", types)

    @property
    def digest(self):
        return _digest(
            {**self.parameters(), "head": self.head, "cell_types": self.cell_types}
        )

    def parameters(self):
        return {name: getattr(self, name) for name in LAYERS}


def make_model(seed=0, width=7, input_size=2):
    """Paired initialization; all methods receive this exact immutable model."""
    rng = np.random.default_rng(seed)
    recurrent = 0.65 * np.eye(width) + rng.normal(0, 0.04, (width, width))
    head = np.array([[(-1.0 if i % 2 else 1.0) / width for i in range(width)]])
    return Model(
        rng.normal(0, 0.2, (width, input_size)),
        recurrent,
        rng.normal(0, 0.03, width),
        head,
        tuple(i % 7 for i in range(width)),
    )


@dataclass(frozen=True)
class Rule:
    """Declared group mapping and independent bounded credit propagation.

    credit_graph[i,j] transports source j into receiver i. Rows sum to one;
    this preserves constant signals and the infinity bound, not total mass.
    Every mapping row has L1 <= 1. Masks specify the same available feedback
    locations for every local rule. BPTT remains an offline full-gradient oracle.
    """

    group_map: np.ndarray
    credit_graph: np.ndarray
    feedback_mask: np.ndarray
    truncation: int = 4
    diffusion_steps: int = 2
    diffusion_rate: float = 0.5
    eligibility_l1_bound: float = 4.0
    shuffle_seed: int = 19

    def __post_init__(self):
        mapping = _array(self.group_map, 2, "group_map")
        graph = _array(self.credit_graph, 2, "credit_graph")
        mask = _array(self.feedback_mask, 1, "feedback_mask")
        if mapping.shape[0] != 7 or not 1 <= mapping.shape[1] <= 8:
            raise ValueError("group_map must have seven rows and 1..8 modulators")
        if np.any(np.abs(mapping).sum(axis=1) > 1.0 + 1e-12):
            raise ValueError("group_map row L1 exceeds one")
        n = len(mask)
        if not 1 <= n <= 256 or graph.shape != (n, n) or np.any(graph < 0):
            raise ValueError("invalid credit graph")
        if not np.allclose(graph.sum(axis=1), 1.0, rtol=0, atol=1e-12):
            raise ValueError("credit graph must be row stochastic")
        if not np.all((mask == 0) | (mask == 1)):
            raise ValueError("feedback_mask must contain zero/one")
        if type(self.truncation) is not int or self.truncation < 1:
            raise ValueError("truncation must be a positive integer")
        if type(self.diffusion_steps) is not int or not 0 <= self.diffusion_steps <= 32:
            raise ValueError("diffusion_steps must be 0..32")
        if not math.isfinite(self.diffusion_rate) or not 0 <= self.diffusion_rate <= 1:
            raise ValueError("diffusion_rate outside [0,1]")
        if (
            not math.isfinite(self.eligibility_l1_bound)
            or not 0 < self.eligibility_l1_bound <= 4
        ):
            raise ValueError("eligibility L1 bound must be (0,4]")
        if type(self.shuffle_seed) is not int or self.shuffle_seed < 0:
            raise ValueError("shuffle seed must be nonnegative integer")
        for name, arr in (
            ("group_map", mapping),
            ("credit_graph", graph),
            ("feedback_mask", mask),
        ):
            arr.setflags(write=False)
            object.__setattr__(self, name, arr)

    @property
    def digest(self):
        return _digest(
            {
                "group_map": self.group_map,
                "credit_graph": self.credit_graph,
                "feedback_mask": self.feedback_mask,
                "config": [
                    self.truncation,
                    self.diffusion_steps,
                    self.diffusion_rate,
                    self.eligibility_l1_bound,
                    self.shuffle_seed,
                ],
            }
        )


def make_rule(model, sparse_feedback=False, truncation=4):
    """Fixed ring transport and type-average head projection, without fitting."""
    width = len(model.bias)
    mapping = np.zeros((7, model.head.shape[0]))
    for group in range(7):
        indices = [i for i, t in enumerate(model.cell_types) if t == group]
        if indices:
            row = model.head[:, indices].mean(axis=1)
            mapping[group] = row / max(1.0, np.abs(row).sum())
    graph = 0.5 * np.eye(width)
    for i in range(width):
        graph[i, (i - 1) % width] += 0.25
        graph[i, (i + 1) % width] += 0.25
    mask = np.ones(width)
    if sparse_feedback:
        mask[:] = 0
        mask[::3] = 1
    return Rule(mapping, graph, mask, truncation=truncation)


def _episode(model, inputs, targets, feedback, messages):
    inputs = _array(inputs, 2, "inputs")
    targets = _array(targets, 2, "targets")
    feedback = _array(feedback, 1, "feedback")
    steps = len(inputs)
    if not 1 <= steps <= 4096 or inputs.shape[1] != model.input.shape[1]:
        raise ValueError("input sequence outside pilot dimensions")
    if targets.shape != (steps, model.head.shape[0]) or feedback.shape != (steps,):
        raise ValueError("target/feedback shape mismatch")
    if np.any(np.abs(targets) > 8):
        raise ValueError("targets exceed declared absolute bound 8")
    if np.any(feedback < 0) or not np.isclose(feedback.sum(), 1.0, rtol=0, atol=1e-12):
        raise ValueError("feedback must be nonnegative and sum to one")
    messages = (
        np.zeros((steps, len(model.bias)))
        if messages is None
        else _array(messages, 2, "messages")
    )
    if messages.shape != (steps, len(model.bias)):
        raise ValueError("message shape mismatch")
    if np.max(np.abs(inputs)) > 8 or np.max(np.abs(messages)) > 8:
        raise ValueError("inputs/messages exceed declared absolute bound 8")
    return inputs, targets, feedback, messages


def forward(model, inputs, messages=None):
    inputs = _array(inputs, 2, "inputs")
    n, width = len(inputs), len(model.bias)
    if not 1 <= n <= 4096 or inputs.shape[1] != model.input.shape[1]:
        raise ValueError("input shape mismatch")
    messages = (
        np.zeros((n, width)) if messages is None else _array(messages, 2, "messages")
    )
    if (
        messages.shape != (n, width)
        or np.max(np.abs(inputs)) > 8
        or np.max(np.abs(messages)) > 8
    ):
        raise ValueError("message shape or input/message bound mismatch")
    states = np.zeros((n + 1, width))
    for t in range(n):
        states[t + 1] = np.tanh(
            model.input @ inputs[t]
            + model.recurrent @ states[t]
            + model.bias
            + messages[t]
        )
    return states, states[1:] @ model.head.T


def flatten(values):
    return np.concatenate([np.asarray(values[name]).ravel() for name in LAYERS])


def compare_gradients(estimate, reference):
    a, b = flatten(estimate), flatten(reference)
    if a.shape != b.shape:
        raise ValueError("gradient dimensions differ")
    a_scale, a_unit, an = _norm_components(a)
    b_scale, b_unit, bn = _norm_components(b)
    cosine = None
    if a_scale != 0 and b_scale != 0:
        cosine = float(
            np.clip(((a / a_scale) / a_unit) @ ((b / b_scale) / b_unit), -1, 1)
        )
    with np.errstate(over="raise", invalid="raise"):
        difference = a - b
    return {
        "estimate_l2": an,
        "reference_l2": bn,
        "cosine": cosine,
        "relative_l2_error": None if b_scale == 0 else _relative_l2(difference, b),
    }


def gradient(model, inputs, targets, feedback, method="bptt", rule=None, messages=None):
    """Compute one loss gradient estimate on the same immutable trajectory.

    tBPTT detaches at nonoverlapping chunk boundaries. A truncation >= horizon
    is exactly BPTT. Local recurrences keep only each unit's self dependency;
    the eligibility projection is recorded. All costs include forward. Returned
    accounted array bytes cover named core arrays only, not copies/temporaries or
    process/device peak memory.
    """
    started = time.perf_counter()
    if method not in METHODS:
        raise ValueError("unknown credit method")
    inputs, targets, feedback, messages = _episode(
        model, inputs, targets, feedback, messages
    )
    rule = make_rule(model) if rule is None else rule
    if (
        len(rule.feedback_mask) != len(model.bias)
        or rule.group_map.shape[1] != model.head.shape[0]
    ):
        raise ValueError("rule/model mismatch")
    states, outputs = forward(model, inputs, messages)
    errors = outputs - targets
    grads = {name: np.zeros_like(value) for name, value in model.parameters().items()}
    projection_count = 0
    modulator_clip_count = 0
    max_eligibility_l1 = 0.0
    transport_digest = None
    if method in ("bptt", "tbptt"):
        carry = np.zeros_like(model.bias)
        for t in range(len(inputs) - 1, -1, -1):
            dz = (feedback[t] * (model.head.T @ errors[t]) + carry) * (
                1 - states[t + 1] ** 2
            )
            grads["input"] += np.outer(dz, inputs[t])
            grads["recurrent"] += np.outer(dz, states[t])
            grads["bias"] += dz
            carry = model.recurrent.T @ dz
            if method == "tbptt" and t % rule.truncation == 0:
                carry.fill(0)
        extra_bytes = carry.nbytes
    else:
        traces = {
            name: np.zeros_like(value) for name, value in model.parameters().items()
        }
        transport = rule.credit_graph
        if method == "shuffled_diffusion":
            perm = np.random.default_rng(rule.shuffle_seed).permutation(len(model.bias))
            transport = transport[np.ix_(perm, perm)]
        transport_digest = _digest({"transport": transport})
        for t in range(len(inputs)):
            derivative = 1 - states[t + 1] ** 2
            self_path = derivative * np.diag(model.recurrent)
            traces["input"] = (
                self_path[:, None] * traces["input"] + derivative[:, None] * inputs[t]
            )
            traces["recurrent"] = (
                self_path[:, None] * traces["recurrent"]
                + derivative[:, None] * states[t]
            )
            traces["bias"] = self_path * traces["bias"] + derivative
            norm = float(np.abs(flatten(traces)).sum())
            if norm > rule.eligibility_l1_bound:
                for name in LAYERS:
                    traces[name] *= rule.eligibility_l1_bound / norm
                projection_count += 1
            max_eligibility_l1 = max(
                max_eligibility_l1, float(np.abs(flatten(traces)).sum())
            )
            if feedback[t] == 0:
                continue
            modulator_clip_count += int(np.count_nonzero(np.abs(errors[t]) > 1))
            modulator = np.clip(errors[t], -1, 1)
            if method == "three_factor":
                # A declared untuned baseline, not the best three-factor rule.
                # Opposite signed rows (and unused rows) can attenuate the mean.
                common_map = rule.group_map.mean(axis=0)
                q = np.full(len(model.bias), common_map @ modulator)
            else:
                q = rule.group_map[np.asarray(model.cell_types)] @ modulator
            q *= rule.feedback_mask
            if method in ("diffusion", "shuffled_diffusion"):
                for _ in range(rule.diffusion_steps):
                    q = (1 - rule.diffusion_rate) * q + rule.diffusion_rate * (
                        transport @ q
                    )
            for name in LAYERS:
                grads[name] += (
                    feedback[t] * (q if name == "bias" else q[:, None]) * traces[name]
                )
        extra_bytes = sum(a.nbytes for a in traces.values()) + rule.credit_graph.nbytes
    if not all(np.isfinite(a).all() for a in grads.values()):
        raise ArithmeticError("nonfinite gradient; candidate refused")
    return {
        "loss": float(0.5 * np.sum(feedback[:, None] * errors**2)),
        "gradients": grads,
        "outputs": outputs,
        "states": states,
        "method": method,
        "model_digest": model.digest,
        "rule_digest": rule.digest,
        "credit_transport_digest": transport_digest,
        "eligibility_projection_count": projection_count,
        "maximum_eligibility_l1": max_eligibility_l1,
        "modulator_clip_count": modulator_clip_count,
        "wall_seconds": time.perf_counter() - started,
        "accounted_core_array_bytes": states.nbytes
        + outputs.nbytes
        + extra_bytes
        + sum(a.nbytes for a in grads.values()),
        "peak_memory_bytes": None,
        "evidence_scope": "fp64_tanh_reference_only",
        "production_activation": False,
    }


def finite_difference(model, inputs, targets, feedback, messages=None, epsilon=1e-6):
    """Central finite difference for the identical objective; diagnostic only."""
    if not math.isfinite(epsilon) or epsilon <= 0:
        raise ValueError("epsilon must be positive")
    inputs, targets, feedback, messages = _episode(
        model, inputs, targets, feedback, messages
    )
    result = {name: np.zeros_like(array) for name, array in model.parameters().items()}
    for name, layer in model.parameters().items():
        for index in np.ndindex(layer.shape):
            losses = []
            for sign in (1, -1):
                values = {
                    key: value.copy() for key, value in model.parameters().items()
                }
                values[name][index] += sign * epsilon
                perturbed = Model(
                    **values, head=model.head, cell_types=model.cell_types
                )
                _, output = forward(perturbed, inputs, messages)
                losses.append(
                    float(0.5 * np.sum(feedback[:, None] * (output - targets) ** 2))
                )
            result[name][index] = (losses[0] - losses[1]) / (2 * epsilon)
    return result


def propose(
    model,
    gradients,
    learning_rate=0.1,
    layer_relative_bound=0.005,
    global_relative_bound=0.0025,
):
    """Return a new research candidate under actual selected-tensor L2 bounds.

    Zero-norm layers cannot receive a nonzero proposal. Native integer Q64
    checks, quantization/sign constraints, provenance and adoption remain owned
    by the production learning.plasticity path; this FP64 result grants none.
    """
    if set(gradients) != set(LAYERS):
        raise ValueError("gradient layer set must be complete")
    for value, maximum in (
        (learning_rate, float("inf")),
        (layer_relative_bound, 0.005),
        (global_relative_bound, 0.0025),
    ):
        if not math.isfinite(value) or value < 0 or value > maximum:
            raise ValueError("invalid learning rate or relaxed trust bound")
    before = model.digest
    deltas = {}
    for name, selected in model.parameters().items():
        grad = _array(gradients[name], selected.ndim, name)
        if grad.shape != selected.shape:
            raise ValueError("gradient shape mismatch")
        with np.errstate(over="raise", invalid="raise"):
            delta = -learning_rate * grad
        maximum = layer_relative_bound * _safe_l2(selected)
        scale, unit, norm = _norm_components(delta)
        if norm > maximum:
            # Normalize before multiplying the bound: maximum/norm can underflow.
            delta = ((delta / scale) / unit) * maximum
        deltas[name] = delta
    max_global = global_relative_bound * _safe_l2(flatten(model.parameters()))
    scale, unit, norm = _norm_components(flatten(deltas))
    if norm > max_global:
        deltas = {
            name: ((delta / scale) / unit) * max_global
            for name, delta in deltas.items()
        }
    candidate = Model(
        **{
            name: selected + deltas[name]
            for name, selected in model.parameters().items()
        },
        head=model.head,
        cell_types=model.cell_types,
    )
    # Measure actual rounded changes, not only planned values.
    actual = {
        name: getattr(candidate, name) - selected
        for name, selected in model.parameters().items()
    }
    layer_ratios = {
        name: _relative_l2(actual[name], selected)
        for name, selected in model.parameters().items()
    }
    global_ratio = _relative_l2(flatten(actual), flatten(model.parameters()))
    changed = any(np.count_nonzero(value) for value in actual.values())
    if (changed and (layer_relative_bound == 0 or global_relative_bound == 0)) or (
        any(v > layer_relative_bound + 1e-12 for v in layer_ratios.values())
        or global_ratio > global_relative_bound + 1e-12
    ):
        raise ArithmeticError("rounded candidate violated trust region")
    if model.digest != before:
        raise AssertionError("selected artifact changed")
    return candidate, {
        "selected_digest": before,
        "candidate_digest": candidate.digest,
        "layer_relative_norms": layer_ratios,
        "global_relative_norm": global_ratio,
        "no_update": all(np.count_nonzero(v) == 0 for v in actual.values()),
        "native_adoption_qualified": False,
    }


def intervene_messages(messages, step, kind, replacement=None, delay=1):
    """Edit one early exogenous message; labels and encoder are held fixed."""
    changed = _array(messages, 2, "messages")
    if type(step) is not int or not 0 <= step < len(changed):
        raise ValueError("invalid message step")
    old = changed[step].copy()
    if kind == "mask":
        changed[step] = 0
    elif kind == "replace":
        value = _array(replacement, 1, "replacement")
        if value.shape != old.shape:
            raise ValueError("replacement shape mismatch")
        changed[step] = value
    elif kind == "delay":
        if type(delay) is not int or delay < 1:
            raise ValueError("delay must be positive integer")
        changed[step] = 0
        if step + delay < len(changed):
            changed[step + delay] += old
    else:
        raise ValueError("unknown intervention")
    if np.max(np.abs(changed)) > 8:
        raise ValueError("intervention exceeds message bound")
    return changed


def causal_probe(
    model, inputs, targets, feedback, messages, step, method, rule, delay=2
):
    """Re-run forward AND credit for paired early-message interventions."""
    baseline = gradient(model, inputs, targets, feedback, method, rule, messages)
    base_candidate, _ = propose(model, baseline["gradients"])
    rows = []
    for kind in ("mask", "replace", "delay"):
        changed = intervene_messages(
            messages, step, kind, replacement=-np.asarray(messages)[step], delay=delay
        )
        observed = gradient(model, inputs, targets, feedback, method, rule, changed)
        candidate, receipt = propose(model, observed["gradients"])
        rows.append(
            {
                "kind": kind,
                "step": step,
                "delay": delay if kind == "delay" else None,
                "message_digest": _digest({"messages": changed}),
                "loss_difference": observed["loss"] - baseline["loss"],
                "final_output_difference_l2": _safe_l2(
                    observed["outputs"][-1] - baseline["outputs"][-1]
                ),
                "gradient_difference_l2": _safe_l2(
                    flatten(observed["gradients"]) - flatten(baseline["gradients"])
                ),
                "candidate_difference_l2": _safe_l2(
                    flatten(candidate.parameters())
                    - flatten(base_candidate.parameters())
                ),
                "candidate_receipt": receipt,
            }
        )
    return {
        "model_digest": model.digest,
        "method": method,
        "baseline_loss": baseline["loss"],
        "original_message_digest": _digest({"messages": messages}),
        "interventions": rows,
        "causal_scope": "paired_synthetic_message_effects_not_real_world_credit_validation",
    }


def copy_episode(rng, horizon=12):
    """Bounded synthetic delayed-copy fixture; no external-task efficacy claim."""
    if type(horizon) is not int or not 2 <= horizon <= 4096:
        raise ValueError("horizon must be an integer in 2..4096")
    inputs = rng.normal(0, 0.015, (horizon, 2))
    cue = float(rng.choice([-0.5, 0.5]))
    inputs[0, 0] = cue
    inputs[:, 1] = np.linspace(0, 0.2, horizon)
    targets = np.full((horizon, 1), cue)
    feedback = np.zeros(horizon)
    feedback[-1] = 1
    messages = np.zeros((horizon, 7))
    messages[1, 0] = cue * 0.2
    return inputs, targets, feedback, messages


def credit_attempt_spec(
    seed,
    method,
    feedback_locations="all",
    updates=12,
    horizon=12,
    include_causal_probe=False,
):
    """Declare one opportunity without generating data or executing training.

    The identity includes its declared budget and diagnostic coverage. An outer
    runner can persist the entire roster before calling run_credit_attempt once
    per entry. A rerun needs a separate outer attempt ID/record; it must not
    replace a failed result in the scientific denominator.
    """
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer, not bool")
    if type(updates) is not int or updates < 1:
        raise ValueError("updates must be a positive integer, not bool")
    if type(horizon) is not int or not 2 <= horizon <= 4096:
        raise ValueError("horizon must be an integer in 2..4096")
    if not isinstance(method, str) or method not in METHODS:
        raise ValueError("unknown credit method")
    if feedback_locations not in ("all", "sparse"):
        raise ValueError("feedback_locations must be all or sparse")
    if type(include_causal_probe) is not bool:
        raise ValueError("include_causal_probe must be bool")
    budget = {
        "optimizer_updates": updates,
        "training_episodes": updates,
        "training_observations": updates * horizon,
        "training_observation_unit": "encoded_timestep_presentations",
        "evaluation_episodes_per_model": 12,
        "evaluation_observations_per_model": 12 * horizon,
        "diagnostic_gradient_calls": 2,
        "causal_gradient_calls": 4 if include_causal_probe else 0,
        "causal_proposal_calls": 4 if include_causal_probe else 0,
        "tuning_trials": 0,
        "fixed_configurations": 1,
        "tuning_protocol": "one_fixed_configuration_without_search",
        "wall_timeout_seconds": None,
        "physical_energy_joules": None,
    }
    identity = {
        "family": "credit",
        "method": method,
        "seed": seed,
        "feedback_locations": feedback_locations,
        "updates": updates,
        "horizon": horizon,
        "include_causal_probe": include_causal_probe,
    }
    return {
        "attempt_id": "credit:" + canonical_digest(identity)[:24],
        **identity,
        "budget": budget,
        "spec_digest": canonical_digest({**identity, "budget": budget}),
    }


def run_credit_attempt(
    seed,
    method,
    feedback_locations="all",
    updates=12,
    horizon=12,
    include_causal_probe=False,
):
    """Execute exactly one declared method/seed/location attempt.

    Runtime exceptions become failed records with their completed work retained.
    KeyboardInterrupt/SystemExit propagate: an outer durable runner must record
    its interruption, not fabricate completion. Invalid input is rejected before
    starting. Observation counts distinguish successful gradient evaluations
    from committed candidate proposals, including a gradient whose proposal fails.
    The comparison profile uses actual counts; its planned counterpart is explicit.
    """
    spec = credit_attempt_spec(
        seed, method, feedback_locations, updates, horizon, include_causal_probe
    )
    started = time.perf_counter()
    cpu_started = time.process_time()
    record = {
        **spec,
        "status": "running",
        "reason": None,
        "failure_stage": None,
        "completed_updates": 0,
        "changed_parameter_updates": 0,
        "training_gradient_calls_started": 0,
        "training_gradient_calls_completed": 0,
        "completed_training_observations": 0,
        "completed_initial_evaluation_episodes": 0,
        "completed_final_evaluation_episodes": 0,
        "source_identity_at_import": _IMPORTED_SOURCE,
        "source_identity_at_start": None,
        "source_identity_at_end": None,
        "planned_profile": None,
        "comparison_profile": None,
        "gradient_diagnostic": None,
        "causal_intervention": None,
    }
    row = {
        "seed": seed,
        "feedback_locations": feedback_locations,
        "method": method,
        "updates": updates,
        "horizon": horizon,
        "initial_model_digest": None,
        "final_model_digest": None,
        "rule_digest": None,
        "train_losses": [],
        "eval_initial_losses": [],
        "eval_final_losses": [],
        "mean_eval_loss_change": None,
        "train_wall_seconds": 0.0,
        "maximum_step_global_relative_norm": 0.0,
        "update_receipts": [],
        "physical_energy_joules": None,
        "production_activation": False,
        "three_factor_definition": _THREE_FACTOR_DEFINITION,
        "three_factor_limitation": _THREE_FACTOR_LIMIT,
        "three_factor_optimality_claim": False,
    }
    record["result"] = row
    observed_episode_digests = []
    applied_models = []
    model = None
    train_started = None
    stage = "source_identity"
    try:
        record["source_identity_at_start"] = source_inventory(
            _SOURCE_ROOT, _SOURCE_FILES
        )
        if record["source_identity_at_start"] != _IMPORTED_SOURCE:
            raise RuntimeError(
                "source files changed since module import; new process required"
            )
        stage = "prepare_data_and_model"
        initial = make_model(seed)
        model = initial
        # Explicit namespaces avoid additive seed-offset collisions across fits.
        train_rng = np.random.default_rng(np.random.SeedSequence([seed, 10000]))
        eval_rng = np.random.default_rng(np.random.SeedSequence([seed, 20000]))
        train = [copy_episode(train_rng, horizon) for _ in range(updates)]
        evaluation = [copy_episode(eval_rng, horizon) for _ in range(12)]
        split_digests = {}
        train_digests = []
        for split_name, episodes in (("train", train), ("evaluation", evaluation)):
            episode_digests = [
                _digest(dict(zip(("inputs", "targets", "feedback", "messages"), ep)))
                for ep in episodes
            ]
            split_digests[split_name] = canonical_digest(episode_digests)
            if split_name == "train":
                train_digests = episode_digests
        split_identity = {
            "seed": seed,
            "rng": "numpy.PCG64_SeedSequence_namespaced",
            "namespace_words": {"train": 10000, "evaluation": 20000},
            "episode_counts": {"train": updates, "evaluation": 12},
            "content_digests": split_digests,
            "horizon": horizon,
        }
        rule = make_rule(initial, sparse_feedback=feedback_locations == "sparse")
        device_detail = {
            "backend": "numpy_cpu",
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "device_energy_sensor": None,
        }
        profile = {
            "encoder_digest": canonical_digest(
                {
                    "kind": "identity",
                    "input_dim": 2,
                    "normalization": "none",
                    "bound": 8,
                    "precision": "float64",
                }
            ),
            "head_initial_digest": _digest({"head": initial.head}),
            "data_split_digest": canonical_digest(split_identity),
            "ndu_profile_digest": canonical_digest(
                {
                    "enabled": False,
                    "profile": "no_ndu_controller_no_recursive_utility_optimization",
                }
            ),
            "training_observations": updates * horizon,
            "optimizer_updates": updates,
            "tuning_trials": 0,
            "fixed_configurations": 1,
            "seed": seed,
            "device_profile": "numpy_cpu:" + canonical_digest(device_detail),
            "precision": "float64",
            "training_scope": "tanh_cell_input_recurrent_bias_with_frozen_identity_encoder_and_head",
            "source_digest": _IMPORTED_SOURCE["digest"],
            "initial_model_digest": initial.digest,
            "initial_state_digest": _digest(
                {"initial_state": np.zeros(len(initial.bias))}
            ),
            "data_split_identity": split_identity,
            "device_profile_detail": device_detail,
            "feedback_timing": "terminal_only",
            "ndu_enabled": False,
        }
        record["planned_profile"] = dict(profile)
        row.update(
            initial_model_digest=initial.digest,
            final_model_digest=model.digest,
            rule_digest=rule.digest,
            common_map_l1=float(np.abs(rule.group_map.mean(axis=0)).sum()),
            mean_group_map_l1=float(np.abs(rule.group_map).sum(axis=1).mean()),
        )
        stage = "gradient_diagnostic"
        ep = train[0]
        oracle = gradient(initial, *ep[:3], "bptt", rule, ep[3])
        estimate = gradient(initial, *ep[:3], method, rule, ep[3])
        record["gradient_diagnostic"] = {
            "seed": seed,
            "feedback_locations": feedback_locations,
            "method": method,
            **compare_gradients(estimate["gradients"], oracle["gradients"]),
            "rule_digest": rule.digest,
            "model_digest": initial.digest,
            "maximum_eligibility_l1": estimate["maximum_eligibility_l1"],
        }
        stage = "training"
        train_started = time.perf_counter()
        for index, ep in enumerate(train):
            record["training_gradient_calls_started"] += 1
            estimate = gradient(model, *ep[:3], method, rule, ep[3])
            record["training_gradient_calls_completed"] += 1
            record["completed_training_observations"] += horizon
            observed_episode_digests.append(train_digests[index])
            applied_models.append(model.digest)
            row["train_losses"].append(estimate["loss"])
            candidate, receipt = propose(model, estimate["gradients"])
            model = candidate
            record["completed_updates"] += 1
            record["changed_parameter_updates"] += int(not receipt["no_update"])
            row["update_receipts"].append(receipt)
            row["maximum_step_global_relative_norm"] = max(
                row["maximum_step_global_relative_norm"],
                receipt["global_relative_norm"],
            )
        row["train_wall_seconds"] = time.perf_counter() - train_started
        train_started = None
        stage = "evaluation"
        for ep in evaluation:
            observed = gradient(initial, *ep[:3], "bptt", rule, ep[3])
            row["eval_initial_losses"].append(observed["loss"])
            record["completed_initial_evaluation_episodes"] += 1
            observed = gradient(model, *ep[:3], "bptt", rule, ep[3])
            row["eval_final_losses"].append(observed["loss"])
            record["completed_final_evaluation_episodes"] += 1
        row["mean_eval_loss_change"] = float(
            np.mean(row["eval_final_losses"]) - np.mean(row["eval_initial_losses"])
        )
        if include_causal_probe:
            stage = "causal_intervention"
            ep = train[0]
            record["causal_intervention"] = {
                "feedback_locations": feedback_locations,
                **causal_probe(initial, *ep[:3], ep[3], 1, method, rule),
            }
        stage = "final_source_identity"
        record["source_identity_at_end"] = source_inventory(_SOURCE_ROOT, _SOURCE_FILES)
        if record["source_identity_at_end"] != _IMPORTED_SOURCE:
            raise RuntimeError("source files changed during attempt")
        record["status"] = "completed"
    except Exception as error:
        # Deliberately not BaseException: cancellation/termination must propagate.
        record.update(
            status="failed",
            reason=type(error).__name__ + ": " + str(error),
            failure_stage=stage,
        )
    finally:
        if train_started is not None:
            row["train_wall_seconds"] = time.perf_counter() - train_started
        if model is not None:
            row["final_model_digest"] = model.digest
        row["completed_updates"] = record["completed_updates"]
        row["completed_training_observations"] = record[
            "completed_training_observations"
        ]
        record["training_observation_coverage"] = (
            "complete_for_started_gradient_calls"
            if record["training_gradient_calls_started"]
            == record["training_gradient_calls_completed"]
            else "lower_bound_incomplete_gradient_call"
        )
        record["training_observation_digest"] = canonical_digest(
            {
                "completed_episode_digests_in_order": observed_episode_digests,
                "observations_per_episode": horizon,
                "completed_observations": record["completed_training_observations"],
            }
        )
        record["training_model_application_digest"] = canonical_digest(applied_models)
        if record["planned_profile"] is not None:
            record["comparison_profile"] = {
                **record["planned_profile"],
                "training_observations": record["completed_training_observations"],
                "optimizer_updates": record["completed_updates"],
                "training_observation_digest": record["training_observation_digest"],
                "training_observation_coverage": record[
                    "training_observation_coverage"
                ],
                "final_model_digest": row["final_model_digest"],
            }
            record["comparison_profile_digest"] = canonical_digest(
                record["comparison_profile"]
            )
        record["attempt_wall_seconds"] = time.perf_counter() - started
        record["attempt_process_cpu_seconds"] = time.process_time() - cpu_started
    return record


def run_credit_panel(seeds=(11, 29, 47), updates=12, horizon=12):
    """Fixed-budget panel retaining every declared opportunity and failure.

    Roster declaration precedes all training. Independent seeds, exact initial
    tensors, encoder/head, train/evaluation payloads and the disabled NDU profile
    are bound per attempt. The single fixed three-factor map may cancel signed
    rows; this is not an optimized three-factor family comparison. Physical
    energy and full process memory remain unmeasured. Runtime exceptions do not
    remove earlier successful or failed attempts from the denominator.
    """
    if not isinstance(seeds, (tuple, list)) or len(seeds) < 2:
        raise ValueError("seeds must be a list/tuple of at least two distinct integers")
    for seed in seeds:
        credit_attempt_spec(seed, "bptt", "all", updates, horizon)
    if len(set(seeds)) != len(seeds):
        raise ValueError("seeds must be distinct")
    roster = [
        credit_attempt_spec(
            seed,
            method,
            location,
            updates,
            horizon,
            include_causal_probe=seed == seeds[0],
        )
        for seed in seeds
        for location in ("all", "sparse")
        for method in METHODS
    ]
    attempts = [
        run_credit_attempt(
            spec["seed"],
            spec["method"],
            spec["feedback_locations"],
            spec["updates"],
            spec["horizon"],
            spec["include_causal_probe"],
        )
        for spec in roster
    ]
    rows = [
        {
            **record["result"],
            "attempt_id": record["attempt_id"],
            "status": record["status"],
            "reason": record["reason"],
            "failure_stage": record["failure_stage"],
            "budget": record["budget"],
            "comparison_profile": record["comparison_profile"],
            "training_observation_digest": record["training_observation_digest"],
        }
        for record in attempts
    ]
    return {
        "schema": "hepta.cell-credit-panel.v2",
        "scope": "synthetic_numerical_pilot",
        "seeds": list(seeds),
        "independent_training_seed_count": len(seeds),
        "planned_attempts": len(roster),
        "training_runs": len(attempts),
        "completed_training_runs": sum(r["status"] == "completed" for r in attempts),
        "failed_training_runs": sum(r["status"] == "failed" for r in attempts),
        "completed_optimizer_updates": sum(r["completed_updates"] for r in attempts),
        "updates_per_run": updates,
        "roster": roster,
        "attempts": attempts,
        "data_split": "content_bound_namespaced_training_and_evaluation_episode_streams",
        "feedback_time": "terminal_only",
        "local_eligibility": "self_recurrence_derivative_l1_projected",
        "modulator": "observed_output_residual_clipped_to_unit_interval",
        "three_factor_definition": _THREE_FACTOR_DEFINITION,
        "three_factor_limitation": _THREE_FACTOR_LIMIT,
        "native_q24_equivalence": False,
        "real_terminal_utility_qualified": False,
        "physical_energy_qualified": False,
        "efficacy_claim": "withheld",
        "rows": rows,
        "gradient_diagnostics": [
            r["gradient_diagnostic"]
            for r in attempts
            if r["gradient_diagnostic"] is not None
        ],
        "causal_interventions": [
            r["causal_intervention"]
            for r in attempts
            if r["causal_intervention"] is not None
        ],
    }
