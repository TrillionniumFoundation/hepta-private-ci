"""Own the bounded three-model diagnostic under the existing GPU lock."""

import argparse
import fcntl
import importlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
runner = importlib.import_module("run_replacement")
codec = runner.codec
LOCK = runner.ARTIFACT / "research-round03-20261118-392934-b/WORKER.lock"
PYTHON = "/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a/venv/bin/python"
ORIGINAL_OWNER = runner.COLLECTION / "execution-code/owner.py"
ORIGINAL_OWNER_SHA = "fc9ec2aa4600b8d554f4a9ef9ee802bf196cc68e8fad890a4090538497bb0ac1"


def owner_utilities():
    if codec.sha(ORIGINAL_OWNER.read_bytes()) != ORIGINAL_OWNER_SHA:
        raise ValueError("original GPU and energy utilities changed")
    sys.modules["native_sandbox"] = codec.native_module()
    spec = importlib.util.spec_from_file_location(
        "replacement_original_owner_utilities", ORIGINAL_OWNER
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stop_owned_child(child):
    if child is None or child.poll() is not None:
        return None
    os.killpg(child.pid, signal.SIGTERM)
    try:
        code = child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        code = child.wait(timeout=10)
    return {
        "pid": child.pid,
        "actual_wait_returncode": code,
        "scope": "this owner's known child process group only",
    }


def own(root, commit):
    deployment, protocol, _ = runner.admitted(root, commit)
    owned = root / "owned-evaluation-1"
    owned.mkdir(exist_ok=False)
    utilities = owner_utilities()
    start, samples, stages = time.perf_counter(), [], []
    child = None

    def sample():
        value = utilities.energy_sample()
        samples.append(value)
        codec.write(owned / ("ENERGY-" + str(len(samples) - 1) + ".json"), value)

    def summary(status):
        totals = []
        for index in (0, 1):
            rows = [value["domains"][index] for value in samples]
            if (
                len(rows) >= 2
                and all(row.get("exit_code") == 0 for row in rows)
                and len({value["boot_id"] for value in samples}) == 1
                and len({row["max_energy_range_uj"] for row in rows}) == 1
            ):
                maximum = rows[0]["max_energy_range_uj"]
                deltas = [
                    (right["energy_uj"] - left["energy_uj"]) % maximum
                    for left, right in zip(rows, rows[1:])
                ]
                totals.append(
                    {
                        "domain_name": rows[0]["domain_name"],
                        "host_window_joules": sum(deltas) / 1e6,
                        "modular_deltas_uj": deltas,
                        "samples": len(rows),
                        "no_multiple_wraps_between_samples_assumption": True,
                    }
                )
        return {
            "status": status,
            "source_commit": commit,
            "protocol_sha256": deployment["protocol_sha256"],
            "stage_exits": stages,
            "finished_at_ns": str(time.time_ns()),
            "owner_wall_seconds": time.perf_counter() - start,
            "energy_samples": len(samples),
            "whole_host_cpu_package_energy": totals,
            "energy_scope": "whole host packages including unrelated activity; no idle subtraction or model-only claim",
            "gpu_energy_joules": None,
            "network_energy_joules": None,
            "monetary_cost": None,
            "full_system_cost_known": False,
            "nested_windows_are_not_additive": True,
            "new_training_updates": 0,
            "B3_model_calls": 0,
            "old_research_NoUpdate_unchanged": True,
        }

    if not LOCK.is_file() or LOCK.is_symlink():
        raise ValueError("original existing shared GPU lock required")
    with LOCK.open("a+b") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        codec.write(
            owned / "INTENT.json",
            {
                "source_commit": commit,
                "deployment_sha256": codec.sha((root / "DEPLOYMENT.json").read_bytes()),
                "protocol_sha256": deployment["protocol_sha256"],
                "started_at_ns": str(time.time_ns()),
                "lock": str(LOCK),
                "planned_modes": protocol["planned_modes"],
                "planned_total_model_calls": 24,
                "planned_training_updates": 0,
                "B3_model_calls": 0,
                "automatic_retry": False,
                "energy_sample_interval_seconds": 20,
                "original_owner_utility_sha256": ORIGINAL_OWNER_SHA,
                "cuda_memory_fraction": 0.70,
                "cuda_allocator": "expandable_segments:True",
            },
        )
        try:
            for mode in protocol["planned_modes"]:
                runner.admitted(root, commit)
                folder = owned / mode
                folder.mkdir()
                codec.write(folder / "GPU_ADMISSION.json", utilities.gpu_admission())
                argv = [
                    PYTHON,
                    "-B",
                    str(HERE / "run_replacement.py"),
                    "--root",
                    str(root),
                    "--mode",
                    mode,
                    "--source-commit",
                    commit,
                ]
                env = {
                    key: value
                    for key, value in os.environ.items()
                    if key
                    not in (
                        "PYTHONPATH",
                        "PYTHONSTARTUP",
                        "PYTHONHOME",
                        "PYTORCH_ALLOC_CONF",
                        "PYTORCH_CUDA_ALLOC_CONF",
                    )
                }
                env.update(
                    PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True",
                    HF_HUB_OFFLINE="1",
                    TRANSFORMERS_OFFLINE="1",
                    HF_DATASETS_OFFLINE="1",
                    PYTHONDONTWRITEBYTECODE="1",
                    PYTHONNOUSERSITE="1",
                    TOKENIZERS_PARALLELISM="false",
                    OMP_NUM_THREADS="2",
                    OPENBLAS_NUM_THREADS="1",
                )
                tick, usage = (
                    time.perf_counter(),
                    resource.getrusage(resource.RUSAGE_CHILDREN),
                )
                sample()
                timed_out = False
                with (
                    (folder / "STDOUT.txt").open("xb") as stdout,
                    (folder / "STDERR.txt").open("xb") as stderr,
                ):
                    child = subprocess.Popen(
                        argv,
                        cwd=HERE,
                        env=env,
                        stdout=stdout,
                        stderr=stderr,
                        start_new_session=True,
                    )
                    codec.write(
                        folder / "STARTED.json",
                        {
                            "pid": child.pid,
                            "process_group_id": child.pid,
                            "argv": argv,
                            "started_at_ns": str(time.time_ns()),
                            "timeout_seconds": 3600,
                        },
                    )
                    while True:
                        try:
                            code = child.wait(timeout=20)
                            break
                        except subprocess.TimeoutExpired:
                            sample()
                            if time.perf_counter() - tick > 3600:
                                timed_out = True
                                cleanup = stop_owned_child(child)
                                code = (
                                    cleanup["actual_wait_returncode"]
                                    if cleanup
                                    else child.returncode
                                )
                                break
                sample()
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                record = {
                    "mode": mode,
                    "pid": child.pid,
                    "wait_returncode": code,
                    "timed_out": timed_out,
                    "exit_source": "subprocess.Popen.wait",
                    "finished_at_ns": str(time.time_ns()),
                    "wall_seconds": time.perf_counter() - tick,
                    "observed_child_cpu_seconds_including_energy_reads": after.ru_utime
                    + after.ru_stime
                    - usage.ru_utime
                    - usage.ru_stime,
                    "stdout_sha256": codec.sha((folder / "STDOUT.txt").read_bytes()),
                    "stderr_sha256": codec.sha((folder / "STDERR.txt").read_bytes()),
                    "full_system_cost_known": False,
                }
                codec.write(folder / "EXIT.json", record)
                stages.append(record)
                child = None
                print(json.dumps(record, sort_keys=True), flush=True)
                if code or timed_out:
                    codec.write(owned / "FAILED.json", summary("FAILED"))
                    return 1
                result = json.loads(
                    (root / "results" / mode / "RESULT.json").read_bytes()
                )
                if (
                    result["actual_model_calls"] != 8
                    or result["new_training_updates"] != 0
                ):
                    raise ValueError(
                        "successful stage did not account for exactly eight actual calls"
                    )
            complete = summary("COMPLETE")
            complete["actual_model_calls"] = 24
            codec.write(owned / "COMPLETE.json", complete)
            return 0
        except BaseException as error:
            cleanup = stop_owned_child(child)
            record = summary("WRAPPER_FAILED")
            record.update(
                error_type=type(error).__name__,
                error=str(error),
                traceback=traceback.format_exc(),
                known_child_cleanup=cleanup,
                automatic_retry=False,
            )
            codec.write(owned / "WRAPPER_FAILED.json", record)
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    raise SystemExit(own(args.root, args.source_commit))
