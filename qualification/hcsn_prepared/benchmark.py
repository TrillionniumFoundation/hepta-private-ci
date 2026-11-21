"""Fresh synthetic paired timing, with source freeze and isolated RSS receipts.

No training dataset, held-out task set, optimizer update or historic finalizer is
opened. A completed result qualifies only this scheduling implementation.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time


PROTOCOL = {"experiment": "HCSN-PREPARED-KERNEL-20261121-1d88-v1",
            "batch_sizes": [1, 2, 32], "widths": [4, 16], "steps": 16,
            "kinds": ["hcsn", "gru"], "executors": ["serial", "prepared"],
            "input_size": 15, "dtype": "float64", "device": "cpu", "seed": 202611211,
            "threads": 1, "interop_threads": 1, "forward_repeats": 5,
            "backward_repeats": 3, "warmup_each": 1, "case_wall_seconds": 25,
            "total_wall_seconds": 180, "peak_rss_ceiling_bytes": 1073741824,
            "optimizer_updates": 0, "heldout_data_reads": 0}


def source_binding():
    root = Path(__file__).resolve().parents[2]
    paths = ["qualification/hcsn_training/__init__.py",
             "qualification/hcsn_training/population_generator.py",
             "qualification/hcsn_adaptive/__init__.py", "qualification/hcsn_adaptive/batched_flow.py",
             "qualification/hcsn_scale/__init__.py", "qualification/hcsn_scale/model.py",
             "qualification/hcsn_prepared/__init__.py", "qualification/hcsn_prepared/model.py",
             "qualification/hcsn_prepared/prepared_tests.py", "qualification/hcsn_prepared/benchmark.py"]
    sources = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths}
    return {"protocol": PROTOCOL, "sources": sources,
            "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                        "torch": importlib.metadata.version("torch"),
                        "numpy": importlib.metadata.version("numpy")}}


def case_worker(case):
    if (set(case) != {"batch", "width", "kind", "executor"}
            or case["batch"] not in PROTOCOL["batch_sizes"] or case["width"] not in PROTOCOL["widths"]
            or case["kind"] not in PROTOCOL["kinds"] or case["executor"] not in PROTOCOL["executors"]):
        raise ValueError("case is outside the frozen protocol")
    import resource
    import torch
    from qualification.hcsn_scale.model import ModelConfig, SequenceModel, tensor_map_digest
    from .model import PreparedSequenceModel
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    generator = torch.Generator().manual_seed(PROTOCOL["seed"])
    x = torch.randn(case["batch"], PROTOCOL["steps"], PROTOCOL["input_size"],
                    generator=generator, dtype=torch.float64)
    dt = torch.randint(1_000_000, 62_000_000, x.shape[:2], generator=generator).double() / 1_000_000
    torch.manual_seed(PROTOCOL["seed"] + case["width"])
    cls = SequenceModel if case["executor"] == "serial" else PreparedSequenceModel
    model = cls(ModelConfig(case["kind"], PROTOCOL["input_size"], case["width"], 310.0))
    weights = tensor_map_digest(model.state_dict())

    def forward():
        with torch.no_grad():
            return model.representations(x, dt)

    def backward():
        model.zero_grad(set_to_none=True)
        loss = model.next_sensor_loss(x, dt)
        loss.backward()
        return float(loss.detach())

    warmup = time.perf_counter()
    forward()
    backward()
    warmup = time.perf_counter() - warmup
    timings = {}
    for name, action, repeats in (("forward", forward, PROTOCOL["forward_repeats"]),
                                  ("forward_backward", backward, PROTOCOL["backward_repeats"])):
        values = []
        for _ in range(repeats):
            started = time.perf_counter()
            action()
            values.append(time.perf_counter() - started)
        timings[name] = {"seconds": values, "median_seconds": statistics.median(values)}
    phases = None
    if case["kind"] == "hcsn" and case["executor"] == "prepared":
        with torch.no_grad():
            start = time.perf_counter()
            operators = model.prepare_windows(x, dt)
            middle = time.perf_counter()
            model.propagate_prepared(operators)
            phases = {"prepare_seconds": middle - start,
                      "propagate_seconds": time.perf_counter() - middle,
                      "diagnostic_only": True}
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss = int(rss * (1 if sys.platform == "darwin" else 1024))
    if weights != tensor_map_digest(model.state_dict()):
        raise RuntimeError("timing unexpectedly changed model state")
    return {"case": case, "status": "completed", "timings": timings,
            "warmup_seconds": warmup, "phase_timing": phases, "peak_process_rss_bytes": rss,
            "within_rss_ceiling": rss <= PROTOCOL["peak_rss_ceiling_bytes"],
            "parameter_sha256": weights, "input_sha256": tensor_map_digest({"x": x, "dt": dt}),
            "model": model.identity()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--freeze", type=Path)
    group.add_argument("--run", type=Path)
    group.add_argument("--case-json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.case_json:
        print(json.dumps(case_worker(json.loads(args.case_json)), sort_keys=True))
        return
    binding = source_binding()
    digest = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    if args.freeze:
        with args.freeze.open("x") as stream:
            json.dump({"sha256": digest, "binding": binding}, stream, indent=2, sort_keys=True)
        print(digest)
        return
    if args.output is None:
        parser.error("--run requires --output")
    manifest = json.loads(args.run.read_text())
    if manifest != {"sha256": digest, "binding": binding}:
        raise ValueError("source/runtime/protocol changed since freeze")
    args.output.mkdir(parents=True, exist_ok=False)
    started, records = time.perf_counter(), []
    (args.output / "started.json").write_text(json.dumps(manifest, sort_keys=True))
    env = dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    for width in PROTOCOL["widths"]:
        for batch in PROTOCOL["batch_sizes"]:
            for kind in PROTOCOL["kinds"]:
                for executor in PROTOCOL["executors"]:
                    case = dict(width=width, batch=batch, kind=kind, executor=executor)
                    remaining = PROTOCOL["total_wall_seconds"] - (time.perf_counter() - started)
                    if remaining <= 0:
                        records.append({"case": case, "status": "budget_exhausted"})
                        continue
                    began = time.perf_counter()
                    try:
                        process = subprocess.run([sys.executable, "-m", "qualification.hcsn_prepared.benchmark",
                                                  "--case-json", json.dumps(case)], env=env, capture_output=True,
                                                 text=True, timeout=min(remaining, PROTOCOL["case_wall_seconds"]))
                        record = (json.loads(process.stdout) if process.returncode == 0 else
                                  {"case": case, "status": "failed", "returncode": process.returncode})
                        record["stderr"] = process.stderr
                    except subprocess.TimeoutExpired:
                        record = {"case": case, "status": "timeout"}
                    record["process_wall_seconds"] = time.perf_counter() - began
                    records.append(record)
                    with (args.output / "cases.jsonl").open("a") as stream:
                        stream.write(json.dumps(record, sort_keys=True) + "\n")
    result = {"manifest_sha256": digest, "cases": records,
              "total_wall_seconds": time.perf_counter() - started,
              "all_cases_completed": all(r["status"] == "completed" for r in records),
              "scope": "synthetic execution equivalence and cost; no task-quality or scaling conclusion"}
    for record in records:
        if record["status"] != "completed" or record["case"]["executor"] != "prepared":
            continue
        paired = next(r for r in records if r["case"] == dict(record["case"], executor="serial"))
        if paired["status"] == "completed" and any(record[key] != paired[key]
                for key in ("parameter_sha256", "input_sha256")):
            raise RuntimeError("paired benchmark parameters or inputs differ")
    (args.output / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True))
    if not result["all_cases_completed"] or any(not r.get("within_rss_ceiling", False) for r in records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
