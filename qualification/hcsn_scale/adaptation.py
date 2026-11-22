"""Conditional next-sensor learning with explicit BP, KEEP and bounded-edit arms.

This extends SequenceModel rather than defining another network. Direct solves
use mechanism_v2's centered SVD ridge problem with one shared factorization and
multiple target columns; its existing objective is reused unchanged. Profiling
holds the optimal readout fixed for the envelope derivative, as in profiled.py;
the nonlinear encoder still uses BP. No test split or external labels are read.
Timings are synchronous CPU/FP64 and include every feature/selection query.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass
import math
import time

import torch

from qualification.hcsn_mechanism_v2.readout import objective
from .model import tensor_map_digest


METHODS = ("keep", "direct", "profile_bp", "joint_bp", "bounded_edit")


@dataclass(frozen=True)
class AdaptationConfig:
    steps: int = 8
    learning_rate: float = 0.001
    ridge: float = 0.001
    gradient_clip: float = 1.0
    max_edit_l2: float = 0.25
    max_edit_linf: float = 0.1
    min_dev_improvement: float = 0.0
    preservation_tolerance: float = 0.01

    def __post_init__(self):
        positive = (
            self.learning_rate,
            self.ridge,
            self.gradient_clip,
            self.max_edit_l2,
            self.max_edit_linf,
        )
        if (
            type(self.steps) is not int
            or not 1 <= self.steps <= 256
            or any(not math.isfinite(v) or v <= 0 for v in positive)
            or self.ridge >= 100
            or self.learning_rate > 1
            or any(
                not math.isfinite(v) or v < 0
                for v in (self.min_dev_improvement, self.preservation_tolerance)
            )
        ):
            raise ValueError(
                "finite positive optimization bounds and nonnegative selection tolerances required"
            )


def collect_next_sensor(model, windows, intervals):
    """Collect differentiable X and observed next-sensor Y; no label solver here."""
    if (
        windows.ndim != 3
        or len(windows) < 1
        or windows.shape[1] < 2
        or windows.shape[2] != model.config.input_size
        or tuple(intervals.shape) != tuple(windows.shape[:2])
        or not bool(torch.isfinite(windows).all())
    ):
        raise ValueError(
            "matching nonempty sensor windows and physical intervals required"
        )
    features = model.encode_batch(windows[:, :-1], intervals[:, :-1])
    return features.flatten(0, 1), windows[:, 1:].flatten(0, 1)


@torch.no_grad()
def fit_predictor(model, features, targets, ridge):
    """One centered SVD, all sensor targets; same per-output ridge problem.

    Factorization is shared only across right-hand sides for this exact design.
    No factorization or feature cache survives an encoder/clock/split change.
    """
    if (
        features.dtype != torch.float64
        or targets.dtype != torch.float64
        or features.ndim != 2
        or targets.ndim != 2
        or len(features) < 1
        or len(targets) != len(features)
        or model.predictor.weight.dtype != torch.float64
        or features.shape[1] != model.predictor.in_features
        or targets.shape[1] != model.predictor.out_features
        or not bool(torch.isfinite(features).all())
        or not bool(torch.isfinite(targets).all())
        or not 0 < ridge < 100
    ):
        raise ValueError(
            "FP64 features and targets matching the existing predictor required"
        )
    xm, ym = features.mean(0), targets.mean(0)
    centered, response = features - xm, targets - ym
    u, singular, vh = torch.linalg.svd(centered, full_matrices=False)
    weight = vh.T @ (
        (singular / (singular.square() + ridge))[:, None] * (u.T @ response)
    )
    bias = ym - xm @ weight
    model.predictor.weight.copy_(weight.T)
    model.predictor.bias.copy_(bias)
    residual = centered.T @ (centered @ weight - response) + ridge * weight
    minimum = (
        float(singular[-1].square()) if len(singular) == features.shape[1] else 0.0
    )
    condition = (float(singular[0].square()) + ridge) / (minimum + ridge)
    objective_sum = (features @ weight + bias - targets).square().sum(
        0
    ) + ridge * weight.square().sum(0)
    return [
        {
            "solver": "centered_svd_multiple_rhs",
            "shared_factorizations": 1,
            "ridge": ridge,
            "penalized_condition": condition,
            "normal_equation_residual_l2": float(
                torch.linalg.vector_norm(residual[:, column])
            ),
            "objective_sum": float(objective_sum[column]),
        }
        for column in range(targets.shape[1])
    ]


def conditional_objective(model, features, targets, ridge):
    """Mean across target coordinates of the existing conditional objective."""
    return torch.stack(
        [
            objective(
                features,
                targets[:, column],
                model.predictor.weight[column],
                model.predictor.bias[column],
                ridge,
            )
            for column in range(targets.shape[1])
        ]
    ).mean()


def _snapshot(model):
    return {name: value.detach().clone() for name, value in model.state_dict().items()}


def _apply_bounded_edit(model, edit, names, config):
    if (
        not isinstance(edit, dict)
        or not edit
        or any(name not in names for name in edit)
    ):
        return {
            "eligible": False,
            "reason": "edit uses undeclared or empty parameter support",
        }
    parameters, deltas = dict(model.named_parameters()), {}
    for name, value in edit.items():
        delta = torch.as_tensor(
            value, dtype=parameters[name].dtype, device=parameters[name].device
        )
        if delta.shape != parameters[name].shape or not bool(
            torch.isfinite(delta).all()
        ):
            return {"eligible": False, "reason": "nonfinite or shape-mismatched edit"}
        deltas[name] = delta.detach()
    l2 = math.sqrt(sum(float(value.square().sum()) for value in deltas.values()))
    linf = max(float(value.abs().max()) for value in deltas.values())
    manifest = {
        "eligible": l2 <= config.max_edit_l2 and linf <= config.max_edit_linf,
        "delta_l2": l2,
        "delta_linf": linf,
        "support": sorted(deltas),
        "edit_digest": tensor_map_digest(deltas),
    }
    if not manifest["eligible"]:
        return {**manifest, "reason": "edit norm exceeds declared bound"}
    with torch.no_grad():
        for name, delta in deltas.items():
            parameters[name].add_(delta)
    return manifest


def adapt_model(
    model,
    train_windows,
    train_intervals,
    dev_windows,
    dev_intervals,
    *,
    method="direct",
    config=None,
    edits=None,
    editable_names=None,
    preservation=None,
):
    """Return selected model, JSON-safe ledger, and all candidate tensor states.

    Selection compares dev next-sensor MSE against KEEP and then the best admitted
    candidate. Preservation bounds MSE increase on supplied windows relative to
    KEEP; it cannot guarantee preservation elsewhere. An unsuccessful search
    returns KEEP. Bounded edits are caller-supplied deltas, each applied to the
    common initial encoder, followed by an explicitly charged conditional solve.
    The bound covers encoder deltas, not that separate readout solve.
    """
    started, cpu_started = time.perf_counter(), time.process_time()
    config = config or AdaptationConfig()
    if method not in METHODS or any(
        p.device.type != "cpu" or p.dtype != torch.float64 for p in model.parameters()
    ):
        raise ValueError("declared adaptation method and CPU/FP64 model required")
    available = {
        name
        for name, _ in model.named_parameters()
        if not name.startswith("predictor.")
    }
    names = tuple(sorted(available if editable_names is None else editable_names))
    if (
        not names
        or len(set(names)) != len(names)
        or any(name not in available for name in names)
    ):
        raise ValueError("nonempty unique declared encoder parameter names required")
    if method == "bounded_edit" and (
        not isinstance(edits, (list, tuple)) or not 1 <= len(edits) <= 64
    ):
        raise ValueError(
            "bounded-edit arm requires one to 64 explicit edit dictionaries"
        )
    working, selected = deepcopy(model), deepcopy(model)
    initial = _snapshot(model)
    costs = {
        "feature_forward_calls": 0,
        "sensor_transition_rows": 0,
        "backward_evaluations": 0,
        "conditional_solves": 0,
        "conditional_rhs": 0,
        "factorizations": 0,
        "dev_queries": 0,
        "preservation_queries": 0,
        "feature_seconds": 0.0,
        "solve_seconds": 0.0,
        "backward_seconds": 0.0,
        "optimizer_seconds": 0.0,
        "selection_seconds": 0.0,
    }
    candidates, states = [], {}

    def collect(windows, intervals):
        start = time.perf_counter()
        x, y = collect_next_sensor(working, windows, intervals)
        costs["feature_seconds"] += time.perf_counter() - start
        costs["feature_forward_calls"] += 1
        costs["sensor_transition_rows"] += len(x)
        return x, y

    def fit(x, y):
        start = time.perf_counter()
        diagnostics = fit_predictor(working, x, y, config.ridge)
        costs["solve_seconds"] += time.perf_counter() - start
        costs["conditional_solves"] += 1
        costs["conditional_rhs"] += y.shape[1]
        costs["factorizations"] += 1
        return {
            "max_normal_residual": max(
                d["normal_equation_residual_l2"] for d in diagnostics
            ),
            "max_penalized_condition": max(
                d["penalized_condition"] for d in diagnostics
            ),
            "training_rows": len(x),
            "target_coordinates": y.shape[1],
            "factorizations": 1,
        }

    @torch.no_grad()
    def evaluate(windows, intervals, key):
        x, y = collect(windows, intervals)
        costs[key] += 1
        return float((working.predictor(x) - y).square().mean())

    with torch.no_grad():
        baseline_dev = evaluate(dev_windows, dev_intervals, "dev_queries")
        baseline_preservation = (
            evaluate(*preservation, "preservation_queries")
            if preservation is not None
            else None
        )
    if not math.isfinite(baseline_dev) or (
        baseline_preservation is not None and not math.isfinite(baseline_preservation)
    ):
        raise FloatingPointError("finite incumbent evaluation required")
    best_dev, best_index = baseline_dev, 0
    initial_digest = tensor_map_digest(initial)
    states[initial_digest] = initial
    candidates.append(
        {
            "index": 0,
            "kind": "keep",
            "state_digest": initial_digest,
            "dev_mse": baseline_dev,
            "preservation_mse": baseline_preservation,
            "admissible": True,
            "selected_when_seen": True,
            "reason": "incumbent",
            "elapsed_seconds": time.perf_counter() - started,
        }
    )

    def consider(kind, details):
        nonlocal best_dev, best_index
        start = time.perf_counter()
        state = _snapshot(working)
        digest = tensor_map_digest(state)
        states[digest] = state
        dev = evaluate(dev_windows, dev_intervals, "dev_queries")
        keep = (
            evaluate(*preservation, "preservation_queries")
            if preservation is not None
            else None
        )
        finite = math.isfinite(dev) and (keep is None or math.isfinite(keep))
        preserved = (
            keep is None
            or keep <= baseline_preservation + config.preservation_tolerance
        )
        admitted = finite and preserved
        improves = admitted and dev < best_dev - config.min_dev_improvement
        reason = (
            "nonfinite evaluation"
            if not finite
            else "preservation tolerance exceeded"
            if not preserved
            else "selected"
            if improves
            else "no required dev improvement"
        )
        row = {
            "index": len(candidates),
            "kind": kind,
            "state_digest": digest,
            "dev_mse": dev if math.isfinite(dev) else None,
            "preservation_mse": keep if keep is None or math.isfinite(keep) else None,
            "admissible": admitted,
            "selected_when_seen": improves,
            "reason": reason,
            **details,
            "elapsed_seconds": time.perf_counter() - started,
        }
        candidates.append(row)
        if improves:
            selected.load_state_dict(state)
            best_dev, best_index = dev, row["index"]
        costs["selection_seconds"] += time.perf_counter() - start

    if method in ("direct", "profile_bp", "joint_bp"):
        with torch.no_grad():
            x, y = collect(train_windows, train_intervals)
            diagnostics = fit(x, y)
        consider("conditional_readout", {"solver": diagnostics})
    if method in ("profile_bp", "joint_bp"):
        for name, parameter in working.named_parameters():
            parameter.requires_grad_(
                name in names
                or (method == "joint_bp" and name.startswith("predictor."))
            )
        parameters = [p for p in working.parameters() if p.requires_grad]
        start = time.perf_counter()
        optimizer = torch.optim.Adam(parameters, lr=config.learning_rate)
        costs["optimizer_seconds"] += time.perf_counter() - start
        for step in range(1, config.steps + 1):
            optimizer.zero_grad(set_to_none=True)
            x, y = collect(train_windows, train_intervals)
            diagnostics = fit(x, y) if method == "profile_bp" else None
            loss = conditional_objective(working, x, y, config.ridge)
            if not bool(torch.isfinite(loss)):
                raise FloatingPointError("nonfinite training objective")
            start = time.perf_counter()
            loss.backward()
            costs["backward_seconds"] += time.perf_counter() - start
            costs["backward_evaluations"] += 1
            if any(
                p.grad is None or not bool(torch.isfinite(p.grad).all())
                for p in parameters
            ):
                raise FloatingPointError("missing or nonfinite outer gradient")
            gradient_norm = float(
                torch.nn.utils.clip_grad_norm_(parameters, config.gradient_clip)
            )
            start = time.perf_counter()
            optimizer.step()
            costs["optimizer_seconds"] += time.perf_counter() - start
            if method == "profile_bp":
                with torch.no_grad():
                    x, y = collect(train_windows, train_intervals)
                    diagnostics = fit(x, y)
            consider(
                method,
                {
                    "step": step,
                    "training_objective_before_step": float(loss.detach()),
                    "gradient_norm_before_clip": gradient_norm,
                    "solver": diagnostics,
                },
            )
    if method == "bounded_edit":
        for index, edit in enumerate(edits):
            working.load_state_dict(initial)
            manifest = _apply_bounded_edit(working, edit, names, config)
            if not manifest["eligible"]:
                candidates.append(
                    {
                        "index": len(candidates),
                        "kind": method,
                        "edit_index": index,
                        "admissible": False,
                        "selected_when_seen": False,
                        **manifest,
                        "elapsed_seconds": time.perf_counter() - started,
                    }
                )
                continue
            with torch.no_grad():
                x, y = collect(train_windows, train_intervals)
                diagnostics = fit(x, y)
            consider(
                method, {"edit_index": index, "edit": manifest, "solver": diagnostics}
            )
    costs.update(
        total_seconds=time.perf_counter() - started,
        total_cpu_seconds=time.process_time() - cpu_started,
    )
    report = {
        "method": method,
        "config": asdict(config),
        "editable_names": list(names),
        "model_identity": model.identity(),
        "selected_index": best_index,
        "selected_state_digest": tensor_map_digest(selected.state_dict()),
        "initial_state_digest": initial_digest,
        "selected_dev_mse": best_dev,
        "candidates": candidates,
        "cost": costs,
        "test_queries": 0,
        "conditional_problem": "per output: sum next-sensor SSE + ridge * squared slope; free intercept",
        "outer_objective": "mean conditional objective across target coordinates",
        "preservation_scope": "supplied next-sensor windows only"
        if preservation is not None
        else "not measured",
        "feature_cache": "none across encoder changes or splits",
        "timing_scope": "CPU FP64; total includes copying, features, all solves and all selection queries",
        "phase_seconds_overlap": "selection_seconds includes feature evaluation time",
        "edit_scope": "caller-supplied bounded encoder deltas; separate unbounded ridge readout solve",
        "program_authoring_seconds": None,
        "program_authoring_tokens": None,
        "bp_free_claim": "conditional head and supplied edits only; profile/joint encoder use actual BP",
    }
    return selected, report, states
