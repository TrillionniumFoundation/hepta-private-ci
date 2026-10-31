"""Additive P0 diagnostics after the original full-study and review seals.

Join existing A gated choices to same-parent physical successors and evaluate
the omitted C gated calibration rows. No fitting, training, new threshold,
bootstrap, production admission, or inference of controller-state equality.
"""

import argparse
from collections import Counter
import gzip
import json
import math
from pathlib import Path
import statistics
import sys
import time


SCHEMA = "hepta.parameter-field.p0-postseal-actions.1"
BASELINES = {17: 2, 29: 3, 43: 3}
MODES = ("field12", "full_current_state", "history6")
COMPONENTS = ("parameters", "momentum", "gradients", "buffers")
C_MODES = ("ordinary", "dual")
C_SEEDS = (701, 702)


def need(condition, message):
    if not condition:
        raise ValueError(message)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def vector4(value):
    need(isinstance(value, (list, tuple)) and len(value) == 4
         and all(finite(x) for x in value), "Four finite action values required")
    return value


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    def constant(value):
        raise ValueError("Nonfinite JSON constant: " + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def validate_choice(choice, baseline):
    scores = vector4(choice["predicted_advantages"])
    need(type(baseline) is int and baseline in range(4) and scores[baseline] == 0,
         "Mislabeled baseline advantage")
    need(finite(choice["threshold"]) and choice["threshold"] >= 0
         and finite(choice["predicted_margin"]) and finite(choice["standardized_norm"])
         and choice["standardized_norm"] >= 0, "Nonfinite choice receipt")
    greedy = max(range(4), key=scores.__getitem__)
    tied = scores.count(scores[greedy]) > 1
    override = greedy != baseline and not tied and scores[greedy] > choice["threshold"]
    expected = greedy if override else baseline
    fallback = None if override else ("baseline_or_tie" if greedy == baseline or tied else "calibration_gate")
    need(type(choice["chosen_action"]) is int and choice["chosen_action"] == expected
         and type(choice["greedy_action"]) is int and choice["greedy_action"] == greedy
         and choice["predicted_margin"] == scores[greedy]
         and choice["override"] is override and choice["fallback_reason"] == fallback
         and choice["certificate"] is False, "Choice differs from frozen strict gate")
    return expected


def metrics(choice, baseline, advantages):
    values = vector4(advantages)
    need(values[baseline] == 0, "Realized baseline advantage is nonzero")
    action = validate_choice(choice, baseline)
    return {"choice": choice, "chosen_action": action,
            "requested_override": choice["override"],
            "realized_baseline_tail_advantage": values[action],
            "gated_regret": max(values) - values[action],
            "attainable_gain": max(values),
            "chosen_action_is_optimal": values[action] == max(values)}


def summarize(rows):
    need(rows, "Empty diagnostic population")
    gain = statistics.fmean(r["attainable_gain"] for r in rows)
    regret = statistics.fmean(r["gated_regret"] for r in rows)
    return {"rows": len(rows), "requested_overrides": sum(r["requested_override"] for r in rows),
            "accepted_requested_overrides": sum(r["requested_override"] and r["guard_accepted"] for r in rows),
            "requested_overrides_same_physical_successor_as_baseline": sum(
                r["requested_override"] and r["same_parent_physical_dynamics_equal"] for r in rows),
            "fallback_counts": dict(Counter(r["choice"]["fallback_reason"] or "no_fallback" for r in rows)),
            "mean_realized_baseline_tail_advantage": statistics.fmean(r["realized_baseline_tail_advantage"] for r in rows),
            "mean_gated_regret": regret, "mean_attainable_gain": gain,
            "mean_regret_over_mean_attainable_gain": regret / gain if gain > 0 else None,
            "optimal_set_accuracy": sum(r["chosen_action_is_optimal"] for r in rows) / len(rows),
            "calibration_rows_used_to_choose_threshold": True,
            "new_independent_samples": 0, "certificate": False}


def a_selected_successors(calibration, differences):
    parents = [f"schedule-{s}-{p}-step-{t}" for s in range(6000, 6004)
               for p in ("baseline", "balanced") for t in range(0, 288, 48)]
    expected = {(s, p, a) for s in BASELINES for p in parents for a in range(4)}
    indexed = {(r["seed"], r["parent"], r["action"]): r for r in differences}
    need(len(indexed) == len(differences) == len(expected) and set(indexed) == expected,
         "A successor bank is incomplete or duplicated")
    expected_cal = {(s, m, p) for s in BASELINES for m in MODES for p in parents if p.startswith("schedule-6003-")}
    need(len(calibration) == len(expected_cal) and {(r["seed"], r["mode"], r["parent"]) for r in calibration} == expected_cal,
         "A gated calibration population differs")
    rows = []
    for item in calibration:
        baseline = BASELINES[item["seed"]]
        need(item["baseline"] == baseline, "A head baseline differs")
        action = validate_choice(item["choice"], baseline)
        selected = indexed[(item["seed"], item["parent"], action)]
        diff = selected["difference"]
        need(selected["baseline"] == baseline and selected["same_parent_baseline_reference"] is True
             and type(selected["guard_accepted"]) is bool
             and selected["successor_clock"] == selected["parent_clock"] + 48
             and item["parent"].endswith("-step-" + str(selected["parent_clock"])), "A selected successor is not aligned")
        changed = diff["different_components"]
        need(isinstance(changed, list) and len(changed) == len(set(changed))
             and type(diff["reference_tail_state_equal"]) is bool
             and diff["reference_tail_state_equal"] == (not changed), "A physical identity is inconsistent")
        for component in COMPONENTS:
            data = diff[component]
            need(all(finite(data[k]) and data[k] >= 0 for k in ("l2", "max_abs")), "A successor norm is invalid")
            key = "optimizer" if component == "momentum" else component
            need(data["l2"] == 0 or key in changed, "Nonzero norm without changed component")
        need(action != baseline or (not changed and all(diff[c]["l2"] == diff[c]["max_abs"] == 0 for c in COMPONENTS)),
             "Baseline successor differs from itself")
        need(all(finite(item[k]) for k in ("chosen_baseline_aligned_advantage", "gated_selection_regret", "attainable_gain"))
             and item["attainable_gain"] >= 0 and item["gated_selection_regret"] >= 0
             and item["gated_selection_regret"] == item["attainable_gain"] - item["chosen_baseline_aligned_advantage"]
             and item["chosen_action_is_optimal"] is (item["gated_selection_regret"] == 0),
             "A supplied gated metric is invalid")
        rows.append({"seed": item["seed"], "mode": item["mode"], "parent": item["parent"],
            "chosen_action": action, "baseline": baseline, "choice": item["choice"],
            "requested_override": item["choice"]["override"], "guard_accepted": selected["guard_accepted"],
            "same_parent_physical_dynamics_equal": diff["reference_tail_state_equal"],
            "parameter_optimizer_component_changed": bool({"parameters", "optimizer"}.intersection(changed)),
            "component_numeric_norms": {c: diff[c] for c in COMPONENTS},
            "controller_history_comparison_available": False,
            "realized_baseline_tail_advantage": item["chosen_baseline_aligned_advantage"],
            "gated_regret": item["gated_selection_regret"], "attainable_gain": item["attainable_gain"],
            "chosen_action_is_optimal": item["chosen_action_is_optimal"]})
    return {"rows": rows, "summaries": [{"seed": s, "mode": m, **summarize(
        [r for r in rows if r["seed"] == s and r["mode"] == m])} for s in BASELINES for m in MODES],
        "scope": "Dependent A calibration parents; same-parent baseline branch, not deployment occupancy."}


def c_rows(mode, head, arrays, source_rows, choose, np):
    expected = [(s, q, p, t) for s in C_SEEDS for q in range(7000, 7004)
                for p in ("baseline", "balanced") for t in range(0, 96, 16)]
    need(len(source_rows) == 96 and [(r["seed"], r["schedule"], r["prefix"], r["clock"]) for r in source_rows] == expected,
         "C bank order or complete population differs")
    need(head["baseline"] == 2 and head["dimension"] == 12 and head["fit_count"] == 72
         and head["calibration_count"] == 24 and head["ridge"] == 1, "C head contract differs")
    x, y, fit, cal = (arrays[k] for k in ("features", "advantages", "fit", "calibration"))
    expected_fit = np.asarray([r[1] != 7003 for r in expected], dtype=bool)
    need(x.shape == (96, 12) and y.shape == (96, 4) and np.isfinite(x).all() and np.isfinite(y).all()
         and fit.dtype == cal.dtype == np.dtype(bool) and np.array_equal(fit, expected_fit)
         and np.array_equal(cal, ~expected_fit), "C fit/calibration split or arrays differ")
    result = []
    for index, row in enumerate(source_rows):
        need(row["mode"] == mode and row["schema"] == "hepta.fullstudy.C.branch-row.1"
             and row["decision"] * 16 == row["clock"] and row["fit"] is bool(fit[index])
             and row["calibration"] is bool(cal[index]) and row["prefix_branch_replay_verified"] is True
             and np.array_equal(x[index], row["feature"]) and np.array_equal(y[index], row["advantages"]),
             "C row identity, arrays or role differs")
        branches = row["branches"]
        need(len(branches) == 4 and [b["action"] for b in branches] == list(range(4)), "C actions incomplete")
        baseline_values = np.asarray(branches[2]["terminal_values"], dtype=np.float64)
        need(baseline_values.ndim == 1 and baseline_values.size > 0 and np.isfinite(baseline_values).all(), "C baseline labels invalid")
        for action, branch in enumerate(branches):
            values = np.asarray(branch["terminal_values"], dtype=np.float64)
            need(values.shape == baseline_values.shape and np.isfinite(values).all()
                 and float((values - baseline_values).mean()) == y[index, action], "C paired realized label differs")
            trace = branch["trace"]
            need(isinstance(trace, list) and len(trace) == (96-row["clock"])//16,
                 "C baseline-tail transition population differs")
            for offset, transition in enumerate(trace):
                need(transition["start"] == row["clock"] + 16*offset
                     and transition["end"] == transition["start"]+16
                     and transition["action"] == (action if offset == 0 else 2)
                     and transition["schedule"] == row["schedule"]
                     and (offset == 0 or transition["before"] == trace[offset-1]["after"]),
                     "C reference tail policy, clock, or state chain differs")
            need(branch["terminal_state_sha256"] == trace[-1]["after"], "C terminal state differs from its trace")
            first = branch["trace"][0]
            need(first["before"] == row["parent_state_sha256"] and first["start"] == row["clock"]
                 and first["end"] == row["clock"] + 16 and first["action"] == action
                 and first["schedule"] == row["schedule"] and type(first["accepted"]) is bool
                 and first["clock_advances"] is True, "C first legal transition identity differs")
        for branch in branches:
            same = [other for other in branches if other["trace"][0]["after"] == branch["trace"][0]["after"]]
            need(all(other["terminal_state_sha256"] == branch["terminal_state_sha256"]
                     and other["terminal_values"] == branch["terminal_values"]
                     and other["terminal_output_sha256"] == branch["terminal_output_sha256"] for other in same),
                 "C equal first dynamics produced different baseline-tail outcomes")
        if not cal[index]:
            continue
        chosen, choice = choose(head, x[index], 2)
        item = metrics(choice, 2, y[index].tolist())
        need(chosen == item["chosen_action"], "C chooser returned another action")
        first, reference = branches[chosen]["trace"][0], branches[2]["trace"][0]
        result.append({"mode": mode, "seed": row["seed"], "schedule": row["schedule"],
            "prefix": row["prefix"], "clock": row["clock"], "parent_state_sha256": row["parent_state_sha256"],
            **item, "guard_accepted": first["accepted"],
            "same_parent_physical_dynamics_equal": first["after"] == reference["after"],
            "component_resolution_available": False, "controller_history_comparison_available": False})
    need(len(result) == 24, "C must retain all 24 calibration rows per architecture")
    return result


def analyze(context):
    gate = context["gate"]
    need(gate["status"] == "FULL_PRIMARY_PIPELINE_AND_LITERAL_RESTORE_VERIFIED"
         and gate["controller_jobs"] == 14 and gate["completion_seals"] == 30
         and gate["original_source_files_verified"] > 0 and context["store"].admitted,
         "Original full-study source/seal gate required")
    import numpy as np
    from operational.parameter_field_five_questions_20261031.finite_head_guard import guarded_choose
    from supplements.parameter_field_fullstudy_20261030.postseal_supplement import frozen_choose
    inputs, store = context["inputs"], context["store"]
    original_choose = frozen_choose(Path(context["plan"]["execution_context"]["source_root"]), inputs, np)
    def choose(head, feature, baseline):
        return guarded_choose(original_choose, head, feature, baseline)
    def jsonl(name):
        item = context["outputs"][name]
        with inputs.opened(item["path"], item["sha256"], item["bytes"], "p0_existing_supplement") as stream:
            return [strict_json(line) for line in stream]
    a = a_selected_successors(jsonl("GATED_CALIBRATION_ROWS.jsonl"), jsonl("SUCCESSOR_DIFFERENCES.jsonl"))
    c = []
    for mode in C_MODES:
        metadata = store.read_json(f"stage_C/heads/{mode}/HEAD.json")
        need(metadata["schema"] == "hepta.fullstudy.C.field-head.1" and metadata["complete"] is True
             and metadata["mode"] == mode and metadata["outcome_selected"] is False, "C head metadata differs")
        item = metadata["array_artifact"]
        name = "stage_C/" + item["path"]
        expected = store.descriptor(name, absolute=False)
        need(item["path"] == f"heads/{mode}/HEAD_AND_BANK.npz"
             and all(item[k] == expected[k] for k in ("sha256", "bytes")), "C head array is not sealed")
        with store.npz(name, np) as saved:
            need(set(saved.files) == {"features", "advantages", "fit", "calibration", "mean", "scale", "coefficients", "intercept"},
                 "C head array inventory differs")
            arrays = {k: saved[k].copy() for k in saved.files}
        head = {**metadata["head"], **{k: arrays[k] for k in ("mean", "scale", "coefficients", "intercept")}}
        source_rows = []
        need(len(metadata["row_artifacts"]) == 96, "C persisted row inventory differs")
        for row_item in metadata["row_artifacts"]:
            relative = "stage_C/" + row_item["path"]
            desc = store.descriptor(relative)
            need(all(row_item[k] == desc[k] for k in ("bytes", "sha256")), "C row is outside sealed manifest")
            with inputs.opened(desc["path"], desc["sha256"], desc["bytes"], "p0_C_sealed_row") as stream:
                with gzip.GzipFile(fileobj=stream) as decoded:
                    raw = decoded.read(16 * 1024**2 + 1)
                need(len(raw) <= 16 * 1024**2, "C row exceeds diagnostic byte bound")
                source_rows.append(strict_json(raw))
        c.extend(c_rows(mode, head, arrays, source_rows, choose, np))
    inputs.unchanged()
    return {"schema": SCHEMA, "status": "ORIGINAL_INTEGRITY_ISSUES" if context["issues"]["issue_count"] else "DESCRIPTIVE_COMPLETE",
            "A_selected_successors": a, "C_gated_calibration": {"rows": c, "summaries": [
                {"mode": m, **summarize([r for r in c if r["mode"] == m])} for m in C_MODES]},
            "original_full_source_seal_gate_reentered": True, "new_independent_samples": 0,
            "certificate": False, "new_training_scoring_refitting": False, "new_acceptance_threshold": False,
            "runtime_guard_deployment_claimed": False, "costs_in_original_outcomes_changed": False,
            "consumed_inputs": [{k: row[k] for k in ("path", "bytes", "sha256", "roles")}
                                for _, row in sorted(inputs.rows.items())],
            "cost_scope": "Postseal diagnostics only; successor norms and realized utility are not full-cost net benefit."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-complete")
    parser.add_argument("--expected-review-complete-sha256")
    args = parser.parse_args(argv)
    admitted, wall, cpu = False, time.monotonic(), time.process_time()
    if not args.review_complete or not args.expected_review_complete_sha256:
        print(json.dumps({"schema": SCHEMA, "status": "NOT_EVALUATED", "scientific_payloads_decoded": False,
                          "reason": "Actual completed original review and externally held SHA256 required."}))
        return 2
    try:
        from operational.parameter_field_five_questions_20261031.postseal_analysis_coverage import read_after_review_complete
        _, _, provenance, context = read_after_review_complete(args.review_complete, args.expected_review_complete_sha256)
        admitted = True
        result = analyze(context)
        result.update(inputs=provenance, diagnostic_wall_seconds=time.monotonic()-wall,
                      diagnostic_cpu_seconds=time.process_time()-cpu,
                      diagnostic_cost_is_not_additive_to_an_inclusive_wrapper=True)
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return 3 if result["status"] == "ORIGINAL_INTEGRITY_ISSUES" else 0
    except (ValueError, KeyError, TypeError, OSError, ImportError, OverflowError, FloatingPointError) as error:
        print(json.dumps({"schema": SCHEMA, "status": "INTEGRITY_FAILURE" if admitted else "NOT_EVALUATED",
                          "reason": str(error), "scientific_inputs_modified": False,
                          "diagnostic_wall_seconds": time.monotonic()-wall,
                          "diagnostic_cpu_seconds": time.process_time()-cpu,
                          "diagnostic_cost_is_not_additive_to_an_inclusive_wrapper": True}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
