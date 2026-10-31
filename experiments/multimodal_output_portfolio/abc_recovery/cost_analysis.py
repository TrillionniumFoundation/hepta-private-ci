"""Descriptive, prospectively specified matched resident quality/cost analysis.

Only completed supplementary_all timing is eligible. Canonical quality uses
round0; every round remains in measured costs. Prices are uncalibrated scenarios,
and random costs remain inside the exponential expectation. No grid winner is a
primary success criterion. See protocol-amendment-003.json.
"""

import time

ENTRY_WALL, ENTRY_CPU = time.perf_counter_ns(), time.process_time_ns()

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import platform
import resource
import subprocess
import sys
import traceback

import numpy as np

from ..v7.sources import digest, read_manifest
from .analysis import COMPONENTS, CONDITIONS, METRICS, PLANS, SEEDS, VIEWS, _comparisons
from .statistics import (_bootstrap_metadata, cost_summary, crossed_bootstrap,
                         loss_tails, paired_comparison, summarize_utility)
from .training_run import AREA, ROOT, file_sha, write_json


MODULE = "experiments.multimodal_output_portfolio.abc_recovery.cost_analysis"
CONDITIONS = tuple(c for c in CONDITIONS if not c[1].startswith("oracle_"))
PRICES = (0., 1e-5, 3e-5, 1e-4, 3e-4, 1e-3, 3e-3, 1e-2)


def _method():
    path = Path(__file__).with_name("protocol-amendment-003.json")
    record = json.loads(path.read_text())
    if (tuple(record["price_sensitivity"]["utility_units_per_wall_millisecond"]) != PRICES
            or record["quality"]["canonical_round"] != 0 or record["cost"]["retained_rounds"] != [0, 1]
            or record["bootstrap"]["replicates"] != 4000 or record["bootstrap"]["confidence"] != .95
            or record["base_protocol_sha256"] != file_sha(path.with_name("protocol.json"))
            or record["amendment001_sha256"] != file_sha(path.with_name("protocol-amendment-001.json"))
            or record["amendment002_sha256"] != file_sha(path.with_name("protocol-amendment-002.json"))):
        raise ValueError("Descriptive analysis amendment or its frozen dependencies changed")
    return record, file_sha(path)


def _timing_arrays(path, axes, pairs, weights):
    """Stream one complete timing census; leave unobserved metrics as NaN."""
    shape = tuple(len(axes[k]) for k in ("seeds", "cases", "views", "scenarios", "rounds"))
    indices = {k: {value: i for i, value in enumerate(axes[k])} for k in ("seeds", "cases", "views", "scenarios", "rounds")}
    quality = {observer: {c: {m: np.full(shape, np.nan) for m in METRICS} for c in axes["conditions"]} for observer in ("primary", "secondary")}
    costs = {c: {m: np.full(shape, np.nan) for m in ("wall_ms", "cpu_ms")} for c in axes["conditions"]}
    seen = {c: np.zeros(shape, dtype=bool) for c in axes["conditions"]}
    output = {c: np.full(shape, None, dtype=object) for c in axes["conditions"]}
    statuses = {c: Counter() for c in axes["conditions"]}
    with Path(path).open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            row = json.loads(line)
            try:
                condition = row["arm"], row["policy"]
                position = tuple(indices[key][row[column]] for key, column in zip(indices, ("seed", "case", "view", "scenario", "round")))
                if condition not in seen or any(type(row[k]) is not int for k in ("seed", "case", "scenario", "round")):
                    raise KeyError("condition/type")
                if tuple(row["source_ids"]) != pairs[row["case"]] or row["actual_stream_key"] != [row[k] for k in ("seed", "case", "view", "scenario")]:
                    raise KeyError("source or stream")
            except KeyError as error:
                raise ValueError(f"Out-of-census/unpaired timing row {number}") from error
            if seen[condition][position]:
                raise ValueError(f"Duplicate timing replay row {number}")
            status, generation_failed = row["status"], row["status"] == "generation_failed"
            if (status not in {"completed", "generation_failed", "offline_scoring_failed"} or set(row["observer_scores"]) != {"primary", "secondary"}
                    or type(row["required_output_complete"]) is not bool or (generation_failed and row["required_output_complete"])):
                raise ValueError("Unknown execution/scoring status")
            statuses[condition][status] += 1
            for kind in ("wall", "cpu"):
                value = row[kind + "_ns"]
                if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError("Actual observed costs must remain finite and nonnegative")
                costs[condition][kind + "_ms"][position] = value / 1e6
            if not generation_failed:
                path_tuple = tuple(row["path"])
                if path_tuple not in PLANS or not isinstance(row["raw"], list) or len(row["raw"]) != 1:
                    raise ValueError("Successful generation must retain its bounded path and original media")
                fixed = {"fixed": ("refine_image", "refine_text"), "encoder_initial_only_fixed": ("refine_image", "refine_text"),
                         "semantic_couple_fixed": ("refine_semantic", "couple"), "shared_state_clamp_semantic_couple": ("refine_semantic", "couple")}
                if ((row["policy"] in fixed and path_tuple != fixed[row["policy"]])
                        or (row["policy"] == "allocation_only_feedback" and any(a not in {"refine_image", "refine_text"} for a in path_tuple))):
                    raise ValueError("The actual path violates the registered policy profile")
                output[condition][position] = (row["raw"][0]["image_sha256"], row["raw"][0]["text_sha256"], path_tuple)
            for observer in quality:
                q, score = quality[observer][condition], row["observer_scores"][observer]
                q["required_output_complete"][position] = float(row["required_output_complete"])
                if score is None:
                    if status != "offline_scoring_failed":
                        raise ValueError("Missing score without an actual recorded scoring exception")
                    continue
                if generation_failed:
                    if (row["score_origin"] != "registered_generation_failure_penalty"
                            or any(score[k] != v for k, v in (("utility", -1.), ("joint_loss", 1.), ("joint_fact_correct", False), ("required_output_complete", False)))):
                        raise ValueError("Generation failure must retain its explicitly assigned penalty")
                    for metric in ("utility", "joint_loss", "joint_fact_correct"):
                        q[metric][position] = score[metric]
                    continue  # Unknown continuation path is never imputed as zero cost.
                for metric in ("utility", "joint_loss", "joint_fact_correct", *COMPONENTS):
                    if not isinstance(score[metric], (int, float)) or not math.isfinite(score[metric]):
                        raise ValueError("Observed quality metrics must be finite")
                    q[metric][position] = score[metric]
                if (any(not 0 <= score[k] <= 1 for k in (*COMPONENTS, "joint_loss"))
                        or score["joint_fact_correct"] not in (0, 1)
                        or bool(score["joint_fact_correct"]) != bool(score["caption_valid"] and all(score[k] == 0 for k in COMPONENTS[:4]))
                        or score["required_output_complete"] != row["required_output_complete"]
                        or abs(score["joint_loss"] - sum(weights[k] * score[k] for k in COMPONENTS)) > 2e-6
                        or abs(score["utility"] - (1 - 2 * score["joint_loss"])) > 2e-6):
                    raise ValueError("Actual observer metric or physical completion identity failed")
                q["net_utility"][position] = score["utility"] - .002 * len(path_tuple)
            seen[condition][position] = True
    if any(not mask.all() for mask in seen.values()):
        raise ValueError("Incomplete balanced resident timing census")
    eligible, replay = {}, {}
    for c in axes["conditions"]:
        paired = all(a is not None and a == b for a, b in zip(output[c][..., 0].ravel(), output[c][..., 1].ravel()))
        replay[c] = {"output_and_path_replay_complete": paired, "all_round_statuses": dict(statuses[c])}
        for observer in quality:
            scores = quality[observer][c]
            agree = all(np.isfinite(v).all() and np.allclose(v[..., 0], v[..., 1], atol=2e-6, rtol=0) for v in scores.values())
            eligible[(observer, c)] = paired and agree and not statuses[c]["generation_failed"]
    return quality, costs, eligible, replay


def _quality_summary(values):
    canonical = {k: a[..., 0] for k, a in values.items()}
    return {"canonical_round": 0, "missing_counts": {k: int((~np.isfinite(a)).sum()) for k, a in canonical.items()},
        "raw_utility": summarize_utility(canonical["utility"]) if np.isfinite(canonical["utility"]).all() else None,
        "proxy_net_utility": summarize_utility(canonical["net_utility"]) if np.isfinite(canonical["net_utility"]).all() else None,
        "means": {k: float(a.mean()) if np.isfinite(a).all() else None for k, a in canonical.items()},
        "joint_loss_tails": loss_tails(canonical["joint_loss"]) if np.isfinite(canonical["joint_loss"]).all() else None}


def price_curve(candidate_utility, reference_utility, candidate_wall, reference_wall, bootstrap, prices=PRICES):
    """Raw canonical utilities [S,N,V,K], paired costs [S,N,V,K,round]."""
    a, b, ta, tb = [np.asarray(x, dtype=np.float64) for x in (candidate_utility, reference_utility, candidate_wall, reference_wall)]
    if a.ndim != 4 or a.shape != b.shape or ta.shape != tb.shape or ta.shape != (*a.shape, 2) or any(not np.isfinite(x).all() for x in (a, b, ta, tb)) or (ta < 0).any() or (tb < 0).any():
        raise ValueError("Priced risk requires a complete aligned utility/cost census with two timing rounds")
    curve = []
    for price in prices:
        if not math.isfinite(price) or price < 0:
            raise ValueError("Price scenarios must be finite and nonnegative")
        first = (a[..., None] - price * ta).reshape(*a.shape[:3], -1)
        second = (b[..., None] - price * tb).reshape(*b.shape[:3], -1)
        comparison = paired_comparison(first, second, bootstrap=bootstrap)
        comparison["within_source_axis_note"] = "last axis is generation_scenario x timing_round, not additional independent generations"
        curve.append({"utility_units_per_wall_ms": price, "priced_ce_gain": comparison})
    crossings = [[x["utility_units_per_wall_ms"], y["utility_units_per_wall_ms"]] for x, y in zip(curve, curve[1:])
                 if x["priced_ce_gain"]["gain"] * y["priced_ce_gain"]["gain"] < 0]
    return {"curve": curve, "strict_grid_sign_change_brackets": crossings, "unique_break_even_threshold_claim": False,
            "external_price_calibration": False, "proxy_action_cost_also_subtracted": False, "grid_winner_is_primary_success": False}


def _reports(quality, costs, eligible, replay, axes):
    plan = crossed_bootstrap(len(axes["seeds"]), len(axes["cases"]), replicates=4000)
    reports = {"conditions": {}, "comparisons": {}, "bootstrap": _bootstrap_metadata(plan)}
    for c in axes["conditions"]:
        reports["conditions"]["/".join(c)] = {"cost_all_rounds": {k: cost_summary(v, unit="ms", bootstrap=plan) for k, v in costs[c].items()},
            "quality_round0": {o: _quality_summary(quality[o][c]) for o in quality}, "replay": replay[c],
            "priced_curve_eligible": {o: eligible[(o, c)] for o in quality}}
    for name, candidate, reference, _ in _comparisons():
        if candidate not in costs or reference not in costs:
            continue
        result = {"candidate": candidate, "reference": reference, "scope": "descriptive matched eight-source cohort only",
                  "cost_increase": {k: cost_summary(v, reference=costs[reference][k], unit="ms", bootstrap=plan) for k, v in costs[candidate].items()}, "observers": {}}
        for observer in quality:
            a, b = quality[observer][candidate], quality[observer][reference]
            metric_results = {}
            for metric, estimand in (("utility", "joint_ce"), ("net_utility", "joint_ce"), ("joint_loss", "loss_reduction"), ("joint_fact_correct", "success_rate"), ("required_output_complete", "success_rate")):
                first, second = a[metric][..., 0], b[metric][..., 0]
                metric_results[metric] = paired_comparison(first, second, estimand=estimand, bootstrap=plan) if np.isfinite(first).all() and np.isfinite(second).all() else None
            allowed = eligible[(observer, candidate)] and eligible[(observer, reference)]
            result["observers"][observer] = {"quality_gains_round0": metric_results,
                "price_sensitivity": price_curve(a["utility"][..., 0], b["utility"][..., 0], costs[candidate]["wall_ms"], costs[reference]["wall_ms"], plan) if allowed else None,
                "price_unavailable_reason": None if allowed else "generation failure, missing metric, or nonidentical/incomplete output/score replay; no rows were dropped"}
        reports["comparisons"][name] = result
    return reports


def _pins():
    return {name: file_sha(AREA / name) for name in ("abc_recovery/cost_analysis.py", "abc_recovery/analysis.py", "abc_recovery/statistics.py", "abc_recovery/training_run.py", "v6/observer.py", "v7/sources.py")}


def freeze(args):
    method, amendment_sha = _method()
    protocol, manifest = json.loads(args.protocol.read_text()), read_manifest(args.manifest)
    result = json.loads((args.timing / "result.json").read_text())
    summary = json.loads((args.timing / "benchmark/summary.json").read_text())
    producer = json.loads((args.timing / "benchmark/registration.json").read_text())
    if (result["status"] != "completed" or summary["view_profile"] != "supplementary_all" or summary["rows"] != 23040
            or not summary["complete_census"] or tuple(summary["timing_views"]) != VIEWS
            or file_sha(args.protocol) != method["base_protocol_sha256"] or file_sha(args.manifest) != protocol["source_manifest_file_sha256"]
            or producer["protocol_sha256"] != digest(protocol) or producer["source_identity"]["manifest_record_sha256"] != digest(manifest)
            or file_sha(args.timing / "benchmark/summary.json") != result["benchmark_summary_sha256"]):
        raise ValueError("Completed supplementary timing, protocol, source or producer summary mismatch")
    paths = {"rows": args.timing / "benchmark/rows.jsonl", "timing_summary": args.timing / "benchmark/summary.json",
             "timing_registration": args.timing / "benchmark/registration.json", "timing_result": args.timing / "result.json",
             "protocol": args.protocol, "manifest": args.manifest}
    hashes = {k: file_sha(p) for k, p in paths.items()}
    if hashes["rows"] != summary["rows_sha256"] or hashes["timing_registration"] != summary["registration_sha256"]:
        raise ValueError("The actual timing census or its registration changed")
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "registration.json", {"schema": "hepta.abc.descriptive-cost-analysis.v1", "registered_unix_ns": time.time_ns(),
        "method_amendment_sha256": amendment_sha, "paths": {k: str(p.resolve()) for k, p in paths.items()}, "input_sha256": hashes,
        "source_sha256": _pins(), "output": str(args.output.resolve()), "conditions": CONDITIONS, "main_primary_endpoints_changed": False})
    return args.output / "registration.json"


def execute(registration_path):
    registration = json.loads(Path(registration_path).read_text())
    paths, outdir = {k: Path(p) for k, p in registration["paths"].items()}, Path(registration["output"])
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        if _pins() != registration["source_sha256"] or _method()[1] != registration["method_amendment_sha256"] or any(file_sha(paths[k]) != v for k, v in registration["input_sha256"].items()):
            raise ValueError("Frozen descriptive analysis inputs changed")
        from ..v6.observer import METRIC
        manifest = read_manifest(paths["manifest"])
        axes = {"seeds": SEEDS, "cases": tuple(range(608, 616)), "views": VIEWS, "scenarios": (0, 1), "rounds": (0, 1), "conditions": CONDITIONS}
        ids = manifest["roles"]["development"]["source_ids"]
        pairs = {c: tuple(ids[2 * c:2 * c + 2]) for c in axes["cases"]}
        if len(set(x for pair in pairs.values() for x in pair)) != 16:
            raise ValueError("Timing cohort does not have eight disjoint source pairs")
        data = _timing_arrays(paths["rows"], axes, pairs, METRIC["weights"])
        report = _reports(*data, axes)
        if _pins() != registration["source_sha256"] or _method()[1] != registration["method_amendment_sha256"] or any(file_sha(paths[k]) != v for k, v in registration["input_sha256"].items()):
            raise RuntimeError("Cost analysis inputs changed while aggregating")
        summary = json.loads(paths["timing_summary"].read_text())
        report.update({"schema": "hepta.abc.matched-cohort-quality-cost.v1", "method_amendment_sha256": registration["method_amendment_sha256"],
            "input_sha256": registration["input_sha256"], "source_sha256": registration["source_sha256"],
            "census": {"source_pairs": 8, "training_seeds": 5, "views": 8, "generation_scenarios": 2, "timing_rounds": 2, "timing_rows": 23040, "canonical_quality_rows": 11520, "additional_independent_sources": 0},
            "producer_evaluation_integrity_gate": summary["evaluation_integrity_gate"], "all_prices_descriptive_and_uncalibrated": True,
            "main128_source_quality_CIs_are_separate": True, "prior_three_view_timings_not_pooled": True,
            "primary_success_inferred_from_grid": False, "production_approved": False, "all_blockers_closed": False,
            "environment": {"python": sys.version, "numpy": np.__version__, "platform": platform.platform()},
            "analysis_wall_ns_before_report_write": time.perf_counter_ns() - wall, "analysis_cpu_ns_before_report_write": time.process_time_ns() - cpu})
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
    for name in ("timing", "protocol", "manifest", "output"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if args.child:
        execute(args.child)
        return
    if any(getattr(args, k) is None for k in ("timing", "protocol", "manifest", "output")):
        parser.error("--timing --protocol --manifest --output are required")
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
        "child_peak_rss_bytes": after.ru_maxrss * 1024, "scope": "parent module entry through child exit, including streaming, all paired bootstraps, price grid, validation and final reports; excludes this receipt write"})
    raise SystemExit(code)


if __name__ == "__main__":
    main()
