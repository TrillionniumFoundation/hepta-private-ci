"""Frozen candidate evaluation with paired source-component resampling.

The percentile bootstrap is approximate and conditional on the three fitted
seeds and sampled sources. Bonferroni allocation is not a distribution-free
family guarantee. Actions and fitted seeds never increase source sample size.
"""

import itertools
import json
from pathlib import Path

import numpy as np

from cell_field_evaluate import metrics
from cell_field_features import file_hash


TASKS = ("uci", "newsgroups")
HEADS = ("linear", "gated")
SEEDS = (7, 17, 29)
POLICIES = ("zero", "myopic_full_h1", "loss2_h8", "q4_h8", "history4_h8",
            "structured4_h8", "full_h8")
SPLITS = ("current", "future", "old")
CANDIDATE = "structured4_h8"


def evaluation_protocol():
    """Embed this exact object in the protocol before any evaluation outcome."""
    return {"tasks": list(TASKS), "heads": list(HEADS), "seeds": list(SEEDS),
            "policies": list(POLICIES), "splits": list(SPLITS), "candidate": CANDIDATE,
            "bootstrap_replicates": 10000, "bootstrap_seed": 20261025,
            "family_alpha": 0.05, "family_size": 12, "improvement_margin": 0.001,
            "retention_margin": 0.0, "max_cpu_ratio": 3.0,
            "bootstrap_method": "class-stratified source-component percentile; per-example seed average; higher quantile",
            "cpu_aggregation": "sum over three paired seeds per task/head",
            "cpu_scope": "dense construction, planning and execution; common encoder and warmup reported separately"}


def verify_pre_label_seal(run_directory, protocol_path):
    """Verify local hash inventory before labels; not a signature/attestation."""
    root = Path(run_directory)
    seal_path = root / "pre_evaluation_seal.json"
    if root.is_symlink() or seal_path.is_symlink():
        raise ValueError("regular sealed run directory required")
    seal = json.loads(seal_path.read_bytes())
    paths = list(root.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("symlink in sealed inventory")
    actual = {path.relative_to(root).as_posix() for path in paths
              if path.is_file() and path != seal_path}
    if (seal.get("final_labels_opened") is not False or not seal.get("files")
            or actual != set(seal["files"]) or file_hash(protocol_path) != seal.get("protocol_sha256")):
        raise ValueError("changed protocol, inventory, or label-access disposition")
    for name, entry in seal["files"].items():
        path = root / name
        if (Path(name).is_absolute() or ".." in Path(name).parts
                or not path.resolve().is_relative_to(root.resolve())
                or type(entry.get("bytes")) is not int or path.stat().st_size != entry["bytes"]
                or file_hash(path) != entry.get("sha256")):
            raise ValueError("sealed prediction artifact changed: " + name)
    return seal


def _draw_components(labels, components, rng, draws):
    labels, components = np.asarray(labels), np.asarray(components)
    if (labels.ndim != 1 or labels.dtype.kind not in "iu" or set(labels.tolist()) != set(range(4))
            or components.shape != labels.shape or components.dtype.kind not in "US"
            or np.any(components == "")):
        raise ValueError("four classes and explicit aligned source-component IDs required")
    names, inverse = np.unique(components, return_inverse=True)
    classes = np.zeros(len(names), dtype=np.int64)
    for index in range(len(names)):
        group = np.unique(labels[inverse == index])
        if len(group) != 1:
            raise ValueError("class-stratified bootstrap requires single-label components")
        classes[index] = group[0]
    samples = np.concatenate([rng.choice(np.flatnonzero(classes == label),
                                         (draws, int(np.sum(classes == label))), replace=True)
                              for label in range(4)], axis=1)
    return inverse, samples


def bootstrap_upper(differences, labels, components, *, draws=10000,
                    seed=20261025, alpha=0.05/12, prepared=None):
    """Seed-averaged per-example differences, clustered and paired across rules."""
    delta = np.asarray(differences, dtype=np.float64)
    if delta.ndim != 1 or delta.shape != np.shape(labels) or not np.isfinite(delta).all():
        raise ValueError("one finite paired difference per source row required")
    if type(draws) is not int or draws < 1 or not 0 < alpha < 1:
        raise ValueError("positive bootstrap count and valid one-sided alpha required")
    inverse, samples = (_draw_components(labels, components, np.random.default_rng(seed), draws)
                        if prepared is None else prepared)
    sums = np.bincount(inverse, weights=delta)
    counts = np.bincount(inverse)
    boot = sums[samples].sum(axis=1) / counts[samples].sum(axis=1)
    return {"difference": float(delta.mean()),
            "upper_bound": float(np.quantile(boot, 1-alpha, method="higher")),
            "one_sided_quantile": 1-alpha, "source_rows": len(delta),
            "source_components": len(counts), "replicates": len(samples)}


def _seed_entry(collection, task, head, seed):
    group = collection.get(task, {}).get(head, {})
    return group.get(seed, group.get(str(seed), {}))


def evaluate_probabilities(probabilities, labels, components, protocol, costs=None):
    """Score a frozen full census; missing/invalid outputs close acceptance gates.

    probabilities[task][head][seed][policy][current|future|old] contains (N,4)
    arrays. Each seed also has warmup_old (Nold,4). Labels and component IDs
    are task/split arrays. Costs use the same task/head/seed/policy nesting.
    This pure core receives already-opened labels; file callers verify the seal
    and persist their access receipt before loading the label payload.
    """
    plan = protocol.get("evaluation", protocol)
    if plan != evaluation_protocol():
        raise ValueError("frozen primary family or evaluation protocol changed")
    rng = np.random.default_rng(plan["bootstrap_seed"])
    prepared = {}
    for task in TASKS:
        seen = set()
        for split in SPLITS:
            ids = set(np.asarray(components[task][split]).tolist())
            if seen & ids:
                raise ValueError("source component crosses declared evaluation roles")
            seen |= ids
            prepared[task, split] = _draw_components(
                labels[task][split], components[task][split], rng, plan["bootstrap_replicates"])
    records, scores = [], {}
    for task, head, seed in itertools.product(TASKS, HEADS, SEEDS):
        entry = _seed_entry(probabilities, task, head, seed)
        for policy in (*POLICIES, "warmup_old"):
            for split in (("old",) if policy == "warmup_old" else SPLITS):
                row = {"task": task, "head": head, "seed": seed, "policy": policy, "split": split}
                policy_rows = entry.get(policy)
                values = entry.get("warmup_old") if policy == "warmup_old" else (
                    policy_rows.get(split) if isinstance(policy_rows, dict) else None)
                if values is None:
                    row.update(status="unavailable", reason="missing frozen policy output")
                else:
                    try:
                        summary, loss, _ = metrics(values, labels[task][split])
                        row.update(status="completed", **summary)
                        scores[task, head, seed, policy, split] = loss
                    except (ValueError, TypeError) as error:
                        row.update(status="invalid", reason=str(error))
                records.append(row)
    census_complete = all(row["status"] == "completed" for row in records)
    primary = []
    comparisons = (("future", "myopic_full_h1", -0.001),
                   ("future", "loss2_h8", -0.001), ("old", "warmup_old", 0.0))
    for task, head, (split, baseline, threshold) in itertools.product(TASKS, HEADS, comparisons):
        row = {"task": task, "head": head, "split": split, "candidate": CANDIDATE,
               "baseline": baseline, "threshold": threshold, "criterion_met": False,
               "status": "unavailable", "fixed_seeds": list(SEEDS)}
        keys = [(task, head, seed, policy, split) for seed in SEEDS for policy in (CANDIDATE, baseline)]
        if all(key in scores for key in keys):
            paired = np.stack([scores[task, head, seed, CANDIDATE, split]
                               - scores[task, head, seed, baseline, split] for seed in SEEDS])
            interval = bootstrap_upper(paired.mean(axis=0), labels[task][split], components[task][split],
                                       prepared=prepared[task, split])
            passed = interval["upper_bound"] < threshold if split == "future" else interval["upper_bound"] <= threshold
            seed_means = paired.mean(axis=1)
            row.update(status="completed", **interval, criterion_met=bool(passed),
                       paired_seed_mean_differences=seed_means.tolist(),
                       paired_seed_range=[float(seed_means.min()), float(seed_means.max())])
        primary.append(row)
    cost_rows = []
    for task, head in itertools.product(TASKS, HEADS):
        row = {"task": task, "head": head, "candidate": CANDIDATE, "baseline": "myopic_full_h1",
               "threshold": 3.0, "status": "unavailable", "criterion_met": False}
        pair = [[_seed_entry(costs or {}, task, head, seed).get(policy, {})
                 for policy in (CANDIDATE, "myopic_full_h1")] for seed in SEEDS]
        if all(info.get("status") == "completed" and type(info.get("cpu_ns")) in (int, float)
               and np.isfinite(info["cpu_ns"]) and info["cpu_ns"] > 0 for both in pair for info in both):
            ratio = sum(both[0]["cpu_ns"] for both in pair)/sum(both[1]["cpu_ns"] for both in pair)
            row.update(status="completed", cpu_ratio=float(ratio), criterion_met=bool(ratio <= 3),
                       paired_seed_cpu_ratios=[both[0]["cpu_ns"]/both[1]["cpu_ns"] for both in pair])
        cost_rows.append(row)
    cost_records = [_seed_entry(costs or {}, task, head, seed).get(policy, {})
                    for task, head, seed, policy in itertools.product(TASKS, HEADS, SEEDS, POLICIES)]
    cost_census_complete = all(info.get("status") == "completed"
                               and type(info.get("cpu_ns")) in (int, float)
                               and np.isfinite(info["cpu_ns"]) and info["cpu_ns"] > 0 for info in cost_records)
    science = census_complete and all(row["criterion_met"] for row in primary)
    resource = cost_census_complete and all(row["criterion_met"] for row in cost_rows)
    return {"schema": "hepta.cell-field-evaluation.v4", "candidate": CANDIDATE,
            "records": records, "primary_contrasts": primary, "cost_contrasts": cost_rows,
            "registered_fits": 12, "registered_policy_outputs": 84,
            "census_complete": census_complete, "cost_census_complete": cost_census_complete,
            "primary_criteria_met": sum(r["criterion_met"] for r in primary),
            "all_scientific_criteria_met": bool(science), "all_cost_criteria_met": bool(resource),
            "all_registered_gates_met": bool(science and resource),
            "bootstrap": {**plan, "scope": "approximate percentile family; conditional on fixed fitted models and sampled cohorts, no seed-population or distribution-free coverage"},
            "production_authority": False}


def predictor_metrics(real_delta, predicted_delta, actions, dt, target, effort_price, names):
    """Descriptive same-action prediction/ranking; actions are not replicates."""
    from scipy.stats import kendalltau, spearmanr
    from cell_field_control import quadratic_cost
    real, predicted, actions = map(np.asarray, (real_delta, predicted_delta, actions))
    if (real.ndim != 3 or real.shape[1] < 2 or real.shape[2] != 2
            or not len(names) or len(set(names)) != len(names)
            or predicted.shape != (len(names), *real.shape)
            or actions.ndim != 2 or len(actions) != len(real)
            or not all(np.isfinite(v).all() for v in (real, predicted, actions))):
        raise ValueError("finite aligned action/predictor loss paths required")
    action_paths = np.zeros((len(actions), real.shape[1]-1, actions.shape[1]))
    action_paths[:, 0] = actions
    actual = np.array([quadratic_cost(path, u, target, dt, effort_price)["total"]
                       for path, u in zip(real, action_paths)])
    output = []
    for name, paths in zip(names, predicted):
        scores = np.array([quadratic_cost(path, u, target, dt, effort_price)["total"]
                           for path, u in zip(paths, action_paths)])
        order = np.argsort(scores, kind="stable")
        varied = np.ptp(actual) > 0 and np.ptp(scores) > 0
        output.append({"mode": name, "loss_rmse": float(np.sqrt(np.square(paths-real).mean())),
                       "terminal_loss_rmse": float(np.sqrt(np.square(paths[:, -1]-real[:, -1]).mean())),
                       "cost_mae": float(np.abs(scores-actual).mean()),
                       "spearman": float(spearmanr(scores, actual).statistic) if varied else None,
                       "kendall": float(kendalltau(scores, actual).statistic) if varied else None,
                       "selected_action_index": int(order[0]),
                       "top1_regret": float(actual[order[0]]-actual.min()),
                       "top5_set_regret": float(actual[order[:min(5, len(order))]].min()-actual.min()),
                       "action_count": len(actions), "inference_scope": "descriptive within one frozen anchor"})
    return output
