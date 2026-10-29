"""Native test bridge: fitting process exits before independent fresh readers."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-snapshot", type=Path, required=True)
    parser.add_argument("--encoder-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1741)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    directory = Path(__file__).resolve().parent
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    processes = []

    def execute(label, command):
        start, before = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)
        with (args.output / f"{label}.stdout").open("wb") as out, (args.output / f"{label}.stderr").open("wb") as err:
            completed = subprocess.run(command, env=env, stdout=out, stderr=err, check=False)
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        receipt = {"label": label, "command": command, "exit_code": completed.returncode,
                   "wall_seconds": time.perf_counter() - start,
                   "child_user_cpu_seconds": after.ru_utime - before.ru_utime,
                   "child_system_cpu_seconds": after.ru_stime - before.ru_stime,
                   "cumulative_child_maxrss_kib": after.ru_maxrss}
        processes.append(receipt)
        (args.output / "PROCESSES.json").write_text(json.dumps(processes, indent=2) + "\n")
        if completed.returncode:
            raise RuntimeError(f"{label} failed; raw stdout/stderr retained")

    execute("training", [sys.executable, str(directory / "native_train_worker.py"),
                         "--owner-snapshot", str(args.owner_snapshot), "--encoder-dir", str(args.encoder_dir),
                         "--output", str(args.output), "--seed", str(args.seed)])
    parity = {"schema": "hepta.memory.v10.native-fresh-reader.v1", "trainer_exited_before_readers": True,
              "models": {}, "numpy_f32_vs_independent_f64": True,
              "native_rust_executed_by_this_script": False, "torch_executed": False}
    for kind in ("semantic", "procedure"):
        for variant in (kind, kind + "-ablation"):
            execute("read-" + variant, [sys.executable, str(directory / "reference.py"),
                                        "--native", str(args.output / f"{variant}.json"),
                                        "--output", str(args.output / f"{variant}-reference.json")])
        base = json.loads((args.output / f"{kind}-reference.json").read_text())
        ablation = json.loads((args.output / f"{kind}-ablation-reference.json").read_text())
        parity["models"][kind] = {"trained": base, "ablated": ablation,
                                    "changed_typed_outputs": sum(a["value"] != b["value"]
                                                                 for a, b in zip(base["rows"], ablation["rows"], strict=True))}
    parity["processes"] = processes
    (args.output / "PARITY.json").write_text(json.dumps(parity, indent=2, allow_nan=False) + "\n")
    if any(not variant["numpy_f32_within_declared_tolerance"] or not variant["numpy_f32_typed_outputs_equal"]
           for model in parity["models"].values() for variant in (model["trained"], model["ablated"])):
        raise RuntimeError("native profile parity exceeds frozen numerical contract; evidence retained")
    print(json.dumps({"output": str(args.output), "training_process_exit_code": processes[0]["exit_code"],
                      "fresh_readers": 4, "parity_sha256": hashlib.sha256((args.output / "PARITY.json").read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
