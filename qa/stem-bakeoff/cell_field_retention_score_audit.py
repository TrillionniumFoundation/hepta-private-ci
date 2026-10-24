"""Independent v2 heldout metric and interval reconstruction; no evaluator import."""

import itertools
import json
from pathlib import Path

import numpy as np

from cell_field_audit import _load_arrays, sha, verify_seal


def audit_evaluation(run_dir, data_dir, protocol_path, evaluation_file):
    root, data = Path(run_dir), Path(data_dir)
    seal = verify_seal(root)
    runs = json.loads((root / "runs.json").read_bytes())
    protocol = json.loads(Path(protocol_path).read_bytes())
    evaluation = json.loads(Path(evaluation_file).read_bytes())
    receipt = json.loads((data / "data_receipt.json").read_bytes())
    if (protocol["seeds"] != [7, 17, 29] or protocol["head_modes"] != ["linear", "gated"]
            or protocol["primary_family"]["alpha"] != 0.05 or protocol["primary_family"]["comparisons"] != 8
            or protocol["primary_family"]["retention_margin"] != 0.0):
        raise ValueError("primary family changed")
    if (sha(Path(protocol_path).read_bytes()) != seal["protocol_sha256"]
            or evaluation["protocol_sha256"] != seal["protocol_sha256"]
            or evaluation["pre_evaluation_seal_sha256"] != sha((root / "pre_evaluation_seal.json").read_bytes())
            or sha((data / "data_receipt.json").read_bytes()) != runs["data_receipt_sha256"]):
        raise ValueError("final evaluation or input identity differs")
    labels_bytes = (data / "final_labels.json").read_bytes()
    if sha(labels_bytes) != receipt["files"]["final_labels.json"]["sha256"] or sha(labels_bytes) != evaluation["final_labels_sha256"]:
        raise ValueError("final label identity differs")
    final = json.loads(labels_bytes)["roles"]
    sources_bytes = (data / "sources.json").read_bytes()
    if sha(sources_bytes) != receipt["files"]["sources.json"]["sha256"]:
        raise ValueError("source identities changed")
    sources = json.loads(sources_bytes)["rows"]
    if ([row["source_id"] for row in sources] != runs["source_ids"]
            or len({row["component_id"] for row in sources}) != len(sources)):
        raise ValueError("source order or independence differs")
    roles = ("old_test", "future_may", "future_june")
    if set(final) != set(roles):
        raise ValueError("final role census differs")
    prediction = _load_arrays(root / "predictions.npz")
    if (prediction["probabilities"].shape != (len(runs["records"]), len(sources), 4)
            or prediction["initial_probabilities"].shape != (len(runs["initial_order"]), len(sources), 4)):
        raise ValueError("prediction tensor census differs")
    saved = {(row["run_id"], row["role"]): row for row in evaluation["records"]}
    saved_initial = {(row["initial_index"], row["role"]): row for row in evaluation["initial"]}
    if (len(saved) != len(evaluation["records"]) or len(saved) != 3 * len(runs["records"])
            or len(saved_initial) != len(evaluation["initial"]) or len(saved_initial) != 3 * len(runs["initial_order"])):
        raise ValueError("final metric census missing or duplicated")
    count, maximum, minimum_gold = 0, 0.0, 1.0

    def close(actual, expected):
        nonlocal count, maximum
        a, b = np.asarray(actual), np.asarray(expected)
        if a.shape != b.shape or not np.isfinite(a).all() or not np.isfinite(b).all():
            raise ValueError("invalid numeric comparison")
        error = float(np.max(np.abs(a - b)))
        count += a.size
        maximum = max(maximum, error)
        if error > 2e-12 * (1 + float(np.max(np.abs(b)))):
            raise ValueError("independent score or interval differs")

    def summarize(p, y):
        nonlocal minimum_gold
        if (p.shape != (len(y), 4) or not np.isfinite(p).all() or np.any(p < 0)
                or not np.allclose(p.sum(axis=1), 1, atol=1e-12, rtol=0)):
            raise ValueError("invalid probability tensor")
        correct = (p.argmax(axis=1) == y).astype(float)
        gold = p[np.arange(len(y)), y]
        minimum_gold = min(minimum_gold, float(gold.min()))
        losses = -np.log(np.maximum(gold, np.finfo(float).tiny))
        summary = {"rows": len(y), "nll": losses.mean(), "accuracy": correct.mean(),
                   "balanced_accuracy": np.mean([correct[y == c].mean() for c in range(4)]),
                   "brier": np.square(p - np.eye(4)[y]).sum(axis=1).mean()}
        return summary, {"nll": losses, "accuracy": correct}

    scores, draws = {}, {}
    rng = np.random.default_rng(820241)
    if protocol["bootstrap_seed"] != 820241 or protocol["bootstrap_replicates"] != 10000:
        raise ValueError("bootstrap design changed")
    for role in roles:
        y, indices = np.asarray(final[role]["labels"]), np.asarray(final[role]["indices"])
        wanted = [i for i, row in enumerate(sources) if row["role"] == role]
        if (indices.dtype.kind not in "iu" or indices.tolist() != wanted or y.shape != indices.shape
                or y.dtype.kind not in "iu" or set(y.tolist()) != set(range(4))
                or [sources[i]["source_id"] for i in indices] != final[role]["source_ids"]):
            raise ValueError("final role order or labels differ")
        draws[role] = np.concatenate([rng.choice(np.where(y == c)[0], size=(10000, int(np.sum(y == c))))
                                      for c in range(4)], axis=1)
        initial_summaries = {}
        for number, info in enumerate(runs["initial_order"]):
            row = saved_initial[(number, role)]
            if info["status"] != "completed":
                if row.get("metrics", "missing") is not None:
                    raise ValueError("failed initial state was scored")
                continue
            summary, individual = summarize(prediction["initial_probabilities"][number, indices], y)
            for key, value in summary.items(): close(row[key], value)
            initial_summaries[number] = summary
            for mask in protocol["action_masks"]:
                scores[(info["seed"], info["head"], mask, "warmup", role)] = individual
        for number, info in enumerate(runs["records"]):
            row = saved[(info["run_id"], role)]
            if info["status"] != "completed":
                if row.get("metrics", "missing") is not None:
                    raise ValueError("failed condition was scored")
                continue
            summary, individual = summarize(prediction["probabilities"][number, indices], y)
            for key, value in summary.items(): close(row[key], value)
            warmup = initial_summaries[info["initial_index"]]
            for metric in ("nll", "accuracy"):
                close(row[metric + "_change_from_warmup"], summary[metric] - warmup[metric])
            scores[(info["seed"], info["head"], info["mask"], info["policy"], role)] = individual

    def difference(head, mask, left, right, role, metric):
        keys = [(seed, head, mask, method, role) for seed in protocol["seeds"] for method in (left, right)]
        if any(key not in scores for key in keys): return None
        return np.array([scores[(seed, head, mask, left, role)][metric]
                         - scores[(seed, head, mask, right, role)][metric] for seed in protocol["seeds"]]).sum(axis=0) / 3

    pairs = (("loss2", "myopic"), ("loss2", "zero"), ("extended", "loss2"), ("full", "loss2"),
             ("loss2", "symmetric_loss2"), ("symmetric_loss2", "zero"))
    expected_secondary = set(itertools.product(protocol["head_modes"], protocol["action_masks"], roles, pairs,
                                               ("nll", "accuracy")))
    actual_secondary = set()
    secondary_completed = 0
    for row in evaluation["contrasts"]:
        key = (row["head"], row["mask"], row["role"], (row["left"], row["right"]), row["metric"])
        if key in actual_secondary: raise ValueError("duplicate secondary comparison")
        actual_secondary.add(key)
        delta = difference(row["head"], row["mask"], row["left"], row["right"], row["role"], row["metric"])
        if delta is None:
            if row["status"] != "incomplete_registered_conditions": raise ValueError("failed seed silently dropped")
            continue
        if row["status"] != "completed" or row["source_components"] != len(delta): raise ValueError("secondary scope differs")
        samples = delta[draws[row["role"]]].sum(axis=1) / len(delta)
        close(row["difference_left_minus_right"], delta.mean())
        close(row["pointwise_percentile_95"], np.percentile(samples, [2.5, 97.5]))
        secondary_completed += 1
    if expected_secondary != actual_secondary: raise ValueError("secondary comparison census differs")
    expected_primary = set(itertools.product(protocol["head_modes"],
                            (("future_equal_month_nll", "zero"), ("future_equal_month_nll", "myopic"),
                             ("old_test", "zero"), ("old_test", "warmup"))))
    actual_primary, primary_complete, decisions = set(), 0, {head: [] for head in protocol["head_modes"]}
    for row in evaluation["primary_contrasts"]:
        key = (row["head"], (row["endpoint"], row["right"]))
        if key in actual_primary: raise ValueError("duplicate primary comparison")
        actual_primary.add(key)
        used_roles = roles[1:] if row["endpoint"] == "future_equal_month_nll" else roles[:1]
        values = [difference(row["head"], "all", "loss2", row["right"], role, "nll") for role in used_roles]
        if (row["mask"] != "all" or row["left"] != "loss2" or row["metric"] != "nll"
                or row["roles"] != list(used_roles) or row["threshold"] != 0
                or row["upper_bound_rule"] != ("strictly_below_zero" if len(used_roles) == 2 else "at_most_zero")):
            raise ValueError("primary endpoint definition changed")
        if any(value is None for value in values):
            if row["status"] != "incomplete_registered_conditions" or row["criterion_met"] is not False:
                raise ValueError("incomplete primary criterion was accepted")
            decisions[row["head"]].append((False, False))
            continue
        point = sum(delta.mean() for delta in values) / len(values)
        samples = sum(delta[draws[role]].sum(axis=1) / len(delta)
                      for role, delta in zip(used_roles, values)) / len(values)
        interval = np.percentile(samples, [0.3125, 99.6875])
        passed = bool(interval[1] < 0) if len(used_roles) == 2 else bool(interval[1] <= 0)
        close(row["difference_left_minus_right"], point)
        close(row["bonferroni_percentile_interval"], interval)
        close(row["quantiles"], [0.003125, 0.996875])
        if (row["criterion_met"] != passed or row["source_components"] != sum(len(delta) for delta in values)
                or row["components_by_role"] != {role: len(delta) for role, delta in zip(used_roles, values)}):
            raise ValueError("primary acceptance or source scope differs")
        decisions[row["head"]].append((True, passed))
        primary_complete += 1
    if expected_primary != actual_primary: raise ValueError("primary comparison census differs")
    expected_decisions = [{"head": head, "registered_criteria": 4,
                           "completed_criteria": sum(value[0] for value in decisions[head]),
                           "met_criteria": sum(value[1] for value in decisions[head]),
                           "all_primary_criteria_met": all(value[1] for value in decisions[head])}
                          for head in protocol["head_modes"]]
    if (evaluation["decisions"] != expected_decisions
            or evaluation["all_heads_primary_criteria_met"] != all(row["all_primary_criteria_met"] for row in expected_decisions)):
        raise ValueError("reported decision differs from registered primary criteria")
    return {"schema": "hepta.cell-retention-independent-score-audit.v2",
            "scored_condition_roles": len(saved), "scored_initial_roles": len(saved_initial),
            "secondary_intervals_recomputed": secondary_completed, "primary_intervals_recomputed": primary_complete,
            "scalar_equalities_checked": count, "maximum_absolute_error": maximum,
            "minimum_gold_probability": minimum_gold, "decisions": expected_decisions,
            "evaluator_imported": False, "evaluation_sha256": sha(Path(evaluation_file).read_bytes()),
            "auditor_sha256": sha(Path(__file__).read_bytes()),
            "interval_scope": "fixed 8-comparison Bonferroni-adjusted approximate source bootstrap; no finite-sample coverage guarantee"}
