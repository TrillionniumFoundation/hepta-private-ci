"""Read-only aggregation of the original frozen 60 numerical controls."""

from datetime import datetime, timezone
from pathlib import Path
import gzip
import hashlib
import itertools
import json


ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    status_path = ROOT / "results/numerical_matrix_status.json"
    status = json.loads(status_path.read_text())
    if status.get("all_completed") is not True:
        raise ValueError("Original matrix must be complete before final reporting")
    outputs = [item for run in status["completed"] for item in run["outputs"]]
    expected = set(itertools.product([101,211,307,401,503], ["test","shift","paired"], range(4)))
    keys, files = set(), []
    totals = {name: 0 for name in (
        "scenario_path_comparisons", "action_disagreement_rows", "action_disagreements",
        "event_count_disagreement_rows", "event_type_sequence_disagreement_rows",
        "event_time_tolerance_failure_rows", "exact_event_log_disagreement_rows",
        "delivered_pulse_disagreement_rows", "expected_utility_disagreement_rows",
        "realized_query_utility_disagreement_rows", "budget_or_renewal_disagreement_rows",
        "per_neuron_count_disagreement_rows", "rng_disagreement_observation_calls",
        "index_disagreement_observation_calls", "count_disagreement_observation_calls",
        "observation_disagreement_calls")}
    maxima = {name: {"value": 0., "location": None} for name in (
        "event_time_absolute_error", "boundary_absolute_error", "drift_absolute_error",
        "logits_absolute_error", "trace_absolute_error", "expected_utility_absolute_error",
        "realized_query_utility_absolute_error")}
    all_invariants, all_initial_weights = True, True
    tolerance = None

    def record(name, value, location):
        if value > maxima[name]["value"]:
            maxima[name] = {"value": value, "location": location}

    for entry in outputs:
        path = ROOT / entry["path"]
        if sha(path) != entry["sha256"]:
            raise ValueError("Raw numerical evidence digest changed")
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            raw = json.load(handle)
        identity, comparison = raw["identity"], raw["comparison"]
        key = (comparison["training_seed"], comparison["dataset"], comparison["latent_replay"])
        if key not in expected or key in keys:
            raise ValueError("Unexpected or duplicated numerical comparison")
        keys.add(key)
        if (identity["selection_sha256"] != status["identity"]["selection_sha256"]
                or identity["controller_sha256"] != status["identity"]["controller_sha256"]
                or comparison["summary"] != entry["summary"]):
            raise ValueError("Matrix identity or summary differs from raw evidence")
        if comparison["event_time_tolerance"] != 1e-7:
            raise ValueError("Original fixed event-time tolerance changed")
        tolerance = comparison["event_time_tolerance"]
        rows, steps = comparison["rows"], comparison["step_comparisons"]
        if len(rows) != 256 or {row["scenario_index"] for row in rows} != set(range(256)):
            raise ValueError("Scenario coverage is incomplete")
        all_invariants &= comparison["summary"]["all_task_resource_invariants_passed"]
        all_initial_weights &= comparison["summary"]["same_weights_and_initial_state"]
        local_time_failures = 0
        for row in rows:
            left, right = row["lambert"], row["brent"]
            location = {"file": entry["path"], "training_seed": key[0], "dataset": key[1],
                        "latent_replay": key[2], "scenario_index": row["scenario_index"],
                        "group": row["group"], "condition": row["condition"]}
            events_a, events_b = left["actual_internal_events"], right["actual_internal_events"]
            same_types = [(e["component"],e["cause"]) for e in events_a] == [
                         (e["component"],e["cause"]) for e in events_b]
            counts_equal = len(events_a) == len(events_b)
            time_error = max((abs(a["time"]-b["time"]) for a,b in zip(events_a, events_b)),
                             default=0.) if same_types else None
            within_tolerance = same_types and time_error <= tolerance
            if (row["counts_equal"] != counts_equal or row["event_type_sequence_equal"] != same_types
                    or row["event_log_equal_with_time_tolerance"] != within_tolerance):
                raise AssertionError("Recorded event flags do not reproduce from raw events")
            totals["scenario_path_comparisons"] += 1
            totals["action_disagreement_rows"] += left["actions"] != right["actions"]
            totals["action_disagreements"] += row["action_disagreement_count"]
            totals["event_count_disagreement_rows"] += not counts_equal
            totals["event_type_sequence_disagreement_rows"] += not same_types
            totals["event_time_tolerance_failure_rows"] += not within_tolerance
            local_time_failures += not within_tolerance
            totals["exact_event_log_disagreement_rows"] += events_a != events_b
            totals["delivered_pulse_disagreement_rows"] += left["delivered"] != right["delivered"]
            totals["expected_utility_disagreement_rows"] += left["expected_utility"] != right["expected_utility"]
            totals["realized_query_utility_disagreement_rows"] += left["realized_query_utility"] != right["realized_query_utility"]
            totals["budget_or_renewal_disagreement_rows"] += any(left[name] != right[name] for name in (
                "budget_final", "budget_spent", "renewals"))
            totals["per_neuron_count_disagreement_rows"] += left["internal_spikes_per_neuron"] != right["internal_spikes_per_neuron"]
            record("expected_utility_absolute_error", abs(row["expected_utility_root_minus_lambert"]), location)
            record("realized_query_utility_absolute_error", max(map(abs,row["realized_utility_root_minus_lambert"])), location)
            if time_error is not None:
                if time_error > maxima["event_time_absolute_error"]["value"]:
                    pair = max(zip(events_a, events_b), key=lambda pair: abs(pair[0]["time"]-pair[1]["time"]), default=None)
                    record("event_time_absolute_error", time_error,
                           {**location, "lambert_event": pair[0] if pair else None,
                            "brent_event": pair[1] if pair else None})
        for step in steps:
            totals["rng_disagreement_observation_calls"] += not step["same_rng_after_observation"]
            totals["index_disagreement_observation_calls"] += not step["same_indices_after_observation"]
            totals["count_disagreement_observation_calls"] += not step["same_count_matrix"]
            totals["observation_disagreement_calls"] += not step["same_observation"]
            for field in ("boundary", "drift", "logits", "trace"):
                record(field+"_absolute_error", step[field+"_maximum_absolute_difference"],
                       {"file": entry["path"], "call": step["call"],
                        "batch_serial": step["batch_serial"], "observation_step": step["observation_step"]})
        if local_time_failures != comparison["summary"]["rows_with_event_divergence_beyond_tolerance"]:
            raise AssertionError("Time failure count does not reproduce from raw rows")
        first_divergences = {}
        for flag in ("same_indices_after_observation", "same_count_matrix", "same_rng_after_observation"):
            first_index = next((i for i, step in enumerate(steps) if not step[flag]), None)
            if first_index is not None:
                selected = steps[first_index]
                first_divergences[flag] = {
                    **{name: value for name, value in selected.items() if name != "time"},
                    "time_range": [min(selected["time"]), max(selected["time"])],
                    "previous_call": ({**{name: value for name, value in steps[first_index-1].items()
                                          if name != "time"},
                        "time_range": [min(steps[first_index-1]["time"]), max(steps[first_index-1]["time"])]}
                        if first_index else None)}
        files.append({"path": entry["path"], "sha256": entry["sha256"],
                      "training_seed": key[0], "dataset": key[1], "latent_replay": key[2],
                      "first_observation_divergences": first_divergences,
                      "summary": comparison["summary"]})
    if keys != expected or len(outputs) != 60:
        raise ValueError("Not all 60 numerical controls were reported")
    frozen = json.loads((ROOT / "pre_data_freeze.json").read_text())
    if not all(sha(ROOT/name)==expected for name,expected in frozen["source_sha256"].items()):
        raise ValueError("Frozen source changed")
    report = {"schema": "rrsnn-v4-original-numerical-matrix-report-1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "matrix_status_sha256": sha(status_path), "report_source_sha256": sha(__file__),
        "identity": status["identity"], "comparison_files": len(files),
        "totals": totals, "maxima": maxima,
        "all_task_resource_invariants_passed": all_invariants,
        "all_weights_and_initial_states_matched": all_initial_weights,
        "original_fixed_event_time_tolerance": tolerance,
        "all_original_event_time_tolerances_passed": totals["event_time_tolerance_failure_rows"] == 0,
        "task_actions_deliveries_budgets_and_utilities_all_identical": all(totals[field]==0 for field in (
            "action_disagreement_rows", "delivered_pulse_disagreement_rows",
            "expected_utility_disagreement_rows", "realized_query_utility_disagreement_rows",
            "budget_or_renewal_disagreement_rows")),
        "internal_spike_counts_and_types_all_identical": all(totals[field]==0 for field in (
            "event_count_disagreement_rows", "event_type_sequence_disagreement_rows",
            "per_neuron_count_disagreement_rows")),
        "discrete_actions_counts_deliveries_and_expected_utility_all_identical": all(totals[field]==0 for field in (
            "action_disagreement_rows", "event_count_disagreement_rows", "event_type_sequence_disagreement_rows",
            "delivered_pulse_disagreement_rows", "expected_utility_disagreement_rows",
            "per_neuron_count_disagreement_rows")),
        "files_with_at_least_one_original_time_tolerance_failure": sum(
            item["summary"]["rows_with_event_divergence_beyond_tolerance"] > 0 for item in files),
        "branch_attribution_caution": "After a discrete index or RNG-consumption branch changes, later event-time, drift, threshold and logit differences include downstream path effects. Their global maxima are not estimates of local Lambert formula roundoff.",
        "batch_coupling_caution": "Normal test/shift evaluation uses one vectorized actor RNG stream per batch. A branch can change later random consumption across rows; counts of affected scenario paths are not independent estimates of a per-scenario roundoff failure probability. Strict paired conditions use their declared separate, matched per-group streams.",
        "scope": "Original frozen same-weight numerical control only; all source hashes, weights, actor seeds and 1e-7 tolerance preserved. Replays and query draws are nested, not independent new scenarios. This report does not establish model utility superiority, production Cell behavior, a true future window, or a successful numerical tolerance gate when failures exist.",
        "raw_files": files}
    destination = ROOT / "results/numerical_matrix_report.json"
    if destination.exists():
        raise FileExistsError("Original matrix report is write-once")
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    temporary.replace(destination)
    print(json.dumps({"report": str(destination), "sha256": sha(destination),
                      "totals": totals, "maxima": maxima}, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
