"""One-shot held-out evaluation of a frozen finite-scene experiment.

This measures decoded synthetic-task behavior, not natural-image capability or
general NDU/FBSDE efficacy. Selection and training never consume this module.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from control import Controller
from data import caption, dataset, decoded_metrics, manifest, outcome_table
from model import JointModel
from utility import joint_value_and_grad

ROOT = Path(__file__).resolve().parent


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def exclusive_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def artifact_path(run, name):
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError("artifact must be a run-local filename")
    path = run / name
    if path.is_symlink() or not path.is_file():
        raise ValueError("artifact missing or not a regular local file")
    return path


def measure(model, controller, data, price, rho, dynamic, forced_route=None):
    ps, qs, latencies, steps = [], [], [], []
    before = model.digest()
    for row in range(len(data["labels"])):
        started = time.perf_counter_ns()
        key = "low" if dynamic else "full"
        p, q = model.forward(data[key][row:row + 1])
        used = 1
        proceed = controller.decide(p, q, remaining_steps=1, price=price)[0] if dynamic else False
        if forced_route is not None:
            proceed = forced_route[row]  # Critic still ran; only its decision is ignored.
        if proceed:
            p, q = model.forward(data["full"][row:row + 1])
            used += 1
        # Include actual greedy decoding in request latency, not the external
        # scoring/rendering used after the request has completed.
        caption(int(p.argmax(axis=1)[0]))
        model.decode_images(q.argmax(axis=1))
        latencies.append((time.perf_counter_ns() - started) / 1e6)
        ps.append(p[0]); qs.append(q[0]); steps.append(used)
    if model.digest() != before:
        raise ValueError("inference changed selected weights")
    p, q = np.asarray(ps), np.asarray(qs)
    reward = outcome_table(model)[data["labels"]]
    metrics = decoded_metrics(model, p, q, data["labels"])
    metrics["task_utility"] = np.einsum("ni,nij,nj->n", p, reward, q)
    metrics["entropic"] = joint_value_and_grad(p, q, reward, rho)[0]
    metrics["greedy_task_utility"] = reward[np.arange(len(p)), p.argmax(1), q.argmax(1)]
    d, k, _, h = model.dimensions
    operations = controller.inference_operation_estimate(len(p)) if dynamic else {
        "scalar_operations": 0, "log_evaluations": 0, "sort_items": 0}
    report = {"means": {key: float(value.mean()) for key, value in metrics.items()},
              "per_row": {key: value.tolist() for key, value in metrics.items()},
              "model_forwards": int(sum(steps)), "model_macs": int(sum(steps) * (d * h + 2 * h * k)),
              "controller_accounting_estimate": operations,
              "continued_fraction": float(np.mean(np.asarray(steps) == 2)),
              "latency_ms": {"p50": float(np.percentile(latencies, 50)),
                             "p95": float(np.percentile(latencies, 95))},
              "maximum_forwards_per_request": max(steps), "budget_violations": sum(s > 2 for s in steps)}
    return report, p, q


def paired_interval(rows, groups, comparator, mode, metric, other_mode=None):
    """Paired crossed seed/source-group bootstrap; variants stay in their group."""
    seeds = sorted({row["seed"] for row in rows})
    ids = np.asarray(groups)
    unique = sorted(set(groups))
    differences = []
    for seed in seeds:
        pair = {row["arm"]: row for row in rows if row["seed"] == seed}
        delta = (np.asarray(pair["ndu"][mode]["per_row"][metric])
                 - np.asarray(pair[comparator][other_mode or mode]["per_row"][metric]))
        differences.append([delta[ids == group].mean() for group in unique])
    delta = np.asarray(differences)
    rng = np.random.default_rng(77431)
    draws = np.empty(2000)
    for i in range(len(draws)):
        sampled_seeds = rng.integers(len(seeds), size=len(seeds))
        sampled_groups = rng.integers(len(unique), size=len(unique))
        draws[i] = delta[np.ix_(sampled_seeds, sampled_groups)].mean()
    low, high = np.percentile(draws, [2.5, 97.5])
    return {"mean": float(delta.mean()), "ci95": [float(low), float(high)],
            "seeds": seeds, "source_groups": len(unique), "replicates": len(draws)}


def run_evaluation(run):
    run = Path(run).resolve()
    if (run / "test-result.json").exists() or (run / "test-opened.json").exists():
        raise ValueError("test already opened; never overwrite or silently re-evaluate")
    selection_path = artifact_path(run, "selection.json")
    selected = json.loads(selection_path.read_text())
    plan = selected["plan"]
    dynamic_gate = plan["dynamic_gate"]
    if (sha256(ROOT / "plan.json") != selected["plan_sha256"]
            or json.loads((ROOT / "plan.json").read_text()) != plan or selected["test_opened"]):
        raise ValueError("frozen plan mismatch")
    for name, digest in selected["sources"].items():
        if sha256(artifact_path(ROOT, name)) != digest:
            raise ValueError("execution source changed after selection: " + name)
    if not {"model.py", "data.py", "utility.py", "control.py"} <= selected["sources"].keys():
        raise ValueError("execution source identity incomplete")
    train, val = dataset("train", plan["variants"]), dataset("validation", plan["variants"])
    for split, data in (("train", train), ("validation", val)):
        if manifest(data) != selected["datasets"][split]:
            raise ValueError("frozen dataset mismatch")
    expected = {(seed, arm) for seed in plan["model_seeds"] for arm in plan["arms"]}
    if {(row["seed"], row["arm"]) for row in selected["selected"]} != expected or len(selected["selected"]) != len(expected):
        raise ValueError("missing or duplicate seed/arm")
    bundles = []
    for row in selected["selected"]:
        model_path, ctrl_path = artifact_path(run, row["model_file"]), artifact_path(run, row["controller_file"])
        if sha256(model_path) != row["model_sha256"] or sha256(ctrl_path) != row["controller_sha256"]:
            raise ValueError("artifact bytes changed")
        model = JointModel.load(model_path)
        with np.load(ctrl_path, allow_pickle=False) as arrays:
            controller = Controller.from_arrays(arrays)
        if (row["rho"] != plan["rho"] or row["compute_price"] != plan["compute_price"]
                or controller.classes != model.dimensions[1] or row["capabilities"] != ["text", "image"]):
            raise ValueError("selected utility/control profile mismatch")
        reload = JointModel.load(model_path)
        if (model.digest() != row["artifact_sha256"] or reload.digest() != model.digest()
                or not all(np.array_equal(a, b) for a, b in zip(model.forward(val["low"][:2]), reload.forward(val["low"][:2])))):
            raise ValueError("reload identity/logits mismatch")
        bundles.append((row, model, controller))
    exclusive_json(run / "test-opened.json", {"selection_sha256": sha256(selection_path),
                   "evaluator_sha256": sha256(__file__), "opened_unix_ns": time.time_ns()})
    test = dataset("test", plan["variants"])  # The only test-set construction.
    for left, right in ((train, val), (train, test), (val, test)):
        if set(left["groups"]) & set(right["groups"]) or set(left["input_hashes"]) & set(right["input_hashes"]):
            raise ValueError("source-group or input-byte leakage")
    rows = []
    for row, model, controller in bundles:
        full, p, q = measure(model, controller, test, row["compute_price"], row["rho"], False)
        dynamic, _, _ = measure(model, controller, test, row["compute_price"], row["rho"], True)
        corrupt = model.clone()
        corrupt.params["decoder"] = np.roll(corrupt.params["decoder"], 1, axis=0)
        bad = np.einsum("ni,nij,nj->n", p, outcome_table(corrupt)[test["labels"]], q).mean()
        rows.append({"seed": row["seed"], "arm": row["arm"], "always_full": full,
                     "dynamic": dynamic, "reload_verified": True,
                     "decoder_corruption_score_drop": full["means"]["task_utility"] - float(bad)})
    for seed in plan["model_seeds"]:
        ndu_row = next(row for row in rows if row["seed"] == seed and row["arm"] == "ndu")
        count = ndu_row["dynamic"]["model_forwards"] - len(test["labels"])
        route = np.zeros(len(test["labels"]), dtype=bool)
        route[np.argsort(np.asarray(test["input_hashes"]), kind="stable")[:count]] = True
        for bundle, model, controller in bundles:
            if bundle["seed"] == seed and bundle["arm"] in ("supervised", "ndu"):
                row = next(row for row in rows if row["seed"] == seed and row["arm"] == bundle["arm"])
                row["matched_random"], _, _ = measure(model, controller, test, bundle["compute_price"],
                                                       bundle["rho"], True, forced_route=route)
                if (row["matched_random"]["model_forwards"] != ndu_row["dynamic"]["model_forwards"]
                        or row["matched_random"]["controller_accounting_estimate"] != ndu_row["dynamic"]["controller_accounting_estimate"]):
                    raise ValueError("dynamic matched-compute accounting differs")
    interval_metrics = ("task_utility", "joint_success", "greedy_task_utility", "greedy_joint_success")
    intervals = {mode: {arm: {metric: paired_interval(rows, test["groups"], arm, mode, metric)
                 for metric in interval_metrics}
                 for arm in ("supervised", "additive")} for mode in ("always_full", "dynamic")}
    matched_intervals = {arm: {metric: paired_interval(rows, test["groups"], arm, "dynamic", metric, "matched_random")
                              for metric in interval_metrics} for arm in ("supervised", "ndu")}
    gate = plan["benefit_gate"]
    positive = all(intervals["always_full"][arm][metric]["ci95"][0] > gate[
        "paired_decoded_utility_ci95_lower_gt" if metric == "task_utility" else "paired_joint_success_ci95_lower_gt"]
        for arm in ("supervised", "additive") for metric in ("task_utility", "joint_success"))
    dynamic_positive = all(matched_intervals["ndu"][metric]["ci95"][0] > dynamic_gate[
        "paired_decoded_utility_ci95_lower_gt" if metric == "task_utility" else "paired_joint_success_ci95_lower_gt"]
        for metric in ("task_utility", "joint_success"))
    max_drop = max(next(r for r in rows if r["seed"] == seed and r["arm"] == arm)["always_full"]["means"]["greedy_joint_success"]
                   - next(r for r in rows if r["seed"] == seed and r["arm"] == "ndu")["always_full"]["means"]["greedy_joint_success"]
                   for seed in plan["model_seeds"] for arm in ("supervised", "additive"))
    corruption = all(row["decoder_corruption_score_drop"] > 0 for row in rows)
    violations = sum(row[mode]["budget_violations"] for row in rows
                     for mode in ("always_full", "dynamic", "matched_random") if mode in row)
    cost_keys = ("examples", "tensor_macs", "joint_outcome_cells")
    matched = all(len({row["cost"][key] for row in selected["selected"]}) == 1 for key in cost_keys)
    common = bool(max_drop <= gate["maximum_greedy_accuracy_drop"] and corruption
                  and violations == gate["strict_budget_violations"] and matched)
    content_benefit = bool(positive and common)
    dynamic_benefit = bool(dynamic_positive and common)
    result = {"schema": "hepta.joint-generation.test-result.v1", "scope": plan["scope"],
              "selection_sha256": sha256(selection_path), "plan_sha256": selected["plan_sha256"],
              "evaluator_sha256": sha256(__file__), "test": manifest(test), "all_seed_results": rows,
              "paired_intervals": intervals, "matched_dynamic_intervals": matched_intervals,
              "routing_only_baseline": "supervised.dynamic",
              "matched_random_route": "input SHA256 stable ascending order, same continue count as NDU dynamic; every critic executes",
              "accounting": "model MAC estimates exclude scalar nonlinearities; controller scalar/log/sort work separately reported; CPU latency measured",
              "adaptation_work_scope": {"included": list(cost_keys), "excluded": ["shared base pretraining", "decoder training",
                  "controller fitting", "hyperparameter search/selection", "validation", "held-out evaluation"]},
              "output_law": "sampling from the two content distributions; greedy metrics are diagnostics and the frozen retention bound",
              "gates": {"positive_paired_intervals": positive, "maximum_greedy_drop": max_drop,
                        "positive_dynamic_matched_intervals": dynamic_positive,
                        "decoder_corruption_reduces_score": corruption, "budget_violations": violations,
                        "matched_adaptation_work": matched, "all_seeds_reported": True},
              "content_benefit_verified": content_benefit, "dynamic_benefit_verified": dynamic_benefit,
              "benefit_verified": content_benefit and dynamic_benefit,
              "claims": {"finite_scene_only": True, "natural_images": False,
                         "general_fbsde": False, "synchronous_audio_video": False, "production_activation": False}}
    exclusive_json(run / "test-result.json", result)
    print(json.dumps({"result": str(run / "test-result.json"), "benefit_verified": result["benefit_verified"],
                      "gates": result["gates"]}, sort_keys=True))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    result = run_evaluation(parser.parse_args().run)
    raise SystemExit(0 if result["benefit_verified"] else 1)
