"""The original candidate's bounded D-only inverse-temperature rule, in float64."""

import math
import numpy as np


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(logits, labels):
    require(type(logits) is np.ndarray and logits.dtype == np.float64
            and logits.ndim == 2 and logits.shape[1] == 11 and logits.shape[0] > 0,
            "nonempty float64 N-by-11 logits")
    require(type(labels) is np.ndarray and labels.ndim == 1 and labels.shape[0] == logits.shape[0]
            and labels.dtype.kind in "iu" and ((labels >= 0) & (labels < 11)).all(), "integer class labels")
    require(np.isfinite(logits).all(), "finite logits")


def fit(logits, labels, checkpoint=lambda: None, observe=lambda event: None):
    """Fit one scalar parameter; no neural model or tensor optimizer is constructed."""
    observe({"event": "scalar_parameter_optimization_started"})
    validate(logits, labels)
    with np.errstate(over="raise", invalid="raise"):
        centered = logits - logits.max(axis=1, keepdims=True)
    truth = centered[np.arange(len(labels)), labels]
    evaluations, cache, trace = [], {}, []

    def evaluate(beta):
        checkpoint()
        require(type(beta) is float and math.isfinite(beta) and .01 <= beta <= 100., "inverse-temperature bounds")
        if beta in cache:
            return cache[beta]
        observe({"event": "calibration_evaluation_started", "beta": beta})
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            scaled = beta * centered
            exponential = np.exp(scaled)
            denominator = exponential.sum(axis=1)
            probability = exponential / denominator[:, None]
            mean = (probability * centered).sum(axis=1)
            values = {"beta": beta, "nll": float((np.log(denominator) - beta * truth).mean()),
                      "gradient": float((mean - truth).mean()),
                      "hessian": float((probability * (centered - mean[:, None]) ** 2).sum(axis=1).mean())}
        require(all(math.isfinite(v) for v in values.values()) and values["hessian"] >= 0, "finite convex objective")
        evaluations.append(values); cache[beta] = values
        observe({"event": "calibration_evaluation_completed", **values})
        return values

    raw, lower, upper = evaluate(1.), evaluate(.01), evaluate(100.)
    low, high = .01, 100.
    flat = bool(np.all(logits == logits[:, :1]))
    if flat:
        beta, outcome, stop = 1., "FLAT", "exactly_equal_classes_in_every_row"
    elif lower["gradient"] >= 0:
        beta, outcome, stop = low, "LOWER_BOUND", "lower_endpoint_KKT"
    elif upper["gradient"] <= 0:
        beta, outcome, stop = high, "UPPER_BOUND", "upper_endpoint_KKT"
    else:
        outcome, stop = "INTERIOR", "iteration_cap"
        for iteration in range(1, 101):
            checkpoint()
            midpoint = low + (high - low) / 2
            if high - low <= 1e-12 * max(1., abs(midpoint)):
                stop = "relative_bracket_width"; break
            if not low < midpoint < high:
                stop = "no_representable_interior"; break
            value = evaluate(float(midpoint))
            move = "lower" if value["gradient"] < 0 else "upper"
            trace.append({"iteration": iteration, "lower_before": low, "upper_before": high,
                          "midpoint": midpoint, "gradient": value["gradient"], "move": move})
            observe({"event": "bisection_update", **trace[-1]})
            if move == "lower":
                low = midpoint
            else:
                high = midpoint
        beta = float(low + (high - low) / 2)
    final = evaluate(beta)
    bracket = {"lower": low, "upper": high, "width": high - low, "midpoint": low + (high - low) / 2}
    if outcome == "INTERIOR":
        bracket.update(lower_gradient=evaluate(float(low))["gradient"], upper_gradient=evaluate(float(high))["gradient"])
    with np.errstate(over="raise", invalid="raise"):
        calibrated_logits = beta * logits
    unchanged = bool(np.array_equal(logits.argmax(axis=1), calibrated_logits.argmax(axis=1)))
    require(unchanged, "raw and calibrated argmax equality")
    return {"schema": "original-candidate-D-temperature-fit-v1", "beta": beta, "temperature": 1 / beta,
            "outcome": outcome, "stop_reason": stop, "flat_exact": flat, "bounds": [.01, 100.],
            "raw": raw, "lower_endpoint": lower, "upper_endpoint": upper, "final": final,
            "final_bracket": bracket, "trace": trace, "evaluations": evaluations,
            "scalar_parameter_optimization_calls": 1, "bisection_updates": len(trace),
            "objective_derivative_hessian_evaluations": len(evaluations), "argmax_unchanged": unchanged,
            "neural_model_forward_backward_calls": 0, "neural_optimizer_operations": 0}
