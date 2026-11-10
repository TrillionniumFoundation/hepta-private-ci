"""Reachability bounds for actual frozen heads; no model training or tuning."""

import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.optimize import linprog, minimize
from scipy.special import logsumexp

BASE = Path("/workspace/scratch/c385a7439f8e")
SOURCE = BASE / "actual-frozen-heads.json"
OUT = BASE / "frozen-head-domain-review-v1.json"
started = time.perf_counter()
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
heads = json.loads(SOURCE.read_bytes())


def linear_margin(weight, bias, target, domain):
    others = np.arange(len(bias)) != target
    differences = weight[target] - weight[others]
    offsets = bias[target] - bias[others]
    objective = np.r_[np.zeros(weight.shape[1]), -1.0]
    bounds = [(-1.0, 1.0)] * weight.shape[1] + [(None, None)]
    if domain == "nonnegative":
        bounds = [(0.0, None)] * weight.shape[1] + [(None, 1.0)]
    solved = linprog(objective, A_ub=np.c_[-differences, np.ones(len(offsets))],
                     b_ub=offsets, bounds=bounds, method="highs")
    if not solved.success:
        raise RuntimeError(solved.message)
    state = solved.x[:-1]
    margin = float(np.min(differences @ state + offsets))
    result = {"target": target, "witness": state.tolist(), "witness_margin": margin,
              "unique_argmax_reachable": margin > 1e-9,
              "lp_margin": float(solved.x[-1]), "lp_status": int(solved.status)}
    if domain == "box":
        multipliers = np.maximum(0., -solved.ineqlin.marginals)
        multipliers /= multipliers.sum()
        upper = float(multipliers @ offsets + np.abs(multipliers @ differences).sum())
        result.update(dual_simplex_weights=multipliers.tolist(), margin_upper_bound=upper,
                      primal_dual_gap=upper - margin)
    else:
        direction = linprog(np.ones(weight.shape[1]), A_ub=-differences,
                            b_ub=-np.ones(len(offsets)), bounds=(0, None), method="highs")
        result["probability_one_supremum_direction_feasible"] = bool(direction.success)
        if direction.success:
            result["positive_direction"] = direction.x.tolist()
            result["direction_minimum_margin"] = float(np.min(differences @ direction.x))
    return result


def box_confidence(weight, bias, target):
    def value_and_gradient(state):
        scores = weight @ state + bias
        log_normalizer = logsumexp(scores)
        probabilities = np.exp(scores - log_normalizer)
        return float(log_normalizer - scores[target]), probabilities @ weight - weight[target]
    result = minimize(value_and_gradient, np.zeros(weight.shape[1]), jac=True,
                      method="L-BFGS-B", bounds=[(-1, 1)] * weight.shape[1],
                      options={"gtol": 1e-12, "ftol": 1e-15, "maxiter": 1000})
    value, gradient = value_and_gradient(result.x)
    # For convex NLL over a box, the Frank-Wolfe gap bounds suboptimality.
    gap = float(gradient @ result.x + np.abs(gradient).sum())
    return {"target": target, "probability_achieved": float(np.exp(-value)),
            "probability_upper_bound": float(min(1., np.exp(-(value - gap)))),
            "nll_lower_bound": value - gap, "convex_optimality_gap": gap,
            "solver_success": bool(result.success), "witness": result.x.tolist()}


cases = []
for head in heads:
    weight, bias = np.array(head["weight"]), np.array(head["bias"])
    classes, width = weight.shape
    if width != 16 or classes != 11:
        raise ValueError("This exact enumeration is scoped to width 16 and 11 classes.")
    states = ((np.arange(2**width, dtype=np.uint32)[:, None]
               >> np.arange(width, dtype=np.uint32)) & 1).astype(float)
    logits = states @ weight.T + bias
    probabilities = np.exp(logits - logsumexp(logits, axis=1, keepdims=True))
    predictions = logits.argmax(1)
    binary = []
    for target in range(classes):
        margin = logits[:, target] - np.max(logits[:, np.arange(classes) != target], axis=1)
        best = int(margin.argmax())
        best_probability = int(probabilities[:, target].argmax())
        binary.append({"target": target, "maximum_margin": float(margin[best]),
            "unique_argmax_reachable": bool(margin[best] > 1e-9),
            "argmax_state_count": int((predictions == target).sum()),
            "margin_witness": states[best].astype(int).tolist(),
            "maximum_probability": float(probabilities[best_probability, target]),
            "probability_witness": states[best_probability].astype(int).tolist()})
    box = [linear_margin(weight, bias, target, "box") for target in range(classes)]
    positive = [linear_margin(weight, bias, target, "nonnegative") for target in range(classes)]
    box_prob = [box_confidence(weight, bias, target) for target in range(classes)]
    singular = np.linalg.svd(weight, compute_uv=False)
    right_inverse = weight.T @ np.linalg.solve(weight @ weight.T, np.eye(classes))
    desired = 20 * np.eye(classes, width)
    adapter_weight, adapter_bias = right_inverse @ desired, -right_inverse @ bias
    witness_states = np.eye(width)[:classes]
    adapted_logits = (witness_states @ adapter_weight.T + adapter_bias) @ weight.T + bias
    margins = [float(adapted_logits[i, i] - max(np.delete(adapted_logits[i], i))) for i in range(classes)]
    case = {"seed": head["seed"], "initial_checkpoint_source": head["source"],
        "initial_checkpoint_sha256": head["initial_file_sha256"],
        "actual_head_sha256": head["initial_head_sha256"], "head_rank": int(np.linalg.matrix_rank(weight)),
        "head_condition_2": float(singular[0] / singular[-1]), "head_singular_values": singular.tolist(),
        "binary_exact_state_count": 2**width, "plif_binary": binary, "gru_box": box,
        "gru_probability_bounds": box_prob, "event_lif_nonnegative": positive,
        "identity_adapter_added_real_parameters": width * width + width,
        "constructed_shared_adapter": {"weight": adapter_weight.tolist(), "bias": adapter_bias.tolist(),
            "target_linear_map": desired.tolist(),
            "head_times_adapter_error": float(np.max(np.abs(weight @ adapter_weight - desired))),
            "bias_cancel_error": float(np.max(np.abs(weight @ adapter_bias + bias))),
            "eleven_binary_class_witness_margins": margins},
    }
    cases.append(case)

report = {"schema": "hcsn-frozen-head-output-domain-review-v1",
    "created_utc": datetime.now(timezone.utc).isoformat(), "reviewer": "/root/math_contract",
    "actual_heads_file": str(SOURCE), "actual_heads_sha256": sha(SOURCE),
    "review_source_sha256": sha(Path(__file__)), "python": platform.python_version(),
    "numpy": np.__version__, "scipy": scipy.__version__, "cases": cases,
    "scope": "Outer output-domain feasibility for actual frozen head weights. It does not prove a temporal core can realize any witness on data or that SGD learns it.",
    "adapter_statement": "When W has full row rank, z=A*h+c before frozen W*z+b can realize any linear logit map V*h+d via A=W_right_inverse*V and c=W_right_inverse*(d-b). This removes a head-domain bottleneck; it is functionally a trainable linear readout over core states and changes the experiment.",
    "training_runs": 0, "scientific_admission": "HOLD", "wall_seconds": time.perf_counter() - started}
with OUT.open("x") as stream:
    json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
    stream.write("\n")
for case in cases:
    print(json.dumps({"seed": case["seed"], "head_rank": case["head_rank"],
        "plif_unreachable": [r["target"] for r in case["plif_binary"] if not r["unique_argmax_reachable"]],
        "gru_unreachable": [r["target"] for r in case["gru_box"] if not r["unique_argmax_reachable"]],
        "event_positive_unreachable": [r["target"] for r in case["event_lif_nonnegative"] if not r["unique_argmax_reachable"]],
        "plif_probability_range": [min(r["maximum_probability"] for r in case["plif_binary"]), max(r["maximum_probability"] for r in case["plif_binary"])],
        "gru_probability_upper_range": [min(r["probability_upper_bound"] for r in case["gru_probability_bounds"]), max(r["probability_upper_bound"] for r in case["gru_probability_bounds"])],
        "box_lp_max_gap": max(r["primal_dual_gap"] for r in case["gru_box"]),
        "box_nll_max_gap": max(r["convex_optimality_gap"] for r in case["gru_probability_bounds"]),
        "adapter_witness_min_margin": min(case["constructed_shared_adapter"]["eleven_binary_class_witness_margins"])}))
print(json.dumps({"path": str(OUT), "bytes": OUT.stat().st_size, "sha256": sha(OUT), "wall_seconds": report["wall_seconds"]}))
