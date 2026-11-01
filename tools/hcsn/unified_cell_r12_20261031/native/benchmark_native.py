"""Independent-process resident/cold costs; shared host, CPU only."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent


def worker(fixture, library, implementation, cells, dt):
    begin = time.process_time_ns()
    import numpy as np
    from adapter import NativeOperator
    if implementation == "cached_matrix":
        from scipy.linalg import expm
    import_cpu = (time.process_time_ns()-begin)*1e-9
    begin = time.process_time_ns()
    model = json.loads(fixture.read_text())
    q, p = np.array(model["Q"]), np.array(model["prior"])
    if implementation == "native":
        operator = NativeOperator(library)
        calculate = lambda: operator.propagate(q, p, dt)
    else:
        matrix = expm(q*dt)
        calculate = lambda: p @ matrix
    setup_cpu = (time.process_time_ns()-begin)*1e-9
    samples = []
    for _ in range(9):
        start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
        for _ in range(cells):
            last = calculate()
        samples.append(dict(cpu_seconds=(time.process_time_ns()-start_cpu)*1e-9,
                            wall_seconds=(time.perf_counter_ns()-start_wall)*1e-9))
    return dict(pid=os.getpid(), implementation=implementation, cells=cells, n_states=len(p), dt=dt,
                import_cpu_seconds=import_cpu, setup_cpu_seconds=setup_cpu, samples=samples,
                median_batch_cpu_seconds=statistics.median(x["cpu_seconds"] for x in samples),
                peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                last_probability=last.tolist())


def run(fixture, output, library):
    output.mkdir(parents=True, exist_ok=False)
    protocol = dict(schema="hcsn-native-isolated-cpu-v1", cells=[24, 64, 256], dts=[.15, .45, 2.1],
                    matrix_dimension=20, implementations=["native", "cached_matrix"], repetitions=9,
                    fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
                    library_sha256=hashlib.sha256(library.read_bytes()).hexdigest(),
                    source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    thread_limits={"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"},
                    scope="Each cell has the same immutable Q/prior in this homogeneous batch. Cache setup/import and cold process are separately charged. No training/full-HX kernel/energy/GPU cost or quality advantage claim.")
    (output/"PROTOCOL.json").write_text(json.dumps(protocol, indent=2)+"\n")
    environment = dict(os.environ, **protocol["thread_limits"])
    records = []
    for dt in protocol["dts"]:
        for cells in protocol["cells"]:
            for implementation in protocol["implementations"]:
                command = [sys.executable, str(Path(__file__).resolve()), "--worker", implementation,
                           "--fixture", str(fixture), "--library", str(library), "--cells", str(cells), "--dt", str(dt)]
                before = resource.getrusage(resource.RUSAGE_CHILDREN)
                started = time.perf_counter()
                completed = subprocess.run(command, env=environment, capture_output=True, text=True)
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                receipt = dict(command=command, returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr,
                               wall_seconds=time.perf_counter()-started,
                               full_child_cpu_seconds=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime)
                if completed.returncode:
                    (output/"FAILED.json").write_text(json.dumps(receipt, indent=2)+"\n")
                    raise RuntimeError(completed.stderr)
                measured = json.loads(completed.stdout)
                records.append(dict(receipt=receipt, measured=measured))
    pairs = []
    for i in range(0, len(records), 2):
        a, b = records[i]["measured"], records[i+1]["measured"]
        error = max(abs(x-y) for x, y in zip(a["last_probability"], b["last_probability"]))
        if error >= 3e-11: raise AssertionError("Performance workers disagreed numerically")
        pairs.append(dict(dt=a["dt"], cells=a["cells"], native_batch_cpu_seconds=a["median_batch_cpu_seconds"],
                          cached_batch_cpu_seconds=b["median_batch_cpu_seconds"],
                          native_setup_cpu_seconds=a["setup_cpu_seconds"], cached_setup_cpu_seconds=b["setup_cpu_seconds"],
                          max_probability_error=error))
    result = dict(protocol=protocol, records=records, pairs=pairs,
                  worker_count=len(records), unique_worker_pids=len({r["measured"]["pid"] for r in records}),
                  end_to_end_economic_advantage_established=False)
    (output/"RESULTS.json").write_text(json.dumps(result, indent=2)+"\n")
    return pairs


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=["native", "cached_matrix"])
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--library", type=Path, default=ROOT/"evidence"/"build"/"libhcsn_native.so")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cells", type=int)
    parser.add_argument("--dt", type=float)
    args = parser.parse_args()
    if args.worker:
        measured = worker(args.fixture.resolve(), args.library.resolve(), args.worker, args.cells, args.dt)
    else:
        if args.output is None: parser.error("--output is required for the controller")
        measured = run(args.fixture.resolve(), args.output.resolve(), args.library.resolve())
    print(json.dumps(measured, indent=2))
