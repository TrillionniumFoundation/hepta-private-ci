"""Prepare or execute exactly one owned, frozen development worker at a time."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time


def bootstrap(root, module_root):
    core = root / "candidate-qwen-03/scripts"
    research = root / "research-sft-v1-source"
    for directory in (root, core, research, module_root):
        if not directory.is_absolute() or directory.resolve() != directory or not directory.is_dir():
            raise ValueError("absolute existing source/artifact directories required")
    sys.path[:0] = [str(core), str(research)]
    import cell_experiments
    cell_experiments.__path__.append(str(module_root))
    import research_sft_contract_v1 as old
    old.bind_helpers(root / "e1e2-operation-helpers-04")


def numerical_gate(root, module_root, directory):
    """Execute the real tiny-model CPU checks; skipped checks are not success."""
    directory.mkdir(parents=True, exist_ok=False)
    program = '''import json, pathlib, sys, unittest
sys.path.insert(0, sys.argv[1])
import cell_experiments
cell_experiments.__path__.append(sys.argv[2])
suite = unittest.defaultTestLoader.loadTestsFromNames([
    "cell_experiments.online_v4.test_onpolicy_tensor",
    "cell_experiments.online_v4.test_shared_pool_v4"])
result = unittest.TextTestRunner(verbosity=2).run(suite)
record = {"tests": result.testsRun, "failures": len(result.failures),
          "errors": len(result.errors), "skipped": len(result.skipped),
          "GPU_jobs_launched": 0, "scope": "tiny actual CPU tensor behavior"}
pathlib.Path(sys.argv[3]).write_text(json.dumps(record, sort_keys=True) + "\\n")
sys.exit(0 if result.wasSuccessful() and result.testsRun >= 2 and not result.skipped else 1)
'''
    command = [sys.executable, "-I", "-B", "-c", program,
               str(root / "candidate-qwen-03/scripts"), str(module_root), str(directory / "TESTS.json")]
    environment = {**os.environ, "CUDA_VISIBLE_DEVICES": "", "PYTHONDONTWRITEBYTECODE": "1",
                   "TMPDIR": str(directory)}
    from cell_experiments.coding_sft import write_new
    write_new(directory / "INTENT.json", {"command": command, "timeout_seconds": 180,
              "CUDA_VISIBLE_DEVICES": "", "automatic_retry": False, "GPU_jobs_launched": 0})
    with (directory / "OUTPUT.log").open("xb") as log:
        completed = subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                   timeout=180, check=False)
    receipt = json.loads((directory / "TESTS.json").read_text())
    if completed.returncode or receipt["tests"] < 2 or receipt["skipped"]:
        raise ValueError("real CPU numerical admission did not pass without skips")
    return {"status": "PASSED", "exit_code": completed.returncode, **receipt,
            "log_sha256": hashlib.sha256((directory / "OUTPUT.log").read_bytes()).hexdigest()}


def prepare(root, module_root, directory, context, manifests, backend):
    from cell_experiments import data
    from cell_experiments.coding_sft import write_new
    from cell_experiments.online_v4.round03_plan import make_comparison

    directory.mkdir(parents=True, exist_ok=False)
    write_new(directory / "PREPARATION_INTENT.json", {"pid": os.getpid(), "automatic_retry": False,
              "GPU_jobs_launched": 0, "started_at_ns": time.time_ns()})
    try:
        gate = numerical_gate(root, module_root, directory / "engineering-numerical")
        a, initial = context["records"][:6], manifests["final_answer"]
        collected = backend.collect(a, initial, directory / "engineering-reference/collection", "teacher", 2)
        corrected = backend.corrections(a, collected, "teacher", 0,
                                       directory / "engineering-reference/corrections")
        plan = backend.make_plan(corrected, initial, "round03-backend-compatibility", 0, "teacher")
        write_new(directory / "engineering-reference/PLAN.json", plan)
        gate.update(backend_smoke="PASSED", reference_record_count=len(corrected),
                    reference_execution_scope="engineering only; receipts retained separately",
                    source_inventory=backend.sources())
        write_new(directory / "ENGINEERING_GATE.json", gate)
        inventory = {"round03_cli.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                     "engineering_gate_digest": data.digest(gate)}
        freeze = make_comparison(context, manifests, backend, directory.name, inventory)
        write_new(directory / "COMPARISON.json", freeze)
        return {"status": "PREPARED", "comparison_digest": freeze["comparison_digest"],
                "GPU_jobs_launched": 0, "independent_sample_increment": 0}
    except BaseException as error:
        write_new(directory / "PREPARATION_FAILED.json", {"status": "FAILED_PRESERVED",
                  "error_type": type(error).__name__, "error": str(error),
                  "automatic_retry": False, "GPU_jobs_launched": 0})
        raise


class Deadline(BaseException):
    """Own-worker elapsed deadline; no unrelated processes are signaled."""


def execute(root, directory, context, manifests, backend, job):
    from cell_experiments import data
    from cell_experiments.coding_sft import write_new
    from cell_experiments.online_v4 import round03_jobs as jobs
    from cell_experiments.online_v4.round03_plan import check_comparison

    freeze = data._parse((directory / "COMPARISON.json").read_bytes())
    gate = data._parse((directory / "ENGINEERING_GATE.json").read_bytes())
    if gate["status"] != "PASSED" or gate["source_inventory"] != backend.sources():
        raise ValueError("current source did not pass engineering admission")
    inventory = {"round03_cli.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                 "engineering_gate_digest": data.digest(gate)}
    check_comparison(freeze, context, manifests, backend, inventory)
    deadline = 7200 if job == "circuit" else 3600
    with (directory / "WORKER.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record_dir = directory / "worker-receipts" / job
        record_dir.mkdir(parents=True, exist_ok=False)
        write_new(record_dir / "INTENT.json", {"pid": os.getpid(), "job": job,
            "comparison_digest": freeze["comparison_digest"], "started_at_ns": time.time_ns(),
            "automatic_retry": False, "deadline_seconds": deadline})
        def expired(signum, frame):
            raise Deadline("own worker elapsed deadline reached")
        previous_handler = signal.signal(signal.SIGALRM, expired)
        signal.alarm(deadline)
        started = time.perf_counter()
        try:
            if job == "circuit":
                result = jobs.run_circuit(context, manifests, root, freeze, directory)
            elif job.startswith("e2-"):
                result = jobs.run_e2(context, manifests, backend, freeze, directory, job[3:])
            else:
                _, mode, phase = job.split("-")
                result = jobs.evaluate_e2(context, root, backend, freeze, directory, mode, phase)
            check_comparison(freeze, context, manifests, backend, inventory)
            receipt = {"status": "COMPLETE", "job": job, "pid": os.getpid(),
                       "result_digest": data.digest(result), "wall_seconds": time.perf_counter() - started,
                       "full_system_cost_complete": False, "scientific_confirmation_qualified": False,
                       "independent_sample_increment": 0}
            write_new(record_dir / "COMPLETE.json", receipt)
            return receipt
        except BaseException as error:
            write_new(record_dir / "FAILED.json", {"status": "FAILED_PRESERVED", "job": job,
                "error_type": type(error).__name__, "error": str(error), "automatic_retry": False,
                "wall_seconds": time.perf_counter() - started, "call_totals_complete": False})
            raise
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous_handler)
            fcntl.flock(lock, fcntl.LOCK_UN)


def main():
    modes = ("teacher", "shadow", "controlled")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--module-root", type=Path, required=True,
                        help="new source directory containing online_v4")
    parser.add_argument("--run-name", required=True)
    parser.add_argument("job", choices=["prepare", "report", "circuit", *["e2-" + mode for mode in modes],
        *["eval-" + mode + "-" + phase for mode in modes for phase in ("primary", "cold")]])
    args = parser.parse_args()
    if not re.fullmatch(r"research-round03-[A-Za-z0-9_-]{1,64}", args.run_name):
        parser.error("a new bounded research-round03 operation name is required")
    bootstrap(args.artifact_root, args.module_root)
    directory = args.artifact_root / args.run_name
    if args.job == "report":
        from cell_experiments.online_v4.round03_report import report_directory
        print(json.dumps(report_directory(directory), sort_keys=True))
        return
    from cell_experiments.online_v4.onpolicy_backend import ResearchBackend
    from cell_experiments.online_v4.round03_plan import material_inputs
    context, manifests = material_inputs(args.artifact_root)
    backend = ResearchBackend(context, args.artifact_root)
    result = (prepare(args.artifact_root, args.module_root, directory, context, manifests, backend)
              if args.job == "prepare" else execute(args.artifact_root, directory, context,
                                                   manifests, backend, args.job))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
