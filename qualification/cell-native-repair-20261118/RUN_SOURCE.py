"""Own one fixed diagnostic process after the previous GPU worker has exited."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import time

ROOT = Path("/home/qian-qi/work/hepta-e4-native-repair-20261118-2e9b")
SOURCE = ROOT / "source"
ARTIFACT = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
RUNTIME = Path("/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a")
OWNED = ROOT / "owned-run-1"
OUTPUT = ROOT / "run-1"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open("xb") as stream:
        stream.write(json.dumps(value, sort_keys=True, allow_nan=False).encode() + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def main():
    OWNED.mkdir(exist_ok=False)
    started = time.monotonic()
    initial_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
    deployment = json.loads((ROOT / "DEPLOYMENT.json").read_text())
    assert deployment["source_commit"] == "ad73c100feece91c152a96ba121d2e9494f10607"
    assert digest(ROOT / "SOURCE.tar.gz") == "46f989ccb6a5393d8ee52fa40600aab7abf8cf8ac325aabeee4f7e026e0f46ae"
    assert len(deployment["files"]) == 165
    for name, expected in deployment["files"].items():
        assert digest(SOURCE / name) == expected, name
    prior_root = Path("/home/qian-qi/work/hepta-e1e6-diagnostic-20261118-556e/candidate-4d9fc82")
    prior = {"exit": prior_root / "owned-run-2/EXIT.json", "result": prior_root / "run-2/RESULT.json"}
    values = {key: json.loads(path.read_text()) for key, path in prior.items()}
    assert values["exit"]["wait_returncode"] == 0 and values["result"]["status"] == "COMPLETE"
    command = [str(RUNTIME / "venv/bin/python"), "-I", "-B",
               str(SOURCE / "scripts/cell_experiments/diagnostic_run_v4.py"),
               "--provider-python", str(RUNTIME / "venv/bin/python"),
               "--provider-script", str(SOURCE / "scripts/cell_experiments/diagnostic_provider_v4.py"),
               "--artifact-root", str(ARTIFACT),
               "--module-root", str(SOURCE / "scripts/cell_experiments"),
               "--output", str(OUTPUT), "--study", "repair_retrieval"]
    lock_path = ARTIFACT / "research-round03-20261118-392934-b/WORKER.lock"
    assert lock_path.is_file() and not lock_path.is_symlink()
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        gpu = subprocess.run(["/usr/bin/nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"], capture_output=True, text=True, check=True)
        assert int(gpu.stdout.splitlines()[0]) >= 4096
        intent = {"schema": "hepta.diagnostic-owned-run.v1", "command": command,
                  "source_commit": deployment["source_commit"], "wrapper_sha256": digest(Path(__file__)),
                  "deployment_sha256": digest(ROOT / "DEPLOYMENT.json"),
                  "prior_receipts": {key: {"path": str(path), "sha256": digest(path)} for key, path in prior.items()},
                  "lock": str(lock_path), "gpu_free_mib_prefilter": int(gpu.stdout.splitlines()[0]),
                  "actual_cuda_gate_unchanged": True, "planned_model_calls": 88,
                  "started_at_ns": time.time_ns(), "automatic_retry": False}
        write(OWNED / "INTENT.json", intent)
        env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1", TOKENIZERS_PARALLELISM="false", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
        timed_out = False
        with (OWNED / "STDOUT.txt").open("xb") as stdout, (OWNED / "STDERR.txt").open("xb") as stderr:
            child = subprocess.Popen(command, cwd=SOURCE, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
            write(OWNED / "STARTED.json", {"pid": child.pid, "process_group_id": child.pid, "started_at_ns": time.time_ns(), "intent_sha256": digest(OWNED / "INTENT.json")})
            try:
                code = child.wait(timeout=1500)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    code = child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    code = child.wait(timeout=30)
        final_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
        receipt = {"pid": child.pid, "wait_returncode": code, "exit_source": "subprocess.Popen.wait", "timed_out": timed_out,
                   "automatic_retry": False, "wall_seconds": time.monotonic() - started,
                   "observed_child_user_cpu_seconds": final_cpu.ru_utime - initial_cpu.ru_utime,
                   "observed_child_system_cpu_seconds": final_cpu.ru_stime - initial_cpu.ru_stime,
                   "cost_scope": "owned child and waited descendants; nested model/verifier costs must not be added again",
                   "full_system_cost_known": False, "monetary_cost": None, "energy_joules": None,
                   "result_present": (OUTPUT / "RESULT.json").is_file(), "failure_present": (OUTPUT / "FAILED.json").is_file(),
                   "stdout_sha256": digest(OWNED / "STDOUT.txt"), "stderr_sha256": digest(OWNED / "STDERR.txt")}
        write(OWNED / "EXIT.json", receipt)
        print(json.dumps(receipt), flush=True)
        raise SystemExit(code if code >= 0 else 1)


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        if not isinstance(error, SystemExit) and OWNED.is_dir():
            write(OWNED / "WRAPPER_FAILED.json", {"error_type": type(error).__name__, "error": str(error), "automatic_retry": False, "cost_complete": False})
        raise
