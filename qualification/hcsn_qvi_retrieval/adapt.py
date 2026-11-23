"""Conditional linear solves and small physical parameter edits for a frozen trial.

Blocks have a common FP64 readout and development utility/retention callback.
Scores and targets must be in the same action order. Holdout data are never
passed to these methods. Cost counters cover this Python process and must be
supplemented with process-launch, agent-discovery and final scoring costs.
"""

import math
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass

import torch


@dataclass(frozen=True)
class FitConfig:
    ridge: float = 0.001
    steps: int = 4
    lr: float = 0.075
    radius: float = 0.35
    tie_tolerance: float = 1e-12

    def __post_init__(self):
        if self.steps < 1 or self.steps > 64 or not isinstance(self.steps, int):
            raise ValueError("steps must be an integer from 1 to 64")
        if not all(math.isfinite(v) and v > 0 for v in (self.ridge, self.lr, self.radius)):
            raise ValueError("ridge, learning rate and radius must be finite and positive")
        if not math.isfinite(self.tie_tolerance) or self.tie_tolerance < 0:
            raise ValueError("invalid tie tolerance")


@dataclass
class FitResult:
    theta: torch.Tensor
    head: torch.Tensor
    report: dict


class IncumbentFailure(RuntimeError):
    """Even the initial model could not be scored. Report retains all work."""

    def __init__(self, report):
        super().__init__("the incumbent failed evaluation")
        self.report = report


def data_arrays(h, split, row_weights=None):
    y = torch.as_tensor(split["targets"], dtype=h.dtype, device=h.device)
    y = y.reshape(-1, y.shape[-1])
    h = h.reshape(-1, h.shape[-1])
    if h.dtype != torch.float64 or y.shape[0] != h.shape[0] or h.shape[0] == 0:
        raise ValueError("expected nonempty FP64 feature and target rows of equal length")
    if not (torch.isfinite(y).all() and torch.isfinite(h).all()):
        raise ValueError("all three value targets, including masked actions, must be finite")
    if row_weights is None:
        row_weights = split.get("row_weights")
    w = torch.ones_like(y[:, 0]) if row_weights is None else torch.as_tensor(
        row_weights, dtype=h.dtype, device=h.device
    ).reshape(-1)
    if w.shape != y[:, 0].shape or not torch.isfinite(w).all() or w.min() < 0 or w.sum() <= 0:
        raise ValueError("invalid training row weights")
    return h, y, w / w.sum()


def predict(features, head):
    return features @ head[:-1] + head[-1]


def solve_readout(h, y, w, ridge):
    """Minimize sum_i w_i ||h_i W+b-y_i||² + ridge ||W||²; w sums to one."""
    xbar, ybar = w @ h, w @ y
    z = w.sqrt().unsqueeze(-1)
    u, s, vh = torch.linalg.svd((h - xbar) * z, full_matrices=False)
    slopes = vh.T @ ((s / (s.square() + ridge))[:, None] * (u.T @ ((y - ybar) * z)))
    return torch.cat((slopes, (ybar - xbar @ slopes)[None])), s


def screen_target_pair(h, y, scores, selected, *, margin=1e-6, head_radius=None):
    """A necessary Frobenius-radius lower bound for a pair of frozen-feature ranks."""
    i, j, a, b = (int(v) for v in selected)
    target = (y[:, a] - y[:, b])[[i, j]]
    if not (i != j and a != b and float(target[0]) > 0 and float(target[1]) < 0):
        raise ValueError("expected opposite strict target preferences")
    if not math.isfinite(margin) or margin <= 0:
        raise ValueError("requested margin must be positive")
    if head_radius is not None and (not math.isfinite(head_radius) or head_radius < 0):
        raise ValueError("invalid optional readout-edit norm bound")
    dx = h[i] - h[j]
    norm = float(torch.linalg.vector_norm(dx))
    gap = (scores[:, a] - scores[:, b])[[i, j]]
    deficit = max(0.0, 2 * margin - float(gap[0] - gap[1]))
    exact_duplicate = bool(torch.equal(h[i], h[j]))
    lower = None if norm == 0 else deficit / (math.sqrt(2.0) * norm)
    return {
        "rows": [i, j], "actions": [a, b], "target_gaps": target.tolist(),
        "incumbent_gaps": gap.tolist(), "requested_margin": margin,
        "identical_frozen_features": exact_duplicate,
        "head_only_structural_contradiction": exact_duplicate,
        "necessary_readout_frobenius_lower": lower, "hypothetical_readout_radius": head_radius,
        "excluded_at_supplied_readout_radius": exact_duplicate or (
            head_radius is not None and lower is not None and lower > head_radius),
        "scope": "two specified rows at fixed features. The radius is for the affine head, not the nonlinear block.",
    }


def _legal_actions(y, split):
    if "legal_actions" in split:
        legal = torch.as_tensor(split["legal_actions"], dtype=torch.bool, device=y.device).reshape_as(y)
    else:
        legal = torch.ones_like(y, dtype=torch.bool)
        if "dt" in split and y.shape[1] == 3:
            horizon = split["dt"].shape[1]
            legal[horizon-1::horizon, 2] = False
    return legal


def _select_pair(y, pred, weights, legal):
    # Choose the most poorly reproduced pair of contrasting policy preferences.
    # Only TRAIN rows with positive mass participate. Tie-order is deterministic.
    best, chosen = -math.inf, None
    for a in range(y.shape[-1]):
        for b in range(a + 1, y.shape[-1]):
            truth, gap = y[:, a] - y[:, b], pred[:, a] - pred[:, b]
            eligible = (weights > 0) & legal[:, a] & legal[:, b]
            pos = torch.where((truth > 1e-9) & eligible)[0]
            neg = torch.where((truth < -1e-9) & eligible)[0]
            if not len(pos) or not len(neg):
                continue
            err = truth - gap
            i, j = int(pos[err[pos].argmax()]), int(neg[err[neg].argmin()])
            severity = float(err[i] - err[j])
            if severity > best:
                best, chosen = severity, (i, j, a, b)
    return chosen


def training_diagnostics(initial, features, train, *, config=FitConfig(), row_weights=None, include_rows=False):
    start, cpu = time.monotonic(), time.process_time()
    with torch.no_grad():
        h, y, w = data_arrays(features(initial, train), train, row_weights)
        head, sv = solve_readout(h, y, w, config.ridge)
        pred = predict(h, head)
        residual = y - pred
        legal = _legal_actions(y, train)
        selected = _select_pair(y, pred, w, legal)
        pair = None
        if selected is not None:
            pair = screen_target_pair(h, y, pred, selected)
            pair["feature_rows"] = h[list(selected[:2])].tolist()
        cutoff = torch.finfo(h.dtype).eps * max(h.shape) * float(sv.max())
        report = {
            "target_rows": len(h), "dimensions": h.shape[1], "raw_theta": initial.tolist(),
            "readout": head.tolist(), "singular_values": sv.tolist(),
            "numerical_centered_rank": int((sv > cutoff).sum()), "rank_cutoff": cutoff,
            "target_mean": (w @ y).tolist(), "mse_by_action": (w @ residual.square()).tolist(),
            "feature_mean": (w @ h).tolist(),
            "feature_sd": (w @ (h - w @ h).square()).sqrt().tolist(),
            "weighted_feature_residual": ((h - w @ h).T @ (w[:, None] * residual)).tolist(),
            "target_pair": pair, "split": "TRAIN", "vjp_calls": 0, "svd_calls": 1,
            "feature_calls": 1, "forward_rows": len(h),
        }
    if include_rows:
        report["rows"] = {"features": h, "scores": pred, "targets": y, "weights": w, "legal": legal}
    report.update(wall_seconds=time.monotonic() - start, cpu_seconds=time.process_time() - cpu)
    return report


def nonlinear_screen(initial, features, train, *, config=FitConfig(), row_weights=None):
    """Local response with the fitted head held fixed; zero derivatives are local only."""
    start, cpu = time.monotonic(), time.process_time()
    theta = initial.detach().clone().requires_grad_(True)
    h, y, w = data_arrays(features(theta, train), train, row_weights)
    head, _ = solve_readout(h.detach(), y, w, config.ridge)
    pred = predict(h, head)
    selected = _select_pair(y.detach(), pred.detach(), w, _legal_actions(y, train))
    pair, derivative, structural = None, None, None
    if selected is not None:
        i, j, a, b = selected
        pair = screen_target_pair(h.detach(), y, pred.detach(), selected)
        gap = pred[:, a] - pred[:, b]
        contrast = gap[i] - gap[j]
        if contrast.requires_grad:
            grad = torch.autograd.grad(contrast, theta, allow_unused=True)[0]
        else:
            grad = None
        derivative = (torch.zeros_like(theta) if grad is None else grad).tolist()
        # The caller may supply exact external identities for the complete causal
        # input prefixes, including all time deltas, masks and the initial state.
        ids = train.get("complete_input_prefix_ids")
        if ids is not None:
            if len(ids) != len(h) or not all(isinstance(k, str) and k for k in ids):
                raise ValueError("expected canonical complete causal prefix identities")
            structural = ids[i] == ids[j]
    return {"pair": pair, "local_fixed_head_contrast_jacobian": derivative,
            "identical_complete_input_prefix": structural,
            "scope": "Local sensitivity at the incumbent. Identical complete prefixes, if supplied, imply equal scores for any deterministic shared model.",
            "feature_calls": 1, "svd_calls": 1,
            "vjp_calls": int(selected is not None and contrast.requires_grad),
            "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.monotonic() - start}


@contextmanager
def _timed(row, stage):
    start, cpu = time.monotonic(), time.process_time()
    try:
        yield
    finally:
        row["stages"][stage] = {"wall_seconds": time.monotonic() - start,
                                "cpu_seconds": time.process_time() - cpu}


def fit_arm(method, initial, features, train, dev, *, score, config=FitConfig(), editor=None, row_weights=None):
    """Return the best admissible development policy from a fixed training-only path.

    score(theta, head) captures DEV and returns (utility, allowed[, extra]).
    editor(theta, TRAIN diagnostics) yields named full replacement vectors inside
    the same L2 radius as BP. Its own development/discovery bill is external.
    """
    if method not in {"keep", "direct", "bp", "wsp"}:
        raise ValueError(f"unknown optimizer {method}")
    if method == "wsp" and editor is None:
        raise ValueError("WSP requires the sealed externally supplied edit program")
    if initial.ndim != 1 or initial.dtype != torch.float64 or not torch.isfinite(initial).all():
        raise ValueError("expected a finite FP64 vector for the registered edit block")
    if dev is train:
        raise ValueError("training and validation sets must be distinct")
    start, cpu = time.monotonic(), time.process_time()
    origin = initial.detach().clone()
    counters = dict(train_feature_calls=0, train_rows=0, condition_solves=0,
                    dev_score_calls=0, backward_calls=0, editor_calls=0)
    report = {"method": method, "config": asdict(config), "attempts": [], "cost": counters,
              "errors": [], "editor_diagnostics_cost": None, "editor_execution_cost": None, "editor_probes": []}
    best = None
    live_gradient = None

    def finalize():
        report.update(wall_seconds=time.monotonic() - start, cpu_seconds=time.process_time() - cpu)
        if best is None:
            raise IncumbentFailure(report)
        utility, theta, head, index = best
        report.update(selected_index=index, selected_utility=utility, selected_theta=theta.tolist(),
                      changed=not torch.equal(theta, origin))
        return FitResult(theta, head, report)

    def attempt(theta, name, reason, need_gradient=False):
        nonlocal best, live_gradient
        started_wall, started_cpu = time.monotonic(), time.process_time()
        live_gradient = None
        row = {"name": name, "rationale": reason, "theta": None, "stages": {}}
        report["attempts"].append(row)
        try:
            theta = torch.as_tensor(theta, dtype=origin.dtype, device=origin.device).detach().clone()
            if theta.shape != origin.shape or not torch.isfinite(theta).all():
                raise ValueError("nonfinite or incompatible replacement")
            row["theta"] = theta.tolist()
            row["edit_norm"] = float(torch.linalg.vector_norm(theta - origin))
            if row["edit_norm"] > config.radius + 1e-12:
                raise ValueError("candidate outside the registered trust radius")
            theta.requires_grad_(need_gradient)
            counters["train_feature_calls"] += 1
            with torch.set_grad_enabled(need_gradient):
                with _timed(row, "train_features"):
                    h, y, w = data_arrays(features(theta, train), train, row_weights)
                counters["train_rows"] += len(h)
                counters["condition_solves"] += 1
                with _timed(row, "conditional_svd"):
                    head, _ = solve_readout(h.detach(), y, w, config.ridge)
                errors = predict(h, head) - y
                loss = w @ errors.square().sum(dim=-1) + config.ridge * head[:-1].square().sum()
                row["train_objective"] = float(loss.detach())
                if need_gradient:
                    counters["backward_calls"] += 1
                    # Envelope theorem at conditionally optimized W,b.
                    with _timed(row, "profiled_backward"):
                        g = torch.autograd.grad(loss, theta, allow_unused=True)[0] if loss.requires_grad else None
                    live_gradient = torch.zeros_like(theta) if g is None else g.detach()
                    if not torch.isfinite(live_gradient).all():
                        raise ValueError("nonfinite profiled gradient")
            counters["dev_score_calls"] += 1
            with torch.no_grad(), _timed(row, "selection_and_retention"):
                evaluation = score(theta.detach(), head.detach())
            utility, allowed, *extra = evaluation
            utility = float(utility)
            if not math.isfinite(utility):
                raise ValueError("nonfinite development utility")
            row.update(utility=utility, allowed=bool(allowed), diagnostics=extra)
            if allowed and (best is None or utility > best[0] + config.tie_tolerance):
                best = (utility, theta.detach().clone(), head.detach().clone(), len(report["attempts"]) - 1)
        except Exception as exc:
            row.update(error=f"{type(exc).__name__}: {exc}")
            report["errors"].append(row["error"])
            live_gradient = None
        finally:
            row.update(wall_seconds=time.monotonic() - started_wall, cpu_seconds=time.process_time() - started_cpu)

    attempt(origin, "KEEP", "unchanged encoder with conditional TRAIN readout", method == "bp")
    if best is None or method in {"direct", "keep"}:
        return finalize()
    if method == "bp":
        theta = origin.clone()
        m, v = torch.zeros_like(theta), torch.zeros_like(theta)
        for step in range(1, config.steps + 1):
            if live_gradient is None:
                break
            m = 0.9 * m + 0.1 * live_gradient
            v = 0.999 * v + 0.001 * live_gradient.square()
            theta = theta - config.lr * (m / (1 - 0.9**step)) / ((v / (1 - 0.999**step)).sqrt() + 1e-8)
            delta = theta - origin
            theta = origin + delta * min(1.0, config.radius / max(float(delta.norm()), 1e-30))
            attempt(theta, f"adam-{step}", "projected Adam on the profiled training objective", step < config.steps)
    else:
        try:
            counters["train_feature_calls"] += 1
            counters["condition_solves"] += 1
            use_probes = bool(getattr(editor, "uses_train_probes", False))
            diagnostics = training_diagnostics(origin, features, train, config=config,
                                               row_weights=row_weights, include_rows=use_probes)
            diagnostics["editor_context"] = train.get("editor_context", {})
            counters["train_rows"] += diagnostics["forward_rows"]
            report["editor_diagnostics_cost"] = {k: diagnostics[k] for k in ("wall_seconds", "cpu_seconds")}
            def train_probe(candidate):
                if len(report["editor_probes"]) >= len(origin):
                    raise ValueError("program exceeded the physical-coordinate TRAIN probe budget")
                if (not isinstance(candidate, torch.Tensor) or candidate.shape != origin.shape
                        or candidate.dtype != origin.dtype or not torch.isfinite(candidate).all()
                        or float((candidate - origin).norm()) > config.radius + 1e-12):
                    raise ValueError("invalid TRAIN probe displacement")
                record = {"theta": candidate.tolist(), "edit_norm": float((candidate-origin).norm()),
                          "stages": {}, "split": "TRAIN"}
                report["editor_probes"].append(record)
                try:
                    counters["train_feature_calls"] += 1
                    with _timed(record, "train_features"):
                        hp, yp, wp = data_arrays(features(candidate, train), train, row_weights)
                    counters["train_rows"] += len(hp)
                    counters["condition_solves"] += 1
                    with _timed(record, "conditional_svd"):
                        readout, _ = solve_readout(hp, yp, wp, config.ridge)
                        scores = predict(hp, readout)
                    record["feature_matrix_shape"] = list(hp.shape)
                    record["score_matrix_shape"] = list(scores.shape)
                    record["mse_by_action"] = (wp @ (yp - scores).square()).tolist()
                    return {"features": hp, "scores": scores}
                except Exception as exc:
                    record["error"] = f"{type(exc).__name__}: {exc}"
                    raise

            t0, c0 = time.monotonic(), time.process_time()
            counters["editor_calls"] += 1
            # Materialize before any DEV response so the frozen program cannot adapt to DEV.
            try:
                with torch.no_grad():
                    if use_probes:
                        proposals = list(editor(origin.clone(), diagnostics, train_probe))
                    else:
                        proposals = list(editor(origin.clone(), diagnostics))
            finally:
                report["editor_execution_cost"] = {"wall_seconds": time.monotonic() - t0,
                                                   "cpu_seconds": time.process_time() - c0}
            if len(proposals) > config.steps:
                raise ValueError("editor exceeded the registered candidate budget")
            for proposal in proposals:
                attempt(proposal["theta"], str(proposal["name"]), str(proposal["rationale"]))
        except Exception as exc:
            report["errors"].append(f"{type(exc).__name__}: {exc}")
    return finalize()
