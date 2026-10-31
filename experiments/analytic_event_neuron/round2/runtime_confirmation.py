"""Qualification-only operational amendment; frozen inference is imported unchanged.

Default admission is the preregistered runtime_confirmation split. Explicit
parity_only=True accepts development data and labels its result as parity only.
No dataset is relabeled, and no training or model selection occurs here.
"""

import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from . import runtime_bridge as frozen_engine
from .runtime_bridge import AdaptiveEventRuntime, Native, ZERO, _atomic, _read, digest, file_sha


def qualify_confirmation(models_file, model_key, dataset_file, output, native_binary, native_receipt, runtime_mode="count_only", *, parity_only=False):
    """Qualify frozen engines on the registered fresh split, or explicit development parity."""
    began, parent_cpu = time.perf_counter_ns(), time.process_time_ns()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    checks, records, recovery, stress_records = [], [], [], []
    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append({"name": name, "passed": True})
    model_sha, data_sha = file_sha(models_file), file_sha(dataset_file)
    with np.load(dataset_file, allow_pickle=False) as source:
        required_split = "development" if parity_only else "runtime_confirmation"
        check("explicit qualification split only", type(parity_only) is bool and str(source["split"].item()) == required_split)
        histories = []
        for i in range(min(4, len(source["ids"]))):
            histories.append({"id": str(source["ids"][i]), "observations": source["obs"][i].tolist(),
                              "times": source["times"][i].tolist(), "mask": source["mask"][i].tolist(),
                              "obs_var": source["obs_var"][i].tolist()})
    settings = {"models_file": str(Path(models_file).resolve()), "model_key": model_key,
                "dataset_digest": data_sha, "directory": str((output / "owners").resolve()),
                "expected_model_sha256": model_sha, "runtime_mode": runtime_mode}
    with Native(native_binary, native_receipt) as native:
        adapter = AdaptiveEventRuntime(native=native, **settings)
        for history in histories:
            for horizon in (0.5, 1.0, 2.0):
                record = adapter.step(history, horizon, "forecast.1", 1)
                records.append(record)
                check("reopened receiver feeds declared head", record["decoder_reopened_from_disk_before_native"] and not record["encoder_residual_used_by_native"]
                      and bool(np.allclose(record["native"]["input_parameters_fp64"][:2],
                                           [record["head_mean"], record["head_variance"]], rtol=0.0, atol=2e-15)))
                if runtime_mode == "anchor_guarded":
                    bound = record["protected_density_bounds"]["after_native_q24_input"]
                    check("actual native Q24 Gaussian has certified old-loss envelope", bound["finite"] and bound["upper_bound"] <= adapter.model["epsilon"] + 1e-12
                          and record["explicit_frozen_anchor_reference"])
                    check("delivered Q24 events have their own protection certificate",
                          record["categorical_guard_certificate"]["exact_mass"]
                          and record["categorical_guard_certificate"]["maximum_event_nll_excess"] <= adapter.model["epsilon"] + 1e-12
                          and record["delivered_probability_source"] == "post_native_research_adapter"
                          and not record["original_rust_witness_binds_post_projection"])
                check("codec probability bound", bool(np.all(np.asarray(record["codec_probability_error"]) <= np.asarray(record["codec_probability_bound"]) + 2e-15)))
                check("qualified numerical head", record["native_cdf_error"] <= 2e-15 and record["native_output_q24_error"] <= 1 / (1 << 24) + 2e-15)
                check("non-authorizing original runtime", record["native"]["abstain"] and record["native"]["legacy_runtime_confidence_ppm"] == 0
                      and record["native"]["original_neuron_runtime"] and record["native"]["independent_anchor_witness"])
        first = records[0]
        try:
            adapter.step(histories[0], 0.5, "stale", 2, expected_checkpoint=ZERO)
        except ValueError:
            check("stale CAS rejected before native", native.calls == len(records))
        else:
            raise AssertionError("stale CAS accepted")
        changed = {**histories[0], "observations": list(histories[0]["observations"])}
        observed_index = next(i for i, present in enumerate(changed["mask"]) if present)
        changed["observations"][observed_index] += 0.01
        try:
            adapter.step(changed, 0.5, "forecast.1", 1)
        except ValueError:
            check("duplicate identity with changed public evidence rejected", native.calls == len(records))
        else:
            raise AssertionError("Changed duplicate accepted")
    for index, step in enumerate([
        {"history": histories[0], "horizon": 0.5, "tick_id": "forecast.1", "sequence": 1},
        {"history": histories[0], "horizon": 0.5, "tick_id": "forecast.2", "sequence": 2,
         "expected_checkpoint": first["checkpoint_after"], "observation_kind": "propagation"},
    ]):
        job = {**settings, "native_binary": str(Path(native_binary).resolve()),
               "native_receipt": str(Path(native_receipt).resolve()), "step": step}
        path, result_path = output / f"recovery_job_{index}.json", output / f"recovery_{index}.json"
        _atomic(path, job)
        completed = subprocess.run([sys.executable, "-m", "experiments.analytic_event_neuron.round2.runtime_bridge", "worker",
                                    "--job", str(path), "--output", str(result_path)], capture_output=True, text=True, check=False)
        if completed.returncode:
            raise RuntimeError(completed.stderr)
        result = json.loads(result_path.read_text())
        recovery.append(result)
    check("fresh-process duplicate produces no native tick", recovery[0]["receipt"] == first and recovery[0]["native_requests_this_process"] == 0)
    second = recovery[1]["receipt"]
    check("fresh-process continuation uses native ancestry", recovery[1]["native_ticks_this_process"] == 1
          and second["native"]["checkpoint_before"] == first["native"]["checkpoint_after"])
    check("unchanged forecast yields zero events, not a neutral label", second["packet"]["counts"] == [0, 0]
          and second["packet"]["observation_kind"] == "propagation" and second["decoded_probabilities"] == first["decoded_probabilities"])
    with Native(native_binary, native_receipt) as native:
        adapter = AdaptiveEventRuntime(native=native, **settings)
        ack = dict(histories[0], id=histories[0]["id"] + "/ack")
        try:
            adapter.step(ack, 1.0, "ack.1", 1, fail_stage="after_commit")
        except RuntimeError:
            pass
        acknowledged = adapter.step(ack, 1.0, "ack.1", 1)
        check("lost acknowledgement replays committed receipt", native.calls == 1 and acknowledged["sequence"] == 1)
        missing = {**histories[0], "id": histories[0]["id"] + "/missing",
                   "observations": list(histories[0]["observations"]), "mask": list(histories[0]["mask"])}
        missing["mask"][-1], missing["observations"][-1] = False, 12345.0
        absent = adapter.step(missing, 1.0, "missing.1", 1)
        calls = native.calls
        missing["observations"][-1] = -99999.0
        same = adapter.step(missing, 1.0, "missing.1", 1)
        check("missing storage does not become a zero observation or extra evidence",
              same == absent and native.calls == calls and absent["packet"]["observation_kind"] == "missing")
        rollback_case = dict(histories[0], id=histories[0]["id"] + "/rollback")
        before = adapter.step(rollback_case, 1.0, "rollback.1", 1)
        state_path = Path(settings["directory"]) / before["subject"] / "state.json"
        delivery_witness_path = state_path.with_name("delivery.witness.json")
        old_bytes = state_path.read_bytes()
        old_delivery_witness = delivery_witness_path.read_bytes()
        after = adapter.step(rollback_case, 1.0, "rollback.2", 2, expected_checkpoint=before["checkpoint_after"])
        new_bytes = state_path.read_bytes()
        new_delivery_witness = delivery_witness_path.read_bytes()
        state_path.write_bytes(old_bytes)
        calls = native.calls
        try:
            adapter.step(rollback_case, 1.0, "rollback.3", 3, expected_checkpoint=after["checkpoint_after"])
        except ValueError:
            check("independent delivery witness rejects composite-state rollback", native.calls == calls)
        else:
            raise AssertionError("Rollback accepted")
        finally:
            state_path.write_bytes(new_bytes)
        delivery_witness_path.write_bytes(old_delivery_witness)
        try:
            adapter.step(rollback_case, 1.0, "witness_rollback", 3, expected_checkpoint=after["checkpoint_after"])
        except ValueError:
            check("composite state rejects independent delivery-witness rollback", native.calls == calls)
        else:
            raise AssertionError("Delivery witness rollback accepted")
        finally:
            delivery_witness_path.write_bytes(new_delivery_witness)
        damaged = bytearray(new_bytes)
        damaged[0] = ord("[")
        state_path.write_bytes(damaged)
        try:
            adapter.step(rollback_case, 1.0, "corrupt", 3, expected_checkpoint=after["checkpoint_after"])
        except (ValueError, KeyError):
            check("corrupt composite state rejected", native.calls == calls)
        else:
            raise AssertionError("Corrupt state accepted")
        finally:
            state_path.write_bytes(new_bytes)
        witness_case = dict(histories[0], id=histories[0]["id"] + "/native_rollback")
        before = adapter.step(witness_case, 1.0, "witness.1", 1)
        journal_path = Path(settings["directory"]) / before["subject"] / "native/state.journal"
        first_journal = journal_path.read_bytes()
        after = adapter.step(witness_case, 1.0, "witness.2", 2, expected_checkpoint=before["checkpoint_after"])
        second_journal = journal_path.read_bytes()
        journal_path.write_bytes(first_journal)
        calls = native.calls
        try:
            adapter.step(witness_case, 1.0, "witness.3", 3, expected_checkpoint=after["checkpoint_after"])
        except ValueError:
            check("independent native witness rejects journal rollback", native.calls == calls)
        else:
            raise AssertionError("Native rollback accepted")
        finally:
            journal_path.write_bytes(second_journal)
        for stage in ("after_pending", "after_native"):
            case = dict(histories[0], id=histories[0]["id"] + "/" + stage)
            try:
                adapter.step(case, 1.0, "partial.1", 1, fail_stage=stage)
            except RuntimeError:
                pass
            calls = native.calls
            try:
                adapter.step(case, 1.0, "partial.1", 1)
            except RuntimeError:
                check("partial commit remains blocked: " + stage, native.calls == calls)
            else:
                raise AssertionError("Partial commit silently retried")
        bounded = AdaptiveEventRuntime(native=native, maximum_ticks=1, **settings)
        case = dict(histories[0], id=histories[0]["id"] + "/capacity")
        before = bounded.step(case, 1.0, "capacity.1", 1)
        calls = native.calls
        try:
            bounded.step(case, 1.0, "capacity.2", 2, expected_checkpoint=before["checkpoint_after"])
        except ValueError:
            check("bounded lifetime rejects additional ticks", native.calls == calls)
        else:
            raise AssertionError("Capacity exceeded")
        if runtime_mode == "anchor_guarded":
            # A numerical qualification fixture, not sampled efficacy evidence:
            # all observations share time zero and precise public noise.
            sensor_variance = 0.006 / adapter.model["anchor"]["parameters"][2]
            stress_history = {"id": histories[0]["id"] + "/categorical_tail_fixture",
                "observations": [2.0] * 6, "times": [0.0] * 6, "mask": [True] * 6,
                "obs_var": [sensor_variance] * 6}
            stress = adapter.step(stress_history, 0.0, "tail.1", 1)
            stress_records.append(stress)
            check("actual native tail rounding loses positive event support",
                  0 in stress["native"]["head"]["probabilities_q24"])
            check("post-native projection restores positive support and exact mass",
                  min(stress["delivered_probabilities_q24"]) > 0
                  and sum(stress["delivered_probabilities_q24"]) == 1 << 24
                  and stress["delivered_probabilities_q24"] != stress["native"]["head"]["probabilities_q24"])
            check("corrected delivered tail has certified event logscore bound",
                  stress["categorical_guard_certificate"]["maximum_event_nll_excess"] <= adapter.model["epsilon"] + 1e-12)
            witness = _read(Path(settings["directory"]) / stress["subject"] / "delivery.witness.json")
            check("independent delivery witness binds corrected tail and original native anchor",
                  witness["records"][-1]["delivered_output_sha256"] == digest(stress["delivered_probabilities_q24"])
                  and witness["records"][-1]["native_checkpoint"] == stress["native"]["checkpoint_after"])
    check("frozen source artifacts unchanged", file_sha(models_file) == model_sha and file_sha(dataset_file) == data_sha)
    protected = [r["protected_density_bounds"] for r in records if r["protected_density_bounds"] is not None]
    summary = {"schema": "hepta.signed-event.runtime-qualification.v1", "passed": True,
               "model_file_sha256": model_sha, "model_key": model_key, "dataset_file_sha256": data_sha,
               "native_binary_sha256": file_sha(native_binary), "current_session_fresh_build": False,
               "forecasts": len(records), "fresh_python_processes": len(recovery), "checks": checks,
               "deterministic_tail_fixtures": len(stress_records),
               "maximum_native_cdf_error": max(r["native_cdf_error"] for r in records),
               "maximum_output_q24_error": max(r["native_output_q24_error"] for r in records),
               "maximum_delivered_event_nll_excess": max((r["categorical_guard_certificate"]["maximum_event_nll_excess"]
                    for r in records if r["categorical_guard_certificate"] is not None), default=None),
               "runtime_mode": runtime_mode, "protected_postcodec_guarantee_claimed": runtime_mode == "anchor_guarded",
               "protected_density_bounds": protected,
               "source_sha256": file_sha(__file__), "production_agentd_owner": False,
               "qualification_data_role": required_split, "parity_only": parity_only,
               "frozen_engine_source_sha256": file_sha(frozen_engine.__file__),
               "wall_ns": time.perf_counter_ns() - began, "parent_cpu_ns": time.process_time_ns() - parent_cpu,
               "cost_scope": "Whole qualification including fresh processes and negative interventions; native timings and file sizes in per-tick receipts",
               "limitation": "Pending partial transactions require explicit reconciliation; no cross-owner atomicity claim"}
    for name, document in (("RUNTIME_QUALIFICATION.json", summary), ("FORECAST_RECEIPTS.json", records),
                           ("RECOVERY_RECEIPTS.json", recovery), ("STRESS_RECEIPTS.json", stress_records)):
        _atomic(output / name, document)
    return summary
