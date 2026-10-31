"""Full subprocess cost for the preselected trained-model execution binding."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--expected-study-commit", required=True)
    parser.add_argument("--expected-study-protocol-sha256", required=True)
    parser.add_argument("--expected-checkpoint-sha256", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, "-m", "experiments.hcsn_blocker_closure_v1.execution_binding.driver",
               "run", "--study", str(args.study.resolve()), "--output", str(args.output.resolve()),
               "--binary", str(args.binary.resolve()), "--expected-study-commit", args.expected_study_commit,
               "--expected-study-protocol-sha256", args.expected_study_protocol_sha256,
               "--expected-checkpoint-sha256", args.expected_checkpoint_sha256]
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
               PYTHONDONTWRITEBYTECODE="1")
    start = time.perf_counter()
    with (args.output/"WORKER.log").open("xb") as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    result = dict(schema="hcsn-trained-binding-whole-cost.v1", command=command, exit_code=process.returncode,
        child_and_reaped_descendant_cpu_seconds=usage.ru_utime+usage.ru_stime,
        wall_seconds=time.perf_counter()-start, process_peak_rss_kib=usage.ru_maxrss,
        launcher_cpu_to_receipt=time.process_time(),
        scope="Exact worker wait4: includes imports, checkpoint verification, all neural/native/resume/scale children, IPC and evidence writing; excludes launcher and dependency installation",
        nested_warning="All inner child, native and inference clocks are contained; do not add them to this total",
        energy_joules=None, neural_kernel_is_python=True, new_training_performed=False)
    (args.output/"WHOLE_WORKER_COST.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    print(json.dumps(result, sort_keys=True), flush=True)
    raise SystemExit(process.returncode)
