"""Read-only raw-event verification and side-by-side precision result report."""

from datetime import datetime, timezone
from pathlib import Path
import gzip
import hashlib
import itertools
import json


ROOT = Path(__file__).resolve().parent
TOLERANCE = 1e-7
FIELDS = ("action_disagreement_rows","count_disagreement_rows",
    "per_neuron_count_disagreement_rows","event_type_disagreement_rows",
    "event_time_tolerance_failure_rows","exact_event_log_disagreement_rows",
    "delivered_pulse_disagreement_rows","budget_disagreement_rows",
    "expected_utility_disagreement_rows","realized_query_utility_disagreement_rows")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_gzip(path):
    with gzip.open(path,"rt",encoding="utf-8") as handle:
        return json.load(handle)


def row_metrics(actual, reference):
    a,b = actual["actual_internal_events"],reference["actual_internal_events"]
    types_equal = [(e["component"],e["cause"]) for e in a] == [(e["component"],e["cause"]) for e in b]
    time_error = max((abs(x["time"]-y["time"]) for x,y in zip(a,b)),default=0.) if types_equal else None
    for path in (actual,reference):
        if len(path["actual_internal_events"]) != path["internal_spikes"]:
            raise AssertionError("Recorded actual events and total count disagree")
        for index,count in enumerate(path["internal_spikes_per_neuron"]):
            if count != sum(e["component"]==index for e in path["actual_internal_events"]):
                raise AssertionError("Recorded events and per-neuron count disagree")
    return {"action_disagreement_rows":int(actual["actions"] != reference["actions"]),
        "count_disagreement_rows":int(len(a) != len(b)),
        "per_neuron_count_disagreement_rows":int(actual["internal_spikes_per_neuron"] != reference["internal_spikes_per_neuron"]),
        "event_type_disagreement_rows":int(not types_equal),
        "event_time_tolerance_failure_rows":int(not (types_equal and time_error <= TOLERANCE)),
        "exact_event_log_disagreement_rows":int(a != b),
        "delivered_pulse_disagreement_rows":int(actual["delivered"] != reference["delivered"]),
        "budget_disagreement_rows":int(any(actual[name] != reference[name] for name in ("budget_final","budget_spent","renewals"))),
        "expected_utility_disagreement_rows":int(actual["expected_utility"] != reference["expected_utility"]),
        "realized_query_utility_disagreement_rows":int(actual["realized_query_utility"] != reference["realized_query_utility"]),
        "maximum_expected_utility_difference":abs(actual["expected_utility"]-reference["expected_utility"]),
        "maximum_realized_utility_difference":max(abs(x-y) for x,y in zip(actual["realized_query_utility"],reference["realized_query_utility"])),
        "maximum_type_aligned_event_time_difference":time_error}


def empty_summary():
    return {"episodes":0,**{name:0 for name in FIELDS},
        "maximum_expected_utility_difference":0.,"maximum_realized_utility_difference":0.,
        "maximum_type_aligned_event_time_difference":None}


def accumulate(destination, source, episodes):
    destination["episodes"] += episodes
    for name in FIELDS:
        destination[name] += source[name]
    for name in ("maximum_expected_utility_difference","maximum_realized_utility_difference",
                 "maximum_type_aligned_event_time_difference"):
        if source[name] is not None:
            destination[name] = (source[name] if destination[name] is None
                                 else max(destination[name],source[name]))


def passed(summary):
    # Exact bit equality is reported separately. The fixed accepted timestamp
    # criterion remains 1e-7; no new criterion is fitted to these results.
    fields = [name for name in FIELDS if name != "exact_event_log_disagreement_rows"]
    fields += ["maximum_expected_utility_difference","maximum_realized_utility_difference"]
    return all(summary[name] == 0 for name in fields)


def main():
    status_path = ROOT/"results/precision_repair_matrix_status.json"
    status = json.loads(status_path.read_text())
    design = json.loads((ROOT/"precision_repair_design.json").read_text())
    original_status_path = ROOT/"results/numerical_matrix_status.json"
    original_status = json.loads(original_status_path.read_text())
    original_report = ROOT/"results/numerical_matrix_report.json"
    if (status.get("all_completed") is not True or original_status.get("all_completed") is not True
            or sha(original_status_path) != design["original_matrix_status_sha256"]
            or sha(original_report) != design["original_matrix_report_sha256"]):
        raise ValueError("Both complete matrices and original fixed identities are required")
    if (status["identity"]["source_sha256"] != sha(ROOT/"precision_repair.py")
            or status["identity"]["design_sha256"] != sha(ROOT/"precision_repair_design.json")
            or status["identity"]["publication_receipt_sha256"] != sha(ROOT/"precision_repair_publication.json")):
        raise ValueError("Repair publication or source identity changed")
    original_files = {item["path"]:item["sha256"] for run in original_status["completed"] for item in run["outputs"]}
    expected = set(itertools.product([101,211,307,401,503],["test","shift","paired"],range(4)))
    seen,entries = set(),[]
    original_total,repair_total = empty_summary(),empty_summary()
    by_dataset = {name:{"original":empty_summary(),"repair":empty_summary()} for name in ("test","shift","paired")}
    all_resources,all_initial = True,True
    for item in status["outputs"]:
        path = ROOT/item["path"]
        if sha(path) != item["sha256"]:
            raise ValueError("Repair raw evidence changed")
        payload = read_gzip(path)
        identity = payload["identity"]
        for key,value in status["identity"].items():
            if identity.get(key) != value:
                raise ValueError("Repair file has a different published identity")
        reference_name = identity["fixed_reference_path"]
        reference_path = ROOT/reference_name
        if original_files.get(reference_name) != sha(reference_path) or identity["fixed_reference_sha256"] != sha(reference_path):
            raise ValueError("The archived original numerical reference changed")
        reference_payload = read_gzip(reference_path)
        if identity["original_reference_identity"] != reference_payload["identity"]:
            raise ValueError("Repair does not use the archived original identity")
        original = reference_payload["comparison"]
        key = (original["training_seed"],original["dataset"],original["latent_replay"])
        if key in seen or key not in expected:
            raise ValueError("Duplicate or undeclared repair comparison")
        seen.add(key)
        if payload["event_time_tolerance"] != TOLERANCE or original["event_time_tolerance"] != TOLERANCE:
            raise ValueError("Original or repair tolerance differs")
        rows = payload["comparison"]["rows"]
        if len(rows) != 256 or len(original["rows"]) != 256:
            raise ValueError("Incomplete scenario coverage")
        local_original,local_repair = empty_summary(),empty_summary()
        for actual,old in zip(rows,original["rows"]):
            for field in ("scenario_index","scenario_digest","group","condition","initial_state_sha256",
                          "query_seeds","query_bits","oracle_expected_utility"):
                if actual[field] != old[field]:
                    raise ValueError("Scenario/initial-state/query identity differs")
            repaired = row_metrics(actual["repair"],old["brent"])
            old_metrics = row_metrics(old["lambert"],old["brent"])
            accumulate(local_repair,repaired,1)
            accumulate(local_original,old_metrics,1)
        stored = payload["comparison"]["summary"]
        for name,value in local_repair.items():
            if name in stored and stored[name] != value:
                raise AssertionError("Stored repair summary differs from independently recomputed raw events")
        if stored != item["summary"]:
            raise AssertionError("Repair status and raw summary differ")
        all_resources &= stored["all_resource_invariants_passed"]
        all_initial &= stored["same_initial_actor_seed_and_state_digests"]
        accumulate(original_total,local_original,256)
        accumulate(repair_total,local_repair,256)
        accumulate(by_dataset[key[1]]["original"],local_original,256)
        accumulate(by_dataset[key[1]]["repair"],local_repair,256)
        entries.append({"training_seed":key[0],"dataset":key[1],"latent_replay":key[2],
            "original_path":reference_name,"original_sha256":sha(reference_path),
            "repair_path":item["path"],"repair_sha256":sha(path),
            "original":local_original,"repair":local_repair,
            "repair_recorded_checks_passed":passed(local_repair)})
    if seen != expected or len(status["outputs"]) != 60:
        raise ValueError("The full 60 comparison matrix is incomplete")
    freeze = json.loads((ROOT/"pre_data_freeze.json").read_text())
    if any(sha(ROOT/name) != value for name,value in freeze["source_sha256"].items()):
        raise ValueError("An original frozen source changed")
    result = {"schema":"rrsnn-v4-original-versus-isolated-precision-report-1",
        "created_at_utc":datetime.now(timezone.utc).isoformat(),"report_source_sha256":sha(__file__),
        "repair_matrix_status_sha256":sha(status_path),"original_matrix_status_sha256":sha(original_status_path),
        "original_matrix_report_sha256":sha(original_report),"repair_identity":status["identity"],
        "repair_source_sha256":sha(ROOT/"precision_repair.py"),
        "repair_design_sha256":sha(ROOT/"precision_repair_design.json"),
        "repair_publication_sha256":sha(ROOT/"precision_repair_publication.json"),
        "all_completed":True,"all_passed":passed(repair_total) and all_resources and all_initial,
        "all_comparisons_passed":passed(repair_total) and all_resources and all_initial,
        "all_passed_scope":"All recorded fixed-reference event/type/count/task/delivery/budget/utility checks under unchanged 1e-7 timestamp tolerance, plus the evaluator's resource and initial-identity checks. This is not full-state/RNG, performance-superiority, or production qualification.",
        "comparison_files":60,"scenario_path_comparisons":repair_total["episodes"],
        "event_time_tolerance":TOLERANCE,"all_original_frozen_sources_unchanged":True,
        "all_original_numerical_raw_files_sha_verified":True,"all_resource_invariants_passed":all_resources,
        "all_initial_actor_seed_and_state_digests_matched":all_initial,
        "original":{"all_completed":True,"all_passed":passed(original_total),**original_total},
        "repair":{"all_completed":True,"all_passed":passed(repair_total),**repair_total,
                  "all_actual_event_logs_bitwise_equal_to_fixed_brent":repair_total["exact_event_log_disagreement_rows"]==0},
        "totals":{"original":original_total,"repair":repair_total},
        "by_dataset":by_dataset,"comparisons":entries,
        "full_state_rng_equivalence":{"status":"not_verified",
            "reason":"Archived Brent records do not contain complete per-observation state or RNG values. Separate development probes do not extend this claim to the 60 production replays."},
        "preserved_failed_or_interrupted_repair_attempts":status.get("preserved_prior_attempts",[]),
        "primary_utility_evidence_replaced":False,"checkpoint_selection_changed":False,"new_training_performed":False,
        "interpretation":"Post-result engineering repair evidence. Original failures remain failures and original primary utility/candidate conclusions stand. The repaired execution is a separately versioned precision proposal using unchanged selected weights and source-bound archived Brent paths.",
        "limits":["The old Brent record lacks full per-observation state/RNG values; no such 60-replay equality is claimed.",
            "The same 5 training seeds, scenarios, 4 latent paths and 4 terminal query draws are reused; these are not new independent examples or a real future window.",
            "Original normal batches use shared vectorized RNG consumption, so a single branch may affect multiple rows. Affected rows are not independent estimates of local rounding failure probability.",
            "No new native bridge manifest, production Cell qualification, retraining or contemporaneous speed benchmark is performed by this report."]}
    destination = ROOT/"results/precision_repair_report.json"
    if destination.exists():
        raise FileExistsError("Side-by-side report is write-once")
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    temporary.replace(destination)
    print(json.dumps({"report":str(destination),"sha256":sha(destination),"all_completed":True,
        "all_passed":result["all_passed"],"original":result["original"],"repair":result["repair"]}),flush=True)


if __name__ == "__main__":
    main()
