"""Describe the complete sealed P0 census without opening withheld labels.

Ranks and repeated anchors are descriptive diagnostics, never independent task
replicates or a post-outcome controller selection rule. Action penalty is not CPU.
"""

import argparse
from collections import Counter, defaultdict
import itertools
import json
from pathlib import Path

import numpy as np

from cell_field_action_control import score_common
from cell_field_action_io import write_json
from cell_field_action_metrics import rank_scores
from cell_field_features import file_hash
from cell_field_fixed_actions import fixed_library
from cell_field_tradeoffs_v4 import summarize_fixed_actions


TIE_TOLERANCE = 1e-10  # Inherited V3 descriptive ranking convention.
SCORES = ("direct_soft_total", "direct_current", "forgetting", "effort",
          "maximum_future_old_excess", "terminal_old_excess", "terminal_current_nll",
          "terminal_old_nll", "future_retention_within_tolerance")


def _json(path):
    return json.loads(Path(path).read_bytes())


def _arrays(path):
    with np.load(path, allow_pickle=False) as archive:
        return {name: archive[name] for name in archive.files}


def verify_seal(root, protocol=None):
    root = Path(root)
    seal_path = root / "pre_evaluation_seal.json"
    paths = list(root.rglob("*"))
    if root.is_symlink() or any(path.is_symlink() for path in paths):
        raise ValueError("regular sealed inventory required")
    seal = _json(seal_path)
    actual = {path.relative_to(root).as_posix() for path in paths
              if path.is_file() and path != seal_path}
    if (not seal.get("files") or actual != set(seal["files"])
            or any(seal.get(key) is not False for key in ("final_labels_opened", "validation_labels_opened"))):
        raise ValueError("changed inventory or withheld-label disposition")
    for name, entry in seal["files"].items():
        path = root / name
        if (Path(name).is_absolute() or ".." in Path(name).parts
                or Path(name).name in {"final_labels.json", "validation_labels.json"}
                or not path.resolve().is_relative_to(root.resolve())
                or path.stat().st_size != entry["bytes"] or file_hash(path) != entry["sha256"]):
            raise ValueError("changed or disallowed sealed artifact: " + name)
    plan = _json(root / "protocol.json")
    if protocol is not None and (file_hash(protocol) != seal.get("protocol_sha256") or _json(protocol) != plan):
        raise ValueError("original protocol differs from the sealed protocol")
    return seal, plan


def _compact(score):
    return None if score is None else {key: score[key] for key in SCORES}


def _same_score(recorded, calculated):
    if any(not np.isclose(recorded[key], calculated[key], rtol=1e-12, atol=1e-15) for key in SCORES):
        raise ValueError("recorded score differs from frozen trajectories")


def _score(fields, actions, baseline, anchor, plan):
    return score_common(fields, actions, baseline, anchor, dt=plan["h"],
        effort_price=plan["effort_price"], current_shift=plan["current_shift"],
        direct_coefficient=plan["direct_coefficient"], feasibility_tolerance=plan["feasibility_tolerance"])


def _timings(rows, keys):
    return {key: {"observed_ns": sum(row[key] for row in rows if row.get(key) is not None),
                  "measured": sum(row.get(key) is not None for row in rows), "registered": len(rows)}
            for key in keys}


def prediction_metrics(ids, predicted, real, scores, forecasts, full, complete):
    """All supplied action slots are retained; any unavailable slot closes metrics."""
    row = {"registered": len(ids), "completed": int(np.sum(complete)), "status": "unavailable"}
    if not all(complete):
        return row
    error = predicted[:, 1:] - real[:, 1:]
    full_error = full[:, 1:] - real[:, 1:]
    rmse, full_rmse = float(np.sqrt(np.mean(error**2))), float(np.sqrt(np.mean(full_error**2)))
    row.update(status="completed", loss_rmse=rmse, current_loss_rmse=float(np.sqrt(np.mean(error[:, :, 0]**2))),
        old_loss_rmse=float(np.sqrt(np.mean(error[:, :, 1]**2))),
        terminal_loss_rmse=float(np.sqrt(np.mean(error[:, -1]**2))), full_loss_rmse=full_rmse,
        rmse_over_full=rmse/full_rmse if full_rmse > 0 else None,
        reduced_vs_full_prediction_rmse=float(np.sqrt(np.mean((predicted[:, 1:]-full[:, 1:])**2))),
        actual_delta_rms=float(np.sqrt(np.mean(real[:, 1:]**2))))
    for key, label in (("direct_soft_total", "direct_soft"), ("direct_current", "current_risk")):
        actual, forecast = [s[key] for s in scores], [s[key] for s in forecasts]
        row[label + "_mae"] = float(np.mean(np.abs(np.asarray(actual)-forecast)))
        row[label + "_rank"] = ({k: v for k, v in rank_scores(ids, forecast, actual,
            tie_tolerance=TIE_TOLERANCE).items() if k not in ("pairs", "candidate_ids", "scope")}
            if len(ids) > 1 else None)
    return row


def _fixed(directory, declaration, plan, parameters):
    library = fixed_library(parameters)
    ids, actions = [name for name, _ in library], np.asarray([u for _, u in library])
    required = ("frozen_plan.json", "branches.json", "frozen_predictions.npz", "actual_trajectories.npz", "reference.npz")
    if declaration.get("status") == "unavailable" and not all((directory / name).is_file() for name in required):
        return {"status": "unavailable", "registered": 49, "completed": 0, "error": declaration.get("error"),
                "actions": [{"action_id": name, "status": "unavailable"} for name in ids],
                "metrics": [{"model": model, "amplitude": amplitude, "status": "unavailable", "completed": 0,
                             "registered": 49 if amplitude == "all" else 16}
                            for model in plan["models"] for amplitude in ("all", *plan["fixed_library"]["amplitudes"])]}
    frozen, rows = _json(directory / "frozen_plan.json"), _json(directory / "branches.json")
    predicted, actual = _arrays(directory / "frozen_predictions.npz"), _arrays(directory / "actual_trajectories.npz")
    baseline = _arrays(directory / "reference.npz")["reference_observations"][:, :2]
    if (frozen["models"] != plan["models"] or frozen["actions"] != ids
            or [row["action_id"] for row in rows] != ids or not np.array_equal(predicted["actions"], actions)
            or predicted["predictions"].shape != (5, 49, 9, 2) or actual["real_delta"].shape != (49, 9, 2)
            or not np.isfinite(predicted["predictions"]).all()
            or file_hash(directory / "frozen_predictions.npz") != frozen["frozen_predictions_sha256"]):
        raise ValueError("incomplete or changed fixed-action census")
    tradeoffs = summarize_fixed_actions(rows, parameters=parameters, dt=plan["h"], effort_price=plan["effort_price"])
    complete = np.array([row["status"] == "completed" for row in rows])
    forecasts, compact = [], []
    for i, row in enumerate(rows):
        sequence = np.zeros((8, parameters))
        sequence[0] = actions[i]
        scores = [_score(path[i], sequence, baseline, frozen["old_anchor"], plan) for path in predicted["predictions"]]
        forecasts.append(scores)
        if complete[i]:
            _same_score(row["scores"], _score(actual["real_delta"][i], sequence, baseline, frozen["old_anchor"], plan))
            if not np.allclose(actual["observations"][i], baseline+actual["real_delta"][i], rtol=0, atol=1e-14):
                raise ValueError("actual loss deviations disagree")
            for model, score in zip(plan["models"], scores):
                _same_score(row["predicted_scores"][model], score)
        compact.append({"action_id": ids[i], "status": row["status"], "error": row.get("error"),
            "physical_impulse_norm": float(np.linalg.norm(plan["h"]*actions[i])),
            "actual": _compact(row["scores"]), "predicted": dict(zip(plan["models"], map(_compact, scores))),
            "cpu_ns": row["cpu_ns"], "wall_ns": row["wall_ns"]})
    metrics, linearity = [], []
    full = predicted["predictions"][plan["models"].index("full")]
    norms = np.linalg.norm(actions, axis=1)
    for amplitude in ("all", *plan["fixed_library"]["amplitudes"]):
        selected = np.arange(49) if amplitude == "all" else np.flatnonzero(np.isclose(norms, amplitude))
        for m, model in enumerate(plan["models"]):
            item = prediction_metrics([ids[i] for i in selected], predicted["predictions"][m, selected],
                actual["real_delta"][selected], [rows[i]["scores"] for i in selected],
                [forecasts[i][m] for i in selected], full[selected], complete[selected])
            metrics.append({"model": model, "amplitude": amplitude, **item})
            if model == "full" and amplitude != "all":
                impulse = plan["h"]*amplitude
                linearity.append({"amplitude": amplitude, "physical_impulse_norm": impulse, **item,
                    "error_per_squared_impulse": item.get("loss_rmse", 0)/impulse**2 if item["status"] == "completed" else None})
    return {"status": "completed" if complete.all() else "incomplete", "stage_status": declaration["status"],
        "stage_error": declaration.get("error"), "registered": 49,
        "completed": int(complete.sum()), "initial_state_sha256": frozen["initial_state_sha256"],
        "old_anchor": frozen["old_anchor"], "actions": compact, "metrics": metrics, "linearity": linearity,
        "preparation": frozen["preparation"], "branch_resources": _timings(rows, ("cpu_ns", "wall_ns")),
        "cost_identity_maximum_residual": tradeoffs["maximum_identity_residual"],
        "same_norm_current_risk_ranges": [{k: g[k] for k in ("amplitude", "control_norm", "complete", "actual_current_risk_range")}
                                           for g in tradeoffs["same_norm_directions"]]}


def pressure_pairs(rows, actions, dt):
    by_id, pairs = {row["candidate_id"]: row for row in rows}, []
    for soft in rows:
        if soft["objective"] != "direct_soft":
            continue
        hard = by_id[soft["candidate_id"].replace("direct_soft", "direct_hard")]
        pair = {"model": soft["model"], "budget_multiplier": soft["budget_multiplier"],
                "soft_status": soft["execution_status"], "hard_status": hard["execution_status"],
                "soft_plan_status": soft["status"], "hard_plan_status": hard["status"]}
        a, b = actions.get(soft["candidate_id"]), actions.get(hard["candidate_id"])
        if a is not None and b is not None:
            pair.update(identical_action=bool(np.array_equal(a, b)),
                        physical_action_difference=float(dt*np.linalg.norm(a-b)),
                        soft_physical_norm=float(dt*np.linalg.norm(a)), hard_physical_norm=float(dt*np.linalg.norm(b)))
        if soft["execution_status"] == hard["execution_status"] == "completed":
            pair.update(actual_hard_minus_soft={key: hard["actual_scores"][key]-soft["actual_scores"][key]
                                               for key in SCORES[:6]},
                        soft_actual_feasible=soft["actual_scores"]["future_retention_within_tolerance"],
                        hard_actual_feasible=hard["actual_scores"]["future_retention_within_tolerance"])
        pairs.append(pair)
    return pairs


def _checkpoint(directory, plan, unavailable=None):
    ids = ["zero"] + [f"{m}:b{b:g}:{o}" for m in plan["models"] for b in plan["pressure"]["budgets"]
                      for o in plan["pressure"]["objectives"]]
    if unavailable is not None and not (directory / "results.json").is_file():
        declared = _json(directory / "frozen_plans.json")["plans"] if (directory / "frozen_plans.json").is_file() else None
        if declared is not None and [row["candidate_id"] for row in declared] != ids:
            raise ValueError("partial pressure stage omitted a declared planning slot")
        return {"status": "unavailable", "registered": 31, "completed": 0, "error": unavailable,
                "slots": [{**row, "execution_status": "unavailable"}
                          for row in (declared or [{"candidate_id": name} for name in ids])], "pairs": []}
    frozen, rows = _json(directory / "frozen_plans.json"), _json(directory / "results.json")
    if [r["candidate_id"] for r in rows] != ids or [r["candidate_id"] for r in frozen["plans"]] != ids:
        raise ValueError("missing pressure slot or changed candidate order")
    baseline = _arrays(directory / "reference.npz")["reference_observations"][:, :2]
    actions, compact = {}, []
    for i, (row, original) in enumerate(zip(rows, frozen["plans"])):
        if any(row.get(k) != v for k, v in original.items()) or file_hash(directory / f"plans/{i}.npz") != frozen["arrays_sha256"][str(i)]:
            raise ValueError("pressure plan changed after freeze")
        arrays = _arrays(directory / f"plans/{i}.npz")
        if row["status"] == "planned":
            actions[row["candidate_id"]] = arrays["actions"]
        if row["execution_status"] == "completed":
            actual = _arrays(directory / f"actual/{i}.npz")
            if not np.array_equal(actual["actions"], arrays["actions"]):
                raise ValueError("pressure executed another action")
            _same_score(row["actual_scores"], _score(actual["fields"], actual["actions"], baseline, row["old_anchor"], plan))
        compact.append({k: row.get(k) for k in ("candidate_id", "model", "budget_multiplier", "objective", "status",
            "solver_status", "execution_status", "error", "inherited_old_excess", "physical_impulse_norm",
            "predicted_feasible_actual_violation", "planning_cpu_ns", "planning_wall_ns", "execution_cpu_ns",
            "execution_wall_ns", "audit_prediction_cpu_ns", "audit_prediction_wall_ns")})
        compact[-1].update(actual=_compact(row.get("actual_scores")),
            predicted={name: _compact(score) for name, score in row.get("predicted_scores", {}).items()})
    return {"status": "recorded", "registered": 31,
        "completed": sum(row["execution_status"] == "completed" for row in rows), "slots": compact,
        "pairs": pressure_pairs(rows, actions, plan["h"]), "preparation": frozen["preparation"],
        "resources": _timings(rows, ("planning_cpu_ns", "planning_wall_ns", "execution_cpu_ns",
                                    "execution_wall_ns", "audit_prediction_cpu_ns", "audit_prediction_wall_ns"))}


def _pressure(directory, declaration, plan):
    unavailable = declaration.get("error") if declaration.get("status") == "unavailable" else None
    if unavailable is not None and not (directory / "search.json").is_file():
        return {"status": "unavailable", "error": unavailable, "checkpoints": []}
    search = _json(directory / "search.json")
    losses = _arrays(directory / "search.npz")["old_losses"]
    if losses.shape != (search["completed_steps"]+1,) or losses[0] != search["old_anchor"] or not np.isfinite(losses).all():
        raise ValueError("pressure search trace disagrees")
    if (search["maximum_steps"] != plan["pressure"]["max_search_steps"] or search["completed_steps"] > search["maximum_steps"]
            or (search["status"] == "no_pressure_crossing" and search["completed_steps"] != search["maximum_steps"])):
        raise ValueError("pressure search stopped outside its bounded protocol")
    crossings = np.flatnonzero(losses > search["old_anchor"])
    checkpoints = []
    if search["status"] == "pressure_crossing":
        tau = search["tau"]
        expected = {"prevention": max(0, tau-8), "recovery": tau}
        if not len(crossings) or int(crossings[0]) != tau or search["completed_steps"] != tau or search["checkpoint_offsets"] != expected:
            raise ValueError("pressure search did not retain its first original-threshold crossing")
        for name, offset in expected.items():
            checkpoints.append({"checkpoint": name, "offset": offset,
                **_checkpoint(directory / name, plan, unavailable)})
    elif search["status"] not in ("no_pressure_crossing", "search_failed") or len(crossings) or search["checkpoint_offsets"]:
        raise ValueError("unregistered or inconsistent pressure search disposition")
    return {**search, "checkpoints": checkpoints, "census_error": unavailable}


def _aggregate(anchors):
    groups = defaultdict(list)
    for anchor in anchors:
        for metric in anchor.get("metrics", []):
            for group in ("all", anchor["task"] + "/" + anchor["head"]):
                groups[group, metric["model"], str(metric["amplitude"])].append(metric)
    rows = []
    for (group, model, amplitude), metrics in sorted(groups.items()):
        expected = 36 if group == "all" else 9
        ready = len(metrics) == expected and all(m["status"] == "completed" for m in metrics)
        row = {"group": group, "model": model, "amplitude": amplitude, "registered_anchors": expected,
               "available_anchors": sum(m["status"] == "completed" for m in metrics), "status": "completed" if ready else "unavailable"}
        if ready:
            rms = float(np.sqrt(np.mean([m["loss_rmse"]**2 for m in metrics])))
            full = float(np.sqrt(np.mean([m["full_loss_rmse"]**2 for m in metrics])))
            rank = [m["direct_soft_rank"] for m in metrics]
            taus = [r["kendall_tau_b"] for r in rank if r["kendall_tau_b"] is not None]
            row.update(pooled_loss_rmse=rms, pooled_full_loss_rmse=full, pooled_rmse_over_full=rms/full if full else None,
                mean_direct_soft_mae=float(np.mean([m["direct_soft_mae"] for m in metrics])),
                mean_kendall_tau_b=float(np.mean(taus)) if taus else None, defined_tau_anchors=len(taus),
                mean_decision_regret=float(np.mean([r["predicted_top_actual_regret"] for r in rank])),
                summed_pair_counts=dict(sum((Counter(r["pair_counts"]) for r in rank), Counter())))
        rows.append(row)
    return rows


def summarize(root, output, protocol=None):
    root, output = Path(root), Path(output)
    if output.resolve().is_relative_to(root.resolve()) or output.exists():
        raise ValueError("write a new summary outside the sealed run")
    seal, plan = verify_seal(root, protocol)
    run = _json(root / "run.json")
    expected = set(itertools.product(plan["tasks"], plan["seeds"], plan["head_modes"]))
    fits = {(f["task"], f["seed"], f["head"]): f for f in run["fits"]}
    if set(fits) != expected or len(run["fits"]) != 12 or len(expected) != 12:
        raise ValueError("missing or duplicate registered fit")
    anchors, searches = [], []
    for (task, seed, head), fit in fits.items():
        directory = root / task / f"seed{seed}-{head}"
        declarations = {a["offset"]: a for a in fit["fixed"]}
        if len(declarations) != len(fit["fixed"]) or set(declarations)-set(plan["anchor_offsets"]):
            raise ValueError("changed fixed-anchor census")
        for offset in plan["anchor_offsets"]:
            declaration = declarations.get(offset)
            if declaration is None:
                if fit["status"] != "failed":
                    raise ValueError("missing declared anchor")
                declaration = {"status": "unavailable", "error": fit.get("error")}
            anchors.append({"fit_id": fit["fit_id"], "task": task, "seed": seed, "head": head, "offset": offset,
                **_fixed(directory / f"fixed/anchor{offset}", declaration, plan, 36 if head == "linear" else 52)})
        pressure = fit.get("pressure")
        if pressure is None:
            if fit["status"] != "failed":
                raise ValueError("missing pressure search")
            pressure = {"status": "unavailable", "error": fit.get("error")}
        searches.append({"fit_id": fit["fit_id"], "task": task, "seed": seed, "head": head,
                         **_pressure(directory / "pressure", pressure, plan)})
    checkpoints = [c for s in searches for c in s["checkpoints"]]
    result = {"schema": "hepta.cell-field-p0-summary.v4", "protocol_sha256": seal["protocol_sha256"],
        "pre_evaluation_seal_sha256": file_hash(root / "pre_evaluation_seal.json"),
        "summary_source_sha256": file_hash(__file__), "executed_source": _json(root / "executed_source.json"),
        "registered_anchors": 36, "registered_fixed_branches": 1764,
        "completed_fixed_branches": sum(a["completed"] for a in anchors), "registered_searches": 12,
        "pressure_search_statuses": dict(Counter(s["status"] for s in searches)),
        "maximum_pressure_checkpoints": 24, "materialized_pressure_checkpoints": len(checkpoints),
        "pressure_slot_statuses": dict(Counter(r["execution_status"] for c in checkpoints for r in c["slots"])),
        "anchors": anchors, "predictor_aggregate": _aggregate(anchors), "pressure_searches": searches,
        "run_resources": {k: run[k] for k in ("cpu_ns", "wall_ns")},
        "scope": {"statistics": "descriptive repeated anchors sharing tasks, sources and seeds; no independent-replicate inference",
            "loss_error": "steps1..8, both development probes; full tangent error combines finite-difference and nonlinear error",
            "rank": "direct_soft J and current-risk separately; all49 includes effort differences; same-amplitude16 holds effort fixed",
            "cost": "preparation total already includes reference; adapter and reference fields are breakdowns; objective effort is not CPU",
            "holdout": "no validation/final labels opened; no acceptance or candidate selection", "tie_tolerance": TIE_TOLERANCE}}
    write_json(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--protocol")
    summarize(**vars(parser.parse_args()))
