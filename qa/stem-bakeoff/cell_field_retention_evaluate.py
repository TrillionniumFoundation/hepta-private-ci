"""Frozen retention-study scoring after the complete policy-output seal.

The eight primary intervals use a Bonferroni-adjusted approximate percentile
bootstrap, conditional on the fixed fitted models. This is not a finite-sample
distribution-free family-coverage guarantee. Equal-month pooling is declared
before outcomes; individual fitted seeds never increase source sample size.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import time

import numpy as np

from cell_field_evaluate import (metrics, stratified_draws, validate_probabilities,
                                 verify_pre_evaluation)
from cell_field_features import file_hash
from cell_learning_models import canonical


ROLES = ("old_test", "future_may", "future_june")
PAIRS = (("loss2", "myopic"), ("loss2", "zero"), ("extended", "loss2"),
         ("full", "loss2"), ("loss2", "symmetric_loss2"), ("symmetric_loss2", "zero"))
PRIMARY = (("future_equal_month_nll", "zero"), ("future_equal_month_nll", "myopic"),
           ("old_test", "zero"), ("old_test", "warmup"))


def validate_plan(plan):
    family = plan["primary_family"]
    if (plan["head_modes"] != ["linear", "gated"]
            or plan["action_masks"] != ["bias", "all"]
            or plan["policies"] != ["zero", "myopic", "loss2", "extended", "full", "symmetric_loss2"]
            or plan["seeds"] != [7, 17, 29] or plan["classes"] != 4
            or plan["bootstrap_replicates"] != 10000 or plan["bootstrap_seed"] != 820241
            or plan["secondary_pairs"] != [list(pair) for pair in PAIRS]
            or family["alpha"] != 0.05 or family["comparisons"] != 8
            or family["mask"] != "all" or family["future_roles"] != list(ROLES[1:])
            or family["future_pooling"] != "equal month means" or family["retention_margin"] != 0.0):
        raise ValueError("primary family or registered evaluation protocol changed")


def paired_delta(scores, seeds, head, mask, left, right, role, metric):
    """Average fixed-model differences at each independent source component."""
    keys = [(seed, head, mask, method, role) for seed in seeds for method in (left, right)]
    if any(key not in scores for key in keys):
        return None
    return np.mean([scores[(seed, head, mask, left, role)][metric]
                    - scores[(seed, head, mask, right, role)][metric] for seed in seeds], axis=0)


def equal_month_bootstrap(differences, draws):
    """Each month receives one half of endpoint weight, regardless of row count."""
    if len(differences) != 2 or len(draws) != 2:
        raise ValueError("two predeclared historical month endpoints required")
    point = float(np.mean([delta.mean() for delta in differences]))
    boot = np.mean([delta[index].mean(axis=1) for delta, index in zip(differences, draws)], axis=0)
    return point, boot


def compare_scores(scores, draws, plan):
    secondary, primary = [], []
    for head, mask, role, pair, metric in itertools.product(
            plan["head_modes"], plan["action_masks"], ROLES, PAIRS, ("nll", "accuracy")):
        delta = paired_delta(scores, plan["seeds"], head, mask, *pair, role, metric)
        row = {"head": head, "mask": mask, "role": role, "left": pair[0], "right": pair[1],
               "metric": metric, "status": "incomplete_registered_conditions"}
        if delta is not None:
            boot = delta[draws[role]].mean(axis=1)
            row.update(status="completed", difference_left_minus_right=float(delta.mean()),
                       pointwise_percentile_95=np.quantile(boot, [0.025, 0.975]).tolist(),
                       source_components=len(delta), fixed_model_seeds=plan["seeds"])
        secondary.append(row)
    quantiles = [plan["primary_family"]["alpha"] / (2 * 8),
                 1 - plan["primary_family"]["alpha"] / (2 * 8)]
    for head, (endpoint, right) in itertools.product(plan["head_modes"], PRIMARY):
        roles = ROLES[1:] if endpoint == "future_equal_month_nll" else ROLES[:1]
        values = [paired_delta(scores, plan["seeds"], head, "all", "loss2", right, role, "nll")
                  for role in roles]
        row = {"head": head, "mask": "all", "endpoint": endpoint, "left": "loss2", "right": right,
               "metric": "nll", "roles": list(roles), "status": "incomplete_registered_conditions",
               "criterion_met": False, "threshold": 0.0,
               "upper_bound_rule": "strictly_below_zero" if len(roles) == 2 else "at_most_zero"}
        if all(value is not None for value in values):
            if len(roles) == 2:
                point, boot = equal_month_bootstrap(values, [draws[role] for role in roles])
            else:
                point, boot = float(values[0].mean()), values[0][draws[roles[0]]].mean(axis=1)
            interval = np.quantile(boot, quantiles).tolist()
            passed = interval[1] < 0 if len(roles) == 2 else interval[1] <= 0
            row.update(status="completed", difference_left_minus_right=point,
                       bonferroni_percentile_interval=interval, quantiles=quantiles,
                       source_components=sum(len(value) for value in values),
                       components_by_role={role: len(value) for role, value in zip(roles, values)},
                       fixed_model_seeds=plan["seeds"], criterion_met=bool(passed))
        primary.append(row)
    decisions = [{"head": head, "registered_criteria": 4,
                  "completed_criteria": sum(row["status"] == "completed" for row in primary if row["head"] == head),
                  "met_criteria": sum(row["criterion_met"] for row in primary if row["head"] == head),
                  "all_primary_criteria_met": all(row["criterion_met"] for row in primary if row["head"] == head)}
                 for head in plan["head_modes"]]
    return secondary, primary, decisions


def evaluate(run_directory, data, protocol, output):
    began, cpu_began = time.perf_counter_ns(), time.process_time_ns()
    root, data, destination = Path(run_directory), Path(data), Path(output)
    seal, runs, plan = verify_pre_evaluation(root, protocol)
    validate_plan(plan)
    if destination.resolve().is_relative_to(root.resolve()):
        raise ValueError("evaluation must not mutate the sealed run directory")
    receipt_bytes = (data / "data_receipt.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    if hashlib.sha256(receipt_bytes).hexdigest() != runs["data_receipt_sha256"]:
        raise ValueError("source cohort receipt changed")
    with np.load(root / "predictions.npz", allow_pickle=False) as archive:
        probabilities, initial = archive["probabilities"], archive["initial_probabilities"]
    if (probabilities.shape != (len(runs["records"]), len(runs["source_ids"]), 4)
            or initial.shape != (len(runs["initial_order"]), len(runs["source_ids"]), 4)):
        raise ValueError("prediction census or ordered row shape differs")
    for collection, values in ((runs["records"], probabilities), (runs["initial_order"], initial)):
        for index, record in enumerate(collection):
            if record["status"] == "completed":
                validate_probabilities(values[index])
    source_bytes = (data / "sources.json").read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != receipt["files"]["sources.json"]["sha256"]:
        raise ValueError("source grouping changed")
    sources = json.loads(source_bytes)["rows"]
    if ([row["source_id"] for row in sources] != runs["source_ids"]
            or len({row["component_id"] for row in sources}) != len(sources)):
        raise ValueError("prediction order or source-component isolation differs")
    destination.mkdir(parents=True, exist_ok=False)
    access = {"schema": "hepta.cell-retention-final-label-access.v2",
              "pre_evaluation_seal_sha256": file_hash(root / "pre_evaluation_seal.json"),
              "verified_files": len(seal["files"]), "verified_registered_conditions": len(runs["records"]),
              "before_final_label_open_utc": datetime.now(timezone.utc).isoformat(),
              "source_sha256": file_hash(__file__), "scope": "local sequencing; no host attestation"}
    (destination / "label_access.json").write_bytes(canonical(access) + b"\n")
    # Only now open the final-label payload; no controller or selection occurs below.
    payload = (data / "final_labels.json").read_bytes()
    if hashlib.sha256(payload).hexdigest() != receipt["files"]["final_labels.json"]["sha256"]:
        raise ValueError("final labels differ from the frozen preparation")
    final = json.loads(payload)["roles"]
    if set(final) != set(ROLES):
        raise ValueError("unexpected final roles")
    per_run, per_initial, scores, draws = [], [], {}, {}
    rng = np.random.default_rng(plan["bootstrap_seed"])
    for role in ROLES:
        row = final[role]
        indices, labels = np.asarray(row["indices"]), np.asarray(row["labels"])
        expected_indices = [i for i, source in enumerate(sources) if source["role"] == role]
        if (indices.ndim != 1 or indices.dtype.kind not in "iu" or indices.tolist() != expected_indices
                or labels.shape != indices.shape or labels.dtype.kind not in "iu"
                or set(labels.tolist()) != set(range(4))
                or [sources[i]["source_id"] for i in indices] != row["source_ids"]):
            raise ValueError("final role indices, labels or identity are invalid")
        draws[role] = stratified_draws(labels, rng, plan["bootstrap_replicates"])
        initial_scores = {}
        for number, info in enumerate(runs["initial_order"]):
            base = {"initial_index": number, "seed": info["seed"], "head": info["head"], "role": role}
            if info["status"] != "completed":
                per_initial.append({**base, "status": "failed", "metrics": None, "error": info.get("error")})
                continue
            summary, losses, correct = metrics(initial[number, indices], labels)
            initial_scores[number] = summary
            per_initial.append({**base, **summary})
            for mask in plan["action_masks"]:
                scores[(info["seed"], info["head"], mask, "warmup", role)] = {"nll": losses, "accuracy": correct}
        for number, info in enumerate(runs["records"]):
            base = {key: info[key] for key in ("run_id", "seed", "head", "mask", "policy", "status")}
            if info["status"] != "completed":
                per_run.append({**base, "role": role, "metrics": None, "error": info.get("error")})
                continue
            summary, losses, correct = metrics(probabilities[number, indices], labels)
            before = initial_scores[info["initial_index"]]
            per_run.append({**base, "role": role, **summary,
                            "nll_change_from_warmup": summary["nll"] - before["nll"],
                            "accuracy_change_from_warmup": summary["accuracy"] - before["accuracy"]})
            scores[(info["seed"], info["head"], info["mask"], info["policy"], role)] = {"nll": losses, "accuracy": correct}
    secondary, primary, decisions = compare_scores(scores, draws, plan)
    result = {"schema": "hepta.cell-retention-evaluation.v2", "protocol_sha256": seal["protocol_sha256"],
              "pre_evaluation_seal_sha256": access["pre_evaluation_seal_sha256"],
              "final_labels_sha256": hashlib.sha256(payload).hexdigest(),
              "records": per_run, "initial": per_initial, "contrasts": secondary,
              "primary_contrasts": primary, "decisions": decisions,
              "all_heads_primary_criteria_met": all(row["all_primary_criteria_met"] for row in decisions),
              "bootstrap": {"replicates": 10000, "seed": 820241, "family_alpha": 0.05,
                            "primary_comparisons": 8,
                            "primary_interval_method": "Bonferroni-adjusted approximate percentile bootstrap",
                            "primary_quantiles": [0.003125, 0.996875],
                            "secondary_interval_method": "pointwise percentile 95%",
                            "stratification": "four source classes within each role; shared draws across methods and seeds",
                            "future_pooling": "equal month means",
                            "scope": "conditional on fixed fitted models and selected historical cohorts; no finite-sample distribution-free or seed-population guarantee"},
              "resources": {"wall_ns": time.perf_counter_ns() - began,
                            "cpu_ns": time.process_time_ns() - cpu_began},
              "evaluation_source_sha256": file_hash(__file__), "authority": "DENY_ALL",
              "production_authority": False}
    (destination / "evaluation.json").write_bytes(canonical(result) + b"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("run-directory", "data", "protocol", "output"):
        parser.add_argument("--" + argument, required=True)
    result = evaluate(**vars(parser.parse_args()))
    print(json.dumps({"scored_rows": len(result["records"]), "secondary": len(result["contrasts"]),
                      "primary": len(result["primary_contrasts"]), "decisions": result["decisions"]}))
