"""Frozen-fit parity, recovery and paired full-execution cost measurements."""

import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import time

import numpy as np
import scipy
import torch

from tools.hcsn.round8_20261031.state_task.data import make_data
from tools.hcsn.round8_20261031.state_task.models import RiskModel, load_state
from tools.hcsn.round9_20261031.streaming.filter import StreamingFilter

HERE = Path(__file__).resolve().parent
R8 = HERE.parents[1] / "round8_20261031" / "state_task"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def output(risk, query):
    return json.dumps({"risk": risk.tolist(), "protect": (risk > query[:, 4]).tolist()},
                      separators=(",", ":"))


def reference(model, history, lengths, query):
    with torch.no_grad():
        return model(torch.tensor(history, dtype=torch.float32),
                     torch.tensor(lengths, dtype=torch.int64),
                     torch.tensor(query, dtype=torch.float32)).numpy()


def build(arm):
    if arm == "ordinary_exact":
        return RiskModel("fixed_ordinary_filter").eval(), None
    seed = int(arm.rsplit("_", 1)[1])
    saved = json.loads((R8 / "evidence" / "models" / f"analytic_filter_{seed}.json").read_text())
    return load_state("analytic_filter", saved["state"]), saved["state"]


def quality(data, model, parameters):
    history, lengths, query = (data[k] for k in ("history", "lengths", "query"))
    one = StreamingFilter(len(history), parameters)
    one.update(history, lengths)
    baseline = reference(model, history, lengths, query)
    risk = one.predict(query)
    stream = StreamingFilter(len(history), parameters)
    recovered = None
    for step in range(history.shape[1]):
        count = (lengths > step).astype(np.int64)
        stream.update(history[:, step:step + 1], count)
        if recovered is not None:
            recovered.update(history[:, step:step + 1], count)
        if step == 15:
            recovered = StreamingFilter.restore(stream.checkpoint(), stream.identity)
    exact_recovery = (stream.checkpoint() == recovered.checkpoint()
                      and np.array_equal(stream.predict(query), recovered.predict(query)))
    action = risk > query[:, 4]
    optimal = data["probability"] > query[:, 4]
    regret = np.where(action != optimal, np.abs(data["probability"] - query[:, 4]), 0.)
    return {"examples": len(history), "max_probability_difference_from_torch": float(np.max(np.abs(risk - baseline))),
            "max_difference_block_vs_stream": float(np.max(np.abs(risk - stream.predict(query)))),
            "action_disagreements_from_torch": int(np.sum(action != (baseline > query[:, 4]))),
            "teacher_mse": float(np.mean((risk - data["probability"]) ** 2)),
            "action_regret": float(regret.mean()), "exact_resume": exact_recovery,
            "state_bytes_per_episode": one.state_bytes / len(history),
            "history_bytes_per_episode": history.nbytes / len(history)}


def malformed_checks():
    state = StreamingFilter()
    state.update([[[.1, .2, .5]]])
    saved = state.checkpoint()
    checks = {}
    for name, bad in (("negative_dt", [[[.1, -.2, .5]]]),
                      ("zero_sensor", [[[.1, .2, 0.]]]),
                      ("nonfinite_input", [[[float("nan"), .2, .5]]])):
        try:
            state.update(bad)
        except ValueError:
            checks[name] = state.checkpoint() == saved
        else:
            checks[name] = False
    for name, change in (("wrong_model", {"identity": "wrong"}),
                         ("negative_precision", {"b": [-1.]}),
                         ("fractional_count", {"count": [1.5]}),
                         ("bad_state_shape", {"a_error": [0., 0.]}),
                         ("nonfinite_state", {"a": [float("nan")]})):
        payload = json.dumps(json.loads(saved) | change)
        try:
            StreamingFilter.restore(payload, state.identity)
        except ValueError:
            checks[name] = True
        else:
            checks[name] = False
    fresh = StreamingFilter()
    checks["irregular_block_resume"] = bool(np.allclose(state.predict([[1., .2, .3, 0., .4]]),
        StreamingFilter.restore(saved, state.identity).predict([[1., .2, .3, 0., .4]]), atol=0, rtol=0))
    checks["empty_history_valid"] = bool(np.isfinite(fresh.predict([[1., .2, .3, 0., .4]])).all())
    return checks


def work(implementation, workload, model, parameters, history, lengths, query, query_calls):
    size = len(history)
    state = StreamingFilter(size, parameters) if implementation == "r9_numpy_sufficient_state" else None
    sink = 0
    if workload == "update_and_query_each_observation":
        for step in range(history.shape[1]):
            if state is None:
                risk = reference(model, history[:, :step + 1], np.minimum(lengths, step + 1), query)
            else:
                state.update(history[:, step:step + 1], (lengths > step).astype(np.int64))
                risk = state.predict(query)
            sink += len(output(risk, query))
    else:
        if state is not None:
            state.update(history, lengths)
        count = query_calls if workload == "ingest_once_query_32_times" else 1
        for _ in range(count):
            risk = reference(model, history, lengths, query) if state is None else state.predict(query)
            sink += len(output(risk, query))
    return sink


def benchmark(protocol, data):
    settings = protocol["benchmark"]
    raw, setup, checkpoints = [], [], []
    for arm in settings["arms"]:
        c, w = time.process_time(), time.perf_counter()
        model, parameters = build(arm)
        setup.append({"arm": arm, "cpu_seconds": time.process_time() - c,
                      "wall_seconds": time.perf_counter() - w,
                      "includes": "JSON weights read and model construction; imports excluded"})
        for size in settings["batch_sizes"]:
            history, lengths, query = (data[k][:size] for k in ("history", "lengths", "query"))
            state = StreamingFilter(size, parameters)
            state.update(history, lengths)
            c, w = time.process_time(), time.perf_counter()
            encoded = state.checkpoint()
            restored = StreamingFilter.restore(encoded, state.identity)
            checkpoints.append({"arm": arm, "batch_size": size, "cpu_seconds": time.process_time() - c,
                                "wall_seconds": time.perf_counter() - w, "serialized_bytes": len(encoded),
                                "exact": restored.checkpoint() == encoded})
            for workload in settings["workloads"]:
                args = (workload, model, parameters, history, lengths, query, settings["cached_query_calls"])
                for implementation in settings["implementations"]:
                    for _ in range(settings["warmup_calls"]):
                        work(implementation, *args)
                for repeat in range(settings["measured_rounds"]):
                    order = settings["implementations"][::1 if repeat % 2 == 0 else -1]
                    for implementation in order:
                        c, w = time.process_time(), time.perf_counter()
                        sink = work(implementation, *args)
                        raw.append({"arm": arm, "batch_size": size, "workload": workload,
                                    "implementation": implementation, "round": repeat,
                                    "cpu_seconds": time.process_time() - c,
                                    "wall_seconds": time.perf_counter() - w, "serialized_output_bytes": sink})
    grouped = {}
    for row in raw:
        key = (row["arm"], row["batch_size"], row["workload"], row["implementation"])
        grouped.setdefault(key, []).append(row)
    summary = [{"arm": k[0], "batch_size": k[1], "workload": k[2], "implementation": k[3],
                "median_cpu_seconds": statistics.median(x["cpu_seconds"] for x in rows),
                "median_wall_seconds": statistics.median(x["wall_seconds"] for x in rows),
                "min_cpu_seconds": min(x["cpu_seconds"] for x in rows),
                "max_cpu_seconds": max(x["cpu_seconds"] for x in rows)} for k, rows in grouped.items()]
    return {"raw": raw, "summary": summary, "setup": setup, "checkpoint_roundtrip": checkpoints}


def main():
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    protocol = json.loads((HERE / "protocol.json").read_text())
    evidence = HERE / "evidence"
    evidence.mkdir(exist_ok=True)
    if (evidence / "results.json").exists():
        raise FileExistsError("refusing to overwrite evidence")
    frozen = json.loads((R8 / "FREEZE.json").read_text())["source_and_checkpoint_sha256"]
    for relative, expected in frozen.items():
        if (R8 / relative).exists() and digest(R8 / relative) != expected:
            raise RuntimeError("R8 frozen file changed: " + relative)
    registration = {"sources": {name: digest(HERE / name) for name in ("filter.py", "audit.py", "protocol.json")},
                    "r8_freeze_sha256": digest(R8 / "FREEZE.json"),
                    "r8_amendment_sha256": digest(R8 / "CONFIRMATION_AMENDMENT.json"),
                    "fit_sha256": {str(seed): digest(R8 / "evidence" / "models" / f"analytic_filter_{seed}.json")
                                   for seed in protocol["quality"]["fit_seeds"]},
                    "written_before_evaluation": True}
    register_path = evidence / "REGISTERED.json"
    if register_path.exists():
        if json.loads(register_path.read_text()) != registration:
            raise RuntimeError("registered sources changed")
    else:
        register_path.write_text(json.dumps(registration, indent=2) + "\n")
    data_protocol = json.loads((R8 / "protocol.json").read_text())
    data_protocol["data_seeds"].update(protocol["quality"]["data_seeds"])
    rows, generation = [], []
    for regime in protocol["quality"]["regimes"]:
        c, w = time.process_time(), time.perf_counter()
        data = make_data(regime, data_protocol)
        generation.append({"regime": regime, "cpu_seconds": time.process_time() - c,
                           "wall_seconds": time.perf_counter() - w,
                           "input_sha256": hashlib.sha256(b"".join(data[k].tobytes()
                           for k in ("history", "lengths", "query"))).hexdigest()})
        arms = [f"calibrated_analytic_{seed}" for seed in protocol["quality"]["fit_seeds"]] + ["ordinary_exact"]
        for arm in arms:
            model, parameters = build(arm)
            rows.append({"arm": arm, "regime": regime} | quality(data, model, parameters))
    checks = malformed_checks()
    costs = benchmark(protocol, data)
    old_training = json.loads((R8 / "evidence" / "training.json").read_text())
    cost_accounting = {"r9_training_cpu_seconds": 0., "r8_all_model_search_cpu_seconds": sum(x["cpu_seconds"] for x in old_training),
                       "r8_analytic_all_three_fits_cpu_seconds": sum(x["cpu_seconds"] for x in old_training if x["model"] == "analytic_filter"),
                       "r8_ordinary_exact_training_cpu_seconds": 0.,
                       "energy_joules": None,
                       "energy_observation": {"powercap_present": Path("/sys/class/powercap").exists(),
                                              "nvidia_device_present": Path("/dev/nvidia0").exists()},
                       "scope": "Run costs include real execution and JSON serialization. Prior R8 data-generation/setup costs remain in original R8 evidence; not recomputed as zero."}
    acceptance = {"numerical_parity": all(x["max_probability_difference_from_torch"] <= protocol["quality"]["max_probability_difference"] for x in rows),
                  "same_actions": all(x["action_disagreements_from_torch"] == 0 for x in rows),
                  "exact_recovery": all(x["exact_resume"] for x in rows),
                  "chunking": all(x["max_difference_block_vs_stream"] < 1e-12 for x in rows),
                  "malformed_inputs": all(checks.values()), "independent_spiking_necessity": False,
                  "energy_advantage_measured": False}
    result = {"registration_sha256": digest(register_path), "quality": rows, "checks": checks,
              "costs": costs, "cost_accounting": cost_accounting, "data_generation": generation,
              "acceptance": acceptance, "environment": {"python": platform.python_version(), "numpy": np.__version__,
                  "scipy": scipy.__version__, "torch": torch.__version__, "cpu_count": os.cpu_count(),
                  "threads": torch.get_num_threads(), "shared_host": True},
              "audit_cpu_seconds": time.process_time() - started_cpu,
              "audit_wall_seconds": time.perf_counter() - started_wall}
    (evidence / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"acceptance": acceptance, "quality_rows": len(rows),
                      "benchmark_rows": len(costs["raw"]), "audit_cpu_seconds": result["audit_cpu_seconds"]}))
    if not all(acceptance[k] for k in ("numerical_parity", "same_actions", "exact_recovery", "chunking", "malformed_inputs")):
        raise AssertionError("streaming implementation acceptance failed; preserve evidence")


if __name__ == "__main__":
    main()
