"""Charged, bounded TRAIN gradient measurements; no optimizer or split creation."""

import numpy as np

from data import prepare_decoded_observer, metrics_from_observations
from independent.learning import CONTENT_PARAMETERS, objective_work, setup_work
from independent.inference import FrozenGenerator
from ndu_training.estimators import Sampler, WeightedObjective, weighted_work
from utility import joint_value_and_grad


def flat(values):
    return np.concatenate([values[key].ravel() for key in CONTENT_PARAMETERS])


def cosine(a, b):
    return float(np.dot(a, b) / max(np.linalg.norm(a) * np.linalg.norm(b), 1e-300))


def gradient(model, x, y, objective, weights, ledger):
    n, (d, k, _, h) = len(y), model.dimensions
    ledger.model_forward(
        "gradient_diagnostic", rows=n, input_dim=d, hidden=h, classes=k
    )
    _, hidden, p, q = model._forward(x)
    ledger.charge_kernel(
        "gradient_diagnostic", "policy_gradient", **objective_work(objective.arm, n)
    )
    objective.row_weights = weights
    _, dt, di = objective.policy_gradients(p, q, y)
    if weights is not None:
        ledger.charge_kernel(
            "gradient_diagnostic", "request_weights", **weighted_work(n)
        )
    ledger.model_backward(
        "gradient_diagnostic", rows=n, input_dim=d, hidden=h, classes=k
    )
    dh = (dt @ model.params["text"].T + di @ model.params["image"].T) * (
        1 - hidden * hidden
    )
    result = {
        "encoder": x.T @ dh,
        "bias": dh.sum(0),
        "text": hidden.T @ dt,
        "text_bias": dt.sum(0),
        "image": hidden.T @ di,
        "image_bias": di.sum(0),
    }
    return flat(result)


def gradient_panel(model, data, ledger, repeats=12):
    # Fixed hash-ordered physical sources, retaining every instruction/variant.
    chosen = set(sorted(set(data["source_ids"]))[:64])
    take = np.array(
        [i for i, source in enumerate(data["source_ids"]) if source in chosen]
    )
    panel = {key: data[key][take] for key in ("full", "low", "labels")}
    y = panel["labels"]
    x = np.concatenate((panel["full"], panel["low"]))
    yy = np.concatenate((y, y))
    objects = {
        arm: WeightedObjective(arm, model, ledger=ledger, stage="gradient_diagnostic")
        for arm in ("A", "N")
    }
    exact = {
        arm: gradient(model, x, yy, obj, None, ledger) for arm, obj in objects.items()
    }
    ce = WeightedObjective("H", model)
    ce_grad = gradient(model, x, yy, ce, None, ledger)
    result = {
        "rows": len(y),
        "physical_sources": len(chosen),
        "risk_vs_raw_utility_cosine": cosine(
            exact["N"] - ce_grad, exact["A"] - ce_grad
        ),
        "objectives": {},
    }
    for arm, obj in objects.items():
        arm_result = {
            "full_gradient_norm": float(np.linalg.norm(exact[arm])),
            "utility_to_anchor_norm": float(
                np.linalg.norm(exact[arm] - ce_grad)
                / max(np.linalg.norm(ce_grad), 1e-300)
            ),
            "utility_anchor_cosine": cosine(exact[arm] - ce_grad, ce_grad),
            "samplers": {},
        }
        for kind in ("iid", "stratified"):
            sampler = Sampler(y, kind, seed=97013)
            samples = []
            for _ in range(repeats):
                idx, w, mask = sampler.draw()
                xx = np.where(mask[:, None], panel["full"][idx], panel["low"][idx])
                samples.append(gradient(model, xx, y[idx], obj, w, ledger))
            g = np.asarray(samples)
            centered = g - g.mean(0)
            variance = float(np.sum(centered * centered) / (repeats - 1))
            arm_result["samplers"][kind] = {
                "repeats": repeats,
                "variance_trace": variance,
                "mean_error_norm": float(np.linalg.norm(g.mean(0) - exact[arm])),
                "signal_squared_over_variance": float(
                    np.dot(exact[arm], exact[arm]) / max(variance, 1e-300)
                ),
            }
            ledger.charge_kernel(
                "gradient_diagnostic",
                "gradient_summary",
                scalar_ops=4 * g.size + 8 * g.shape[1],
                div_ops=g.shape[1] + 4,
                sqrt_ops=4,
            )
        result["objectives"][arm] = arm_result
    # Independent log-domain implementation, on an actual TRAIN policy panel.
    ledger.model_forward(
        "gradient_diagnostic",
        rows=64,
        input_dim=202,
        hidden=model.dimensions[3],
        classes=12,
    )
    p, q = model.forward(panel["full"][:64])
    obj = objects["N"]
    obj.row_weights = None
    _, dt, di = obj.policy_gradients(p, q, y[:64])
    ledger.charge_kernel(
        "gradient_diagnostic", "cached_reference", **objective_work("N", 64)
    )
    _, gt, gi = joint_value_and_grad(p, q, obj.reward[y[:64]], 1.5)
    # Declared bound for the independently evaluated log-domain reference.
    ledger.charge_kernel(
        "gradient_diagnostic",
        "log_domain_reference",
        scalar_ops=20 * 64 * 144,
        compare_ops=10 * 64 * 144,
        exp_ops=64 * 144,
        log_ops=2 * 64 * 144,
        div_ops=4 * 64 * 144,
    )
    ce_dt, ce_di = ce.policy_gradients(p, q, y[:64])[1:]
    ledger.charge_kernel(
        "gradient_diagnostic", "anchor_reference", **objective_work("H", 64)
    )
    result["cached_log_domain_max_error"] = float(
        max(abs(dt - ce_dt - gt).max(), abs(di - ce_di - gi).max())
    )
    result["minimum_shifted_kernel"] = float(obj.kernel.min())
    result["finite"] = bool(all(np.isfinite(v).all() for v in exact.values()))
    return result


def score(model, data, ledger, stage):
    generator = FrozenGenerator(model, prepare_low=False, ledger=ledger, stage=stage)
    p, q = generator.forward_full(data["full"], ledger, stage)
    ledger.charge_kernel(stage, "decoded_observer", **setup_work(model.dimensions, "A"))
    observer = prepare_decoded_observer(model)
    n = len(p)
    ledger.charge_kernel(
        stage,
        "decoded_metrics",
        macs=4 * n * 144,
        scalar_ops=124 * n,
        compare_ops=14 * n,
        div_ops=n,
    )
    metrics = metrics_from_observations(observer.observations, p, q, data["labels"])
    metrics["task_utility"] = np.einsum(
        "ni,nij,nj->n", p, observer.reward[data["labels"]], q
    )
    bad = model.clone()
    bad.params["decoder"] = np.roll(bad.params["decoder"], 1, axis=0)
    ledger.charge_kernel(
        stage, "corrupted_decoded_observer", **setup_work(model.dimensions, "A")
    )
    bad_observer = prepare_decoded_observer(bad)
    ledger.charge_kernel(
        stage, "corrupted_utility", macs=n * 144, scalar_ops=2 * n * 12
    )
    corrupted = np.einsum("ni,nij,nj->n", p, bad_observer.reward[data["labels"]], q)
    metrics["decoder_corruption_score_drop"] = metrics["task_utility"] - corrupted
    return {key: float(value.mean()) for key, value in metrics.items()}
