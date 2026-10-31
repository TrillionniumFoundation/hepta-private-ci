"""Paired costs against the NumPy baseline newly delivered at 00b94d5.

Retains the earlier Torch comparison. Varying-horizon queries avoid timing
32 identical answers. The ordinary filter receives the same state optimization.
"""

import hashlib
import json
from pathlib import Path
import platform
import statistics
import time

import numpy as np

from tools.hcsn.round8_20261031.state_task.data import make_data
from tools.hcsn.round8_20261031.state_task.replay import predict
from tools.hcsn.round9_20261031.streaming.filter import StreamingFilter

HERE = Path(__file__).resolve().parent
R8 = HERE.parents[1] / "round8_20261031/state_task"


def work(implementation, workload, family, parameters, history, lengths, queries):
    state = StreamingFilter(len(history), parameters) if implementation == "streaming" else None
    if state is not None and workload != "online":
        state.update(history, lengths)
    calls = 1 if workload == "one_shot" else 32
    sink = 0
    for step in range(calls):
        query = queries[step]
        if state is None:
            partial = history[:, :step + 1] if workload == "online" else history
            partial_lengths = np.minimum(lengths, step + 1) if workload == "online" else lengths
            risk = predict(family, parameters or {}, partial, partial_lengths, query)
        else:
            if workload == "online":
                state.update(history[:, step:step + 1], (lengths > step).astype(np.int64))
            risk = state.predict(query)
        sink += len(json.dumps({"risk": risk.tolist(), "protect": (risk > query[:, 4]).tolist()},
                               separators=(",", ":")))
    return sink


def main():
    out = HERE / "evidence/v2"
    target = out / "numpy_comparison.json"
    if target.exists():
        raise FileExistsError("refusing to overwrite paired cost evidence")
    protocol = {"baseline_commit": "00b94d54a9b85f285298d1a964777bdecfa85385",
                "source_sha256": {str(p.relative_to(HERE.parents[3])): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (Path(__file__), HERE / "filter.py", R8 / "replay.py")},
                "regimes": ["iid", "long_history", "low_noise", "moving_boundary"],
                "seeds": {"iid": 191001, "long_history": 191002, "low_noise": 191003, "moving_boundary": 191004},
                "arms": ["analytic_filter", "fixed_ordinary_filter"], "fit_seed": 17,
                "implementations": ["full_history_numpy", "streaming"],
                "batch_sizes": [1, 64, 2048], "rounds": 5, "warmups": 1,
                "workloads": ["one_shot", "varying_horizon", "online"],
                "queries": "32 horizons evenly spaced from .25 to 1.8; every call has a different horizon. Online consumes each new public observation once.",
                "timed_scope": "Input conversion in each actual implementation, state initialization/updates, risk, action and JSON output. Frozen parameters and input slicing prepared before timing for both.",
                "order": "Alternate paired implementation order each repeat; same data for each pair.",
                "interpretation": "Additional implementation/cost check on existing confirmation inputs, not a new efficacy trial. Shared CPU, one BLAS thread; no measured energy.",
                "written_before_measurement": True}
    (out / "NUMPY_REGISTERED.json").write_text(json.dumps(protocol, indent=2) + "\n")
    data_protocol = json.loads((R8 / "protocol.json").read_text())
    data_protocol["data_seeds"].update(protocol["seeds"])
    calibrated = json.loads((R8 / "evidence/models/analytic_filter_17.json").read_text())["state"]
    models = {"analytic_filter": {k: np.asarray(v) for k, v in calibrated.items()}, "fixed_ordinary_filter": None}
    start, wall = time.process_time(), time.perf_counter()
    rows, parity = [], []
    for regime in protocol["regimes"]:
        data = make_data(regime, data_protocol)
        for family, parameters in models.items():
            state = StreamingFilter(len(data["history"]), parameters)
            state.update(data["history"], data["lengths"])
            old = predict(family, parameters or {}, data["history"], data["lengths"], data["query"])
            new = state.predict(data["query"])
            parity.append({"regime": regime, "family": family, "examples": len(old),
                           "max_probability_difference": float(np.max(np.abs(old - new))),
                           "action_disagreements": int(np.sum((old > data["query"][:, 4]) != (new > data["query"][:, 4])))})
            for size in protocol["batch_sizes"]:
                history, lengths, query = (data[k][:size] for k in ("history", "lengths", "query"))
                queries = []
                for horizon in np.linspace(.25, 1.8, 32):
                    current = query.copy()
                    current[:, 2] = horizon
                    queries.append(current)
                for workload in protocol["workloads"]:
                    args = (workload, family, parameters, history, lengths, queries)
                    for implementation in protocol["implementations"]:
                        work(implementation, *args)
                    for repeat in range(protocol["rounds"]):
                        for implementation in protocol["implementations"][::1 if repeat % 2 == 0 else -1]:
                            c, w = time.process_time(), time.perf_counter()
                            sink = work(implementation, *args)
                            rows.append({"regime": regime, "family": family, "batch_size": size, "workload": workload,
                                         "implementation": implementation, "round": repeat,
                                         "cpu_seconds": time.process_time() - c, "wall_seconds": time.perf_counter() - w,
                                         "serialized_output_bytes": sink})
    keys = ("regime", "family", "batch_size", "workload", "implementation")
    groups = {}
    for row in rows:
        groups.setdefault(tuple(row[k] for k in keys), []).append(row)
    summary = [dict(zip(keys, key)) | {"median_cpu_seconds": statistics.median(r["cpu_seconds"] for r in values),
                                      "median_wall_seconds": statistics.median(r["wall_seconds"] for r in values),
                                      "min_cpu_seconds": min(r["cpu_seconds"] for r in values),
                                      "max_cpu_seconds": max(r["cpu_seconds"] for r in values)}
               for key, values in groups.items()]
    passed = all(p["max_probability_difference"] <= 3e-6 and p["action_disagreements"] == 0 for p in parity)
    result = {"parity": parity, "parity_passed": passed, "raw": rows, "summary": summary,
              "cpu_seconds": time.process_time() - start, "wall_seconds": time.perf_counter() - wall,
              "environment": {"python": platform.python_version(), "numpy": np.__version__},
              "energy_joules": None, "probability_spike_necessity_proved": False}
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"parity_passed": passed, "rows": len(rows), "cpu_seconds": result["cpu_seconds"]}))
    if not passed:
        raise AssertionError("current-backend parity failed")


if __name__ == "__main__":
    main()
