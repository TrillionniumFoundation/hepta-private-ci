"""Fixed full-objective and adversarial hand checks, including actual NativeAdam."""

import hashlib

import numpy as np

from independent.learning import CONTENT_PARAMETERS
from independent.mixed_training import MixedEncoderBatch
from independent.native_adam import NativeAdam, setup_work
from ndu_training.diagnostics import gradient
from ndu_training.estimators import WeightedObjective
from ndu_training.fused_pullback.hand import draw, moments
from ndu_training.fused_pullback.kernel import combine, combine_work, form_gradients
from ndu_training.mechanism_readout.anchor_cv import correct, correction_work
from ndu_training.reinfer_d1.kernels import flat


def compare(actual, expected, rtol, atol, ledger):
    size = sum(actual[key].size for key in CONTENT_PARAMETERS)
    ledger.charge_kernel(
        "numeric_comparison",
        "coordinate_tolerances",
        scalar_ops=6 * size - 6,
        compare_ops=3 * size,
        div_ops=size,
    )
    maximum, ratio, bad = 0.0, 0.0, 0
    for key in CONTENT_PARAMETERS:
        error = np.abs(actual[key] - expected[key])
        budget = atol + rtol * np.abs(expected[key])
        maximum = max(maximum, float(error.max()))
        ratio = max(ratio, float(np.max(error / budget)))
        bad += int(np.sum(error > budget))
    return {
        "pass": bad == 0,
        "maximum_absolute_error": maximum,
        "maximum_error_to_tolerance": ratio,
        "failing_coordinates": bad,
    }


def update(model, grads, scale, clock, library, ledger):
    clone = model.clone()
    moments(clone, clock)
    ledger.charge_kernel("hand_Adam", "setup", **setup_work(clone))
    optimizer = NativeAdam(clone, library)
    ledger.optimizer(
        "hand_Adam",
        parameter_sizes=[clone.params[key].size for key in CONTENT_PARAMETERS],
    )
    ledger.charge_kernel(
        "hand_Adam",
        "finite_gradient_scan",
        compare_ops=sum(g.size for g in grads.values()),
    )
    ledger.charge_kernel(
        "hand_Adam", "fixture_scale", scalar_ops=sum(g.size for g in grads.values())
    )
    optimizer.apply_gradients(
        clone, {key: scale * value for key, value in grads.items()}, 0.003
    )
    assert clone.updates == 1
    assert all(clone._moments[key][2] == clock + 1 for key in CONTENT_PARAMETERS)
    return clone


def compare_update(model, gold, candidate, scale, clock, library, ledger, p):
    a, b = (update(model, g, scale, clock, library, ledger) for g in (gold, candidate))
    first = compare(
        {key: b._moments[key][0] for key in CONTENT_PARAMETERS},
        {key: a._moments[key][0] for key in CONTENT_PARAMETERS},
        p["moment_rtol"],
        p["moment_atol"],
        ledger,
    )
    second = compare(
        {key: b._moments[key][1] for key in CONTENT_PARAMETERS},
        {key: a._moments[key][1] for key in CONTENT_PARAMETERS},
        p["moment_rtol"],
        p["moment_atol"],
        ledger,
    )
    parameters = compare(b.params, a.params, p["update_rtol"], p["update_atol"], ledger)
    return {
        "parameters": parameters,
        "first_moment": first,
        "second_moment": second,
        "pass": all(x["pass"] for x in (parameters, first, second)),
        "gold_parameters_sha256": a.digest(),
        "candidate_parameters_sha256": b.digest(),
    }


def run(models, bound, arrays, p, ledger, library, vectors, result=None):
    result = {} if result is None else result
    result.update(
        {
            "ordinary": [],
            "adversarial": [],
            "required_pass": True,
            "unconditional_raw_failures_retained": [],
            "max_updates_per_hand_model": 1,
        }
    )
    for state in p["numeric_current_states"]:
        model = models[state]
        for arm in p["numeric_arms"]:
            obj = WeightedObjective(arm, model, ledger=ledger, stage="hand_objective")
            for kind in p["numeric_samplers"]:
                for low in p["numeric_low_counts"]:
                    x, y, full, idx, w = draw(arrays, p, kind, low)
                    obj.row_weights = w
                    gv = gradient(model, x, y, obj, w, ledger)
                    gold, offset = {}, 0
                    for key in CONTENT_PARAMETERS:
                        size = model.params[key].size
                        gold[key] = gv[offset : offset + size].reshape(
                            model.params[key].shape
                        )
                        offset += size
                    ref = bound.ref.pull(
                        idx + np.where(full, 0, len(arrays["labels"])),
                        w,
                        ledger,
                        "hand_reference_pull",
                    )
                    ledger.charge_kernel(
                        "hand_reference_pull", "correction", **correction_work(len(gv))
                    )
                    gold_cv = correct(gold, bound.ref.mean, ref)
                    case = {
                        "state": state,
                        "arm": arm,
                        "sampler": kind,
                        "low_rows": low,
                        "gradients": {},
                        "updates": [],
                    }
                    number = len(result["ordinary"])
                    vectors[f"case{number}_gold_plain"] = flat(gold)
                    vectors[f"case{number}_gold_CV"] = flat(gold_cv)
                    candidates = {}
                    for mode in ("plain", "CV-d2", "CV-fused", "CV-hybrid"):
                        _, g, info = form_gradients(
                            model, obj, x, y, full, idx, w, bound, mode, ledger
                        )
                        check = compare(
                            g,
                            gold if mode == "plain" else gold_cv,
                            p["gradient_rtol"],
                            p["gradient_atol"],
                            ledger,
                        )
                        case["gradients"][mode] = {**check, "path": info}
                        result["required_pass"] &= check["pass"]
                        candidates[mode] = g
                        if mode in ("CV-fused", "CV-hybrid"):
                            vectors[f"case{number}_{mode}"] = flat(g)
                    empty_model = model.clone()
                    _, empty_g, empty_info = form_gradients(
                        empty_model, obj, x, y, full, idx, w, bound, "CV-hybrid", ledger
                    )
                    assert empty_info["fallback"] == "empty_moments"
                    for clock in p["moment_fixture_clocks"]:
                        for scale in p["clip_fixture_gradient_scales"]:
                            for mode in ("CV-fused", "CV-hybrid"):
                                g = (
                                    empty_g
                                    if mode == "CV-hybrid" and clock == 0
                                    else candidates[mode]
                                )
                                check = compare_update(
                                    model, gold_cv, g, scale, clock, library, ledger, p
                                )
                                case["updates"].append(
                                    {
                                        "mode": mode,
                                        "scale": scale,
                                        "initial_clock": clock,
                                        **check,
                                    }
                                )
                                if mode == "CV-hybrid":
                                    result["required_pass"] &= check["pass"]
                                elif not check["pass"]:
                                    result[
                                        "unconditional_raw_failures_retained"
                                    ].append(
                                        {
                                            "case": number,
                                            "scale": scale,
                                            "clock": clock,
                                            **check,
                                        }
                                    )
                    _, old_observed, old_info = form_gradients(
                        model, obj, x, y, full, idx, w, bound, "CV-d2", ledger, step=64
                    )
                    _, new_observed, new_info = form_gradients(
                        model,
                        obj,
                        x,
                        y,
                        full,
                        idx,
                        w,
                        bound,
                        "CV-hybrid",
                        ledger,
                        step=64,
                    )
                    observed = compare(
                        new_observed,
                        old_observed,
                        p["gradient_rtol"],
                        p["gradient_atol"],
                        ledger,
                    )
                    assert new_info["fallback"] == "observed"
                    for field in ("raw_preclip_norm", "applied_preclip_norm"):
                        np.testing.assert_allclose(
                            new_info[field],
                            old_info[field],
                            rtol=p["gradient_rtol"],
                            atol=p["gradient_atol"],
                        )
                    case["observed_step64"] = observed
                    result["required_pass"] &= observed["pass"]
                    result["ordinary"].append(case)
    # Arbitrary already-weighted/tanh-pulled internal derivatives stress the
    # algebra and Adam eps boundary, not an altered task utility or fitted model.
    x, _, full, _, _ = draw(arrays, p, "iid", 32)
    mixed = MixedEncoderBatch(x, full)
    rng = np.random.default_rng(p["draw_seed"] + 1)
    rdh = rng.normal(size=(64, 32)) * p["adversarial_dH_reference_scale"]
    model = models["drifted"].clone()
    for key in CONTENT_PARAMETERS:
        model.params[key].fill(0)
    heads = {
        key: np.zeros_like(model.params[key])
        for key in CONTENT_PARAMETERS
        if key not in ("encoder", "bias")
    }
    rb = (np.zeros((64, 32)), rdh, np.zeros((64, 12)), np.zeros((64, 12)))
    for name in ("hidden_cancellation", "mean_cancellation"):
        dh = (
            0.2 * rdh + rng.normal(size=(64, 32)) * p["adversarial_dH_residual_scale"]
            if name == "hidden_cancellation"
            else rng.normal(size=(64, 32)) * 0.01
        )
        mean = {key: np.zeros_like(model.params[key]) for key in CONTENT_PARAMETERS}
        if name == "mean_cancellation":
            changed = dh - 0.2 * rdh
            mean["encoder"] = -mixed.encoder_gradient(changed) / 0.2
            mean["bias"] = -changed.sum(0) / 0.2
        old, _ = combine(model, mixed, dh, heads, rb, mean, "CV-d2", False)
        raw, _ = combine(model, mixed, dh, heads, rb, mean, "CV-fused", False)
        for mode in ("CV-d2", "CV-fused"):
            ledger.charge_kernel(
                "adversarial", mode, **combine_work(model.dimensions, 64, 32, mode)
            )
        row = {
            "fixture": name,
            "raw_gradient": compare(
                raw, old, p["gradient_rtol"], p["gradient_atol"], ledger
            ),
            "updates": [],
        }
        vectors[name + "_gold"] = flat(old)
        vectors[name + "_unconditional_raw"] = flat(raw)
        for clock in p["moment_fixture_clocks"]:
            moments(model, clock)
            hybrid, info = combine(
                model, mixed, dh, heads, rb, mean, "CV-hybrid", False
            )
            ledger.charge_kernel(
                "adversarial",
                "CV-hybrid",
                **combine_work(
                    model.dimensions, 64, 32, "CV-hybrid", fallback=info["fallback"]
                ),
            )
            assert info["fallback"] == ("empty_moments" if clock == 0 else name)
            hybrid_check = compare_update(
                model, old, hybrid, 1.0, clock, library, ledger, p
            )
            raw_check = compare_update(model, old, raw, 1.0, clock, library, ledger, p)
            row["updates"].append(
                {
                    "clock": clock,
                    "hybrid": hybrid_check,
                    "hybrid_path": info,
                    "unconditional_raw": raw_check,
                }
            )
            result["required_pass"] &= hybrid_check["pass"]
            if not raw_check["pass"]:
                result["unconditional_raw_failures_retained"].append(
                    {"fixture": name, "clock": clock, **raw_check}
                )
        result["adversarial"].append(row)
    result["gradient_vector_sha256"] = {
        key: hashlib.sha256(value.astype("<f8").tobytes()).hexdigest()
        for key, value in vectors.items()
    }
    result["analytic_first_empty_Adam_sensitivity_LR_over_eps"] = (
        p["unit_update_learning_rate"] / 1e-8
    )
    result["limits"] = (
        "conditional panel checks; not a global numerical or bitwise proof; raw failures stay failures"
    )
    return result
