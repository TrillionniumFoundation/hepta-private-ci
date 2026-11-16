"""Post-run descriptive V5/V6 census; no label access or controller selection.

Repeated anchors share tasks and are not independent statistical replicates.
This reporter is intentionally outside the executed controller source closure.
"""

import argparse
from collections import Counter
import itertools
import json
from pathlib import Path

import numpy as np

from cell_field_action_control import score_common
from cell_field_action_io import write_json
from cell_field_features import file_hash
from cell_field_summary_v4 import _aggregate, prediction_metrics, verify_seal


def read(path):
    return json.loads(Path(path).read_bytes())


def arrays(path):
    with np.load(path, allow_pickle=False) as source:
        return {key: source[key] for key in source.files}


def summarize(root, output, protocol):
    root, output = Path(root), Path(output)
    if output.exists() or output.resolve().is_relative_to(root.resolve()):
        raise ValueError("new output outside the sealed run required")
    seal, plan = verify_seal(root, protocol)
    run = read(root / "run.json")
    version = int(plan["schema"].rsplit("v", 1)[1])
    expected = set(itertools.product(plan["tasks"], plan["seeds"], plan["head_modes"]))
    observed = {(f["task"], f["seed"], f["head"]) for f in run["fits"]}
    if version not in (5, 6) or len(run["fits"]) != 12 or observed != expected:
        raise ValueError("complete V5/V6 fit census required")
    anchors, preparation, tradeoffs, policy_rows, pressure_rows, searches = [], [], [], [], [], []
    parity = []
    for fit in run["fits"]:
        task, seed, head = (fit[key] for key in ("task", "seed", "head"))
        directory = root / task / f"seed{seed}-{head}"
        identity = {key: fit[key] for key in ("fit_id", "task", "seed", "head")}
        for offset in plan["anchor_offsets"]:
            where = directory / f"fixed/anchor{offset}"
            frozen, rows = read(where / "frozen_plan.json"), read(where / "branches.json")
            predicted, actual = arrays(where / "frozen_predictions.npz"), arrays(where / "actual_trajectories.npz")
            baseline = arrays(where / "reference.npz")["reference_observations"][:, :2]
            actions, models = predicted["actions"], list(frozen["models"])
            paths = list(predicted["predictions"])
            if models != plan["models"] or predicted["predictions"].shape != (7, 49, 9, 2):
                raise ValueError("fixed prediction census changed")
            if version == 6:
                extra = arrays(where.with_name(where.name + "-future-field.npz"))
                if not np.array_equal(extra["actions"], actions):
                    raise ValueError("field and common action libraries differ")
                paths.append(extra["predictions"])
                models.append("future_field")
            if len(rows) != 49 or frozen["actions"] != [row["action_id"] for row in rows]:
                raise ValueError("fixed action census changed")
            complete = np.array([row["status"] == "completed" for row in rows])
            if not complete.all():
                raise ValueError("this descriptive aggregation requires all fixed branches")
            scoring = plan["fixed_scoring"]
            forecast_scores = []
            for path in paths:
                scores = []
                for index, action in enumerate(actions):
                    sequence = np.zeros((8, actions.shape[1]))
                    sequence[0] = action
                    scores.append(score_common(path[index], sequence, baseline, frozen["old_anchor"],
                        **{k: scoring[k] for k in ("dt", "effort_price", "direct_coefficient", "current_shift", "feasibility_tolerance")}))
                forecast_scores.append(scores)
            metrics = []
            norms = np.linalg.norm(actions, axis=1)
            for amplitude in ("all", .125, .5, 1.):
                selected = np.arange(49) if amplitude == "all" else np.flatnonzero(np.isclose(norms, amplitude))
                for model, path, scores in zip(models, paths, forecast_scores):
                    metric = prediction_metrics([frozen["actions"][i] for i in selected], path[selected],
                        actual["real_delta"][selected], [rows[i]["scores"] for i in selected],
                        [scores[i] for i in selected], paths[models.index("full")][selected], complete[selected])
                    metrics.append({"model": model, "amplitude": amplitude, **metric})
            anchors.append({**identity, "offset": offset, "metrics": metrics})
            prep = frozen["preparation"]
            compact = {**identity, "offset": offset, "response": prep["response_v5"],
                "preparation_resources": {k: v for k, v in prep.items() if k not in ("models", "response_v5")}}
            if version == 6:
                compact["future_field"] = read(where.with_name(where.name + "-future-field.json"))
                compact["field_vs_analytic_max_abs"] = float(np.max(np.abs(paths[-1] - paths[models.index("analytic")])))
            preparation.append(compact)
            trade = read(where / "tradeoffs.json")
            groups = []
            for group in trade["same_norm_directions"]:
                entries = group["entries"]
                groups.append({key: group[key] for key in ("amplitude", "control_norm", "complete", "actual_current_risk_range")})
                groups[-1].update(parameter_penalty=entries[0]["effort"],
                    forgetting_range=[min(e["forgetting"] for e in entries), max(e["forgetting"] for e in entries)],
                    cpu_ns_range=[min(e["cpu_ns"] for e in entries), max(e["cpu_ns"] for e in entries)],
                    strict_current_improvement_count=sum(e["difference_from_zero"]["direct_current"] < 0 for e in entries),
                    strict_total_improvement_count=sum(e["difference_from_zero"]["direct_soft_total"] < 0 for e in entries))
            tradeoffs.append({**identity, "offset": offset, "same_norm": groups,
                "cost_identity_max_abs": trade["maximum_identity_residual"],
                "amplitude_scaling": [{"direction": group["direction"], "polarity": group["polarity"],
                    "entries": [{k: e[k] for k in ("action_id", "physical_impulse_norm", "direct_current", "forgetting", "effort", "cpu_ns")}
                                for e in group["entries"]]} for group in trade["fixed_direction_amplitudes"]]})
        for policy in plan["mpc"]["policies"]:
            record = read(directory / "mpc" / policy / "result.json")
            repairs = [step["repair"] for step in record["steps"] if "repair" in step]
            committed_repairs = [step["repair"] for step in record["steps"]
                                 if "repair" in step and step.get("committed_steps", 0) > 0]
            policy_rows.append({**identity, **{k: record.get(k) for k in
                ("policy", "status", "registered_steps", "completed_steps", "cpu_ns", "wall_ns", "error", "parameter_action_penalty")},
                "prospective_repaired_steps": sum(r["repaired_steps"] for r in repairs),
                "committed_repaired_steps": sum(r["repaired_steps"] for r in committed_repairs),
                "probe_head_evaluations": sum(r["probe_head_evaluations"] for r in repairs),
                "maximum_certified_probe_excess": max((r["maximum_future_excess"] for r in repairs if r["certified"]), default=None)})
        if version == 6:
            full = arrays(directory / "mpc/adjoint_h8_repaired/trajectory.npz")
            field = arrays(directory / "mpc/future_field_h8_repaired/trajectory.npz")
            parity.append({**identity, **{key + "_max_abs": float(np.max(np.abs(full[key]-field[key])))
                           for key in ("states", "actions", "probabilities")}})
        pressure = directory / "pressure"
        search = read(pressure / "search.json")
        searches.append({**identity, **{k: search[k] for k in ("status", "tau", "completed_steps", "maximum_steps")}})
        repaired = read(pressure / "results.json")
        guarded = read(pressure / "guarded-results.json") if version == 6 else repaired
        if len(repaired) != len(guarded):
            raise ValueError("paired pressure census differs")
        for left, right in zip(guarded, repaired):
            if (left["checkpoint"], left["candidate_id"]) != (right["checkpoint"], right["candidate_id"]):
                raise ValueError("pressure IDs differ")
            a, b = left["verification"], right["verification"]
            pressure_rows.append({**identity, "checkpoint": right["checkpoint"], "candidate_id": right["candidate_id"],
                "plan_status": right["plan"]["status"], "guard_status": a["status"], "repair_status": b["status"],
                "guard_certified": a["certified"], "repair_certified": b["certified"],
                "initial_old_excess": b.get("initial_old_excess"),
                "maximum_future_excess": b.get("maximum_future_excess"), "repaired_steps": b.get("repaired_steps", 0),
                "guard_cpu_ns": a["cpu_ns"], "repair_cpu_ns": b["cpu_ns"],
                "intended_action_changed": b.get("accepted_actions_sha256") is not None and
                    b.get("accepted_actions_sha256") != b.get("candidate_actions_sha256")})
    aggregate = _aggregate(anchors)
    for row in aggregate:
        selected = [m for a in anchors if row["group"] in ("all", a["task"] + "/" + a["head"])
                    for m in a["metrics"] if m["model"] == row["model"] and str(m["amplitude"]) == row["amplitude"]]
        ranks = [m["current_risk_rank"] for m in selected]
        taus = [r["kendall_tau_b"] for r in ranks if r["kendall_tau_b"] is not None]
        row["mean_current_risk_tau_b"] = float(np.mean(taus)) if taus else None
        row["mean_current_risk_decision_regret"] = float(np.mean([r["predicted_top_actual_regret"] for r in ranks]))
        row["reduced_vs_full_prediction_rmse"] = float(np.sqrt(np.mean([m["reduced_vs_full_prediction_rmse"]**2 for m in selected])))
    result = {"schema": "hepta.cell-field-descriptive-census.v6", "experiment_version": version,
        "protocol_sha256": seal["protocol_sha256"], "seal_sha256": file_hash(root / "pre_evaluation_seal.json"),
        "reporter_sha256": file_hash(__file__), "registered_fixed_branches": 1764, "completed_fixed_branches": 1764,
        "registered_prediction_paths": 1764*(8 if version == 6 else 7), "predictor_aggregate": aggregate,
        "preparation": preparation, "tradeoffs": tradeoffs, "policies": policy_rows, "full_field_policy_parity": parity,
        "policy_statuses": dict(Counter(r["status"] for r in policy_rows)),
        "pressure_searches": searches, "pressure_rows": pressure_rows,
        "pressure_census": {"maximum_slots": 312, "instantiated_slots": len(pressure_rows),
            "no_crossing_searches": sum(s["status"] == "no_pressure_crossing" for s in searches),
            "plan_statuses": dict(Counter(r["plan_status"] for r in pressure_rows)),
            "guard_statuses": dict(Counter(r["guard_status"] for r in pressure_rows)),
            "repair_statuses": dict(Counter(r["repair_status"] for r in pressure_rows)),
            "paired_certification": dict(Counter(f"guard={r['guard_certified']},repair={r['repair_certified']}" for r in pressure_rows)),
            "certified_action_changes": sum(r["repair_certified"] and r["intended_action_changed"] for r in pressure_rows),
            "certified_repaired_steps": sum(r["repaired_steps"] for r in pressure_rows if r["repair_certified"])},
        "run_resources": {k: run[k] for k in ("cpu_ns", "wall_ns")},
        "scope": {"statistics": "descriptive shared anchors; no independent replicate inference",
            "rank": "all49 mixes effort; same-amplitude16 holds effort fixed; tie tolerance1e-10",
            "cost": "objective penalty, model preparation, verification and measured CPU remain separate",
            "labels": "reporter does not open held-out labels", "production_authority": False}}
    write_json(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "output", "protocol"):
        parser.add_argument("--" + name, required=True)
    summarize(**vars(parser.parse_args()))
