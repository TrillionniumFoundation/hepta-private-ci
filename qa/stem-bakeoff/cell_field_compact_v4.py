"""Losslessly retain selected P0 audit columns and gzip the complete summary.

This post-run presentation step reads only the already validated probe summary.
The full summary remains the source of every omitted critic or trajectory detail.
"""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
from statistics import fmean

from prepare_news_cohorts import canonical


MODELS = ["loss2", "q4", "history4", "structured4", "full"]
AMPLITUDES = ["all", .125, .5, 1.]
STATUS = ["completed", "not_executed_tangent_infeasible", "not_executed_unresolved", "execution_failed", "unavailable"]
COMPONENTS = ["direct_soft_total", "direct_current", "forgetting", "effort", "maximum_future_old_excess", "terminal_old_excess"]


def compact(summary, output, full_gzip):
    source, output, full_gzip = map(Path, (summary, output, full_gzip))
    if output.exists() or full_gzip.exists() or source.resolve() in (output.resolve(), full_gzip.resolve()):
        raise ValueError("new publication paths required")
    payload = source.read_bytes()
    data = json.loads(payload)
    action_ids = [r["action_id"] for r in data["anchors"][0]["actions"]]
    anchor_index, metrics, linearity = [], [], []
    for index, anchor in enumerate(data["anchors"]):
        anchor_index.append({k: anchor.get(k) for k in ("fit_id", "task", "seed", "head", "offset", "status", "completed")})
        preparation = anchor.get("preparation", {})
        anchor_index[-1].update(preparation_cpu_ns=preparation.get("total_preparation_cpu_ns"),
            reference_cpu_ns=preparation.get("reference_cpu_ns"),
            branch_cpu_ns=anchor.get("branch_resources", {}).get("cpu_ns", {}).get("observed_ns"),
            adapter_cpu_ns=[preparation.get("models", {}).get(m, {}).get("build_cpu_ns") for m in MODELS])
        for m in anchor["metrics"]:
            rank, risk = m.get("direct_soft_rank") or {}, m.get("current_risk_rank") or {}
            counts = rank.get("pair_counts", {})
            metrics.append([index, MODELS.index(m["model"]), AMPLITUDES.index(m["amplitude"]), m["status"], m["completed"],
                *[m.get(k) for k in ("loss_rmse", "current_loss_rmse", "old_loss_rmse", "full_loss_rmse", "rmse_over_full", "direct_soft_mae")],
                rank.get("kendall_tau_b"), rank.get("predicted_top_actual_regret"), risk.get("kendall_tau_b"),
                risk.get("predicted_top_actual_regret"),
                action_ids.index(rank["predicted_top"]) if "predicted_top" in rank else None,
                action_ids.index(rank["executed_candidate_oracle"]) if "executed_candidate_oracle" in rank else None,
                *[counts.get(k, 0) for k in ("concordant", "discordant", "predicted_only_tie", "actual_only_tie", "both_tied")]])
        for row in anchor.get("linearity", []):
            linearity.append([index, row["amplitude"], row["physical_impulse_norm"], row.get("loss_rmse"), row.get("error_per_squared_impulse")])
    searches, checkpoints, slots, pairs, raw_pairs, raw_slots = [], [], [], [], [], []
    candidate_ids = None
    for search in data["pressure_searches"]:
        searches.append({k: search.get(k) for k in ("fit_id", "status", "tau", "completed_steps", "old_anchor", "checkpoint_offsets", "cpu_ns", "wall_ns")})
        for checkpoint in search["checkpoints"]:
            index = len(checkpoints)
            checkpoints.append({"fit_id": search["fit_id"], **{k: checkpoint[k] for k in ("checkpoint", "offset", "status", "registered", "completed")}})
            checkpoints[-1].update(preparation_cpu_ns=checkpoint.get("preparation", {}).get("total_preparation_cpu_ns"),
                reference_cpu_ns=checkpoint.get("preparation", {}).get("reference_cpu_ns"),
                **{key: value["observed_ns"] for key, value in checkpoint.get("resources", {}).items()})
            ids = [r["candidate_id"] for r in checkpoint["slots"]]
            if candidate_ids is not None and ids != candidate_ids:
                raise ValueError("checkpoint candidate order differs")
            candidate_ids = ids
            for number, row in enumerate(checkpoint["slots"]):
                actual, own = row.get("actual") or {}, row.get("predicted", {}).get(row.get("model")) or {}
                slots.append([index, number, STATUS.index(row["execution_status"]), row.get("status"), row.get("solver_status"),
                    actual.get("future_retention_within_tolerance"), own.get("future_retention_within_tolerance"),
                    row.get("predicted_feasible_actual_violation"), row.get("physical_impulse_norm"),
                    *[actual.get(k) for k in COMPONENTS],
                    *[row.get(k) for k in ("planning_cpu_ns", "execution_cpu_ns", "audit_prediction_cpu_ns")]])
                raw_slots.append(row)
            for pair in checkpoint["pairs"]:
                delta = pair.get("actual_hard_minus_soft") or {}
                pairs.append([index, MODELS.index(pair["model"]), pair["budget_multiplier"],
                    STATUS.index(pair["soft_status"]), STATUS.index(pair["hard_status"]), pair.get("identical_action"),
                    *[pair.get(k) for k in ("physical_action_difference", "soft_physical_norm", "hard_physical_norm", "soft_actual_feasible", "hard_actual_feasible")],
                    *[delta.get(k) for k in COMPONENTS]])
                raw_pairs.append(pair)
    paired = []
    for model in MODELS:
        for budget in (.25, 1., 4.):
            declared = [r for r in raw_pairs if r["model"] == model and r["budget_multiplier"] == budget]
            ready = [r for r in declared if "actual_hard_minus_soft" in r]
            paired.append({"model": model, "budget": budget, "registered_pairs": len(declared), "executed_pairs": len(ready),
                "hard_only_feasible": sum(r["hard_actual_feasible"] and not r["soft_actual_feasible"] for r in ready),
                "soft_only_feasible": sum(r["soft_actual_feasible"] and not r["hard_actual_feasible"] for r in ready),
                "both_feasible": sum(r["hard_actual_feasible"] and r["soft_actual_feasible"] for r in ready),
                "neither_feasible": sum(not r["hard_actual_feasible"] and not r["soft_actual_feasible"] for r in ready),
                "max_old_excess_decreased": sum(r["actual_hard_minus_soft"]["maximum_future_old_excess"] < 0 for r in ready),
                "max_old_excess_increased": sum(r["actual_hard_minus_soft"]["maximum_future_old_excess"] > 0 for r in ready),
                "mean_hard_minus_soft": {k: fmean(r["actual_hard_minus_soft"][k] for r in ready) if ready else None for k in COMPONENTS}})
    directions = []
    if all(a["completed"] == 49 for a in data["anchors"]):
        for amplitude in AMPLITUDES[1:]:
            risk, penalties, differences, widths = [], [], [], []
            for a in data["anchors"]:
                rows = [r for r in a["actions"] if abs(r["physical_impulse_norm"]-.02*amplitude) < 1e-12]
                zero = next(r for r in a["actions"] if r["action_id"] == "zero")["actual"]["direct_soft_total"]
                values = [r["actual"]["direct_current"] for r in rows]
                risk.extend(values)
                widths.append(max(values)-min(values))
                penalties.extend(r["actual"]["effort"] for r in rows)
                differences.extend(r["actual"]["direct_soft_total"]-zero for r in rows)
            directions.append({"amplitude": amplitude, "physical_impulse_norm": .02*amplitude, "actions": len(risk),
                "action_penalty_range": [min(penalties), max(penalties)], "current_risk_range": [min(risk), max(risk)],
                "mean_same_norm_current_risk_width": fmean(widths), "max_same_norm_current_risk_width": max(widths),
                "current_risk_improvements": sum(r < 0 for r in risk), "J_improvements_over_zero": sum(d < 0 for d in differences),
                "J_minus_zero_range": [min(differences), max(differences)]})
    result = {"schema": "hepta.cell-field-p0-compact.v4", "full_summary_sha256": hashlib.sha256(payload).hexdigest(),
        "compact_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        **{k: data[k] for k in ("protocol_sha256", "pre_evaluation_seal_sha256", "registered_anchors", "registered_fixed_branches",
           "completed_fixed_branches", "registered_searches", "pressure_search_statuses", "maximum_pressure_checkpoints",
           "materialized_pressure_checkpoints", "pressure_slot_statuses", "run_resources", "scope")},
        "model_index": MODELS, "amplitude_index": AMPLITUDES, "action_index": action_ids, "status_index": STATUS,
        "anchor_index": anchor_index, "predictor_aggregate": data["predictor_aggregate"],
        "anchor_metrics": {"columns": ["anchor", "model", "amplitude", "status", "completed", "loss_rmse", "current_rmse", "old_rmse",
            "full_rmse", "rmse_over_full", "J_mae", "J_tau_b", "J_decision_regret", "risk_tau_b", "risk_regret", "predicted_best_action",
            "actual_oracle_action", "concordant", "discordant", "predicted_only_tie", "actual_only_tie", "both_tied"], "rows": metrics},
        "linearity": {"columns": ["anchor", "amplitude", "physical_impulse_norm", "full_loss_rmse", "error_per_squared_impulse"], "rows": linearity},
        "pressure_searches": searches, "checkpoint_index": checkpoints, "candidate_index": candidate_ids,
        "pressure_slots": {"columns": ["checkpoint", "candidate", "execution_status", "plan_status", "solver_status", "actual_feasible",
            "own_predicted_feasible", "predicted_feasible_actual_violation", "physical_impulse_norm", *COMPONENTS,
            "planning_cpu_ns", "execution_cpu_ns", "audit_prediction_cpu_ns"], "rows": slots},
        "pressure_pairs": {"columns": ["checkpoint", "model", "budget", "soft_status", "hard_status", "identical_action",
            "physical_action_difference", "soft_physical_norm", "hard_physical_norm", "soft_actual_feasible", "hard_actual_feasible",
            *["hard_minus_soft_"+k for k in COMPONENTS]], "rows": pairs},
        "pressure_pair_aggregates": paired, "direction_amplitude_decomposition": directions,
        "raw_pressure_status_counts": dict(Counter(r["execution_status"] for r in raw_slots))}
    packed = canonical(result)+b"\n"
    if len(packed) > 500000:
        raise ValueError("compact publication exceeds its declared500KB bound")
    output.parent.mkdir(parents=True, exist_ok=True)
    full_gzip.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(packed)
    full_gzip.write_bytes(gzip.compress(payload, compresslevel=9, mtime=0))
    if gzip.decompress(full_gzip.read_bytes()) != payload:
        raise ValueError("complete summary gzip readback mismatch")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("summary", "output", "full-gzip"):
        parser.add_argument("--"+name, required=True)
    compact(**vars(parser.parse_args()))
