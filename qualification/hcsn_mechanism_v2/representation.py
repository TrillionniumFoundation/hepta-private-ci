"""Train-only representation diagnostics and controlled feature/readout ablations.

The exposure pool fixes units of interval increments. It does NOT make endpoint
quadrature or interval first-hit probabilities invariant to time subdivision.
The separate clock process tests exact terminal/cumulative semigroup quantities.
Output projection is shared post-fit processing; ridge still optimizes raw MSE.
"""

from contextlib import nullcontext

import torch


BANKS = ("same_generator", "drop_value_risk", "ordinary_tanh")
POOLS = ("legacy", "exposure")
SCALERS = ("empirical", "bounded_floor")
LINKS = ("identity", "clip_unit")


def _matrix(value, name):
    if (
        not isinstance(value, torch.Tensor)
        or value.ndim != 2
        or value.shape[1] < 1
        or value.dtype != torch.float64
        or len(value) < 1
        or not bool(torch.isfinite(value).all())
    ):
        raise ValueError(f"{name} must be a nonempty finite FP64 matrix")
    return value


def pool_sequence(values, dt, x, feature_names, pooling="legacy"):
    """Return a last/pooled/two-extra bank; preserve explicit interval semantics."""
    if (
        pooling not in POOLS
        or values.ndim != 3
        or dt.shape != values.shape[:2]
        or x.shape[:2] != dt.shape
        or x.shape[-1] != 4
        or values.shape[-1] != len(feature_names)
        or len(feature_names) != 9
        or not bool(torch.isfinite(values).all())
        or not bool(torch.isfinite(dt).all())
        or bool((dt <= 0).any())
    ):
        raise ValueError("finite matching four-input/nine-feature sequence required")
    means, last = values.mean(1), values[:, -1]
    event_rate = (values[:, :, 0] / dt).mean(1)
    if pooling == "exposure":
        total = dt.sum(1)
        increment = 1 + sum(name.startswith("content_") for name in feature_names)
        last = torch.cat(
            (values[:, -1, :increment] / dt[:, -1, None], values[:, -1, increment:]), 1
        )
        means = (values * dt[:, :, None]).sum(1) / total[:, None]
        means = torch.cat(
            (values[:, :, :increment].sum(1) / total[:, None], means[:, increment:]), 1
        )
        # Risk excludes initially refractory cohorts. This is an interval
        # probability per second, NOT an exact instantaneous event intensity.
        risk = feature_names.index("risk")
        last = last.clone()
        means = means.clone()
        last[:, risk] = values[:, -1, risk] / dt[:, -1]
        means[:, risk] = values[:, :, risk].sum(1) / total
        event_rate = values[:, :, 0].sum(1) / total
    extra = torch.stack((event_rate, x[:, -1, 3] * means[:, 2]), 1)
    names = [f"{pool}.{name}" for pool in ("last", "mean") for name in feature_names]
    names += ["mean.event_rate", "query.mean.content_1"]
    return torch.cat((last, means, extra), 1), names


def feature_banks(model, data, pooling="legacy", grad=False, chunk_size=32):
    """All banks pay for the complete encoder/tanh bank; no label access.

    Chunking respects Prepared's 2,048-event cap. Caller owns model parameters,
    creation cost and whether encoder edits are permitted. No feature cache is
    reused across different parameters or splits.
    """
    x, dt = torch.from_numpy(data["x"]), torch.from_numpy(data["dt"])
    if (
        x.ndim != 3
        or len(x) < 1
        or x.shape[-1] != 4
        or x.dtype != torch.float64
        or dt.dtype != torch.float64
        or dt.shape != x.shape[:2]
        or x.shape[1] > 256
        or not 1 <= chunk_size <= 256
    ):
        raise ValueError("bounded FP64 windows and positive chunk size required")
    limit = min(chunk_size, 2048 // x.shape[1])
    outputs = []
    with nullcontext() if grad else torch.no_grad():
        for start in range(0, len(x), limit):
            values = model.encode_batch(
                x[start : start + limit], dt[start : start + limit]
            )
            pooled, names = pool_sequence(
                values,
                dt[start : start + limit],
                x[start : start + limit],
                model.encoder.feature_names,
                pooling,
            )
            outputs.append(pooled)
        common = torch.cat(outputs)
        columns = [
            names.index(f"{pool}.{name}")
            for pool in ("last", "mean")
            for name in ("call", "risk")
        ]
        projection = x.new_tensor([[0.7, -0.4, 0.2, 0.0], [0.3, 0.6, 0.0, -0.5]])
        plain = torch.tanh(x @ projection.T)
        average = (
            plain.mean(1)
            if pooling == "legacy"
            else (plain * dt[:, :, None]).sum(1) / dt.sum(1)[:, None]
        )
        replacement = torch.cat((plain[:, -1], average), 1)
        dropped, ordinary = common.clone(), common.clone()
        dropped[:, columns], ordinary[:, columns] = 0, replacement
    return dict(zip(BANKS, (common, dropped, ordinary), strict=True)), names


def fit_scaler(train, mode="empirical", floor=0.05):
    """Fit exactly once on training features; floor is a predeclared intervention."""
    train = _matrix(train, "train")
    if len(train) < 2 or mode not in SCALERS or not 0 < floor <= 10:
        raise ValueError("at least two training rows and a valid scale floor required")
    mean, empirical = train.mean(0).detach(), train.std(0, unbiased=False).detach()
    minimum = 1e-8 if mode == "empirical" else floor
    return {
        "mean": mean,
        "scale": empirical.clamp_min(minimum),
        "mode": mode,
        "floor": minimum,
        "empirical_std": empirical,
        "floored_columns": torch.nonzero(empirical < minimum).flatten().tolist(),
        "fit_rows": len(train),
    }


def standardize(values, scaler):
    values = _matrix(values, "values")
    mean = torch.as_tensor(scaler["mean"], dtype=values.dtype, device=values.device)
    scale = torch.as_tensor(scaler["scale"], dtype=values.dtype, device=values.device)
    if (
        mean.shape != values.shape[1:]
        or scale.shape != mean.shape
        or not bool(torch.isfinite(mean).all())
        or not bool(torch.isfinite(scale).all())
        or bool((scale <= 0).any())
    ):
        raise ValueError(
            "finite frozen training scaler matching feature width required"
        )
    return (values - mean) / scale


def spectrum_diagnostics(values, extra_columns=()):
    """No labels; empirical rank/redundancy, not an out-of-sample utility claim."""
    values = _matrix(values, "values")
    centered = values - values.mean(0)
    singular = torch.linalg.svdvals(centered)
    largest = float(singular[0]) if len(singular) else 0.0
    tolerance = torch.finfo(values.dtype).eps * max(values.shape) * largest
    rank = int((singular > tolerance).sum())
    result = {
        "rows": len(values),
        "columns": values.shape[1],
        "rank": rank,
        "singular_values": singular.tolist(),
        "rank_tolerance": tolerance,
        "condition_full_column_rank": (
            largest / float(singular[-1]) if rank == values.shape[1] else None
        ),
    }
    extras = tuple(extra_columns)
    if extras:
        if (
            len(set(extras)) != len(extras)
            or min(extras) < 0
            or max(extras) >= values.shape[1]
        ):
            raise ValueError("distinct existing extra columns required")
        base = centered[:, [i for i in range(values.shape[1]) if i not in extras]]
        extra = centered[:, list(extras)]
        u, s, _ = torch.linalg.svd(base, full_matrices=False)
        tol = (
            torch.finfo(values.dtype).eps * max(base.shape) * float(s[0])
            if len(s)
            else 0.0
        )
        basis = u[:, s > tol]
        residual = extra - basis @ (basis.T @ extra)
        residual_s = torch.linalg.svdvals(residual)
        # Use original-matrix tolerance to avoid promoting projection roundoff.
        result.update(
            {
                "extra_columns": list(extras),
                "extra_residual_singular_values": residual_s.tolist(),
                "extra_residual_rank": int((residual_s > tolerance).sum()),
                "extra_residual_energy_fraction": (
                    float(residual.square().sum() / extra.square().sum())
                    if bool(extra.square().sum() > 0)
                    else 0.0
                ),
            }
        )
    return result


def ridge_fit(values, target, ridge=0.001):
    """SVD solution of sum(raw squared error)+ridge*||weight||²; free intercept.

    Returning a linear state does not solve a nonlinear encoder or a clipped/
    logistic training objective. Positive ridge gives a unique penalized slope.
    """
    values = _matrix(values, "values")
    target = torch.as_tensor(target, dtype=values.dtype, device=values.device)
    if target.ndim == 2 and target.shape[1] == 1:
        target = target[:, 0]
    if (
        target.shape != (len(values),)
        or not bool(torch.isfinite(target).all())
        or not 0 < ridge < 100
    ):
        raise ValueError(
            "one finite target per row and positive bounded ridge required"
        )
    xm, ym = values.mean(0), target.mean()
    centered, response = values - xm, target - ym
    u, s, vh = torch.linalg.svd(centered, full_matrices=False)
    weight = vh.T @ ((s / (s.square() + ridge)) * (u.T @ response))
    bias = ym - xm @ weight
    residual = centered.T @ (centered @ weight - response) + ridge * weight
    minimum = float(s[-1].square()) if len(s) == values.shape[1] else 0.0
    diagnostics = spectrum_diagnostics(values)
    diagnostics.update(
        {
            "solver": "centered_svd",
            "ridge": ridge,
            "penalized_condition": (float(s[0].square()) + ridge) / (minimum + ridge),
            "effective_degrees_of_freedom": float(
                (s.square() / (s.square() + ridge)).sum()
            )
            + 1,
            "normal_equation_residual_l2": float(torch.linalg.vector_norm(residual)),
            "objective_sum": float(
                (values @ weight + bias - target).square().sum()
                + ridge * weight.square().sum()
            ),
        }
    )
    return {"weight": weight, "bias": bias, "diagnostics": diagnostics}


def predict(values, state, link="identity"):
    values = _matrix(values, "values")
    weight = torch.as_tensor(state["weight"], dtype=values.dtype, device=values.device)
    bias = torch.as_tensor(state["bias"], dtype=values.dtype, device=values.device)
    if weight.shape != values.shape[1:] or bias.ndim != 0 or link not in LINKS:
        raise ValueError("matching linear state and declared output link required")
    raw = values @ weight + bias
    if not bool(torch.isfinite(raw).all()):
        raise FloatingPointError("nonfinite linear prediction")
    return raw if link == "identity" else raw.clamp(0, 1)


def shift_diagnostics(values, scaler, state):
    """Frozen-scaler shifts and exact linear contributions; no refitting."""
    z = standardize(values, scaler)
    w = torch.as_tensor(state["weight"], dtype=z.dtype, device=z.device)
    if w.shape != z.shape[1:]:
        raise ValueError("matching slope required")
    contributions = z * w
    return {
        "standardized_max_abs": z.abs().amax(0).tolist(),
        "standardized_mean": z.mean(0).tolist(),
        "raw_slope": (w / torch.as_tensor(scaler["scale"], dtype=z.dtype)).tolist(),
        "mean_contribution": contributions.mean(0).tolist(),
        "max_abs_contribution": contributions.abs().amax(0).tolist(),
    }
