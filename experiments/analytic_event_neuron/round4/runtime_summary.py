"""Frozen paired utility gates; representation, latency and byte results apart."""

import gzip
import json
import math
from pathlib import Path

import numpy as np

from ..statistics import paired_interval
from .runtime_evidence import write_json
from .runtime_law import Q24, cdf, event_logs
from .runtime_learning import ARMS, SEEDS
from .runtime_owner import file_sha
from .runtime_study import REGISTRATION


def summarize(run_dir):
    from .freeze import verify
    root = Path(run_dir)
    frozen = verify(root)
    arrays, all_rows, scopes = {arm: [] for arm in ARMS}, {arm: [] for arm in ARMS}, []
    for seed in SEEDS:
        output = root / "runtime_confirmation" / f"seed_{seed}"
        summary, audit = [json.loads((output / name).read_text()) for name in ("SUMMARY.json", "AUDIT.json")]
        if (not audit["passed"] or summary["independent_trajectories"] != REGISTRATION["confirmation_rows"]
                or file_sha(output / "ROWS.json.gz") != summary["rows_sha256"]
                or summary["model_file_sha256"] != frozen["artifacts_sha256"][f"runtime_prepared/seed_{seed}/MODELS.json"]):
            raise ValueError("Incomplete or unbound runtime confirmation scope")
        with gzip.open(output / "ROWS.json.gz", "rt") as stream:
            rows = json.load(stream)
        expected_ids = {f"feedback4:confirmation:{seed}:{i}" for i in range(REGISTRATION["confirmation_rows"])}
        for arm in ARMS:
            selected = sorted((r for r in rows if r["arm"] == arm), key=lambda r: r["case"])
            if len(selected) != len(expected_ids) or {r["case"] for r in selected} != expected_ids:
                raise ValueError("Unpaired or duplicate runtime control rows")
            arrays[arm].append(np.asarray([r["utility"] for r in selected]))
            all_rows[arm].extend(selected)
        scopes.append({"seed": seed, "execution": summary, "audit": audit,
                       "qualification": json.loads((root / "runtime_qualification" / f"seed_{seed}" / "QUALIFICATION.json").read_text()),
                       "training": json.loads((root / "runtime_prepared" / f"seed_{seed}" / "TRAINING_RECEIPT.json").read_text())})
    comparisons = REGISTRATION["primary_noninferiority"] + REGISTRATION["secondary"]
    contrasts, mechanism, costs = {}, {}, {}
    for index, (candidate, baseline) in enumerate(comparisons):
        delta = np.asarray(arrays[candidate]) - arrays[baseline]
        primary = index < 2
        contrast = paired_interval(delta, REGISTRATION["bootstrap_replicates"], REGISTRATION["bootstrap_seed"] + index,
                                   .025 if primary else .05)
        contrast.update(primary_noninferiority=primary, noninferiority_margin=.01,
                        passes_noninferiority=bool(contrast["interval"][0] > -.01 and np.all(delta.mean(1) > -.01)),
                        superiority_claimed=False, empirical_interval_not_population_guarantee=True)
        key = candidate + "_vs_" + baseline
        contrasts[key] = contrast
        left, right = all_rows[candidate], all_rows[baseline]
        mechanism[key] = {"discrete_action_disagreements": sum(a["actions"] != b["actions"] for a, b in zip(left, right)),
            "final_output_disagreements": sum(a["delivered"] != b["delivered"] for a, b in zip(left, right)),
            "max_initial_release_probability_difference": max(max(abs(x-y) for x,y in zip(a["stages"][0]["runtime"]["law"]["probabilities"], b["stages"][0]["runtime"]["law"]["probabilities"])) for a,b in zip(left,right)),
            "max_abs_utility_difference": float(np.max(np.abs(delta))),
            "mean_error_reduction": float(np.mean([b["squared_error"] - a["squared_error"] for a,b in zip(left,right)])),
            "mean_paid_cost_increase": float(np.mean([a["cost"] - b["cost"] for a,b in zip(left,right)]))}
        if primary:
            costs[key] = {}
            for offset, metric in enumerate(("packet_bytes", "wall_ns", "cpu_ns", "native_roundtrip_ns")):
                difference = np.asarray([a[metric] - b[metric] for a,b in zip(left,right)]).reshape(len(SEEDS), -1)
                result = paired_interval(difference, 4000, REGISTRATION["bootstrap_seed"] + 100 + 10 * index + offset, .05)
                result["direction"] = "candidate minus baseline; negative means smaller"
                result["descriptive_only"] = True
                costs[key][metric] = result
    metrics = {}
    for arm, rows in all_rows.items():
        p = np.asarray([r["stages"][0]["runtime"]["law"]["probabilities"] for r in rows])
        raw = np.asarray([r["stages"][0]["runtime"]["law"]["raw_probabilities_q24"] for r in rows]) / Q24
        labels, covered, parameter_errors = [], [], []
        for row in rows:
            stage = row["stages"][0]["runtime"]
            law = stage["law"]
            error = row["target"] - stage["public"]["initial"]
            labels.append(0 if error <= law["lower"] else 2 if error > law["upper"] else 1)
            rank = float(cdf(law["conditional_law"], error))
            covered.append(.025 <= rank <= .975)
            source_probability = np.exp(event_logs(stage["source_law"], law["lower"], law["upper"]))
            parameter_errors.append(float(np.max(np.abs(source_probability - law["physical_probabilities"]))))
        labels = np.asarray(labels)
        class_ece = []
        for category in range(3):
            bins = np.minimum((10 * p[:,category]).astype(int), 9)
            class_ece.append(sum(np.mean(bins==j) * abs(float(p[bins==j,category].mean())-float(np.mean(labels[bins==j]==category))) for j in range(10) if np.any(bins==j)))
        selected, raw_selected = p[np.arange(len(rows)),labels], raw[np.arange(len(rows)),labels]
        physical_logs = np.asarray([r["stages"][0]["runtime"]["law"]["physical_log_probabilities"] for r in rows])
        metrics[arm] = {key: float(np.mean([r[key] for r in rows])) for key in
            ("utility", "squared_error", "cost", "wall_ns", "cpu_ns", "packet_bytes", "native_requests", "native_ticks", "native_roundtrip_ns")}
        metrics[arm].update(executions=len(rows), waits=sum("wait" in r["actions"] for r in rows),
            repairs=sum("repair" in r["actions"] for r in rows), initial_classwise_ece=float(np.mean(class_ece)),
            initial_exact_mixture_95_coverage=float(np.mean(covered)),
            initial_released_event_nll=float(-np.log(selected).mean()),
            initial_physical_event_nll=float(-physical_logs[np.arange(len(rows)),labels].mean()),
            initial_raw_q24_nll=None if np.any(raw_selected==0) else float(-np.log(raw_selected).mean()),
            raw_q24_any_zero_rows=int(np.sum(np.any(raw==0,axis=1))), raw_q24_true_event_zero_rows=int(np.sum(raw_selected==0)),
            released_zero_rows=int(np.sum(np.any(p==0,axis=1))), max_source_to_effective_category_error=max(parameter_errors),
            released_zero_forecasts=sum(min(s["runtime"]["law"]["probabilities_q24"]) < 1 for r in rows for s in r["stages"]),
            released_bad_total_forecasts=sum(sum(s["runtime"]["law"]["probabilities_q24"]) != Q24 for r in rows for s in r["stages"]),
            max_native_to_released_coordinate_error=max(max(abs(a-b) for a,b in zip(s["runtime"]["law"]["native_mixture_probabilities"], s["runtime"]["law"]["probabilities"])) for r in rows for s in r["stages"]),
            source_to_effective_error_scope="mixture-weight/state transport and native parameter rounding; separate from final Q24 release error",
            packet_bytes_total=sum(r["packet_bytes"] for r in rows),
            native_journal_bytes_written=sum(n["journal_bytes_written"] for r in rows for s in r["stages"] for n in s["runtime"]["native"]),
            native_witness_bytes_final_per_component=sum(n["witness_bytes"] for r in rows for n in r["stages"][-1]["runtime"]["native"]))
    event_units = {"mixture_weight_q24": 0, "component_mean_q12": 0, "component_logvariance_q12": 0}
    for row in all_rows["event"]:
        previous = None
        for stage in row["stages"]:
            state = stage["runtime"]["decoder"]
            count = state["components"]
            before = previous or [0] * len(state["values"])
            changes = [abs(a-b) for a,b in zip(state["values"],before)]
            event_units["mixture_weight_q24"] += sum(changes[:count-1])
            event_units["component_mean_q12"] += sum(changes[count-1:2*count-1])
            event_units["component_logvariance_q12"] += sum(changes[2*count-1:])
            previous = state["values"]
    acceptance = {
        "event_vs_direct_noninferiority": contrasts["event_vs_direct"]["passes_noninferiority"],
        "event_vs_float_noninferiority": contrasts["event_vs_float"]["passes_noninferiority"],
        "event_direct_exact_actions_outputs_utility": all(mechanism["event_vs_direct"][k] == 0 for k in
            ("discrete_action_disagreements", "final_output_disagreements", "max_abs_utility_difference", "max_initial_release_probability_difference")),
        "positive_q24_all_scored_outputs": all(v["released_zero_forecasts"] == 0 and v["released_bad_total_forecasts"] == 0
            and v["max_native_to_released_coordinate_error"] <= 3/Q24 for v in metrics.values()),
        "all_replays_passed": all(s["audit"]["passed"] for s in scopes),
        "all_runtime_qualifications_passed": all(s["qualification"]["passed"] for s in scopes),
        "production_promotion": False,
    }
    report = {"schema": "hepta.packed-feedback.results.v4", "complete": True, "seeds": list(SEEDS),
              "independent_trajectories": len(SEEDS)*REGISTRATION["confirmation_rows"],
              "completed_control_executions": len(SEEDS)*REGISTRATION["confirmation_rows"]*len(ARMS),
              "metrics": metrics, "utility_contrasts": contrasts, "mechanism": mechanism,
              "descriptive_paired_cost_contrasts": costs, "acceptance": acceptance,
              "event_integer_quantum_units": event_units, "quantum_units_are_not_physical_spike_operations": True,
              "scopes": scopes, "source_commit": frozen["source_commit"],
              "scope": "controlled synthetic mixture residual; actual Hepta text/PNG/native feedback execution",
              "wait_value": "fixed GH64 approximation with separately checked quadrature error; all codec arms share planner",
              "positive_release_does_not_claim_physical_tail_or_calibration_equivalence": True,
              "runtime_latencies_are_shared_host_python_io_measurements": True, "hardware_energy_measured": False}
    verify(root)
    write_json(root / "RUNTIME_RESULTS.json", report)
    return report
