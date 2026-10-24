"""Fixed paired contrasts with source-group bootstrap and separate task families.

Seeds are averaged after scoring within each replicate; probabilities are never
ensembled. Shared resamples retain dependence across targets, seeds and arms.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from cell_calibrated_curve import inventory, sha_file, write_json
from cell_learning_models import canonical


METRICS = ("balanced_accuracy", "nll", "auroc", "balanced_accuracy_at_prior_threshold")


def metric_vectors(case, counts, group_index):
    """Recompute row-denominator metrics under cluster multiplicities."""
    y, p = case["labels"], case["probabilities"]
    w = counts[:, [group_index[g] for g in case["group_ids"]]].astype(np.float64)
    positive, negative = y == 1, y == 0
    pos, neg = w[:, positive].sum(axis=1), w[:, negative].sum(axis=1)
    predicted = p.argmax(axis=1)
    balanced = p[:, 1] > case["prior_threshold"] + 1e-12
    with np.errstate(divide="ignore", invalid="ignore"):
        ba = .5*((w[:, positive]*predicted[positive]).sum(axis=1)/pos
                 +(w[:, negative]*(1-predicted[negative])).sum(axis=1)/neg)
        prior_ba = .5*((w[:, positive]*balanced[positive]).sum(axis=1)/pos
                       +(w[:, negative]*(~balanced[negative])).sum(axis=1)/neg)
        nll = (w @ -np.log(np.clip(p[np.arange(len(y)), y], 1e-15, 1))) / (pos+neg)
        order = np.argsort(p[:, 1], kind="stable")
        _, starts, sizes = np.unique(p[order, 1], return_index=True, return_counts=True)
        ends = starts+sizes-1
        weighted_negative = w[:, order]*(1-y[order])
        cumulative = np.cumsum(weighted_negative, axis=1)
        through = cumulative[:, ends]
        before = np.concatenate((np.zeros((len(w), 1)), through[:, :-1]), axis=1)
        mid = .5*(through+before)
        tie_index = np.repeat(np.arange(len(starts)), sizes)
        auc = (w[:, order]*y[order]*mid[:, tie_index]).sum(axis=1)/(pos*neg)
    return np.column_stack((ba, nll, auc, prior_ba))


def load_cases(study, arm, budget):
    root = Path(study).resolve()
    plan = json.loads((root/"study-plan.json").read_bytes())
    summary = json.loads((root/"summary.json").read_bytes())
    bindings = {str(root/name): sha_file(root/name) for name in ("study-plan.json", "summary.json")}
    cases, unavailable = {}, []
    for task in plan["tasks"]:
        if task not in summary["tasks_evaluated"]:
            unavailable.append({"task": task, "reason": "task unavailable in completed study"})
            continue
        evaluation = root/task/"evaluation"
        seal = json.loads((evaluation/"seal.json").read_bytes())
        if (seal.get("schema") not in ("hepta.calibrated-evaluation-seal.v1", "hepta.modality-off-evaluation-seal.v1")
                or seal.get("files") != inventory(evaluation)):
            raise ValueError("evaluation inventory is not unchanged and sealed")
        bindings.update({str(evaluation/name): sha_file(evaluation/name) for name in ("seal.json", "report.json")})
        report = json.loads((evaluation/"report.json").read_bytes())
        prepared_path = root/task/"prepared/frozen.json"
        prepared = None
        if prepared_path.exists():
            prepared_seal = prepared_path.parent/"seal.json"
            seal_value = json.loads(prepared_seal.read_bytes())
            if (report["plan"]["prepared_seal_sha256"] != sha_file(prepared_seal)
                    or seal_value["files"]["frozen.json"]["sha256"] != sha_file(prepared_path)):
                raise ValueError("prepared source-selection binding changed")
            prepared = json.loads(prepared_path.read_bytes())
            bindings.update({str(p): sha_file(p) for p in (prepared_path, prepared_seal)})
        if report["plan"]["family_id"] != plan["families"][task]:
            raise ValueError("task family changed between study and evaluation")
        if any(type(y) is not int or y not in (0, 1) for y in report["labels"]):
            raise ValueError("sealed labels must be binary integers")
        y = np.asarray(report["labels"], dtype=np.int64)
        for seed in plan["protocol"]["seeds"]:
            run = next((r for r in report["runs"] if r["budget"] == budget and r["seed"] == seed), None)
            if run is None:
                unavailable.append({"task": task, "seed": seed, "budget": budget, "reason": "training budget unavailable"})
                continue
            name = run["selected_arm"] if arm == "selected" else arm
            bits = name.split(".")
            scored = run["arms"][bits[0]]
            if len(bits) == 2:
                scored = scored["controls"][bits[1]]
            elif len(bits) != 1:
                raise ValueError("invalid fixed arm reference")
            path = evaluation/run["directory"]/scored["prediction_file"]
            if sha_file(path) != scored["prediction_sha256"]:
                raise ValueError("raw prediction artifact changed")
            bindings[str(path)] = sha_file(path)
            with np.load(path, allow_pickle=False) as archive:
                p = archive["probabilities"].copy()
            if (p.shape != (len(y), 2) or not np.isfinite(p).all() or np.any(p < 0)
                    or not np.allclose(p.sum(axis=1), 1, rtol=1e-10, atol=1e-10)):
                raise ValueError("invalid sealed probabilities")
            case = {"task": task, "seed": seed, "family": plan["families"][task],
                    "source_ids": tuple(report["source_ids"]), "group_ids": tuple(report["group_ids"]),
                    "labels": y, "probabilities": p,
                    "prior_threshold": scored["secondary_discrimination"]["calibration_prior_threshold"]}
            source_run = next((r for r in prepared["runs"] if r["seed"] == seed and r["budget"] == budget), None) if prepared else run
            source_plan = prepared["plan"] if prepared else report["plan"]
            case["training_source_ids"] = tuple(source_run["training_source_ids"]) if source_run and "training_source_ids" in source_run else None
            for field in ("tuning_source_ids", "calibration_source_ids"):
                case[field] = tuple(source_plan[field]) if field in source_plan else None
            groups = {g: i for i, g in enumerate(sorted(set(case["group_ids"])))}
            recomputed = metric_vectors(case, np.ones((1, len(groups))), groups)[0]
            expected = [scored["semantic"][k] if k in ("balanced_accuracy", "nll")
                        else scored["secondary_discrimination"][k] for k in METRICS]
            if any((v is None and np.isfinite(a)) or (v is not None and not np.isclose(a, v, atol=1e-10, rtol=1e-10))
                   for a, v in zip(recomputed, expected)):
                raise ValueError("raw probabilities do not reproduce reported point metrics")
            cases[(task, seed)] = case
    return plan, cases, unavailable, bindings


def paired_bootstrap(left, right, *, seeds, declared_tasks, families, draws=2000, seed=20261024):
    if type(draws) is not int or not 100 <= draws <= 10000 or type(seed) is not int:
        raise ValueError("bounded fixed bootstrap plan required")
    included, unavailable = [], []
    for task in declared_tasks:
        if any((task, s) not in left or (task, s) not in right for s in seeds):
            unavailable.append({"task": task, "reason": "not all fixed seeds and paired budgets available"})
            continue
        for s in seeds:
            a, b = left[(task, s)], right[(task, s)]
            if (a["source_ids"] != b["source_ids"] or a["group_ids"] != b["group_ids"]
                    or not np.array_equal(a["labels"], b["labels"]) or a["family"] != b["family"]
                    or a["family"] != families[task]):
                raise ValueError("paired source rows, group identities, labels or target family differ")
            if any(a.get(field) != b.get(field) for field in
                   ("training_source_ids", "tuning_source_ids", "calibration_source_ids")):
                raise ValueError("paired training, tuning or calibration source selections differ")
            first = left[(task, seeds[0])]
            if a["source_ids"] != first["source_ids"] or a["group_ids"] != first["group_ids"] or not np.array_equal(a["labels"], first["labels"]):
                raise ValueError("seed cohorts differ")
        included.append(task)
    groups = sorted({g for task in included for g in left[(task, seeds[0])]["group_ids"]})
    if not groups:
        return {"status": "not_evaluable", "families": [], "unavailable_tasks": unavailable}, np.empty((draws, 0), dtype=np.int32), []
    index = {g: i for i, g in enumerate(groups)}
    counts = np.random.default_rng(seed).multinomial(len(groups), np.full(len(groups), 1/len(groups)), size=draws)
    # The first row is the exact observed dataset; remaining rows are resamples.
    all_counts = np.vstack((np.ones((1, len(groups)), dtype=np.int64), counts))
    task_values = {}
    for task in included:
        values = []
        for condition in (left, right):
            values.append(np.mean([metric_vectors(condition[(task, s)], all_counts, index) for s in seeds], axis=0))
        task_values[task] = values
    results = []
    for family in sorted(set(families.values())):
        selected = [t for t in included if families[t] == family]
        declared = [t for t in declared_tasks if families[t] == family]
        if not selected:
            results.append({"family": family, "status": "not_evaluable", "declared_tasks": declared})
            continue
        a = np.mean([task_values[t][0] for t in selected], axis=0)
        b = np.mean([task_values[t][1] for t in selected], axis=0)
        delta, estimates = a-b, {}
        for i, metric in enumerate(METRICS):
            valid = np.isfinite(a[1:, i]) & np.isfinite(b[1:, i])
            sampled = delta[1:, i][valid]
            estimates[metric] = {"left": float(a[0, i]) if np.isfinite(a[0, i]) else None,
                "right": float(b[0, i]) if np.isfinite(b[0, i]) else None,
                "difference_left_minus_right": float(delta[0, i]) if np.isfinite(delta[0, i]) else None,
                "ci95_percentile": np.quantile(sampled, [.025, .975]).tolist() if len(sampled) >= 100 else None,
                "valid_bootstrap_draws": int(valid.sum()), "invalid_bootstrap_draws": int((~valid).sum())}
        results.append({"family": family, "status": "evaluated", "tasks": selected, "declared_tasks": declared,
            "all_declared_tasks_present": selected == declared, "fixed_seed_count": len(seeds),
            "source_groups": len({g for t in selected for g in left[(t, seeds[0])]["group_ids"]}),
            "metrics": estimates})
    return {"status": "evaluated", "families": results, "unavailable_tasks": unavailable,
        "joint_source_group_count": len(groups), "bootstrap_draws": draws, "bootstrap_seed": seed,
        "averaging": "score each seed within each group draw, mean seeds within task, mean tasks within family",
        "cross_family_grand_mean": None, "confidence_scope": "descriptive conditional fixed-contrast intervals; no multiplicity correction",
        "training_tuning_calibration_source_pairing_verified": all(
            left[(t, s)].get(field) is not None for t in included for s in seeds
            for field in ("training_source_ids", "tuning_source_ids", "calibration_source_ids")),
        "tasks_or_seeds_treated_as_independent": False}, counts.astype(np.int32), groups


def analyze_pair(left_study, right_study, *, left_arm, right_arm, output, budget=128, draws=2000, seed=20261024):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    plan = {"schema": "hepta.calibrated-paired-analysis.v1", "left_study": str(Path(left_study).resolve()),
        "right_study": str(Path(right_study).resolve()), "left_arm": left_arm, "right_arm": right_arm,
        "budget": budget, "draws": draws, "seed": seed, "metrics": list(METRICS),
        "source_sha256": sha_file(__file__), "selection_by_heldout_outcomes": False,
        "aggregation_scope": "separate declared task families; no universal aggregate"}
    write_json(root/"plan.json", plan)
    lp, lc, lu, lb = load_cases(left_study, left_arm, budget)
    rp, rc, ru, rb = load_cases(right_study, right_arm, budget)
    if (lp["dataset_sha256"] != rp["dataset_sha256"] or lp["tasks"] != rp["tasks"]
            or lp["families"] != rp["families"] or canonical(lp["protocol"]) != canonical(rp["protocol"])
            or lp["holdout_use"] != rp["holdout_use"]):
        raise ValueError("contrast does not share dataset, targets, protocol and heldout-use designation")
    report, counts, groups = paired_bootstrap(lc, rc, seeds=lp["protocol"]["seeds"],
        declared_tasks=lp["tasks"], families=lp["families"], draws=draws, seed=seed)
    bindings = {**lb, **rb}
    if any(sha_file(path) != digest for path, digest in bindings.items()):
        raise ValueError("raw comparison inputs changed during analysis")
    with (root/"bootstrap-counts.npz").open("xb") as stream:
        np.savez_compressed(stream, counts=counts)
    result = {"plan": plan, **report, "source_groups_in_column_order": groups,
        "holdout_use": lp["holdout_use"], "unavailable_left": lu, "unavailable_right": ru,
        "source_bindings": bindings, "draw_archive_sha256": sha_file(root/"bootstrap-counts.npz")}
    write_json(root/"report.json", result)
    write_json(root/"seal.json", {"schema": "hepta.paired-analysis-seal.v1", "files": inventory(root)})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("left-study", "right-study", "left-arm", "right-arm", "output"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--budget", type=int, choices=(8, 32, 122, 128), default=128)
    args = parser.parse_args()
    analyze_pair(args.left_study, args.right_study, left_arm=args.left_arm,
                 right_arm=args.right_arm, output=args.output, budget=args.budget)


if __name__ == "__main__":
    main()
