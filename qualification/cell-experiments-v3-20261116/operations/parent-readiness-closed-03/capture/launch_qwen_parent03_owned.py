"""Own one child and retain its real wait result and original streams in RAM."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path("/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a")
WORKSPACE = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
HELPER = WORKSPACE / "operations/run_qwen_readiness_v3_03.py"
HELPER_SHA = "9d1d462d219cbdf83e37f041b55b1f36e23cc407135b89adf0507a7ef0fdbf75"
PREFLIGHT = WORKSPACE / "readiness-preflight-03b/RESULT.json"
PREFLIGHT_SHA = "928350d07d2db84beb4e7305a7bdc9403910c5e22700986f8ccb5a42bae6a882"
BOOT = "8c55b477-233a-4771-995a-6f666f6299b3"
KEY = "hepta-e1e6-v3-20261116-0c078a-qwen-readiness03"
OUTPUT = WORKSPACE / "owned-qwen-parent-03"


def sha(path):
    assert path.is_file() and path.resolve() == path
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for raw in iter(lambda: stream.read(1024**2), b""):
            result.update(raw)
    return result.hexdigest()


def write_new(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def notify(value):
    try:
        os.write(sys.stdout.fileno(), json.dumps(value).encode() + b"\n")
    except OSError:
        pass


def process_identity(pid):
    path = Path("/proc", str(pid), "stat")
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return {"pid": pid, "boot": BOOT, "start_time_ticks": None,
                "observation": "process stat absent before identity read"}
    fields = raw.rsplit(")", 1)[1].split()
    return {"pid": pid, "boot": BOOT, "start_time_ticks": int(fields[19]),
            "stat_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "clock_ticks_per_second": os.sysconf("SC_CLK_TCK")}


def observe_resources():
    memory = next(int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:"))
    available = shutil.disk_usage(WORKSPACE).free
    assert memory >= 10 * 1024**3 and available >= 8 * 1024**3
    commands = []
    for query in (("--query-gpu=index,name,memory.free,memory.total", "--format=csv,noheader,nounits"),
                  ("--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits")):
        argv = ["/usr/bin/nvidia-smi", *query]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
        commands.append({"argv": argv, "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        assert result.returncode == 0
    zero = [line.split(",") for line in commands[0]["stdout"].splitlines() if line.split(",")[0].strip() == "0"]
    assert len(zero) == 1 and int(zero[0][2].strip()) >= 4096
    for line in commands[1]["stdout"].splitlines():
        if not line.strip():
            continue
        pid, remainder = line.split(",", 1)
        process, _memory = remainder.rsplit(",", 1)
        pid, process = int(pid.strip()), process.strip()
        assert ((pid == 9243 and process.startswith("/opt/google/chrome/chrome --type=gpu-process "))
                or (pid == 10568 and process == "/home/qian-qi/.local/opt/Telegram/Telegram"))
    return {"observed_at_ns": time.time_ns(), "MemAvailable_bytes": memory,
            "tmpfs_available_bytes": available, "gpu_commands": commands,
            "device_isolation_claimed": False}


def main():
    assert Path(sys.executable) == ROOT / "venv/bin/python" and Path(sys.prefix) == ROOT / "venv"
    assert sys.flags.isolated and sys.dont_write_bytecode
    assert Path("/proc/sys/kernel/random/boot_id").read_text().strip() == BOOT
    assert WORKSPACE.resolve() == WORKSPACE and WORKSPACE.stat().st_uid == os.getuid()
    assert sha(HELPER) == HELPER_SHA and sha(PREFLIGHT) == PREFLIGHT_SHA
    preflight = json.loads(PREFLIGHT.read_bytes())
    assert preflight["status"] == "PASS" and preflight["helper_sha256"] == HELPER_SHA
    assert preflight["workspace_root"] == str(WORKSPACE) and preflight["runtime_root"] == str(ROOT)
    assert preflight["model_calls_added"] == preflight["training_steps_added"] == 0
    assert not any(Path("/proc", str(pid)).exists() for pid in (1555758, 1555742))
    for name in ("candidate-qwen-03", "probe-qwen-parent-03", "owned-qwen-parent-03"):
        assert not (WORKSPACE / name).exists() and not (WORKSPACE / name).is_symlink()
    resources = observe_resources()
    OUTPUT.mkdir(mode=0o700, exist_ok=False)
    environment = os.environ.copy()
    for key, relative in (("TMPDIR", "tmp"), ("XDG_CACHE_HOME", "cache"),
                          ("CUDA_CACHE_PATH", "cuda-cache"), ("TRITON_CACHE_DIR", "triton-cache"),
                          ("TORCH_HOME", "torch-cache"), ("HF_HOME", "hf-cache")):
        directory = WORKSPACE / relative
        assert directory.is_dir() and directory.resolve() == directory
        environment[key] = str(directory)
    argv = [str(ROOT / "venv/bin/python"), "-I", "-B", str(HELPER)]
    intent = {"schema": "hepta.qwen-owned-launch-intent.v3", "operation_key": KEY,
              "created_at_ns": time.time_ns(), "argv": argv, "cwd": str(WORKSPACE),
              "helper_sha256": HELPER_SHA, "wrapper_sha256": sha(Path(__file__)),
              "preflight_sha256": PREFLIGHT_SHA, "resources": resources,
              "wrapper_identity": process_identity(os.getpid()),
              "automatic_retry": False, "training_started": False,
              "prior_02_exit_code": None, "prior_02_capture_complete": False,
              "prior_02_costs_remain_additional": True, "independent_sample_increment": 0}
    intent_sha = write_new(OUTPUT / "INTENT.json", intent)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    stdout, stderr = OUTPUT / "stdout.log", OUTPUT / "stderr.log"
    before = time.perf_counter()
    with stdout.open("xb", buffering=0) as out, stderr.open("xb", buffering=0) as err:
        child = subprocess.Popen(argv, cwd=WORKSPACE, env=environment, stdin=subprocess.DEVNULL,
                                 stdout=out, stderr=err, start_new_session=True)
        started = {"schema": "hepta.qwen-owned-child-started.v3", "operation_key": KEY,
                   "started_at_ns": time.time_ns(), "intent_sha256": intent_sha,
                   "argv": argv, "helper_sha256": HELPER_SHA,
                   "child_identity": process_identity(child.pid),
                   "wrapper_identity": process_identity(os.getpid()),
                   "stdout_path": str(stdout), "stderr_path": str(stderr)}
        started_sha = write_new(OUTPUT / "STARTED.json", started)
        notify({"state": "CHILD_STARTED", "pid": child.pid, "started_sha256": started_sha})
        exit_code = child.wait()
        os.fsync(out.fileno())
        os.fsync(err.fileno())
    result = {"schema": "hepta.qwen-owned-child-exit.v3", "operation_key": KEY,
              "completed_at_ns": time.time_ns(), "child_identity": started["child_identity"],
              "wait_returncode": exit_code, "exit_source": "subprocess.Popen.wait",
              "argv": argv, "helper_sha256_before": HELPER_SHA, "helper_sha256_after": sha(HELPER),
              "intent_sha256": intent_sha, "started_sha256": started_sha,
              "child_wall_seconds": time.perf_counter() - before,
              "stdout": {"bytes": stdout.stat().st_size, "sha256": sha(stdout)},
              "stderr": {"bytes": stderr.stat().st_size, "sha256": sha(stderr)},
              "h_terminal_status": "not_observed_by_this_wrapper",
              "automatic_retry": False, "independent_sample_increment": 0}
    exit_sha = write_new(OUTPUT / "EXIT.json", result)
    notify({"state": "CHILD_EXIT", "wait_returncode": exit_code,
            "exit_sha256": exit_sha, "stdout_bytes": stdout.stat().st_size,
            "stderr_bytes": stderr.stat().st_size})
    return exit_code if exit_code >= 0 else 128 - exit_code


if __name__ == "__main__":
    raise SystemExit(main())
