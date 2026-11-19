#!/usr/bin/env python3
"""Read already-opened V4 result receipts; no model/label/experiment execution.

Write only new descriptive report artifacts. Raw owner files remain untouched.
"""
import argparse
import csv
import hashlib
import json
import os
import pathlib
import statistics
import tempfile

EXPECTED = {
    "evaluation.json": "512104e3709b7c4916e621d7b8a46447785ad1fbf9733d6296e0fdee41473456",
    "pre-unseal-audit.json": "1f99364a998fe6e33be55b9f04974bb3134396ab67aa65be3eb3ab0735cb9991",
    "execution.json": "6824be16670c536fe72e2c39bbedfd789b1ad9add03b258e756f4e9ffe6a7fc9",
}
ARMS = ["loss2", "history2", "history4", "moment4", "full"]
COST_SHA256 = "accf5e39b045b7d1be627e5f68f3bdb5ab875d33ae1b1b675831b8271f748e38"
PROTOCOL_SHA256 = "fe0057c499c1a77ca7f5781a05425d83d59693b4250fb1560cab978afb4cd5b2"
PREREGISTRATION_SHA256 = "ae4be0a7c2c8807f286f8d96581c6efa51e3a9f935cec7c1e515dd18d146866b"


def read_original(root, name):
    data = (root / name).read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != EXPECTED[name]:
        raise ValueError("Original owner evidence hash differs: " + name)
    return json.loads(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=pathlib.Path, required=True)
    parser.add_argument("--cost-summary", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    evaluation = read_original(args.results, "evaluation.json")
    audit = read_original(args.results, "pre-unseal-audit.json")
    execution = read_original(args.results, "execution.json")
    cost_raw = args.cost_summary.read_bytes()
    if hashlib.sha256(cost_raw).hexdigest() != COST_SHA256:
        raise ValueError("Original cost aggregation receipt hash differs")
    cost = json.loads(cost_raw)
    assert cost["source_commit"] == evaluation["source_commit"]
    assert cost["run_seal_sha256"] == evaluation["run_seal_sha256"]
    assert cost["executed_protocol_sha256"] == PROTOCOL_SHA256
    assert cost["collector_revision"] == 2 and cost["raw_bundle"]["verified_by_this_helper"] is True
    assert cost["census"] == {"anchors": 18, "map_builds": 90, "branch_records": 306,
                              "branch_optimizer_steps": 2448, "bridge_sources": 8,
                              "new_sources": 96, "feature_forward_calls": 7}
    assert evaluation["run_seal_sha256"] == audit["run_seal_sha256"]
    assert evaluation["primary_registered"] == 6 and evaluation["primary_passed"] == 0
    assert audit["status"] == "passed" and audit["final_labels_opened"] is False
    assert audit["registered_branches"] == 306 and audit["replayed_optimizer_steps"] == 2448
    assert len(audit["ranking_rows"]) == 90
    assert len(execution) == 5 and all(row["exit"] == 0 for row in execution)
    mechanism, steps = [], []
    for arm in ARMS:
        rows = [row for row in audit["ranking_rows"] if row["arm"] == arm]
        assert len(rows) == 18 and all(len(row["per_step_loss_mae"]) == 9 for row in rows)
        primary_rows = [row for row in rows if row["anchor"].endswith("step16")]
        assert len(primary_rows) == 6 and all(row["chosen_action"] == 0 for row in primary_rows)
        mechanism.append({
            "arm": arm, "anchors": 18, "selected_zero": sum(row["chosen_action"] == 0 for row in rows),
            "h8_current_response_mae_mean": statistics.mean(row["per_step_loss_mae"][8][0] for row in rows),
            "h8_old_response_mae_mean": statistics.mean(row["per_step_loss_mae"][8][1] for row in rows),
            "nonzero_action_cost_mae_mean": statistics.mean(row["same_action_cost_mae"] for row in rows),
            "nonzero_direction_tau_b_mean": statistics.mean(row["equal_radius_ranking"]["tau_b"] for row in rows),
            "nonzero_direction_tau_b_min": min(row["equal_radius_ranking"]["tau_b"] for row in rows),
            "nonzero_direction_tau_b_max": max(row["equal_radius_ranking"]["tau_b"] for row in rows),
            "full_pool_selected_regret_mean": statistics.mean(row["actual_regret"] for row in rows),
            "full_pool_selected_regret_max": max(row["actual_regret"] for row in rows),
            "anchors_with_positive_regret": sum(row["actual_regret"] > 0 for row in rows),
        })
        for step in range(9):
            steps.append({"arm": arm, "step": step,
                          "current_response_mae_mean": statistics.mean(row["per_step_loss_mae"][step][0] for row in rows),
                          "old_response_mae_mean": statistics.mean(row["per_step_loss_mae"][step][1] for row in rows)})
    totals = {
        "five_stage_wall_seconds": sum(row["wall_seconds"] for row in execution),
        "five_stage_child_cpu_seconds": sum(row["child_cpu_seconds"] for row in execution),
        "maximum_recorded_cumulative_child_peak_rss_kib": max(row["peak_child_rss_kib"] for row in execution),
    }
    totals["maximum_recorded_cumulative_child_peak_rss_gib"] = totals["maximum_recorded_cumulative_child_peak_rss_kib"] / 1048576
    selected_secondary = [row for row in evaluation["secondary_point_estimates"]
                          if row["anchor_offset"] == 16 and row["arm"] == "loss2"]
    for row in selected_secondary:
        counterparts = [candidate for candidate in evaluation["secondary_point_estimates"]
                        if candidate["anchor_offset"] == 16 and candidate["head"] == row["head"]
                        and candidate["role"] == row["role"] and candidate["arm"] in ARMS + ["zero"]]
        assert len(counterparts) == 6
        assert all(candidate["nll"] == row["nll"] and candidate["accuracy"] == row["accuracy"] for candidate in counterparts)
    summary = {
        "schema": "hepta.cell-closure-report-derived.v4", "authority": "DENY_ALL", "production_authority": False,
        "report_revision": 2,
        "source_commit": evaluation["source_commit"], "run_seal_sha256": evaluation["run_seal_sha256"],
        "input_file_sha256": EXPECTED, "primary": evaluation["primary"],
        "primary_passed": 0, "primary_registered": 6, "sources": evaluation["sources"],
        "reserved_components": evaluation["reserved_components"],
        "mechanism_aggregation": "unweighted mean over the 18 fixed correlated anchors; each source row already averages the 16 NONZERO actions; exact finite census, not an independent-task confidence interval",
        "mechanism": mechanism, "primary_anchor_all_arms_selected_action_zero": True,
        "selected_secondary_at_anchor16": selected_secondary, "execution": execution, "totals": totals,
        "audit": {key: audit[key] for key in ["status", "registered_branches", "replayed_optimizer_steps",
                    "replayed_anchor_training_steps", "arithmetic_comparisons", "max_actual_cost_error", "max_forecast_cost_error"]},
        "no_new_experiment_or_label_access": True,
        "cost_summary_sha256": COST_SHA256, "cost_accounting": cost,
        "executed_protocol_sha256": PROTOCOL_SHA256,
        "executed_preregistration_sha256": PREREGISTRATION_SHA256,
        "remaining_unmeasured_or_unseparated_costs": ["separate reference CPU", "separate bridge CPU",
                    "isolated per-stage RSS except the feature process receipt", "energy",
                    "end-to-end independent controller deployment cost"],
    }
    with (args.out / "derived-summary.json").open("x") as stream:
        json.dump(summary, stream, indent=2); stream.write("\n")
    for name, rows in [("mechanism-summary.csv", mechanism), ("per-step-response-mae.csv", steps)]:
        with (args.out / name).open("x", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    write_cost_tables(args.out, cost)
    make_figure(args.out, steps)
    print(json.dumps({"result": "descriptive_derivatives_created", "primary": "0/6", "totals": totals,
                      "raw_evidence_modified": False, "new_model_or_label_calls": 0}))


def write_cost_tables(out, cost):
    """Keep timing scopes separate; integer ns preserve original precision."""
    reference, maps, branches, interval = (cost[key] for key in ("reference", "maps", "branches", "run_interval"))
    components = [
        {"component": "shared_reference", "count": 18, "wall_ns": reference["wall_ns"]["sum"], "cpu_ns": None,
         "scope": "shared once per anchor; separate CPU unrecorded"},
        {"component": "all_arm_maps", "count": 90, "wall_ns": maps["all_builds"]["wall_ns"]["sum"],
         "cpu_ns": maps["all_builds"]["cpu_ns"]["sum"], "scope": "excludes shared reference"},
        {"component": "all_real_branches", "count": 306, "wall_ns": branches["wall_ns"]["sum"],
         "cpu_ns": branches["cpu_ns"]["sum"], "scope": "all 17 actions at each of 18 anchors"},
        {"component": "other_unallocated", "count": None, "wall_ns": interval["wall_ns_other_unallocated"],
         "cpu_ns": None, "scope": "separate CPU unavailable; residual CPU includes reference"},
        {"component": "inner_run_total", "count": 1, "wall_ns": interval["wall_ns"],
         "cpu_ns": interval["cpu_ns"], "scope": "contains preceding components; nested within wrapper run stage"},
    ]
    map_rows, state_rows = [], []
    for row in maps["per_arm"]:
        map_rows.append({"arm": row["arm"], "anchors": row["anchors"],
                         "wall_ns_sum": row["wall_ns"]["sum"], "cpu_ns_sum": row["cpu_ns"]["sum"],
                         "wall_ns_median": row["wall_ns"]["median"], "cpu_ns_median": row["cpu_ns"]["median"],
                         "wall_ns_minimum": row["wall_ns"]["minimum"], "wall_ns_maximum": row["wall_ns"]["maximum"],
                         "logical_map_array_nbytes_sum": row["map_array_nbytes_sum"],
                         "includes_shared_reference": False})
        for head in row["by_head"]:
            state = {"arm": row["arm"], "head": head["head"], "anchors": head["anchors"],
                     "wall_ns_sum": head["wall_ns"]["sum"], "cpu_ns_sum": head["cpu_ns"]["sum"]}
            for key in ("map_bytes", "projected_dimension", "retained_output_scalars",
                        "retained_action_scalars_upper_bound", "common_full_state_dimension",
                        "retained_state_scalars_upper_bounds"):
                assert len(head[key]) == 1
                state[key] = head[key][0]
            state_rows.append(state)
    feature = cost["features"]
    feature_stages = [{"component": key, "wall_ns": feature[key]["wall_ns"],
                       "cpu_ns": feature[key]["cpu_ns"], "scope": "nested within wrapper features stage"}
                      for key in ("encoder_load", "encoding")]
    artifact_rows = [{"category": key, **row, "scope": "original run-seal inventory"}
                     for key, row in sorted(cost["sealed_run_artifact_inventory"]["by_category"].items())]
    tables = [
        ("cost-run-components.csv", components), ("cost-map-summary.csv", map_rows),
        ("cost-map-state-by-head.csv", state_rows), ("cost-reference-by-anchor.csv", reference["per_anchor"]),
        ("cost-feature-stages.csv", feature_stages),
        ("cost-feature-forwards.csv", [feature["bridge"]["receipt"], *feature["new_source_receipts"]]),
        ("cost-artifact-inventory.csv", artifact_rows),
    ]
    for name, rows in tables:
        with (out / name).open("x", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)


def make_figure(out, rows):
    with tempfile.TemporaryDirectory(prefix="hepta-v4-report-mpl-") as cache:
        os.environ["MPLCONFIGDIR"] = cache
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib import pyplot as plt
        plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                             "svg.hashsalt": "hepta-v4-fixed-report-20261025"})
        colors = {"loss2": "#536878", "history2": "#cc7c22", "history4": "#007c91",
                  "moment4": "#b64258", "full": "#4b3e9f"}
        markers = {"loss2": "o", "history2": "s", "history4": "^", "moment4": "D", "full": "x"}
        fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.7), sharey=True)
        for ax, field, title in zip(axes, ["current_response_mae_mean", "old_response_mae_mean"],
                                   ["Current-probe loss response", "Old-probe loss response"]):
            for arm in ARMS:
                selected = [row for row in rows if row["arm"] == arm and row["step"] > 0]
                ax.plot([row["step"] for row in selected], [row[field] for row in selected],
                        label=arm, color=colors[arm], marker=markers[arm], markersize=4, linewidth=1.5)
            ax.set_yscale("log"); ax.set_xticks(range(1, 9)); ax.set_xlabel("Optimizer step after the registered impulse")
            ax.set_title(title, pad=10); ax.grid(True, which="major", color="#e0e5e8", linewidth=.7)
            ax.spines[["top", "right"]].set_visible(False)
        axes[0].set_ylabel("Mean absolute response-prediction error (log scale)")
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc="lower center", ncol=5, frameon=False, bbox_to_anchor=(.5, .12))
        fig.suptitle("V4: eight-step local response closure on the fixed action census", fontsize=13, y=.98)
        fig.text(.5, .045, "Means over 18 correlated anchors; each anchor averages 16 nonzero actions. No uncertainty bands.\n"
                 "All six external primary comparisons failed the preregistered superiority rule (exact paired difference = 0).",
                 ha="center", va="center", fontsize=9, color="#424c54")
        fig.subplots_adjust(top=.83, bottom=.29, left=.09, right=.98, wspace=.14)
        fig.savefig(out / "eight-step-response-mae.png", dpi=180, facecolor="white", metadata={"Software": "Matplotlib; exact owner receipt aggregation"})
        fig.savefig(out / "eight-step-response-mae.svg", facecolor="white", metadata={"Date": None})
        plt.close(fig)


if __name__ == "__main__":
    main()
