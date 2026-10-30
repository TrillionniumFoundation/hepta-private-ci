"""Frozen development-first experiment; heldout construction is gate-dependent."""
import time
IMPORT_START = time.perf_counter()
import argparse
import json
import os
import traceback
from identity import HERE, protocol, save, sha, freeze, verify
from adapter import ContentAdapter
from cohorts import prepare_development, calibrate, prepare_heldout
from training_v2 import seed_data, train_one
from audit_v2 import validate_numerical, recompute_gate
from execute_v2 import run_confirmation
IMPORT_SECONDS = time.perf_counter()-IMPORT_START


def run():
    verify()
    assert not (HERE / "development_results.json").exists(), "Never replace an exposed study"
    start, cpu = time.perf_counter(), time.process_time()
    numerical = validate_numerical()
    manifest = prepare_development()
    adapter = ContentAdapter()
    result = dict(complete=False, runs=[], seed_costs=[],
        source_import_wall_seconds=IMPORT_SECONDS, numerical_validation=numerical,
        adapter_setup=adapter.setup, data={k: v for k, v in manifest.items() if k not in ("records", "files", "calibration")},
        scientific_freeze_sha256=sha(HERE / "freeze.json"),
        development_manifest_sha256=sha(HERE / "development_manifest.json"),
        environment=dict(python=os.sys.version, affinity=sorted(os.sched_getaffinity(0)),
                         blas_threads=os.environ.get("OPENBLAS_NUM_THREADS")))
    save(HERE / "development_results.json", result)
    calibrations = {}
    for seed in protocol()["seeds"]:
        confusion, calibrated = calibrate(seed, adapter, manifest)
        calibrations[str(seed)] = confusion.tolist()
        train, val, mean, scale, costs = seed_data(seed, manifest, confusion)
        costs.update(calibration_wall_seconds=calibrated["wall_seconds"], calibration_cpu_seconds=calibrated["cpu_seconds"])
        result["seed_costs"].append(costs)
        for family in protocol()["families"]:
            result["runs"].append(train_one(seed, family, train, val, mean, scale))
            save(HERE / "development_results.json", result)
    result.update(complete=True, development_wall_seconds=time.perf_counter()-start,
                  development_cpu_seconds=time.process_time()-cpu)
    save(HERE / "development_results.json", result)
    gate = recompute_gate(result["runs"])
    save(HERE / "gate.json", gate)
    if gate["passed"]:
        heldout = prepare_heldout(manifest, gate)
        confirmation = run_confirmation(heldout, result, adapter, calibrations)
    else:
        assert not (HERE / "heldout").exists()
        confirmation = dict(status="not_generated_development_gate_failed", policy_sessions=0,
            no_heldout_metadata_or_payload_constructed=True, gate_sha256=sha(HERE / "gate.json"),
            meaning="All15 trainings preserved; no threshold change, added tuning or confirmation generation")
        save(HERE / "confirmation.json", confirmation)
    save(HERE / "completion.json", dict(complete=True, development_gate_passed=gate["passed"],
        heldout_status=confirmation["status"], total_wall_seconds=time.perf_counter()-start,
        total_cpu_seconds=time.process_time()-cpu, source_import_wall_seconds=IMPORT_SECONDS,
        original_v1_preserved=True, development_results_sha256=sha(HERE / "development_results.json")))
    verify()
    print(json.dumps(dict(complete=True, gate=gate, confirmation=confirmation["status"])), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "run"))
    action = parser.parse_args().action
    if action == "freeze":
        print(json.dumps(freeze(), indent=2))
    else:
        try:
            run()
        except Exception:
            save(HERE / "failure.json", dict(traceback=traceback.format_exc()))
            raise
