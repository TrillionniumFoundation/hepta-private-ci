"""V3 validation-before-final scoring of sealed one-intervention branches.

Primary comparisons are four distinct diagnostics per Head, not a unified
utility guarantee for one policy. Bootstrap intervals condition on the three
fixed fitted seeds and selected source cohorts; anchors are not resampled.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import time

import numpy as np

from cell_field_action_metrics import path_retention, rank_scores
from cell_field_evaluate import metrics, stratified_draws, validate_probabilities
from cell_learning_models import canonical


VALIDATION_ROLES = ("old_validation", "current_validation")
FINAL_ROLES = ("old_test", "future_june", "future_july", "future_august")
STATUSES = {"completed", "tangent_infeasible", "solver_failure", "execution_failure", "initial_failure"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    Path(path).write_bytes(canonical(value) + b"\n")


def method_id(observation, horizon, objective):
    return "zero" if observation == "zero" else f"{observation}_h{horizon}_{objective}"


def registered_methods(plan):
    return [("zero", 0, "zero")] + [(obs, lookahead, objective) for objective in plan["objectives"]
                                   for obs in plan["observations"] for lookahead in plan["lookaheads"]]


def validate_plan(plan):
    family = plan["primary_family"]
    if (plan["seeds"] != [7, 17, 29] or plan["head_modes"] != ["linear", "gated"]
            or plan["anchor_offsets"] != [0, 8, 16] or plan["evaluation_horizon"] != 8
            or plan["observations"] != ["loss2", "full"] or plan["lookaheads"] != [1, 4, 8]
            or plan["objectives"] != ["tracking_soft", "direct_soft", "direct_hard"]
            or plan["classes"] != 4 or family["anchor_offset"] != 16
            or family["alpha"] != 0.05 or family["comparisons"] != 8
            or plan["bootstrap_replicates"] != 10000 or plan["bootstrap_seed"] != 830241):
        raise ValueError("registered V3 design changed")
    wanted = [("loss2_h8_direct_soft", "loss2_h8_tracking_soft", FINAL_ROLES[1:], "strictly_below_zero"),
              ("loss2_h8_direct_soft", "loss2_h1_direct_soft", FINAL_ROLES[1:], "strictly_below_zero"),
              ("loss2_h8_direct_hard", "loss2_h8_direct_soft", FINAL_ROLES[:1], "at_most_zero"),
              ("loss2_h8_direct_hard", "warmup", FINAL_ROLES[:1], "at_most_zero")]
    actual = [(row["left"], row["right"], tuple(row["roles"]), row["upper_bound_rule"])
              for row in plan["primary_comparisons"]]
    if actual != wanted or any(row["metric"] != "nll" for row in plan["primary_comparisons"]):
        raise ValueError("fixed primary diagnostic family changed")
    if (len({row["id"] for row in plan["primary_comparisons"]}) != 4
            or plan["secondary_pairs"] != [["loss2_h8_direct_hard", "loss2_h8_direct_soft"],
                ["loss2_h8_direct_soft", "zero"], ["full_h8_direct_soft", "loss2_h8_direct_soft"],
                ["full_h8_direct_hard", "loss2_h8_direct_hard"], ["loss2_h8_tracking_soft", "zero"],
                ["loss2_h8_direct_soft", "loss2_h4_direct_soft"]]):
        raise ValueError("diagnostic identity or secondary family changed")


def verify_run(run_directory, data_directory, protocol_path):
    root, data = Path(run_directory), Path(data_directory)
    seal_bytes = (root / "pre_evaluation_seal.json").read_bytes()
    seal = json.loads(seal_bytes)
    actual_files = {p.relative_to(root).as_posix() for p in root.rglob("*")
                    if p.is_file() and p != root / "pre_evaluation_seal.json"}
    if (actual_files != set(seal["files"]) or seal["final_labels_opened"] is not False
            or seal["validation_labels_opened"] is not False):
        raise ValueError("incomplete pre-evaluation inventory or labels opened during decisions")
    for name, expected in seal["files"].items():
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("unsafe sealed path")
        value = path.read_bytes()
        if len(value) != expected["bytes"] or sha(value) != expected["sha256"]:
            raise ValueError("sealed file changed: " + name)
    plan_bytes = Path(protocol_path).read_bytes()
    plan = json.loads(plan_bytes)
    validate_plan(plan)
    runs = json.loads((root / "runs.json").read_bytes())
    if runs["sourcecode_hashes"] != seal["sourcecode_hashes"]:
        raise ValueError("execution source identity differs from its seal")
    for name, expected in seal["sourcecode_hashes"].items():
        if Path(name).name != name or sha(Path(__file__).with_name(name).read_bytes()) != expected:
            raise ValueError("scoring source changed after predictions were sealed")
    receipt_bytes = (data / "data_receipt.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    if (sha(plan_bytes) != seal["protocol_sha256"] or runs["protocol_sha256"] != seal["protocol_sha256"]
            or sha(receipt_bytes) != runs["data_receipt_sha256"]):
        raise ValueError("protocol or data identity differs")
    source_bytes = (data / "sources.json").read_bytes()
    if sha(source_bytes) != receipt["files"]["sources.json"]["sha256"]:
        raise ValueError("source identity changed")
    sources = json.loads(source_bytes)["rows"]
    if ([r["source_id"] for r in sources] != runs["source_ids"]
            or [r["role"] for r in sources] != runs["row_roles"]
            or len({r["component_id"] for r in sources}) != len(sources)
            or dict(Counter(r["role"] for r in sources)) != plan["source_counts"]):
        raise ValueError("source order, roles or component isolation changed")
    wanted_initials = list(itertools.product(plan["seeds"], plan["head_modes"], plan["anchor_offsets"]))
    initial_keys = [(r["seed"], r["head"], r["anchor_offset"]) for r in runs["initial_order"]]
    warmup_keys = [(r["seed"], r["head"]) for r in runs["warmup_order"]]
    if (initial_keys != wanted_initials
            or warmup_keys != list(itertools.product(plan["seeds"], plan["head_modes"]))):
        raise ValueError("common state census missing or duplicated")
    wanted = [(seed, head, anchor, obs, horizon, obj) for seed, head, anchor in wanted_initials
              for obs, horizon, obj in registered_methods(plan)]
    records = runs["records"]
    keys = [(r["seed"], r["head"], r["anchor_offset"], r["observation"], r["lookahead"], r["objective"])
            for r in records]
    if (keys != wanted or seal["record_count"] != len(wanted)
            or runs["record_count"] != len(wanted) or len({r["run_id"] for r in records}) != len(records)):
        raise ValueError("registered branch census missing or duplicated")
    for record in records:
        index, warmup = record["initial_index"], record["warmup_index"]
        if (type(index) is not int or not 0 <= index < len(initial_keys)
                or type(warmup) is not int or not 0 <= warmup < len(warmup_keys)
                or initial_keys[index] != (record["seed"], record["head"], record["anchor_offset"])
                or warmup_keys[warmup] != (record["seed"], record["head"])
                or record["method_id"] != method_id(record["observation"], record["lookahead"], record["objective"])
                or record["status"] not in STATUSES):
            raise ValueError("branch identity, state binding or disposition differs")
    for collection in (runs["initial_order"], runs["warmup_order"]):
        for state in collection:
            if state["status"] not in {"completed", "initial_failure"}:
                raise ValueError("unrecognized common-state disposition")
            if state["status"] == "completed":
                required = {state["checkpoint_path"] + "/" + name for name in ("manifest.json", "state.npz")}
                if not required <= set(seal["files"]): raise ValueError("unsealed common checkpoint")
    with np.load(root / "predictions.npz", allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    retention_indices = [i for i, row in enumerate(sources) if row["role"] in ("old_validation", "old_test")]
    if runs["retention_indices"] != retention_indices:
        raise ValueError("retention source order changed")
    expected_shapes = {"terminal_probabilities": (len(records), len(sources), 4),
        "retention_probabilities": (len(records), plan["evaluation_horizon"] + 1, len(retention_indices), 4),
        "warmup_probabilities": (len(warmup_keys), len(sources), 4),
        "initial_probabilities": (len(initial_keys), len(sources), 4)}
    if set(arrays) != set(expected_shapes) or any(arrays[name].shape != shape for name, shape in expected_shapes.items()):
        raise ValueError("prediction array census or shape differs")
    for rows, key in ((records, "terminal_probabilities"), (runs["warmup_order"], "warmup_probabilities"),
                      (runs["initial_order"], "initial_probabilities")):
        for index, record in enumerate(rows):
            if record["status"] == "completed": validate_probabilities(arrays[key][index])
            elif not np.isnan(arrays[key][index]).all(): raise ValueError("failed condition hides scored predictions")
    for index, record in enumerate(records):
        trace = arrays["retention_probabilities"][index]
        if record["status"] == "completed":
            if (runs["initial_order"][record["initial_index"]]["status"] != "completed"
                    or runs["warmup_order"][record["warmup_index"]]["status"] != "completed"):
                raise ValueError("completed branch has failed common state")
            validate_probabilities(trace.reshape(-1, 4))
            if (not np.array_equal(trace[-1], arrays["terminal_probabilities"][index, retention_indices])
                    or not np.array_equal(trace[0], arrays["initial_probabilities"][record["initial_index"], retention_indices])):
                raise ValueError("retention path endpoints differ from common/terminal predictions")
        elif not np.isnan(trace).all(): raise ValueError("failed condition hides a retention trace")
    return root, data, seal, runs, plan, receipt, sources, arrays, sha(seal_bytes)


def ranking_report(runs, plan):
    rows = []
    for index, initial in enumerate(runs["initial_order"]):
        all_rows = [r for r in runs["records"] if r["initial_index"] == index]
        candidates = [r for r in all_rows if r["status"] == "completed"]
        excluded = [{"run_id": r["run_id"], "status": r["status"]} for r in all_rows if r["status"] != "completed"]
        for objective, observation in itertools.product(("direct_soft_total", "tracking_soft_total"), plan["observations"]):
            row = {"initial_index": index, "seed": initial["seed"], "head": initial["head"],
                   "anchor_offset": initial["anchor_offset"], "common_objective": objective,
                   "prediction_model": observation, "registered_candidates": len(all_rows), "excluded": excluded,
                   "status": "insufficient_executed_candidates"}
            if len(candidates) >= 2:
                ranking = rank_scores([r["run_id"] for r in candidates],
                    [r["predicted_scores"][observation][objective] for r in candidates],
                    [r["actual_scores"][objective] for r in candidates], tie_tolerance=plan["ranking_tie_tolerance"])
                ranking.pop("pairs")
                row.update(status="completed", **ranking)
            rows.append(row)
    return {"schema": "hepta.cell-action-ranking.v3", "records": rows,
            "scope": "fixed checkpoints and executed candidate pools; no independent-anchor bootstrap or policy selection",
            "primary_common_objective": "direct_soft_total", "secondary_common_objective": "tracking_soft_total",
            "pair_details": "reconstructible from all sealed per-candidate predicted and actual common scores"}


def score_payload(context, roles, payload):
    _, _, _, runs, plan, _, sources, arrays, _ = context
    envelope = json.loads(payload)
    if envelope.get("schema") != "hepta.cell-action-news.v3" or envelope.get("classes") != 4:
        raise ValueError("heldout payload schema or class identity differs")
    labels = envelope["roles"]
    if set(labels) != set(roles): raise ValueError("heldout role census differs")
    records, warmups, initials, paths, scores, targets = [], [], [], [], {}, {}
    position = {index: p for p, index in enumerate(runs["retention_indices"])}
    for role in roles:
        row = labels[role]
        indices, y = np.asarray(row["indices"]), np.asarray(row["labels"])
        if (indices.dtype.kind not in "iu" or indices.tolist() != [i for i, s in enumerate(sources) if s["role"] == role]
                or y.dtype.kind not in "iu" or y.shape != indices.shape or set(y.tolist()) != set(range(4))
                or row["source_ids"] != [sources[i]["source_id"] for i in indices]):
            raise ValueError("heldout labels or source binding changed")
        targets[role] = y
        warmup_scores, initial_scores = {}, {}
        for collection, key, destination, name in ((runs["warmup_order"], "warmup_probabilities", warmups, "warmup_index"),
                                                  (runs["initial_order"], "initial_probabilities", initials, "initial_index")):
            for index, info in enumerate(collection):
                base = {name: index, "seed": info["seed"], "head": info["head"], "role": role, "status": info["status"]}
                if "anchor_offset" in info: base["anchor_offset"] = info["anchor_offset"]
                if info["status"] != "completed": destination.append({**base, "metrics": None}); continue
                summary, loss, correct = metrics(arrays[key][index, indices], y)
                destination.append({**base, **summary})
                (warmup_scores if name == "warmup_index" else initial_scores)[index] = (summary, loss)
                if name == "warmup_index":
                    for anchor in plan["anchor_offsets"]:
                        scores[(info["seed"], info["head"], anchor, "warmup", role)] = {"nll": loss, "accuracy": correct}
        for index, info in enumerate(runs["records"]):
            base = {key: info[key] for key in ("run_id", "seed", "head", "anchor_offset", "method_id", "status")}
            if info["status"] != "completed":
                records.append({**base, "role": role, "metrics": None})
                if role.startswith("old_"): paths.append({**base, "role": role, "metrics": None})
                continue
            summary, loss, correct = metrics(arrays["terminal_probabilities"][index, indices], y)
            before, warmup_loss = warmup_scores[info["warmup_index"]]
            anchor_summary, _ = initial_scores[info["initial_index"]]
            records.append({**base, "role": role, **summary,
                "nll_change_from_warmup": summary["nll"] - before["nll"],
                "nll_change_from_anchor": summary["nll"] - anchor_summary["nll"]})
            scores[(info["seed"], info["head"], info["anchor_offset"], info["method_id"], role)] = {"nll": loss, "accuracy": correct}
            if role.startswith("old_"):
                p = arrays["retention_probabilities"][index][:, [position[int(i)] for i in indices]]
                losses = -np.log(np.maximum(p[:, np.arange(len(y)), y], np.finfo(float).tiny))
                paths.append({**base, "role": role, **path_retention(losses, warmup_loss, tolerance=1e-9),
                              "scope": "heldout finite-source arithmetic check, not population retention guarantee"})
    return {"records": records, "warmup": warmups, "initial": initials, "retention_paths": paths}, scores, targets


def compare_scores(scores, targets, plan):
    rng = np.random.default_rng(plan["bootstrap_seed"])
    draws = {role: stratified_draws(targets[role], rng, plan["bootstrap_replicates"]) for role in FINAL_ROLES}
    anchor = plan["primary_family"]["anchor_offset"]
    quantiles = [plan["primary_family"]["alpha"] / 16, 1 - plan["primary_family"]["alpha"] / 16]

    def difference(head, left, right, role, metric):
        keys = [(seed, head, anchor, method, role) for seed in plan["seeds"] for method in (left, right)]
        if any(key not in scores for key in keys): return None
        return np.mean([scores[(seed, head, anchor, left, role)][metric]
                        - scores[(seed, head, anchor, right, role)][metric] for seed in plan["seeds"]], axis=0)

    secondary, primary = [], []
    for head, role, pair, metric in itertools.product(plan["head_modes"], FINAL_ROLES, plan["secondary_pairs"], ("nll", "accuracy")):
        delta = difference(head, *pair, role, metric)
        row = {"head": head, "anchor_offset": anchor, "role": role, "left": pair[0], "right": pair[1],
               "metric": metric, "status": "unavailable_registered_seed"}
        if delta is not None:
            row.update(status="completed", difference_left_minus_right=float(delta.mean()),
                pointwise_percentile_95=np.quantile(delta[draws[role]].mean(axis=1), [0.025, 0.975]).tolist(),
                source_components=len(delta), fixed_model_seeds=plan["seeds"])
        secondary.append(row)
    for head, item in itertools.product(plan["head_modes"], plan["primary_comparisons"]):
        values = [difference(head, item["left"], item["right"], role, "nll") for role in item["roles"]]
        row = {**item, "head": head, "anchor_offset": anchor, "status": "unavailable_registered_seed",
               "criterion_met": False, "threshold": 0.0}
        if all(value is not None for value in values):
            point = float(np.mean([v.mean() for v in values]))
            boot = np.mean([v[draws[role]].mean(axis=1) for v, role in zip(values, item["roles"])], axis=0)
            interval = np.quantile(boot, quantiles).tolist()
            passed = interval[1] < 0 if item["upper_bound_rule"] == "strictly_below_zero" else interval[1] <= 0
            row.update(status="completed", difference_left_minus_right=point,
                bonferroni_percentile_interval=interval, quantiles=quantiles,
                source_components=sum(len(v) for v in values),
                components_by_role={role: len(v) for role, v in zip(item["roles"], values)},
                fixed_model_seeds=plan["seeds"], criterion_met=bool(passed))
        primary.append(row)
    decisions = [{"head": head, "registered_diagnostics": 4,
        "completed_diagnostics": sum(r["status"] == "completed" for r in primary if r["head"] == head),
        "met_diagnostics": sum(r["criterion_met"] for r in primary if r["head"] == head),
        "all_registered_diagnostics_met": all(r["criterion_met"] for r in primary if r["head"] == head)}
        for head in plan["head_modes"]]
    return secondary, primary, decisions


def evaluate(run_directory, data, protocol, output):
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    context = verify_run(run_directory, data, protocol)
    root, data, seal, runs, plan, receipt, _, _, seal_hash = context
    destination = Path(output)
    if destination.resolve().is_relative_to(root.resolve()): raise ValueError("scoring cannot mutate sealed run")
    destination.mkdir(parents=True, exist_ok=False)
    common = {"protocol_sha256": seal["protocol_sha256"], "pre_evaluation_seal_sha256": seal_hash,
              "evaluation_source_sha256": sha(Path(__file__).read_bytes()),
              "authority": "DENY_ALL", "production_authority": False}
    write_json(destination / "ranking.json", {**common, **ranking_report(runs, plan)})
    common["ranking_report_sha256"] = sha((destination / "ranking.json").read_bytes())
    access_base = {"pre_evaluation_seal_sha256": seal_hash, "verified_files": len(seal["files"]),
                   "verified_registered_conditions": len(runs["records"]),
                   "source_sha256": common["evaluation_source_sha256"], "scope": "local sequencing, no host attestation"}
    write_json(destination / "validation_label_access.json", {**access_base, "schema": "hepta.cell-action-validation-access.v3",
        "before_label_open_utc": datetime.now(timezone.utc).isoformat()})
    validation_payload = (data / "validation_labels.json").read_bytes()
    if (sha(validation_payload) != receipt["files"]["validation_labels.json"]["sha256"]
            or len(validation_payload) != receipt["files"]["validation_labels.json"]["bytes"]):
        raise ValueError("validation payload changed")
    validation, _, _ = score_payload(context, VALIDATION_ROLES, validation_payload)
    write_json(destination / "validation.json", {**common, "schema": "hepta.cell-action-validation.v3",
        "validation_labels_sha256": sha(validation_payload), "used_for_policy_selection": False, **validation})
    validation_seal = {"schema": "hepta.cell-action-validation-seal.v3", "pre_evaluation_seal_sha256": seal_hash,
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(), "final_labels_opened": False,
        "files": {name: {"bytes": (destination / name).stat().st_size, "sha256": sha((destination / name).read_bytes())}
                  for name in ("validation.json", "validation_label_access.json")}}
    write_json(destination / "validation_seal.json", validation_seal)
    for name, item in validation_seal["files"].items():
        if sha((destination / name).read_bytes()) != item["sha256"]: raise ValueError("validation seal changed")
    write_json(destination / "final_label_access.json", {**access_base, "schema": "hepta.cell-action-final-access.v3",
        "validation_seal_sha256": sha((destination / "validation_seal.json").read_bytes()),
        "before_label_open_utc": datetime.now(timezone.utc).isoformat()})
    # Every prediction and the independent validation report have now been sealed.
    final_payload = (data / "final_labels.json").read_bytes()
    if (sha(final_payload) != receipt["files"]["final_labels.json"]["sha256"]
            or len(final_payload) != receipt["files"]["final_labels.json"]["bytes"]): raise ValueError("final payload changed")
    final, scores, targets = score_payload(context, FINAL_ROLES, final_payload)
    secondary, primary, decisions = compare_scores(scores, targets, plan)
    result = {**common, "schema": "hepta.cell-action-evaluation.v3", **final,
        "final_labels_sha256": sha(final_payload), "validation_seal_sha256": sha((destination / "validation_seal.json").read_bytes()),
        "contrasts": secondary, "primary_contrasts": primary, "decisions": decisions,
        "all_registered_diagnostics_met": all(r["all_registered_diagnostics_met"] for r in decisions),
        "diagnostic_scope": "Four different hypotheses per Head; not a joint utility guarantee for one policy.",
        "bootstrap": {"replicates": plan["bootstrap_replicates"], "seed": plan["bootstrap_seed"],
            "family_alpha": 0.05, "primary_comparisons": 8, "primary_quantiles": [0.003125, 0.996875],
            "primary_interval_method": "Bonferroni-adjusted approximate percentile bootstrap",
            "secondary_interval_method": "pointwise percentile 95%", "future_pooling": "equal three-month means",
            "scope": "fixed fitted seeds and selected source cohorts; no seed-population, prospective or finite-sample distribution-free guarantee"},
        "resources": {"wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu_started}}
    write_json(destination / "evaluation.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run-directory", "data", "protocol", "output"): parser.add_argument("--" + name, required=True)
    result = evaluate(**vars(parser.parse_args()))
    print(json.dumps({"scored_rows": len(result["records"]), "secondary": len(result["contrasts"]),
                      "primary": len(result["primary_contrasts"]), "decisions": result["decisions"]}))
