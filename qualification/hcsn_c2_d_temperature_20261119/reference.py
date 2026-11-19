"""Different blockwise long-double arithmetic; no rigorous enclosure is claimed."""

import math
import numpy as np


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(logits, labels, result, checkpoint=lambda: None, observe=lambda event: None):
    require(np.finfo(np.longdouble).eps < np.finfo(np.float64).eps, "independent wider arithmetic available")
    references = {}

    def calculate(beta):
        if beta in references:
            return references[beta]
        observe({"event": "reference_evaluation_started", "beta": beta})
        totals = np.zeros(3, dtype=np.longdouble)
        for first in range(0, len(labels), 2048):
            checkpoint()
            z = logits[first:first + 2048].astype(np.longdouble)
            y = labels[first:first + 2048]
            a = np.longdouble(beta) * z
            a -= a.max(axis=1, keepdims=True)
            weights = np.exp(a)
            weights /= weights.sum(axis=1, keepdims=True, dtype=np.longdouble)
            per_nll = np.log(np.exp(a).sum(axis=1, dtype=np.longdouble)) - a[np.arange(len(y)), y]
            differences = z - z[np.arange(len(y)), y, None]
            per_gradient = (weights * differences).sum(axis=1, dtype=np.longdouble)
            per_hessian = (weights * (differences - per_gradient[:, None]) ** 2).sum(axis=1, dtype=np.longdouble)
            totals += np.array([per_nll.sum(dtype=np.longdouble), per_gradient.sum(dtype=np.longdouble),
                                per_hessian.sum(dtype=np.longdouble)])
        values = {name: float(value / len(labels)) for name, value in zip(["nll", "gradient", "hessian"], totals)}
        require(all(math.isfinite(v) for v in values.values()) and values["hessian"] >= 0, "finite independent arithmetic")
        references[beta] = {"beta": beta, **values}
        observe({"event": "reference_evaluation_completed", **references[beta]})
        return references[beta]

    # This new arithmetic-consistency tolerance is frozen before fitting; it is
    # not an original protocol convergence criterion or a rigorous error bound.
    def close(actual, expected):
        return abs(actual - expected) <= 1e-10 * max(1., abs(expected))

    errors = []
    for key in ["raw", "lower_endpoint", "upper_endpoint", "final"]:
        saved = result[key]; reference = calculate(saved["beta"])
        for field in ["nll", "gradient", "hessian"]:
            require(close(saved[field], reference[field]), "independent " + key + " " + field)
            errors.append({"point": key, "field": field, "absolute_error": abs(saved[field] - reference[field])})
    low, high = .01, 100.
    for number, step in enumerate(result["trace"], 1):
        midpoint = low + (high - low) / 2
        require(step["iteration"] == number and step["lower_before"] == low and step["upper_before"] == high
                and step["midpoint"] == midpoint and low < midpoint < high, "exact bisection trajectory")
        require(step["move"] == ("lower" if step["gradient"] < 0 else "upper"), "derivative-sign bisection move")
        if step["move"] == "lower":
            low = midpoint
        else:
            high = midpoint
    require(len(result["trace"]) <= 100 and result["bisection_updates"] == len(result["trace"]), "bounded scalar updates")
    require(result["objective_derivative_hessian_evaluations"] == len(result["evaluations"]), "complete evaluation count")
    beta, outcome, strict_signs = result["beta"], result["outcome"], None
    lower, upper = calculate(.01)["gradient"], calculate(100.)["gradient"]
    flat = bool(np.all(logits == logits[:, :1]))
    if outcome == "FLAT":
        require(flat and beta == 1. and not result["trace"], "only exact flat exception")
    elif outcome == "LOWER_BOUND":
        strict_signs = lower >= 0
        require(not flat and beta == .01 and lower >= -1e-10 and not result["trace"], "lower endpoint KKT consistency")
    elif outcome == "UPPER_BOUND":
        strict_signs = lower < 0 and upper <= 0
        require(not flat and beta == 100. and lower < 0 and upper <= 1e-10 and not result["trace"], "upper endpoint KKT consistency")
    else:
        require(outcome == "INTERIOR" and not flat and lower < 0 and upper > 0, "interior endpoint signs")
        bracket = result["final_bracket"]
        require(bracket["lower"] == low and bracket["upper"] == high and beta == low + (high - low) / 2,
                "final bracket and midpoint")
        require(high - low <= 1e-12 * max(1., abs(beta)) or not low < beta < high, "original stopping criterion")
        lo_grad, hi_grad = calculate(low)["gradient"], calculate(high)["gradient"]
        strict_signs = lo_grad <= 0 <= hi_grad
        require(lo_grad <= 1e-10 and hi_grad >= -1e-10, "final-bracket sign consistency at declared tolerance")
    require(result["temperature"] == 1 / beta and .01 <= beta <= 100., "positive temperature identity")
    require(calculate(beta)["nll"] <= calculate(1.)["nll"] + 1e-10, "calibration does not increase D NLL")
    require(np.array_equal(logits.argmax(axis=1), (np.longdouble(beta) * logits.astype(np.longdouble)).argmax(axis=1)),
            "independent argmax equality")
    return {"schema": "D-temperature-independent-arithmetic-v1", "status": "PASS", "errors": errors,
            "reference_points": list(references.values()), "strict_KKT_or_bracket_signs": strict_signs,
            "consistency_tolerance": "1e-10 * max(1,abs(reference)); sign and NLL slack 1e-10",
            "tolerance_origin": "new implementation check frozen before D calibration, not the original stopping rule",
            "longdouble_epsilon": str(np.finfo(np.longdouble).eps), "argmax_unchanged": True,
            "independent_reference_evaluations": len(references), "intermediate_gradients_recomputed": False,
            "neural_forward_backward_calls": 0, "scalar_optimization_calls": 0,
            "scope": "Independent endpoint/final/bracket arithmetic and trajectory structure; longdouble is not a rigorous enclosure."}
