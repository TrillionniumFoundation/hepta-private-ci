"""Audit and aggregate the full development census, without refitting policies.

Each observer gets one streaming JSON pass. Risk is evaluated within a trained
seed, then averaged across seeds. Views, scenarios, policies and observer
re-evaluations never become independent source units. Run separately from
resident timing. All intervals have the finite-seed limitations in statistics.py.
"""

import time

ENTRY_WALL, ENTRY_CPU = time.perf_counter_ns(), time.process_time_ns()

import argparse
import gzip
import itertools
import json
import math
from pathlib import Path
import platform
import resource
import subprocess
import sys
import traceback

import numpy as np

from ..v7.sources import read_manifest
from .statistics import (_bootstrap_metadata, _ce, _cube, _plan, crossed_bootstrap,
                         loss_tails, paired_comparison, rows_to_cube, summarize_utility)
from .training_run import AREA, ROOT, file_sha, write_json


MODULE = "experiments.multimodal_output_portfolio.abc_recovery.analysis"
SEEDS = (17, 29, 43, 59, 71)
ARMS = ("sft_continuation", "output_mean", "output_ndu")
VIEWS = ("clean", "noise", "occlusion", "missing_trusted", "conflict_untrusted", "missing_untrusted", "missing_unknown", "both_missing")
CORE = ("fixed", "tuned_static", "feedback", "oracle_primary", "oracle_primary_allocation")
EXTRA = ("risk_neutral_feedback", "allocation_only_feedback", "draft_masked_feedback", "modality_local_feedback", "one_shot_route", "semantic_couple_fixed", "independent_random_stream_MPC", "shared_state_clamp_semantic_couple", "encoder_initial_only_fixed")
CONDITIONS = tuple((arm, policy) for arm in ARMS for policy in (CORE + EXTRA if arm == "output_ndu" else CORE))
COMPONENTS = ("text_fact", "relation", "image_fact", "crossmodal_disagreement", "pixel_mse")
METRICS = ("utility", "net_utility", "joint_loss", "joint_fact_correct", "required_output_complete", *COMPONENTS)
ACTIONS = ("refine_semantic", "refine_image", "refine_text", "couple")
PLANS = ((),) + tuple((a,) for a in ACTIONS) + tuple(itertools.product(ACTIONS, repeat=2))
PRIMARY = ("risk_training_under_fixed", "feedback_under_output_ndu")


def _census(protocol, manifest):
    if (tuple(protocol["training_seeds"]) != SEEDS or tuple(protocol["views"]) != VIEWS
            or tuple(protocol["training"]["arms"]) != ARMS or protocol["evaluation_generation_scenarios"] != 4
            or protocol["roles"]["evaluation"] != {"role": "development", "pair_start": 608, "pair_count": 128}
            or protocol["utility"]["risk_aversion"] != 2. or protocol["utility"]["continuation_action_penalty"] != .002
            or protocol["statistics"]["bootstrap_replicates"] != 4000):
        raise ValueError("Analysis requires the unchanged registered census and risk profile")
    cases = tuple(range(608, 736))
    ids = manifest["roles"]["development"]["source_ids"]
    pairs = {case: tuple(ids[2 * case:2 * case + 2]) for case in cases}
    if any(len(pair) != 2 for pair in pairs.values()) or len(set(itertools.chain.from_iterable(pairs.values()))) != 256:
        raise ValueError("The development cohort must contain 128 disjoint complete source pairs")
    return {"seeds": SEEDS, "cases": cases, "views": VIEWS, "scenarios": tuple(range(4)), "conditions": CONDITIONS, "metrics": METRICS}, pairs


def _observer_rows(path, observer, pairs, weights, views, scenarios):
    """Validate original identity/path/score relationships before yielding a row."""
    cases = {case: index for index, case in enumerate(pairs)}
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            row = json.loads(line)
            if (any(type(row[k]) is not int for k in ("seed", "case", "scenario", "continuation_actions", "tree_row_index"))
                    or row["case"] not in pairs or tuple(row["source_ids"]) != pairs[row["case"]]
                    or row["view"] not in views or row["scenario"] not in scenarios):
                raise ValueError(f"Unpaired source/census identity at line {line_number}")
            expected_index = (views.index(row["view"]) * len(pairs) + cases[row["case"]]) * len(scenarios) + scenarios.index(row["scenario"])
            path_tuple = tuple(row["path"])
            oracle = row["policy"].startswith("oracle_")
            if (row["tree_row_index"] != expected_index or path_tuple not in PLANS
                    or row["continuation_actions"] != len(path_tuple)
                    or row["selection_is_privileged_offline_oracle"] is not oracle
                    or ("plan_index" in row and row["plan_index"] != PLANS.index(path_tuple))):
                raise ValueError(f"Invalid path/oracle provenance at line {line_number}")
            fixed = {"fixed": ACTIONS[1:3], "encoder_initial_only_fixed": ACTIONS[1:3],
                     "semantic_couple_fixed": (ACTIONS[0], ACTIONS[3]), "shared_state_clamp_semantic_couple": (ACTIONS[0], ACTIONS[3])}
            if ((row["policy"] in fixed and path_tuple != fixed[row["policy"]])
                    or (row["policy"] in {"allocation_only_feedback", "oracle_primary_allocation"} and any(a not in ACTIONS[1:3] for a in path_tuple))
                    or set(row["observers"]) != {"primary", "secondary"}):
                raise ValueError(f"Policy or dual-observer contract changed at line {line_number}")
            score = row["observers"][observer]
            if not isinstance(score, dict) or set(score) != set(METRICS) or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in score.values()):
                raise ValueError(f"Unobserved/non-finite/unregistered metrics at line {line_number}")
            loss = sum(weights[k] * score[k] for k in COMPONENTS)
            correct = all(score[k] == 0 for k in COMPONENTS[:4])
            if (any(not 0 <= score[k] <= 1 for k in (*COMPONENTS, "joint_loss"))
                    or score["joint_fact_correct"] not in (0, 1) or score["required_output_complete"] not in (0, 1)
                    or bool(score["joint_fact_correct"]) != correct or abs(score["joint_loss"] - loss) > 2e-6
                    or abs(score["utility"] - (1 - 2 * score["joint_loss"])) > 2e-6
                    or abs(score["net_utility"] - (score["utility"] - .002 * len(path_tuple))) > 2e-6):
                raise ValueError(f"Metric, success, or action-penalty identity failed at line {line_number}")
            yield {**{key: row[key] for key in ("seed", "arm", "policy", "case", "view", "scenario")}, **score}


def ce_interaction(ndu_feedback, ndu_fixed, sft_feedback, sft_fixed, *, gamma=2., confidence=.95, bootstrap=None, batch_size=256):
    """Difference of four cell CEs, never CE of an output-wise difference."""
    cubes = [_cube(c) for c in (ndu_feedback, ndu_fixed, sft_feedback, sft_fixed)]
    if any(c.shape != cubes[0].shape for c in cubes):
        raise ValueError("All interaction cells must share the paired census")
    plan = _plan(cubes[0].shape, bootstrap, 4000, 20261024, confidence, batch_size)
    source = [_ce(c.reshape(*c.shape[:2], -1), gamma) for c in cubes]
    coefficients = (1., -1., -1., 1.)
    per_seed = sum(k * _ce(a, gamma) for k, a in zip(coefficients, source))
    draws = np.empty(len(plan.seed_indices))
    for start in range(0, len(draws), batch_size):
        si, ci = plan.seed_indices[start:start + batch_size, :, None], plan.source_indices[start:start + batch_size, None, :]
        values = sum(k * _ce(a[si, ci], gamma).mean(-1) for k, a in zip(coefficients, source))
        draws[start:start + len(values)] = values
    alpha = (1 - confidence) / 2
    return {"estimand": "[CE(NDU,feedback)-CE(NDU,fixed)]-[CE(SFT,feedback)-CE(SFT,fixed)]",
            "gain": float(per_seed.mean()), "per_seed_gain": per_seed.tolist(), "confidence": confidence,
            "interval": np.quantile(draws, (alpha, 1 - alpha), method="linear").tolist(),
            "positive_means": "feedback CE increment is greater under NDU than under SFT; does not imply either increment is positive",
            "bootstrap": _bootstrap_metadata(plan), "scope": "descriptive four-cell contrast"}


def _condition_summary(metrics, views):
    def summarize(values):
        return {"raw_utility": summarize_utility(values["utility"]), "net_utility": summarize_utility(values["net_utility"]),
                "mean_joint_loss": float(values["joint_loss"].mean()), "task_success_rate": float(values["joint_fact_correct"].mean()),
                "required_output_complete_rate": float(values["required_output_complete"].mean()),
                "component_means": {key: float(values[key].mean()) for key in COMPONENTS}}
    result = summarize(metrics)
    result["joint_loss_tails"] = loss_tails(metrics["joint_loss"])
    result["per_view"] = {view: summarize({key: values[:, :, i:i + 1, :] for key, values in metrics.items()}) for i, view in enumerate(views)}
    return result


def _comparisons():
    n, s, m = "output_ndu", "sft_continuation", "output_mean"
    result = [(PRIMARY[0], (n, "fixed"), (m, "fixed"), "primary"),
              (PRIMARY[1], (n, "feedback"), (n, "fixed"), "primary"),
              ("NDU_vs_SFT_fixed", (n, "fixed"), (s, "fixed"), "descriptive"),
              ("feedback_under_SFT", (s, "feedback"), (s, "fixed"), "descriptive"),
              ("feedback_under_mean_training", (m, "feedback"), (m, "fixed"), "descriptive"),
              ("NDU_vs_SFT_feedback", (n, "feedback"), (s, "feedback"), "descriptive")]
    for policy in ("tuned_static", "one_shot_route", "risk_neutral_feedback", "allocation_only_feedback", "draft_masked_feedback", "modality_local_feedback", "independent_random_stream_MPC"):
        result.append(("feedback_vs_" + policy, (n, "feedback"), (n, policy), "descriptive"))
    result.extend((("shared_state_fixed_path", (n, "semantic_couple_fixed"), (n, "shared_state_clamp_semantic_couple"), "fixed_mechanism"),
                   ("persistent_vs_initial_only", (n, "fixed"), (n, "encoder_initial_only_fixed"), "fixed_mechanism")))
    for arm in ARMS:
        for policy in ("fixed", "feedback", "oracle_primary_allocation"):
            result.append((arm + "_oracle_vs_" + policy, (arm, "oracle_primary"), (arm, policy), "offline_oracle_diagnostic"))
    return result


def _observer_report(cubes, views, observer, bootstrap):
    results = {"conditions": {"/".join(c): _condition_summary(values, views) for c, values in cubes.items()}, "comparisons": {}}
    if observer == "primary":
        gaps = {arm: min(float(np.min(cubes[(arm, "oracle_primary")]["net_utility"] - values["net_utility"]))
                for (other_arm, policy), values in cubes.items() if other_arm == arm and policy not in
                {"oracle_primary", "shared_state_clamp_semantic_couple", "encoder_initial_only_fixed"}) for arm in ARMS}
        if min(gaps.values()) < -2e-6:
            raise ValueError("Primary hindsight oracle fails native-path net-utility dominance")
        results["oracle_pointwise_check"] = {"minimum_net_utility_gaps": gaps, "tolerance": 2e-6, "causal_attainability_claim": False}
    else:
        results["oracle_pointwise_check"] = {"secondary_upper_bound_claim": False}
    for name, candidate, reference, kind in _comparisons():
        confidence = .975 if observer == "primary" and kind == "primary" else .95
        a, b = cubes[candidate], cubes[reference]
        results["comparisons"][name] = {"candidate": candidate, "reference": reference, "kind": kind,
            "net_ce": paired_comparison(a["net_utility"], b["net_utility"], confidence=confidence, bootstrap=bootstrap),
            "raw_ce": paired_comparison(a["utility"], b["utility"], bootstrap=bootstrap),
            "mean_conditional_net_ce": paired_comparison(a["net_utility"], b["net_utility"], estimand="mean_conditional_ce", bootstrap=bootstrap),
            "loss_reduction": paired_comparison(a["joint_loss"], b["joint_loss"], estimand="loss_reduction", bootstrap=bootstrap),
            "task_success_gain": paired_comparison(a["joint_fact_correct"], b["joint_fact_correct"], estimand="success_rate", bootstrap=bootstrap),
            "completion_gain": paired_comparison(a["required_output_complete"], b["required_output_complete"], estimand="success_rate", bootstrap=bootstrap),
            "oracle_interpretation": None if kind != "offline_oracle_diagnostic" else (
                "hindsight bound only for primary net utility and its monotone functionals within the native 21-plan family; other metrics are re-evaluations; not causal attainability or a bound for intervention dynamics"
                if observer == "primary" else "secondary re-evaluation of primary-selected hindsight paths; not a secondary upper bound")}
    results["net_ce_2x2_interaction"] = ce_interaction(*(cubes[(arm, policy)]["net_utility"] for arm, policy in
        (("output_ndu", "feedback"), ("output_ndu", "fixed"), ("sft_continuation", "feedback"), ("sft_continuation", "fixed"))), bootstrap=bootstrap)
    return results


def _support_flags(reports):
    primary = {name: reports["primary"]["comparisons"][name]["net_ce"] for name in PRIMARY}
    secondary = {name: reports["secondary"]["comparisons"][name]["net_ce"] for name in PRIMARY}
    return {"nominal_support_for_both_registered_primary_comparisons": all(value["interval"][0] > 0 for value in primary.values()),
            "primary_checks": {name: {"gain": value["gain"], "interval": value["interval"], "confidence": value["confidence"], "lower_bound_positive": value["interval"][0] > 0} for name, value in primary.items()},
            "secondary_descriptive_checks": {name: {"gain": value["gain"], "interval": value["interval"], "confidence": value["confidence"], "direction_positive": value["gain"] > 0, "lower_bound_positive": value["interval"][0] > 0} for name, value in secondary.items()},
            "confirmatory_coverage_guaranteed": False, "global_or_causal_optimality_proved": False,
            "actual_cost_gate_assessed_here": False, "production_approved": False, "all_blockers_closed": False}


def _pins():
    return {name: file_sha(AREA / name) for name in ("abc_recovery/analysis.py", "abc_recovery/statistics.py", "abc_recovery/training_run.py", "v6/observer.py", "v7/sources.py")}


def freeze(args):
    protocol, manifest = json.loads(args.protocol.read_text()), read_manifest(args.manifest)
    _census(protocol, manifest)
    result = json.loads((args.control / "result.json").read_text())
    control_registration = json.loads((args.control / "registration.json").read_text())
    evaluated = {(r["seed"], r["arm"]): r for r in result["evaluated"]}
    if (result["status"] != "completed" or len(result["evaluated"]) != 15 or set(evaluated) != set(itertools.product(SEEDS, ARMS))
            or sum(r["policy_replay_rows"] for r in evaluated.values()) != 491520
            or any(r["source_pairs"] != 128 for r in evaluated.values())
            or file_sha(args.protocol) != control_registration["protocol_sha256"]
            or file_sha(args.manifest) != control_registration["manifest_sha256"]
            or file_sha(args.manifest) != protocol["source_manifest_file_sha256"]):
        raise ValueError("Control completion, protocol, manifest, or exact 491520-row census mismatch")
    paths = {"rows": args.control / "evaluation-rows.jsonl.gz", "control_result": args.control / "result.json",
             "control_registration": args.control / "registration.json", "protocol": args.protocol, "manifest": args.manifest}
    hashes = {name: file_sha(path) for name, path in paths.items()}
    if hashes["rows"] != result["evaluation_rows_file_sha256"]:
        raise ValueError("Completed control outcome bytes changed")
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "registration.json", {"schema": "hepta.abc.analysis-registration.v1", "registered_unix_ns": time.time_ns(),
        "paths": {name: str(path.resolve()) for name, path in paths.items()}, "input_sha256": hashes,
        "source_sha256": _pins(), "output": str(args.output.resolve()), "conditions": CONDITIONS,
        "rows": 491520, "source_pairs": 128, "training_seeds": 5, "observer_passes": 2,
        "bootstrap_replicates": 4000, "primary_endpoint": "net_utility joint CE", "primary_comparisons": PRIMARY})
    return args.output / "registration.json"


def execute(registration_path):
    registration = json.loads(Path(registration_path).read_text())
    outdir, paths = Path(registration["output"]), {k: Path(v) for k, v in registration["paths"].items()}
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        if _pins() != registration["source_sha256"] or any(file_sha(paths[k]) != v for k, v in registration["input_sha256"].items()):
            raise ValueError("Frozen analysis input/code identity changed")
        from ..v6.observer import METRIC, METRIC_DIGEST
        import torch
        protocol, manifest = json.loads(paths["protocol"].read_text()), read_manifest(paths["manifest"])
        axes, pairs = _census(protocol, manifest)
        bootstrap = crossed_bootstrap(len(SEEDS), len(pairs), replicates=4000)
        reports = {}
        for observer in ("primary", "secondary"):
            print(json.dumps({"phase": "observer_analysis", "observer": observer}), flush=True)
            cubes = rows_to_cube(_observer_rows(paths["rows"], observer, pairs, METRIC["weights"], axes["views"], axes["scenarios"]), **axes)
            reports[observer] = _observer_report(cubes, axes["views"], observer, bootstrap)
            del cubes
        if _pins() != registration["source_sha256"] or any(file_sha(paths[k]) != v for k, v in registration["input_sha256"].items()):
            raise RuntimeError("Analysis inputs changed while aggregating")
        report = {"schema": "hepta.abc.development-analysis.v1", "observers": reports, "scientific_support_flags": _support_flags(reports),
            "census": {"conditions": 24, "rows_per_condition": 20480, "policy_replay_rows": 491520, "source_pairs": 128, "training_seeds": 5, "views": 8, "generation_scenarios": 4,
                       "independent_n_is_not_rows_or_seed_times_sources": True, "observer_re_evaluation_adds_no_sources": True},
            "bootstrap": _bootstrap_metadata(bootstrap), "input_sha256": registration["input_sha256"], "source_sha256": registration["source_sha256"],
            "metric_sha256": METRIC_DIGEST, "environment": {"python": sys.version, "numpy": np.__version__, "torch": str(torch.__version__), "platform": platform.platform()},
            "risk_scope": "joint task/view/scenario CE within trained seed then mean; conditional CE only over generation within source/view; four-scenario plug-in, not unbiased population conditional CE",
            "training_objective_scope": "joint exponential moment plus declared supervised auxiliary; not pure CE or the same-lambda CE-regularized objective",
            "oracle_scope": "primary-net-utility native finite hindsight diagnostic only; headroom need not be causally reachable; raw utility, other metrics and secondary are re-scoring, not asserted upper bounds",
            "cost_scope": "main128-source quality only; actual timing requires a separate matched cohort analysis",
            "elapsed_analysis_wall_ns": time.perf_counter_ns() - wall, "elapsed_analysis_cpu_ns": time.process_time_ns() - cpu}
        write_json(outdir / "report.json", report)
        write_json(outdir / "result.json", {"status": "completed", "report_sha256": file_sha(outdir / "report.json"),
            "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu, "all_blockers_closed": False})
    except BaseException as error:
        write_json(outdir / "failure.json", {"status": "failed", "error": repr(error), "traceback": traceback.format_exc(),
                   "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", type=Path)
    for name in ("control", "protocol", "manifest", "output"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if args.child:
        execute(args.child)
        return
    if any(getattr(args, k) is None for k in ("control", "protocol", "manifest", "output")):
        parser.error("--control --protocol --manifest --output are required")
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    registration = freeze(args)
    with (args.output / "process.log").open("x") as log:
        child = subprocess.Popen([sys.executable, "-B", "-m", MODULE, "--child", str(registration)], cwd=ROOT,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in child.stdout:
            log.write(line)
            log.flush()
            print(line, end="", flush=True)
        code = child.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    write_json(args.output / "whole-process-cost.json", {"exit_code": code, "wall_ns": time.perf_counter_ns() - ENTRY_WALL,
        "parent_cpu_ns": time.process_time_ns() - ENTRY_CPU, "child_cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
        "child_peak_rss_bytes": after.ru_maxrss * 1024, "scope": "parent module entry through child exit; includes child startup/imports, both stream passes, validation, bootstrap, hashes and final reports; excludes this last receipt write"})
    raise SystemExit(code)


if __name__ == "__main__":
    main()
