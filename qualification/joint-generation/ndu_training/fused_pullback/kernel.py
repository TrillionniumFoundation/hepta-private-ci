"""Exact-real-arithmetic fixed CE CV fusion. This module never updates a model."""

import numpy as np

from independent.learning import CONTENT_PARAMETERS, objective_work
from independent.mixed_training import MixedEncoderBatch
from model import softmax
from ndu_training.estimators import weighted_work
from ndu_training.mechanism_readout.anchor_cv import correct, correction_work
from ndu_training.reinfer_d1.kernels import backward_work, forward_work, pullback_work

MODES = ("plain", "CV-d2", "CV-unfused", "CV-fused", "CV-hybrid")
CANCEL_THRESHOLD = 1e-8


def merge(*parts):
    result = {}
    for part in parts:
        for key, value in part.items():
            result[key] = result.get(key, 0) + value
    return result


def gradient_work(
    dimensions, arm, n, low_count, weighted, mode, *, observed=False, fallback=None
):
    d, k, _, h = dimensions
    elements = d * h + h + 2 * h * k + 2 * k
    base = merge(forward_work(n, h), backward_work(n, h), objective_work(arm, n, k))
    base["compare_ops"] += n * d + 2 * n + k * 192 + 192
    base["scalar_ops"] += n
    base["compare_ops"] += 2 * n
    if low_count:
        base["macs"] -= 288 * h * low_count
        base["scalar_ops"] += 144 * h
        base["compare_ops"] += 144 * low_count
        if low_count < n:
            base["scalar_ops"] += d * h
    if weighted:
        base = merge(base, weighted_work(n, k))
    if observed:
        number = 1 if mode == "plain" else 2
        base = merge(
            base, {"scalar_ops": number * (2 * elements - 1), "sqrt_ops": number}
        )
    if mode == "plain":
        return base
    # Explicit index bounds plus matching x AND labels, shared by all CV modes.
    common = {"scalar_ops": n, "compare_ops": 0 if mode == "CV-d2" else n * (d + 3)}
    old = merge(base, common, pullback_work(n, h, weighted), correction_work(elements))
    if mode in ("CV-d2", "CV-unfused") or fallback in ("observed", "empty_moments"):
        return merge(
            old,
            {"compare_ops": 6, "scalar_ops": 5} if fallback == "empty_moments" else {},
        )
    if mode not in ("CV-fused", "CV-hybrid"):
        raise ValueError("unknown pullback mode")
    encoder_bias = d * h + h
    heads = 2 * h * k + 2 * k
    extra = {
        "macs": 2 * n * h * k,
        "scalar_ops": n * (h + 2 * k)
        + 2 * n * h
        + 2 * encoder_bias
        + 3 * heads
        + (n - 1) * 2 * k,
        "div_ops": n if weighted else 1,
        "compare_ops": 3 * elements,
    }
    fused = merge(base, common, extra)
    if mode == "CV-fused":
        return fused
    # Actual guards are billed even if they reject fusion. No result-based rule.
    hidden_guard = {
        "scalar_ops": 3 * n * h + 3 + 5,
        "compare_ops": 3 * (n * h - 1) + 1 + 6,
    }
    if fallback == "hidden_cancellation":
        return merge(old, hidden_guard, {"scalar_ops": 2 * n * h})
    mean_guard = {"scalar_ops": 7 * encoder_bias - 1, "compare_ops": 2 * encoder_bias}
    if fallback == "mean_cancellation":
        # Fused encoder already ran; then the old two encoder pullbacks run too.
        enc_macs = (n * d - 144 * low_count) * h
        enc_merge = d * h if 0 < low_count < n else 0
        return merge(
            old,
            hidden_guard,
            mean_guard,
            {
                "macs": enc_macs,
                "scalar_ops": 2 * n * h + 2 * encoder_bias + (n - 1) * h + enc_merge,
            },
        )
    return merge(fused, hidden_guard, mean_guard)


def combine_work(dimensions, n, low_count, mode, observed=False, fallback=None):
    """Only the exposed primitive: no forward/objective or reference gathering."""
    d, k, _, h = dimensions
    simple = {
        "macs": (n * d - 144 * low_count) * h,
        "scalar_ops": (n - 1) * h + (d * h if 0 < low_count < n else 0),
    }
    if mode == "plain":
        return simple
    whole = gradient_work(
        dimensions, "A", n, low_count, True, mode, observed=observed, fallback=fallback
    )
    base = gradient_work(dimensions, "A", n, low_count, True, "plain")
    batch = {
        "scalar_ops": n + n * (h + 2 * k),
        "compare_ops": 0 if mode == "CV-d2" else n * (d + 3),
        "div_ops": n,
    }
    result = {
        key: whole.get(key, 0)
        - base.get(key, 0)
        - batch.get(key, 0)
        + simple.get(key, 0)
        for key in set(whole) | set(base) | set(batch) | set(simple)
    }
    if any(value < 0 for value in result.values()):
        raise ValueError("negative primitive inventory")
    return result


class BoundReference:
    """One paid immutable-cache validation, with per-batch x/y identity checks."""

    def __init__(self, reference, ledger=None):
        self.ref = reference
        n, d = reference.x.shape
        h = reference.h.shape[1]
        if n % 2 or reference.y.shape != (n,) or d != 202:
            raise ValueError("full/low reference geometry required")
        expected = (
            (reference.h, (n, h)),
            (reference.dh, (n, h)),
            (reference.dt, (n, 12)),
            (reference.di, (n, 12)),
        )
        if any(value.shape != shape for value, shape in expected):
            raise ValueError("reference derivative geometry differs")
        values = [
            reference.x,
            reference.h,
            reference.dh,
            reference.dt,
            reference.di,
            *reference.mean.values(),
        ]
        if set(reference.mean) != set(CONTENT_PARAMETERS) or any(
            value.dtype != np.float64 or not np.isfinite(value).all()
            for value in values
        ):
            raise ValueError(
                "finite float64 reference cache and complete mean required"
            )
        if ledger is not None:
            ledger.charge_kernel(
                "reference_bind",
                "immutable_cache_validation",
                compare_ops=sum(value.size for value in values),
            )
        for value in (*values, reference.y):
            value.flags.writeable = False

    def batch(self, x, y, indices, full, weights, verify=True):
        ref, n = self.ref, len(x)
        indices = np.asarray(indices)
        if verify and (
            indices.shape != (n,)
            or indices.dtype.kind not in "iu"
            or np.any(indices < 0)
            or np.any(indices >= len(ref.y) // 2)
        ):
            raise ValueError("indices must address original full-view rows")
        selected = indices + np.where(full, 0, len(ref.y) // 2)
        if verify and (
            not np.array_equal(x, ref.x[selected])
            or not np.array_equal(y, ref.y[selected])
        ):
            raise ValueError("current and reference x/indices/views/labels differ")
        factors = np.full(n, 1 / n) if weights is None else weights / n
        return (
            ref.h[selected],
            ref.dh[selected] * factors[:, None],
            ref.dt[selected] * factors[:, None],
            ref.di[selected] * factors[:, None],
        )


def norm(grads):
    return float(np.sqrt(sum(float(np.sum(value * value)) for value in grads.values())))


def finite_maps(model, mean, output):
    # Three genuine complete finite scans, matching the old 3E check inventory.
    # The fused path cannot check nonexistent separate encoder-gradient arrays.
    for mapping in (model.params, mean, output):
        if any(not np.isfinite(mapping[key]).all() for key in CONTENT_PARAMETERS):
            raise ValueError(
                "nonfinite parameters, reference mean or corrected gradient"
            )


def combine(model, mixed, dh, current_heads, reference_batch, mean, mode, observed):
    """Pure pullback algebra, also exposed for adversarial hand-array checks."""
    info = {
        "requested_mode": mode,
        "observed": observed,
        "fallback": None,
        "raw_preclip_norm": None,
        "applied_preclip_norm": None,
    }
    if mode == "plain":
        out = {
            "encoder": mixed.encoder_gradient(dh),
            "bias": dh.sum(0),
            **current_heads,
        }
        if observed:
            info["raw_preclip_norm"] = info["applied_preclip_norm"] = norm(out)
        return out, info
    rh, rdh, rdt, rdi = reference_batch
    ref_heads = {
        "text": rh.T @ rdt,
        "text_bias": rdt.sum(0),
        "image": rh.T @ rdi,
        "image_bias": rdi.sum(0),
    }

    def old_path():
        current = {
            "encoder": mixed.encoder_gradient(dh),
            "bias": dh.sum(0),
            **current_heads,
        }
        ref = {"encoder": mixed.x.T @ rdh, "bias": rdh.sum(0), **ref_heads}
        out = correct(current, mean, ref)
        if observed:
            info["raw_preclip_norm"], info["applied_preclip_norm"] = (
                norm(current),
                norm(out),
            )
        return out

    if observed:
        info["fallback"] = "observed"
        return old_path(), info
    if mode in ("CV-d2", "CV-unfused"):
        return old_path(), info
    if mode == "CV-hybrid":
        clocks = np.array(
            [model._moments.get(key, (None, None, 0))[2] for key in CONTENT_PARAMETERS]
        )
        if np.any(clocks <= 0):
            info["fallback"] = "empty_moments"
            return old_path(), info
    changed_hidden = dh - 0.2 * rdh
    if mode == "CV-hybrid":
        small = np.max(np.abs(changed_hidden)) <= CANCEL_THRESHOLD * (
            np.max(np.abs(dh)) + 0.2 * np.max(np.abs(rdh))
        )
        if small:
            info["fallback"] = "hidden_cancellation"
            return old_path(), info
    data_encoder, data_bias = (
        mixed.encoder_gradient(changed_hidden),
        changed_hidden.sum(0),
    )
    scaled_encoder, scaled_bias = 0.2 * mean["encoder"], 0.2 * mean["bias"]
    encoder, bias = data_encoder + scaled_encoder, data_bias + scaled_bias
    if mode == "CV-hybrid":
        checks = []
        for data, scaled, total in (
            (data_encoder, scaled_encoder, encoder),
            (data_bias, scaled_bias, bias),
        ):
            scale = np.abs(data) + np.abs(scaled)
            checks.append(
                bool(np.any((scale > 0) & (np.abs(total) <= CANCEL_THRESHOLD * scale)))
            )
        if any(checks):
            info["fallback"] = "mean_cancellation"
            return old_path(), info
    out = {
        "encoder": encoder,
        "bias": bias,
        **{
            key: current_heads[key] + 0.2 * (mean[key] - ref_heads[key])
            for key in current_heads
        },
    }
    finite_maps(model, mean, out)
    return out, info


def form_gradients(
    model,
    objective,
    x,
    labels,
    full,
    indices,
    weights,
    reference,
    mode,
    ledger=None,
    *,
    step=65,
):
    """Same objective/importance law. Returns loss and PRE-CLIP six-group gradient.

    Clipping, Adam moments/clocks and parameter writes remain the caller's
    unchanged NativeAdam responsibility. Reference mean stays unweighted CE.
    """
    if mode not in MODES or (mode != "plain" and reference is None):
        raise ValueError("valid mode and corresponding reference required")
    x, y = model._input(x), np.asarray(labels)
    n, (_, k, _, _) = len(x), model.dimensions
    if y.shape != (n,) or y.dtype.kind not in "iu" or np.any(y < 0) or np.any(y >= k):
        raise ValueError("valid categorical labels required")
    if (
        tuple(model.dimensions) != tuple(objective.dimensions)
        or objective.ce_weight != 0.2
        or objective.rho != 1.5
    ):
        raise ValueError("unchanged dimensions, rho1.5 and CE.2 required")
    if any(
        not np.array_equal(model.params[key], value)
        for key, value in objective._decoder.items()
    ):
        raise ValueError("fixed decoder changed")
    mixed = MixedEncoderBatch(x, full)
    hidden = mixed.hidden(model.params["encoder"], model.params["bias"])
    p = softmax(hidden @ model.params["text"] + model.params["text_bias"])
    q = softmax(hidden @ model.params["image"] + model.params["image_bias"])
    objective.row_weights = weights
    loss, dt, di = objective._policy_gradients_checked(p, q, y)
    dh = (dt @ model.params["text"].T + di @ model.params["image"].T) * (
        1 - hidden * hidden
    )
    current_heads = {
        "text": hidden.T @ dt,
        "text_bias": dt.sum(0),
        "image": hidden.T @ di,
        "image_bias": di.sum(0),
    }
    batch = (
        None
        if mode == "plain"
        else reference.batch(x, y, indices, full, weights, verify=mode != "CV-d2")
    )
    observed = step == 1 or step % 64 == 0
    out, info = combine(
        model,
        mixed,
        dh,
        current_heads,
        batch,
        None if reference is None else reference.ref.mean,
        mode,
        observed,
    )
    if ledger is not None:
        ledger.charge_kernel(
            "gradient",
            mode,
            **gradient_work(
                model.dimensions,
                objective.arm,
                n,
                mixed.low_count,
                weights is not None,
                mode,
                observed=observed,
                fallback=info["fallback"],
            ),
        )
    return loss, out, info
