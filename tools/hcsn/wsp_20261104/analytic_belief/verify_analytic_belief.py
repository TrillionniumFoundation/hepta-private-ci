#!/usr/bin/env python3
"""Read-only evidence verification; never import or execute the model/evaluator.

Recompute metrics with scalar Python arithmetic, not the experiment's NumPy
metric functions. Check existing world-value means and every reported five-fit
contrast, including the interaction. Utility, the model's bank, and teacher
targets are recorded inputs here: this does not reevaluate any of them.
"""
from pathlib import Path
import argparse
import datetime
import gzip
import hashlib
import json
import math
import statistics

import numpy as np  # Only for reading the archived head-parameter fixture.

ROOT = Path(__file__).resolve().parent
FITS = [11, 23, 37, 53, 71]
RAW_ARMS = ["A", "C", "P", "CP"]
ALL_ARMS = RAW_ARMS + ["P_gated", "CP_gated"]
METRICS = ["belief_brier", "q_mse", "continuation_q_mse", "teacher_behavior_regret"]
TCRIT = 2.7764451051977987
PROTOCOL_SHA = "88de0753b8e1c36bab97768b3fa8c55cb43d5ef17a3f0700fa0ed8912fe15515"
DRIVER_SHA = "9e8950bbf7949a4d9caf5841f3507e042b3a934df0d1be7aba19158e7b7e23c0"
GEOMETRY_SHA = "2928beeceabd3c6b48cda7d1b5df2de4ddbbaecc2ebedb23d2a8ce75df1816d5"
OLD_RESULTS_SHA = "a55a8136842d366f3d3663b05028bae8fa7eedad63bfa731662fb692104eedb4"
OLD_HEADS_SHA = "d4f220739bc5b76d19ab02e1440e48b2ef82f6098a7ff78516284e61d32518e1"
SOURCE_SHA = {
    "checked_replay.py": "d0922ab0c458d9d382e1f9c851c52731c4a71256870000862dbebf5d38366b24",
    "joint_deploy.py": "c91ef40c484000e2a2b923425467c03fbbfb4e15a1f54856f6c850f9242c8e26",
    "joint_law.py": "2e7f19a2534567e31370eea24dec096a309e4db4aa42770efbf544bed84bcf65",
    "joint_protocol.json": "1c6ffc51d8d9df8f57bb350dd9d80a264b889a14882da553c63e60c547a18606",
    "joint_task.py": "51139ba57004f2a5d69381af2f781b3717404318f122d8b6bec8416004efffa5",
    "legacy_task.py": "d8e88364932bb344e4df811f40163550e9c198b8e34778b5664c72367f4bde06",
    "run_head_edit.py": "fe0681ef732b660db0b195bda21cf9ab40b0d6cd8b7fe0c69ade7b9e67198b6f",
    "truth_transitions.npz": "3a62c48272d90b459622ed8818fddf36de983831fbc0c1306fc39b27345228f0",
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def uncompressed(path):
    path = Path(path)
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data


def read(path):
    return json.loads(uncompressed(path))


def close(actual, expected, label):
    actual, expected = float(actual), float(expected)
    require(math.isfinite(actual) and math.isfinite(expected), label + ": nonfinite")
    require(abs(actual - expected) <= 2e-12, f"{label}: {actual!r} != {expected!r}")


def same_vector(actual, expected, label):
    require(len(actual) == len(expected), label + ": length")
    for a, b in zip(actual, expected):
        close(a, b, label)


def mean(values):
    require(len(values) > 0, "nonempty sample required")
    require(all(math.isfinite(v) for v in values), "finite sample required")
    return math.fsum(values) / len(values)


def record_path(records, name):
    require(isinstance(name, str) and Path(name).name == name, "flat record name required")
    return records / name


def hashed_record(records, name, expected_sha):
    path = record_path(records, name)
    require(sha(path) == expected_sha, name + ": hash")
    return read(path)


def metric_values(probe, arm):
    """Independent scalar definitions; first legal maximum matches argmax ties."""
    n = probe["rows"]
    require(isinstance(n, int) and n > 0, "positive probe row count")
    fields = ["world_ids", "teacher_q", "legal", "teacher_belief", "model_bank7",
              "learned_belief", "A_continuation", "C_continuation"]
    require(all(len(probe[k]) == n for k in fields), "probe field lengths")
    probability = probe["model_bank7" if arm in ("P", "CP") else "learned_belief"]
    continuation = probe["C_continuation" if arm in ("C", "CP") else "A_continuation"]
    brier, mse, regret, continuation_squared = [], [], [], []
    continuation_count = 0
    for i in range(n):
        p, target = probability[i], probe["teacher_belief"][i]
        require(math.isfinite(p) and 0 <= p <= 1, "probability outside [0,1]")
        require(math.isfinite(target) and 0 <= target <= 1, "teacher target outside [0,1]")
        y, mask, head = probe["teacher_q"][i], probe["legal"][i], continuation[i]
        require(len(y) == len(mask) == 6 and len(head) == 3, "probe dimensions")
        require(all(math.isfinite(v) for v in y + head), "nonfinite Q/continuation")
        require(all(v in (False, True) for v in mask) and any(mask), "legal-action mask")
        q = [0.0] + head + [1 - 2 * p, 2 * p - 1]
        legal = [j for j in range(6) if mask[j]]
        action = max(legal, key=lambda j: q[j])
        brier.append((p - target) ** 2)
        mse.append(math.fsum((q[j] - y[j]) ** 2 for j in legal) / len(legal))
        regret.append(max(y[j] for j in legal) - y[action])
        for j in (1, 2, 3):
            if mask[j]:
                continuation_squared.append((q[j] - y[j]) ** 2)
                continuation_count += 1
    require(continuation_count > 0, "no continuation metric support")
    return {"belief_brier": mean(brier), "q_mse": mean(mse),
            "continuation_q_mse": math.fsum(continuation_squared) / continuation_count,
            "teacher_behavior_regret": mean(regret), "rows": n}


def verify_arm(record, probe, arm, worlds):
    require(len(record["world_utilities"]) == worlds, "utility-world count")
    close(record["expected_utility"], mean(record["world_utilities"]), "utility mean")
    computed = metric_values(probe, arm)
    require(record["rows"] == computed["rows"], "metric row count")
    for metric in METRICS:
        close(record[metric], computed[metric], metric + " " + arm)


def verify_ci(record, values, label):
    require(len(values) == record["independent_fits"] == 5, label + ": fit units")
    same_vector(record["per_fit"], values, label + ": per-fit")
    m = mean(values)
    half = TCRIT * statistics.stdev(values) / math.sqrt(5)
    close(record["mean"], m, label + ": mean")
    same_vector(record["descriptive_paired_95_ci"], [m - half, m + half], label + ": CI")


def verify_previous_payload(study):
    before = read(ROOT / "PREVIOUS_123_BEFORE.json")
    after = read(ROOT / "OLD_123_PRESERVATION.json")
    require(sha(ROOT / "PREVIOUS_123_BEFORE.json") == after["before_manifest_sha256"], "old-payload before hash")
    require(before["total_files"] == after["total_files"] == 123 and after["all123_unchanged"] is True,
            "old-payload preservation count/receipt")
    groups = [("previous_root_payload", study.parent, 88),
              ("previous_ndu_value_grid", study.parent / "ndu_value_grid", 35)]
    for key, root, count in groups:
        require(len(before[key]) == count and before[key] == after["after"][key], "old-payload exact before/after map")
        for name, entry in before[key].items():
            relative = Path(name)
            require(not relative.is_absolute() and ".." not in relative.parts, "old-payload relative path")
            path = root / relative
            require(path.stat().st_size == entry["bytes"] and sha(path) == entry["sha256"], "current frozen payload: " + name)
    return 123


def verify_transfer_and_process(records, result, qualification):
    transfer = read(ROOT / "TRANSFER_VERIFICATION.json")
    expected = {f"fit_{fit}_BEFORE_TEST.json" for fit in FITS}
    expected.update(f"fit_{fit}_{split}_PROBE.json.gz" for fit in FITS for split in ("train", "validation", "iid", "ood"))
    expected.update(f"fit_{fit}_{domain}_WORLDS.json.gz" for fit in FITS for domain in ("iid", "ood"))
    expected.update(["ALL_TRAIN_VAL_BEFORE_TEST.json", "RESULTS.json.gz", "QUALIFICATION.json"])
    require(len(transfer["files"]) == len(expected) == 38 and transfer["all38_files_verified"] is True,
            "complete transferred raw records")
    require({x["name"] for x in transfer["files"]} == expected, "transfer inventory")
    for entry in transfer["files"]:
        path = record_path(records, entry["name"])
        require(path.stat().st_size == entry["bytes"] and sha(path) == entry["sha256"], "transfer file bytes/hash")
    process = read(records / "PROCESS_VERIFICATION.json")
    require(process["exit_code"] == 0 and process["state"] == "succeeded", "process completion")
    require(process["output_complete"] is True and process["output_durable"] is True
            and process["stderr_bytes"] == 0, "durable complete output")
    require(process["timed_out"] is False and process["cancelled"] is False and process["automatic_retry"] is False,
            "single uncancelled execution")
    events = process["events"]
    stages = ["original_train_val_fixed"] * 5 + ["all_five_gates_frozen_before_new_test"] + ["fresh_test_complete"] * 5 + ["finished"]
    require([e["stage"] for e in events] == stages, "all five gates precede all fresh-test completions")
    require([e["fit"] for e in events[:5]] == [e["fit"] for e in events[6:11]] == FITS, "ordered progress fit identities")
    for event, fit in zip(events[:5], result["fits"]):
        for arm in ("P", "CP"):
            require(event[arm + "_accepted"] == fit["gates"][arm]["accepted"]
                    and event[arm + "_val_gain"] == fit["gates"][arm]["validation_gain"], "progress gate identity")
    require(events[5]["sha256"] == result["before_test_sha256"], "progress freezes exact receipt")
    require(events[-1]["status"] == "completed" and events[-1]["error"] is None
            and events[-1]["results_sha256"] == qualification["results_sha256"], "progress final identity")
    require(events[-1]["measurement"] == result["measurement"], "process measurement identity")
    for arm in ("P", "CP"):
        require(events[-1][arm + "_accepted"] == qualification[arm + "_accepted_fits"], "process final gate count")
    cpu = [e["cpu"] for e in events if "cpu" in e] + [result["measurement"]["cpu_seconds"]]
    require(cpu == sorted(cpu) and cpu[-1] < 120, "monotone bounded recorded CPU progress")
    return 38


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", required=True)
    parser.add_argument("--old-heads", required=True)
    args = parser.parse_args()
    study, records = Path(args.study_root), ROOT / "records"
    p = read(ROOT / "PROTOCOL_BEFORE_RESULTS.json")
    require(sha(ROOT / "PROTOCOL_BEFORE_RESULTS.json") == PROTOCOL_SHA, "frozen protocol identity")
    require(sha(ROOT / "run_analytic_belief.py") == p["driver_sha256"] == DRIVER_SHA, "executed source identity")
    require(p["fits"] == FITS and p["seed"] == 870160000, "fits/seed")
    require(p["raw_arms"] == RAW_ARMS and p["gated_arms"] == ALL_ARMS[4:], "declared arms")
    require(p["new_parameter_edits"] == p["candidate_searches"] == p["gradient_steps"] == 0, "zero new fitting/edits")
    require(p["validation_gate"]["threshold"] == .005 and p["validation_gate"]["all_five_before_fresh_tests"], "gate declaration")
    require(p["cpu_hard_limit_seconds"] == 120 and p["worlds_per_fit_per_domain"] == 32, "resource/test declaration")
    require(p["source_sha256"] == SOURCE_SHA, "original dependency pins")
    require(all(sha(study / n) == h for n, h in SOURCE_SHA.items()), "original dependency hashes")
    require(p["original_results_uncompressed_sha256"] == OLD_RESULTS_SHA, "old-results declaration")
    prior_bytes = uncompressed(study / "records/results_strict.json.gz")
    require(hashlib.sha256(prior_bytes).hexdigest() == OLD_RESULTS_SHA, "original results")
    oldfits = {f["fit"]: f for f in json.loads(prior_bytes)["fits"]}
    require(sha(args.old_heads) == p["old_heads_gzip_sha256"] == OLD_HEADS_SHA, "frozen C heads")
    oldheads = {f["fit"]: f for f in read(args.old_heads)["fits"]}
    geometry_path = study / "fixtures/train_linear_geometry.npz"
    require(sha(geometry_path) == GEOMETRY_SHA, "original head fixture")
    geometry = np.load(geometry_path, allow_pickle=False)
    require(sha(ROOT / "SEMANTICS_BEFORE_RUN.json") == p["semantics_sha256"], "semantics identity")
    require(sha(ROOT / "SOURCE_SEMANTICS.md") == p["source_argument_sha256"], "source argument identity")
    semantics = read(ROOT / "SEMANTICS_BEFORE_RUN.json")
    require(semantics["bank_index_zero_based"] == 7 and semantics["raw_input_index_zero_based"] == 83
            and semantics["required_deadline"] == 6, "deadline/index semantics")
    semfits = {f["fit"]: f for f in semantics["models"]}
    require(all(sha(study / name) == h for name, h in semantics["source_read_only_identity"].items()),
            "all six semantic argument source identities")
    r, qualification = read(records / "RESULTS.json.gz"), read(records / "QUALIFICATION.json")
    require(r["protocol"] == p and r["protocol_sha256"] == qualification["protocol_sha256"] == PROTOCOL_SHA, "protocol chain")
    require(qualification["driver_sha256"] == DRIVER_SHA, "qualification source")
    require(sha(records / "RESULTS.json.gz") == qualification["results_sha256"], "final results identity")
    require(r["status"] == qualification["status"] == "completed", "completed execution")
    require(r["new_weight_parameters_changed"] == qualification["new_weight_parameters_changed"] == 0, "no new weight edits")
    require(r["execution_graph_changed"] is True and qualification["execution_graph_changed"] is True, "structural, not pure WSP")
    require(r["fresh_holdout_generated"] is True and r["all_original_inputs_unchanged"] is True, "run completion flags")
    frozen = read(records / "ALL_TRAIN_VAL_BEFORE_TEST.json")
    require(sha(records / "ALL_TRAIN_VAL_BEFORE_TEST.json") == r["before_test_sha256"], "freeze receipt identity")
    require(frozen["protocol_sha256"] == PROTOCOL_SHA and frozen["driver_sha256"] == DRIVER_SHA, "freeze source chain")
    require(frozen["fresh_test_generated_at_write"] is False, "no fresh test before freeze")
    require(datetime.datetime.fromisoformat(p["written_utc"]) < datetime.datetime.fromisoformat(frozen["written_utc"]), "declaration precedes freeze")
    require([f["fit"] for f in r["fits"]] == [f["fit"] for f in frozen["fits"]] == FITS, "complete ordered five fits")
    expected_frozen_files = {f"fit_{fit}_BEFORE_TEST.json" for fit in FITS}
    expected_frozen_files.update(f"fit_{fit}_{split}_PROBE.json.gz" for fit in FITS for split in ("train", "validation"))
    require(set(frozen["record_file_sha256"]) == expected_frozen_files, "all 15 pre-test record files")
    for n, h in frozen["record_file_sha256"].items():
        require(sha(record_path(records, n)) == h, n + ": frozen hash")
    probes_checked = arm_records_checked = world_records_checked = 0
    for f, pre in zip(r["fits"], frozen["fits"]):
        fit, old, oldhead, sem = f["fit"], oldfits[f["fit"]], oldheads[f["fit"]], semfits[f["fit"]]
        require(pre == read(records / f"fit_{fit}_BEFORE_TEST.json") and pre["tests"] == {}, "per-fit freeze identity")
        require(all(f[k] == v for k, v in pre.items() if k != "timing" and k != "tests"), "pre-test choices remain frozen")
        require(all(f["timing"][k] == v for k, v in pre["timing"].items()), "pre-test timing unchanged")
        require(f["source_model_sha256"] == old["source_model_sha256"] == oldhead["source_model_sha256"] == sem["sha256"], "A source identity")
        require(f["source_data_sha256"] == old["source_data_sha256"], "original TRAIN/VAL data identity")
        require(f["C_model_sha256"] == old["candidate_model_sha256"] == oldhead["candidate_model_sha256"], "C source identity")
        require(sem["family"] == "renewal" and sem["head_dimensions"] == [85, 48, 4] and sem["n_grid"] == 31, "model family/dimensions")
        require(sem["target"] == p["required_target"] and sem["bank_semantics"] == p["required_bank_semantics"], "model event semantics")
        A = np.asarray(geometry[f"fit{fit}_theta"], dtype="<f8")
        C = np.asarray(np.c_[oldhead["network_w2"], oldhead["network_b2"]], dtype="<f8")
        require(A.shape == C.shape == (4, 49) and np.isfinite(A).all() and np.isfinite(C).all(), "head dimensions/finite")
        require(np.array_equal(A[3], C[3]), "prior C kept original learned Belief")
        require(hashlib.sha256(A.tobytes()).hexdigest() == f["A_P_head_sha256"], "A/P same archived parameters")
        require(hashlib.sha256(C.tobytes()).hexdigest() == f["C_CP_head_sha256"], "C/CP same archived parameters")
        require(f["new_weight_parameters_changed"] == 0 and f["same_representation_and_decoder_for_all_arms"] is True
                and f["runtime_model_parameters_unchanged"] is True, "paired parameter preservation receipts")
        seen = {}
        for split, nworld in (("train", 64), ("validation", 16)):
            link = f["probes"][split]
            probe = hashed_record(records, link["file"], link["sha256"])
            require(link["rows"] == probe["rows"] and f[split]["world_count"] == nworld, "original probe/world counts")
            seen[split] = set(probe["world_ids"])
            require(len(seen[split]) == nworld, "probe covers every original world")
            require(set(f[split]) == set(RAW_ARMS + ["world_count"]), "four raw arms on original split")
            for arm in RAW_ARMS:
                verify_arm(f[split][arm], probe, arm, nworld)
                arm_records_checked += 1
            probes_checked += 1
        require(not seen["train"] & seen["validation"], "original splits disjoint")
        close(f["validation"]["A"]["expected_utility"], old["baseline_validation_utility"], "A parity with archived VAL")
        close(f["validation"]["C"]["expected_utility"], old["selected_direct"]["validation_utility"], "C parity with archived VAL")
        effective = {}
        for intervention, baseline in (("P", "A"), ("CP", "C")):
            g = f["gates"][intervention]
            gain = f["validation"][intervention]["expected_utility"] - f["validation"][baseline]["expected_utility"]
            require(g["reference"] == baseline and g["validation_gain"] == gain, "correct paired incumbent")
            require(g["accepted"] == (gain >= .005), "fixed .005 gate")
            require(g["restored_execution_mode_if_rejected"] == (not g["accepted"])
                    and g["paired_checkpoint_parameters_unchanged"] is True, "execution-mode restoration receipt")
            effective[intervention + "_gated"] = intervention if g["accepted"] else baseline
        require(set(f["tests"]) == {"iid", "ood"}, "both new domains")
        for domain, test in f["tests"].items():
            worlds = hashed_record(records, test["world_file"], test["world_file_sha256"])
            require(len(worlds) == test["world_count"] == 32, "32 new worlds")
            ids = [f"analytic_belief_870160000_{domain}_{fit}_{i}" for i in range(32)]
            require([w["id"] for w in worlds] == ids, "new-seed world identities")
            require(not set(ids) & (seen["train"] | seen["validation"]), "fresh world ids")
            require(all(w["schema"] == "joint-current-at-due-fixed-deadline-v1" and w["deadline"] == w["target_tick"] == 6 for w in worlds), "new-world event semantics")
            probe = hashed_record(records, test["probe_file"], test["probe_file_sha256"])
            require(set(probe["world_ids"]) == set(ids), "shared fresh probe covers worlds")
            require(set(test["arms"]) == set(ALL_ARMS), "all raw and gated test arms")
            for arm in ALL_ARMS:
                verify_arm(test["arms"][arm], probe, effective.get(arm, arm), 32)
                arm_records_checked += 1
            for gated, raw in effective.items():
                require(test["arms"][gated] == test["arms"][raw], "exact recorded gated-arm identity")
            for first, second in (("A", "P"), ("C", "CP")):
                require(test["arms"][first]["continuation_q_mse"] == test["arms"][second]["continuation_q_mse"], "paired continuation unchanged")
            probes_checked += 1
            world_records_checked += len(worlds)
        audit = f["probability_audit"]
        require(0 <= audit["minimum_bank7"] <= audit["maximum_bank7"] <= 1, "reported bank probability range")
        require(0 <= audit["maximum_same_model_deadline_identity_error"] <= 2e-12, "same-model deadline identity")
        require(audit["out_of_range_or_nonfinite"] == audit["projection_clipping_operations"] == audit["teacher_inputs_to_projection"] == 0, "projection audit flags")
    pairs = {"P_minus_A": ("P", "A"), "CP_minus_C": ("CP", "C"),
             "P_gated_minus_A": ("P_gated", "A"), "CP_gated_minus_C": ("CP_gated", "C"),
             "C_minus_A": ("C", "A"), "interaction": None}
    require(set(r["summary"]) == {"iid", "ood"}, "summary domains")
    contrasts_checked = 0
    for domain, summary in r["summary"].items():
        def values(arm, metric):
            return [f["tests"][domain]["arms"][arm][metric] for f in r["fits"]]
        require(set(summary["arms"]) == set(ALL_ARMS), "complete arm summary")
        for arm, metrics in summary["arms"].items():
            require(set(metrics) == set(METRICS + ["expected_utility"]), "all five arm metrics")
            for metric, entry in metrics.items():
                v = values(arm, metric)
                same_vector(entry["per_fit"], v, "arm summary per-fit")
                close(entry["mean"], mean(v), "arm summary mean")
        require(set(summary["contrasts"]) == set(pairs), "all six contrasts including interaction")
        for name, pair in pairs.items():
            require(set(summary["contrasts"][name]) == {"expected_utility", "belief_brier", "q_mse"}, "contrast metrics")
            for metric, entry in summary["contrasts"][name].items():
                if pair:
                    deltas = [a - b for a, b in zip(values(pair[0], metric), values(pair[1], metric))]
                else:
                    deltas = [cp - c - pp + aa for cp, c, pp, aa in zip(values("CP", metric), values("C", metric), values("P", metric), values("A", metric))]
                verify_ci(entry, deltas, domain + "/" + name + "/" + metric)
                contrasts_checked += 1
    for arm in ("P", "CP"):
        require(qualification[arm + "_accepted_fits"] == sum(f["gates"][arm]["accepted"] for f in r["fits"]), "gate count qualification")
    require(qualification["measurement"] == r["measurement"], "measurement receipt")
    require(r["measurement"]["process_cpu_seconds_at_measurement"] < 120
            and r["measurement"]["peak_rss_bytes"] <= 4 * 1024 ** 3, "recorded resource bounds")
    require(r["matmul_audit"]["nonfinite_count"] == 0, "recorded finite products")
    previous_files_checked = verify_previous_payload(study)
    transferred_files_checked = verify_transfer_and_process(records, r, qualification)
    geometry.close()
    print(json.dumps({"status": "passed", "protocol_sha256": PROTOCOL_SHA,
        "executed_driver_sha256": DRIVER_SHA, "verifier_sha256": sha(__file__),
        "probe_files_verified": probes_checked, "arm_split_records_verified": arm_records_checked,
        "fresh_world_records_verified": world_records_checked, "metric_contrast_CIs_verified": contrasts_checked,
        "previous_frozen_files_hash_verified": previous_files_checked,
        "transferred_raw_files_verified": transferred_files_checked,
        "P_validation_accepts": qualification["P_accepted_fits"], "CP_validation_accepts": qualification["CP_accepted_fits"],
        "new_parameter_edits": 0, "execution_graph_changed": True,
        "scope": "Read-only source/hash/record verification; scalar recomputation of recorded probe metrics, world-value means, and all contrasts. No model forward, utility reevaluation, world generation, or teacher/model posterior recomputation. Freeze hashes establish recorded ordering, not an independent timestamp authority."}, indent=2))


if __name__ == "__main__":
    main()
