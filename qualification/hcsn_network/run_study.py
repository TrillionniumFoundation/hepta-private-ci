"""One-shot stdlib process envelope; limits apply before numerical imports."""

import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


def main(output):
    if output.exists():
        raise FileExistsError("attempt directory already exists")
    output.mkdir(parents=True)
    command = [sys.executable, "-m", "qualification.hcsn_network.study", "--output", str(output / "RAW")]
    cpu = max(os.sched_getaffinity(0))
    request = {"command": command, "cpu_affinity": [cpu], "address_space_bytes": 8 * 1024**3,
               "cpu_soft_seconds": 120, "cpu_hard_seconds": 125, "wall_seconds": 150,
               "source_freeze": "local Git before this attempt; no prior model execution"}
    (output / "REQUEST.json").write_text(json.dumps(request, indent=2) + "\n")
    def limits():
        resource.setrlimit(resource.RLIMIT_AS, (request["address_space_bytes"], request["address_space_bytes"]))
        resource.setrlimit(resource.RLIMIT_CPU, (120, 125))
        os.sched_setaffinity(0, {cpu})
    started = time.perf_counter()
    previous = resource.getrusage(resource.RUSAGE_CHILDREN)
    with (output / "stdout").open("w") as stdout, (output / "stderr").open("w") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, preexec_fn=limits,
                                   env={**os.environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                                        "OPENBLAS_NUM_THREADS": "1"})
        timed_out = False
        try:
            exit_code = process.wait(timeout=150)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            exit_code = process.wait()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {"exit_code": exit_code, "timed_out": timed_out,
              "full_wall_seconds_including_imports_and_cold_child": time.perf_counter() - started,
              "full_cpu_seconds_including_cold_child": usage.ru_utime + usage.ru_stime - previous.ru_utime - previous.ru_stime,
              "waited_process_tree_peak_rss_kib": usage.ru_maxrss, "measurement": "fresh stdlib parent wait/rusage"}
    (output / "COST.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    if exit_code != 0:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output.resolve())
