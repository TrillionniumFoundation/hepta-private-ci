"""Independent V3 heldout scoring; no evaluator or metric-helper import."""

from collections import Counter
import itertools
import json
from pathlib import Path

import numpy as np

from cell_field_audit import _load_arrays, sha, verify_seal
from cell_field_action_math_audit import audit_ranking


def audit_evaluation(run_dir, data_dir, protocol_path, evaluation_dir):
    root, data, output = Path(run_dir), Path(data_dir), Path(evaluation_dir)
    seal = verify_seal(root)
    protocol_bytes = Path(protocol_path).read_bytes()
    protocol = json.loads(protocol_bytes)
    runs = json.loads((root / "runs.json").read_bytes())
    receipt_bytes = (data / "data_receipt.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    source_bytes = (data / "sources.json").read_bytes()
    sources = json.loads(source_bytes)["rows"]
    if (sha(protocol_bytes) != seal["protocol_sha256"] or seal["validation_labels_opened"] is not False
            or runs["protocol_sha256"] != seal["protocol_sha256"]
            or sha(receipt_bytes) != runs["data_receipt_sha256"]
            or sha(source_bytes) != receipt["files"]["sources.json"]["sha256"]
            or [s["source_id"] for s in sources] != runs["source_ids"]
            or len({s["component_id"] for s in sources}) != len(sources)
            or dict(Counter(s["role"] for s in sources)) != protocol["source_counts"]):
        raise ValueError("protocol, source identity or evaluation boundary differs")
    if (runs["sourcecode_hashes"] != seal["sourcecode_hashes"]
            or any(Path(name).name != name or sha(Path(__file__).with_name(name).read_bytes()) != expected
                   for name, expected in seal["sourcecode_hashes"].items())):
        raise ValueError("independent score source changed after execution")
    if (protocol["bootstrap_seed"] != 830241 or protocol["bootstrap_replicates"] != 10000
            or protocol["primary_family"] != {"alpha": 0.05, "comparisons": 8, "anchor_offset": 16, "retention_margin": 0.0}):
        raise ValueError("registered uncertainty design changed")
    predictions = _load_arrays(root / "predictions.npz")
    positions = {index: j for j, index in enumerate(runs["retention_indices"])}
    counter, max_error, minimum_gold = 0, 0.0, 1.0

    def close(actual, expected):
        nonlocal counter, max_error
        a, b = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
        if a.shape != b.shape or not np.isfinite(a).all() or not np.isfinite(b).all():
            raise ValueError("invalid heldout numeric comparison")
        error = float(np.max(np.abs(a - b))) if a.size else 0.0
        counter += a.size
        max_error = max(error, max_error)
        if error > 3e-12 * (1 + (float(np.max(np.abs(b))) if b.size else 0.0)):
            raise ValueError("independent heldout score or interval differs")

    def summarize(p, y):
        nonlocal minimum_gold
        if (p.shape != (len(y), 4) or not np.isfinite(p).all() or np.any(p < 0)
                or not np.allclose(p.sum(axis=1), 1, rtol=0, atol=1e-12)):
            raise ValueError("invalid probabilities")
        gold = p[np.arange(len(y)), y]
        minimum_gold = min(minimum_gold, float(gold.min()))
        losses = -np.log(np.maximum(gold, np.finfo(float).tiny))
        correct = (p.argmax(axis=1) == y).astype(float)
        return {"rows": len(y), "nll": float(losses.mean()), "accuracy": float(correct.mean()),
                "balanced_accuracy": float(np.mean([correct[y == c].mean() for c in range(4)])),
                "brier": float(np.square(p - np.eye(4)[y]).sum(axis=1).mean())}, losses, correct

    ranking_bytes = (output / "ranking.json").read_bytes()
    ranking = json.loads(ranking_bytes)
    if (ranking["protocol_sha256"] != seal["protocol_sha256"]
            or ranking["pre_evaluation_seal_sha256"] != sha((root / "pre_evaluation_seal.json").read_bytes())
            or ranking["evaluation_source_sha256"] != seal["sourcecode_hashes"].get("cell_field_action_evaluate.py")):
        raise ValueError("ranking source or run binding differs")
    ranking_check = audit_ranking(runs, protocol, ranking, lambda name, actual, wanted: close(actual, wanted))
    labels_by_role, scores = {}, {}
    stage_counts = {}
    validation_seal_bytes = (output / "validation_seal.json").read_bytes()
    validation_seal = json.loads(validation_seal_bytes)
    if (validation_seal["final_labels_opened"] is not False
            or validation_seal["pre_evaluation_seal_sha256"] != sha((root / "pre_evaluation_seal.json").read_bytes())
            or set(validation_seal["files"]) != {"validation.json", "validation_label_access.json"}):
        raise ValueError("validation was not separately sealed before final")
    for name, item in validation_seal["files"].items():
        content = (output / name).read_bytes()
        if len(content) != item["bytes"] or sha(content) != item["sha256"]:
            raise ValueError("validation report changed after its seal")
    final_access = json.loads((output / "final_label_access.json").read_bytes())
    if final_access["validation_seal_sha256"] != sha(validation_seal_bytes):
        raise ValueError("final label access not bound to validation seal")
    for name in ("validation_label_access.json", "final_label_access.json"):
        access = json.loads((output / name).read_bytes())
        if (access["source_sha256"] != seal["sourcecode_hashes"].get("cell_field_action_evaluate.py")
                or access["pre_evaluation_seal_sha256"] != sha((root / "pre_evaluation_seal.json").read_bytes())
                or access["verified_files"] != len(seal["files"]) or access["verified_registered_conditions"] != 342):
            raise ValueError("heldout access receipt source or run binding differs")
    evaluation = None
    for stage, roles, payload_name, report_name in [
            ("validation", ("old_validation", "current_validation"), "validation_labels.json", "validation.json"),
            ("final", ("old_test", "future_june", "future_july", "future_august"), "final_labels.json", "evaluation.json")]:
        payload = (data / payload_name).read_bytes()
        envelope = json.loads(payload)
        if envelope.get("schema") != "hepta.cell-action-news.v3" or envelope.get("classes") != 4:
            raise ValueError("heldout envelope schema or class identity differs")
        labels = envelope["roles"]
        report = json.loads((output / report_name).read_bytes())
        if (set(labels) != set(roles) or sha(payload) != receipt["files"][payload_name]["sha256"]
                or len(payload) != receipt["files"][payload_name]["bytes"]
                or sha(payload) != report[stage + "_labels_sha256"]
                or report["protocol_sha256"] != seal["protocol_sha256"]
                or report["pre_evaluation_seal_sha256"] != sha((root / "pre_evaluation_seal.json").read_bytes())):
            raise ValueError("heldout report or payload identity differs")
        if (report["evaluation_source_sha256"] != seal["sourcecode_hashes"].get("cell_field_action_evaluate.py")
                or report["ranking_report_sha256"] != sha(ranking_bytes)):
            raise ValueError("report evaluator source differs from frozen source")
        if stage == "final" and report["validation_seal_sha256"] != sha(validation_seal_bytes):
            raise ValueError("evaluation lost its validation seal binding")
        if stage == "validation" and report["used_for_policy_selection"] is not False:
            raise ValueError("independent validation was used for selection")
        saved = {(row["run_id"], row["role"]): row for row in report["records"]}
        warmup_saved = {(row["warmup_index"], row["role"]): row for row in report["warmup"]}
        initial_saved = {(row["initial_index"], row["role"]): row for row in report["initial"]}
        paths = {(row["run_id"], row["role"]): row for row in report["retention_paths"]}
        for index, rows, expected in [(saved, report["records"], len(runs["records"]) * len(roles)),
                (warmup_saved, report["warmup"], 6 * len(roles)), (initial_saved, report["initial"], 18 * len(roles)),
                (paths, report["retention_paths"], len(runs["records"]))]:
            if len(index) != len(rows) or len(index) != expected:
                raise ValueError("heldout metric or retention-path census incomplete")
        for role in roles:
            row = labels[role]
            indices, y = np.asarray(row["indices"]), np.asarray(row["labels"])
            if (indices.dtype.kind not in "iu" or indices.tolist() != [i for i, s in enumerate(sources) if s["role"] == role]
                    or y.dtype.kind not in "iu" or y.shape != indices.shape or set(y.tolist()) != set(range(4))
                    or row["source_ids"] != [sources[i]["source_id"] for i in indices]):
                raise ValueError("heldout role identity differs")
            labels_by_role[role] = y
            warmup_metrics, initial_metrics = {}, {}
            for collection, key, saved_base, flag in [(runs["warmup_order"], "warmup_probabilities", warmup_saved, "warmup"),
                                                     (runs["initial_order"], "initial_probabilities", initial_saved, "initial")]:
                for number, info in enumerate(collection):
                    row = saved_base[(number, role)]
                    if any(row[name] != info[name] for name in ("seed", "head", "status")):
                        raise ValueError("heldout common-state identity differs")
                    if info["status"] != "completed":
                        if row.get("metrics", "missing") is not None: raise ValueError("failed state silently scored")
                        continue
                    summary, losses, correct = summarize(predictions[key][number, indices], y)
                    for name, value in summary.items(): close(row[name], value)
                    (warmup_metrics if flag == "warmup" else initial_metrics)[number] = (summary, losses)
                    if flag == "warmup":
                        scores[(info["seed"], info["head"], "warmup", role)] = {"nll": losses, "accuracy": correct}
            for number, info in enumerate(runs["records"]):
                row = saved[(info["run_id"], role)]
                if any(row[name] != info[name] for name in ("seed", "head", "anchor_offset", "method_id", "status")):
                    raise ValueError("heldout branch identity differs")
                if role.startswith("old_") and any(paths[(info["run_id"], role)][name] != info[name]
                        for name in ("seed", "head", "anchor_offset", "method_id", "status")):
                    raise ValueError("heldout retention identity differs")
                if info["status"] != "completed":
                    if row.get("metrics", "missing") is not None: raise ValueError("unexecuted branch silently scored")
                    if role.startswith("old_") and paths[(info["run_id"], role)].get("metrics", "missing") is not None:
                        raise ValueError("unexecuted branch has a claimed retention path")
                    continue
                summary, losses, correct = summarize(predictions["terminal_probabilities"][number, indices], y)
                for name, value in summary.items(): close(row[name], value)
                warmup_summary, warmup_losses = warmup_metrics[info["warmup_index"]]
                close(row["nll_change_from_warmup"], summary["nll"] - warmup_summary["nll"])
                close(row["nll_change_from_anchor"], summary["nll"] - initial_metrics[info["initial_index"]][0]["nll"])
                if info["anchor_offset"] == 16:
                    scores[(info["seed"], info["head"], info["method_id"], role)] = {"nll": losses, "accuracy": correct}
                if role.startswith("old_"):
                    path = paths[(info["run_id"], role)]
                    p = predictions["retention_probabilities"][number][:, [positions[int(i)] for i in indices]]
                    path_losses = np.array([summarize(p[k], y)[1] for k in range(len(p))])
                    excess = np.mean(path_losses - warmup_losses, axis=1)
                    expected = {"initial_mean_nll_excess": excess[0], "terminal_mean_nll_excess": excess[-1],
                        "maximum_whole_path_mean_nll_excess": excess.max(), "maximum_future_mean_nll_excess": excess[1:].max(),
                        "mean_nll_excess_by_step": excess, "rows": len(y), "tolerance": 1e-9}
                    for name, value in expected.items(): close(path[name], value)
                    expected_flags = {"initial_probe_style_feasible": bool(excess[0] <= 1e-9),
                        "whole_path_probe_style_feasible": bool(np.all(excess <= 1e-9)),
                        "future_probe_style_feasible": bool(np.all(excess[1:] <= 1e-9)),
                        "future_violation_steps": [int(i + 1) for i in np.where(excess[1:] > 1e-9)[0]]}
                    if any(path[name] != value for name, value in expected_flags.items()):
                        raise ValueError("independent retention feasibility differs")
        stage_counts[stage] = {"condition_roles": len(saved), "warmup_roles": len(warmup_saved),
                               "initial_roles": len(initial_saved), "retention_paths": len(paths)}
        if stage == "final": evaluation = report
    rng = np.random.default_rng(830241)
    final_roles = ("old_test", "future_june", "future_july", "future_august")
    draws = {role: np.concatenate([rng.choice(np.flatnonzero(labels_by_role[role] == c),
                size=(10000, int(np.sum(labels_by_role[role] == c))), replace=True) for c in range(4)], axis=1)
             for role in final_roles}

    def delta(head, left, right, role, metric):
        if any((seed, head, method, role) not in scores for seed in [7, 17, 29] for method in (left, right)): return None
        return np.mean([scores[(seed, head, left, role)][metric] - scores[(seed, head, right, role)][metric]
                        for seed in [7, 17, 29]], axis=0)

    secondary_index = {(r["head"], r["role"], r["left"], r["right"], r["metric"]): r for r in evaluation["contrasts"]}
    primary_index = {(r["head"], r["id"]): r for r in evaluation["primary_contrasts"]}
    if (len(secondary_index) != 96 or len(evaluation["contrasts"]) != 96
            or len(primary_index) != 8 or len(evaluation["primary_contrasts"]) != 8):
        raise ValueError("fixed contrast census incomplete or duplicated")
    for head, role, pair, metric in itertools.product(["linear", "gated"], final_roles, protocol["secondary_pairs"], ("nll", "accuracy")):
        row = secondary_index[(head, role, *pair, metric)]
        if row["anchor_offset"] != 16: raise ValueError("secondary anchor changed")
        value = delta(head, *pair, role, metric)
        if value is None:
            if row["status"] != "unavailable_registered_seed" or "difference_left_minus_right" in row:
                raise ValueError("missing registered seed was silently dropped")
        else:
            if row["status"] != "completed" or row["fixed_model_seeds"] != [7, 17, 29]:
                raise ValueError("paired inference status or fixed seeds changed")
            close(row["difference_left_minus_right"], value.mean())
            close(row["source_components"], len(value))
            close(row["pointwise_percentile_95"], np.quantile(value[draws[role]].mean(axis=1), [0.025, 0.975]))
    decisions = []
    for head in ("linear", "gated"):
        met = complete = 0
        for item in protocol["primary_comparisons"]:
            row = primary_index[(head, item["id"])]
            if (any(row[key] != value for key, value in item.items()) or row["anchor_offset"] != 16
                    or row["threshold"] != 0.0): raise ValueError("primary comparison identity changed")
            values = [delta(head, item["left"], item["right"], role, "nll") for role in item["roles"]]
            if any(v is None for v in values):
                if row["status"] != "unavailable_registered_seed" or row["criterion_met"] is not False:
                    raise ValueError("incomplete diagnostic silently passed")
                continue
            point = float(np.mean([v.mean() for v in values]))
            boot = np.mean([v[draws[role]].mean(axis=1) for v, role in zip(values, item["roles"])], axis=0)
            bounds = np.quantile(boot, [0.003125, 0.996875])
            passed = bool(bounds[1] < 0 if item["upper_bound_rule"] == "strictly_below_zero" else bounds[1] <= 0)
            if row["status"] != "completed" or row["criterion_met"] != passed: raise ValueError("primary decision differs")
            close(row["difference_left_minus_right"], point)
            close(row["bonferroni_percentile_interval"], bounds)
            close(row["source_components"], sum(len(v) for v in values))
            if (row["fixed_model_seeds"] != [7, 17, 29] or row["quantiles"] != [0.003125, 0.996875]
                    or row["components_by_role"] != {role: len(v) for role, v in zip(item["roles"], values)}):
                raise ValueError("primary source or fixed-seed scope changed")
            complete += 1
            met += passed
        decisions.append({"head": head, "registered_diagnostics": 4, "completed_diagnostics": complete,
                          "met_diagnostics": met, "all_registered_diagnostics_met": met == 4})
    if (evaluation["decisions"] != decisions
            or evaluation["all_registered_diagnostics_met"] != all(r["all_registered_diagnostics_met"] for r in decisions)):
        raise ValueError("aggregate diagnostic decisions differ")
    return {"schema": "hepta.cell-action-independent-score-audit.v3", "stages": stage_counts,
            "ranking": ranking_check,
            "primary_comparisons_checked": 8, "secondary_comparisons_checked": 96,
            "primary_intervals_recomputed": sum(r["status"] == "completed" for r in evaluation["primary_contrasts"]),
            "secondary_intervals_recomputed": sum(r["status"] == "completed" for r in evaluation["contrasts"]),
            "scalar_equalities_checked": int(counter), "maximum_absolute_error": max_error,
            "minimum_gold_probability": minimum_gold, "decisions": decisions,
            "evaluation_sha256": sha((output / "evaluation.json").read_bytes()),
            "validation_sha256": sha((output / "validation.json").read_bytes()),
            "validation_seal_sha256": sha(validation_seal_bytes), "auditor_sha256": sha(Path(__file__).read_bytes()),
            "evaluator_imported": False, "metric_helper_imported": False,
            "scope": "source-conditional approximate intervals; distinct diagnostics, no unified policy utility guarantee"}
