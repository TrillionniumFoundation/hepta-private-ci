"""One bounded 21-fit D-calibration process; original E and training gates stay HOLD."""

from collections import Counter
import io
import json
import os
from pathlib import Path
import platform
import resource
import sys
import time

from io_contract import canonical, digest, identity, read_exact, require, save, verify_sources


def main(root, stage_started):
    body_started, cpu_started = time.monotonic(), time.process_time()
    request = json.loads((root / "REQUEST.json").read_text())
    output = root / "RESULTS"; output.mkdir(exist_ok=False)
    counters, receipts, failure, current_name = Counter(), [], None, None
    journal = (output / "events.jsonl").open("x")

    def observe(event):
        counters[event["event"]] += 1
        journal.write(json.dumps({"name": current_name, "elapsed_stage_seconds": time.monotonic() - stage_started,
                                  **event}, sort_keys=True, allow_nan=False) + "\n")
        journal.flush()

    def checkpoint():
        require(time.monotonic() - stage_started < request["budget"]["whole_seconds"] - request["budget"]["reserve_seconds"],
                "D-only stage work deadline; preserve partial receipts without retry")
        require(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 <= request["budget"]["rss_bytes"], "RSS cap")

    try:
        resource.setrlimit(resource.RLIMIT_AS, (request["budget"]["address_space_bytes"],) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (request["budget"]["whole_seconds"],) * 2)
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
        import numpy as np
        import torch
        from numpy._core import _multiarray_umath
        from reference import verify
        from solver import fit, validate
        torch.set_num_threads(1); torch.set_num_interop_threads(1); torch.set_grad_enabled(False)
        freeze = verify_sources(root)
        dispatch = json.loads((root / "DISPATCH.json").read_text())
        require(dispatch["source_freeze_sha256"] == freeze["sha256"], "dispatch frozen-source identity")
        ledger = json.loads((root / "INPUT_LEDGER.json").read_text())
        require(identity(root / "INPUT_LEDGER.json")["sha256"] == request["ledger_sha256"], "fixed selection ledger")
        require(len(ledger["roster"]) == 21 and len({r["name"] for r in ledger["roster"]}) == 21, "complete fixed roster")
        require(request["E_access_authorized"] is False and request["automatic_trigger"] is False
                and request["scientific_admission"] == "HOLD", "D-only authority")
        require(ledger["scientific_admission"] == "HOLD" and ledger["original_controller_terminal"] == "UNKNOWN"
                and ledger["independent_original_full_training_replays"] == "0/6", "unchanged prior gates")
        runtime_paths = [Path(sys.executable).resolve(), Path(np.__file__), Path(_multiarray_umath.__file__),
                         Path(torch.__file__), Path(torch._C.__file__), Path(torch.serialization.__file__),
                         Path(torch.__file__).parent / "lib/libtorch_cpu.so"]
        runtime = {"python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__,
                   "torch_git": torch.version.git_version, "executable": sys.executable,
                   "resolved_executable_sha256": identity(runtime_paths[0])["sha256"],
                   "affinity": sorted(os.sched_getaffinity(0)), "torch_threads": torch.get_num_threads(),
                   "torch_interop_threads": torch.get_num_interop_threads(),
                   "longdouble_epsilon": str(np.finfo(np.longdouble).eps),
                   "runtime_files": [identity(p) for p in runtime_paths],
                   "scope": "Named interpreter/package/native arithmetic artifacts, not a claim of every dynamic dependency or old cu128 runtime equivalence."}
        for key, expected in request["expected_runtime"].items():
            require(runtime[key] == expected, "frozen runtime field: " + key)
        save(output / "RUNTIME_BEFORE.json", runtime)
        observe({"event": "runtime_and_selection_frozen", "runtime_sha256": digest(canonical(runtime)),
                 "ledger_sha256": request["ledger_sha256"], "source_freeze": freeze})
        for selected in ledger["roster"]:
            checkpoint(); current_name = selected["name"]
            observe({"event": "D_artifact_read_started"})
            fit_started, fit_cpu = time.monotonic(), time.process_time()
            blob = read_exact(selected["D_logits"])
            data = torch.load(io.BytesIO(blob), map_location="cpu", weights_only=True)
            logits, labels = data["logits"].numpy(), data["labels"].numpy()
            validate(logits, labels)
            require(logits.shape == (31952, 11) and labels.shape == (31952,), "full fixed D rows")
            require(digest(logits.tobytes()) == selected["D_logits_array_sha256"]
                    and digest(labels.tobytes()) == selected["D_label_array_sha256"], "bound D arrays")
            ids = data["episode_ids"]
            require(all(type(s) is str and s.startswith("D") for s in ids)
                    and digest(canonical(ids)) == selected["D_episode_order_sha256"], "D-only episode order")
            observe({"event": "D_artifact_verified", "D_logits_sha256": selected["D_logits"]["sha256"],
                     "model_binding_sha256": selected["model_binding_sha256"]})
            result = fit(logits, labels, checkpoint=checkpoint, observe=observe)
            check_started, check_cpu = time.monotonic(), time.process_time()
            arithmetic = verify(logits, labels, result, checkpoint=checkpoint, observe=observe)
            check_wall, check_used_cpu = time.monotonic() - check_started, time.process_time() - check_cpu
            read_exact(selected["D_logits"])
            receipt = {"schema": "fixed-selected-D-temperature-receipt-v1", "name": current_name,
                       "selected_model": selected, "fit": result, "independent_arithmetic": arithmetic,
                       "body_wall_seconds": time.monotonic() - fit_started, "body_cpu_seconds": time.process_time() - fit_cpu,
                       "included_reference_wall_seconds": check_wall, "included_reference_cpu_seconds": check_used_cpu,
                       "cost_scope": "Per-model D read, scalar fit, independent arithmetic and final input hash; excludes this receipt serialization; reference timers are nested.",
                       "E_payload_or_labels_accessed": False, "neural_model_construction_calls": 0,
                       "neural_model_forward_backward_calls": 0, "neural_optimizer_operations": 0,
                       "scalar_parameter_optimization_calls": 1, "status": "CALIBRATED_AND_ARITHMETIC_CHECKED"}
            record = save(output / (current_name + ".json"), receipt)
            receipts.append({"name": current_name, "model_binding_sha256": selected["model_binding_sha256"],
                             "D_logits_sha256": selected["D_logits"]["sha256"], "beta": result["beta"],
                             "temperature": result["temperature"], "receipt": record})
            observe({"event": "temperature_receipt_frozen", "receipt": record})
            print(json.dumps({"name": current_name, "status": receipt["status"], "beta": result["beta"],
                              "bisection_updates": result["bisection_updates"]}), flush=True)
            del data, blob, logits, labels
        after = [identity(p) for p in runtime_paths]
        require(after == runtime["runtime_files"], "runtime bytes changed during calibration")
        save(output / "RUNTIME_AFTER.json", {"runtime_files": after, "same_as_before": True})
        verify_sources(root)
    except Exception as error:
        failure = {"name": current_name, "type": type(error).__name__, "message": str(error)}
        observe({"event": "failure_preserved_no_retry", "failure": failure})
        save(output / "FAILURE.json", failure)
    journal.flush(); os.fsync(journal.fileno()); journal.close()
    complete = failure is None and len(receipts) == 21
    manifest = {"schema": "fixed-21-D-temperature-manifest-v1", "status": "COMPLETE_E_BLOCKED" if complete else "HOLD_INCOMPLETE",
                "source_parent_commit": request["source_parent_commit"], "ledger_sha256": request["ledger_sha256"],
                "dispatch": json.loads((root / "DISPATCH.json").read_text()),
                "source_freeze": identity(root / "SOURCE_FREEZE.json"), "receipts": receipts, "counts": dict(counters),
                "journal": identity(output / "events.jsonl"), "complete_temperatures": len(receipts), "failure": failure,
                "body_wall_seconds": time.monotonic() - body_started, "body_cpu_seconds": time.process_time() - cpu_started,
                "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "cost_scope": "Runner main body including scientific imports; full child process measured separately by supervisor. Per-fit/reference timers are nested.",
                "E_payload_or_labels_accessed": False, "E_execution_authorized": False, "automatic_trigger": False,
                "neural_model_forward_backward_calls": 0, "neural_optimizer_operations": 0,
                "original_controller_terminal": "UNKNOWN", "independent_original_full_training_replays": "0/6",
                "scientific_admission": "HOLD", "retry_count": 0}
    save(output / "TEMPERATURE_MANIFEST.json", manifest)
    print(json.dumps({"status": manifest["status"], "complete_temperatures": len(receipts), "counts": dict(counters)}), flush=True)
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), float(sys.argv[2])))
