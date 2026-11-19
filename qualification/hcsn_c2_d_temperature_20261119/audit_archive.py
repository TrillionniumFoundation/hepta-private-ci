"""Read original calibration bytes and reconcile identities, trajectories and costs."""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import resource
import sys
import time
import zipfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def audit(root):
    started, cpu = time.monotonic(), time.process_time()
    native = root / "evidence/native"
    metadata_bytes = (native / "ARCHIVE.json").read_bytes()
    metadata = json.loads(metadata_bytes)
    terminal = json.loads((native / "STAGE_TERMINAL.json").read_bytes())
    archive_bytes = (native / "calibration-originals.zip").read_bytes()
    require(sha(archive_bytes) == metadata["archive"]["sha256"], "archive digest")
    require(len(archive_bytes) == metadata["archive"]["bytes"], "archive size")
    require(sha(metadata_bytes) == terminal["archive"]["sha256"], "terminal archive binding")
    with zipfile.ZipFile(native / "calibration-originals.zip") as archive:
        require(len(archive.namelist()) == len(set(archive.namelist())), "no duplicate members")
        require(set(archive.namelist()) == set(metadata["members"]), "all original members")
        contents = {name: archive.read(name) for name in archive.namelist()}
    for name, data in contents.items():
        require(sha(data) == metadata["members"][name]["sha256"], "original member digest: " + name)
        require(len(data) == metadata["members"][name]["bytes"], "original member size: " + name)
    parse = lambda name: json.loads(contents[name])
    freeze = parse("SOURCE_FREEZE.json")
    for name, expected in freeze["files"].items():
        require(sha(contents[name]) == expected, "pre-dispatch source/input digest: " + name)
        require((root / name).read_bytes() == contents[name], "unchanged dispatched source/input: " + name)
    dispatch = parse("DISPATCH.json")
    require(sha(contents["SOURCE_FREEZE.json"]) == dispatch["source_freeze_sha256"], "dispatch freeze")
    require(sha((root / "evidence/dispatch/DISPATCH_WRAPPER.py").read_bytes()) == dispatch["wrapper_sha256"], "wrapper bytes")
    runtime = parse("RESULTS/RUNTIME_BEFORE.json")
    after = parse("RESULTS/RUNTIME_AFTER.json")
    require(after["same_as_before"] and after["runtime_files"] == runtime["runtime_files"], "unchanged native runtime")
    request = parse("REQUEST.json")
    for key, expected in request["expected_runtime"].items():
        require(runtime[key] == expected, "pinned runtime: " + key)
    ledger = parse("INPUT_LEDGER.json")
    manifest = parse("RESULTS/TEMPERATURE_MANIFEST.json")
    require(manifest["status"] == "COMPLETE_E_BLOCKED" and manifest["failure"] is None, "complete stage")
    require(manifest["complete_temperatures"] == 21 and len(manifest["receipts"]) == 21, "all 21 receipts")
    require(manifest["ledger_sha256"] == sha(contents["INPUT_LEDGER.json"]), "input ledger binding")
    require(manifest["dispatch"] == dispatch, "exact dispatch binding")
    require(manifest["retry_count"] == 0 and not manifest["E_execution_authorized"]
            and not manifest["E_payload_or_labels_accessed"] and not manifest["automatic_trigger"], "scope")
    require(manifest["neural_model_forward_backward_calls"] == 0 and manifest["neural_optimizer_operations"] == 0, "no neural work")
    require(manifest["independent_original_full_training_replays"] == "0/6"
            and manifest["original_controller_terminal"] == "UNKNOWN", "historical gates retained")
    roster = {row["name"]: row for row in ledger["roster"]}
    require(len(roster) == 21 and set(roster) == {row["name"] for row in manifest["receipts"]}, "exact selected roster")
    events = [json.loads(line) for line in contents["RESULTS/events.jsonl"].splitlines()]
    require(dict(Counter(event["event"] for event in events)) == manifest["counts"], "complete journal accounting")
    require(sha(contents["RESULTS/events.jsonl"]) == manifest["journal"]["sha256"], "journal digest")
    rows, maximum_error, evaluations, references, updates = [], 0., 0, 0, 0
    for item in manifest["receipts"]:
        name = item["name"]
        receipt_bytes = contents["RESULTS/" + name + ".json"]
        require(sha(receipt_bytes) == item["receipt"]["sha256"] and len(receipt_bytes) == item["receipt"]["bytes"], "receipt identity")
        receipt = json.loads(receipt_bytes)
        require(receipt["selected_model"] == roster[name], "exact selected model and D identity")
        fit, arithmetic = receipt["fit"], receipt["independent_arithmetic"]
        require(receipt["status"] == "CALIBRATED_AND_ARITHMETIC_CHECKED" and arithmetic["status"] == "PASS", "completed fit/check")
        require(arithmetic["strict_KKT_or_bracket_signs"] is True, "actual strict bracket signs")
        require(fit["outcome"] == "INTERIOR", "observed interior outcome")
        require(fit["beta"] == item["beta"] and fit["temperature"] == item["temperature"] == 1 / fit["beta"], "temperature parameter")
        require(fit["argmax_unchanged"] and arithmetic["argmax_unchanged"], "reported unchanged predictions")
        low, high = .01, 100.
        for number, step in enumerate(fit["trace"], 1):
            mid = low + (high - low) / 2
            require(step["iteration"] == number and step["lower_before"] == low
                    and step["upper_before"] == high and step["midpoint"] == mid, "saved bisection chain")
            require(step["move"] == ("lower" if step["gradient"] < 0 else "upper"), "saved gradient move")
            if step["move"] == "lower":
                low = mid
            else:
                high = mid
        require(fit["beta"] == low + (high - low) / 2
                and high - low <= 1e-12 * max(1., abs(fit["beta"])), "original stopping rule")
        require(fit["final_bracket"]["lower"] == low and fit["final_bracket"]["upper"] == high, "saved final bracket")
        require(fit["final"]["nll"] <= fit["raw"]["nll"], "actual D NLL did not increase")
        for value in fit["evaluations"]:
            require(all(math.isfinite(value[key]) for key in ["beta", "nll", "gradient", "hessian"]), "finite saved evaluations")
            require(value["hessian"] >= 0, "convex saved objective")
        evaluations += fit["objective_derivative_hessian_evaluations"]
        references += arithmetic["independent_reference_evaluations"]
        updates += fit["bisection_updates"]
        maximum_error = max(maximum_error, *(error["absolute_error"] for error in arithmetic["errors"]))
        rows.append({"name": name, "temperature": fit["temperature"], "beta": fit["beta"],
                     "D_raw_nll": fit["raw"]["nll"], "D_calibrated_nll": fit["final"]["nll"],
                     "strict_bracket_signs": True, "argmax_unchanged": True})
    require((evaluations, references, updates) == (manifest["counts"]["calibration_evaluation_completed"],
            manifest["counts"]["reference_evaluation_completed"], manifest["counts"]["bisection_update"]), "receipt/journal counters")
    child = parse("CHILD_COST.json")
    require(child == terminal["child"] and child["exit_code"] == 0 and not child["killed_at_phase_limit"], "measured child exit")
    require(child["child_peak_rss_kib"] * 1024 <= request["budget"]["rss_bytes"], "actual RSS limit")
    require(terminal["stage_elapsed_before_terminal_receipt_seconds"] < request["budget"]["whole_seconds"], "stage duration limit")
    job = json.loads((root / "evidence/dispatch/RECOVERED_JOB.json").read_text())
    status = json.loads(job["final_status"]["value"]["content"][0]["text"])
    require(status["exit_code"] == 0 and status["state"] == "succeeded" and status["output_complete"]
            and status["output_durable"] and status["terminal_publication_confirmed"], "authoritative native terminal")
    return {"schema": "D-calibration-archive-audit-v1", "status": "PASS", "verified_members": len(contents),
            "archive_sha256": sha(archive_bytes), "temperature_manifest_sha256": sha(contents["RESULTS/TEMPERATURE_MANIFEST.json"]),
            "source_commit": dispatch["source_commit"], "native_job": status["job_id"], "temperatures": rows,
            "completed_temperatures": len(rows), "float64_longdouble_max_absolute_error": maximum_error,
            "scalar_objective_evaluations": evaluations, "independent_arithmetic_evaluations": references,
            "bisection_updates": updates, "all_strict_bracket_signs": True,
            "model_forward_backward_optimizer_calls": 0, "E_access": False,
            "historical_original_training_replays": "0/6", "original_controller_terminal": "UNKNOWN",
            "scientific_admission": "HOLD", "whole_native_child_cost": child,
            "audit_body_wall_seconds": time.monotonic() - started,
            "audit_body_cpu_seconds": time.process_time() - cpu,
            "audit_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "audit_scope": "Read-only original archive/source/identity/trajectory/cost reconciliation; no D logits, model inference, temperature refit or independent gradient recalculation."}


if __name__ == "__main__":
    report = audit(Path(__file__).resolve().parent)
    output = Path(sys.argv[1])
    with output.open("x") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "models": report["completed_temperatures"],
                      "archive_sha256": report["archive_sha256"]}))
