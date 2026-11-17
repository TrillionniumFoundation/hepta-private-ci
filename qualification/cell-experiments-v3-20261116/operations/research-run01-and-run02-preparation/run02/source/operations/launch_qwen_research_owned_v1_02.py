"""Run one frozen research writer and preserve actual wait and log evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import subprocess
import sys
import time

RUNTIME = Path("/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a")
WORKSPACE = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
ROLES = {
    "research": ("research-sft-v1-source/run_research_sft_v1.py",
                 "research-sft-02", "owned-research-sft-02", "RESEARCH_LAUNCH_FREEZE_02.json"),
    "postrun": ("research-diagnostic-v1-source-02/qwen_research_diagnostic_v1.py",
                "research-diagnostic-02", "owned-research-diagnostic-02",
                "RESEARCH_POSTRUN_LAUNCH_FREEZE_02.json"),
}
DISQUALIFIED = {
    "research_only": True, "scientific_confirmation_qualified": False,
    "native_cell_adoption": False, "proof_of_useful_work_eligible": False,
    "circuit_qualified": False, "new_C": False, "candidate_selected": None,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checksum(path):
    require(path.is_file() and path.resolve() == path, "regular nonsymlink input required")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 ** 2), b""):
            digest.update(block)
    return digest.hexdigest()


def bounded(relative):
    name = PurePosixPath(relative)
    require(name.parts and not name.is_absolute() and ".." not in name.parts
            and str(name) == relative and "\\" not in relative, "bounded workspace path required")
    path = WORKSPACE / name
    require(path.resolve() == path and path.is_relative_to(WORKSPACE), "symlink or escape rejected")
    return path


def write_new(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def identity(pid):
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    try:
        raw = Path("/proc", str(pid), "stat").read_text()
    except FileNotFoundError:
        return {"pid": pid, "boot": boot, "start_time_ticks": None,
                "observation": "absent_before_identity_read"}
    fields = raw.rsplit(")", 1)[1].split()
    return {"pid": pid, "boot": boot, "start_time_ticks": int(fields[19]),
            "process_group_id": int(fields[2]), "stat_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "clock_ticks_per_second": os.sysconf("SC_CLK_TCK")}


def notify(value, descriptor=1):
    try:
        os.write(descriptor, json.dumps(value).encode() + b"\n")
    except OSError:
        pass


def run_owned(output, argv, cwd, environment, metadata, descriptor=1):
    output.mkdir(mode=0o700, exist_ok=False)
    intent = dict(metadata, schema="hepta.research-owned-intent.v1",
                  created_at_ns=time.time_ns(), argv=argv, cwd=str(cwd),
                  wrapper_identity=identity(os.getpid()), automatic_retry=False)
    intent_sha = write_new(output / "INTENT.json", intent)
    before = time.perf_counter()
    stdout, stderr = output / "stdout.log", output / "stderr.log"
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    with stdout.open("xb", buffering=0) as out, stderr.open("xb", buffering=0) as err:
        child = subprocess.Popen(argv, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                                 stdout=out, stderr=err, start_new_session=True)
        started = {"schema": "hepta.research-owned-started.v1", "started_at_ns": time.time_ns(),
                   "intent_sha256": intent_sha, "argv": argv,
                   "child_identity": identity(child.pid), "wrapper_identity": identity(os.getpid()),
                   "stdout_path": str(stdout), "stderr_path": str(stderr)}
        started_sha = write_new(output / "STARTED.json", started)
        notify({"state": "CHILD_STARTED", "role": metadata["role"],
                "pid": child.pid, "started_sha256": started_sha}, descriptor)
        exit_code = child.wait()
        os.fsync(out.fileno())
        os.fsync(err.fileno())
    result = {"schema": "hepta.research-owned-exit.v1", "completed_at_ns": time.time_ns(),
              "role": metadata["role"], "operation_key": metadata["operation_key"],
              "child_identity": started["child_identity"], "argv": argv,
              "wait_returncode": exit_code, "exit_source": "subprocess.Popen.wait",
              "intent_sha256": intent_sha, "started_sha256": started_sha,
              "child_wall_seconds": time.perf_counter() - before,
              "stdout": {"bytes": stdout.stat().st_size, "sha256": checksum(stdout)},
              "stderr": {"bytes": stderr.stat().st_size, "sha256": checksum(stderr)},
              "h_terminal_status": "not_observed_by_this_wrapper",
              "automatic_retry": False, "independent_sample_increment": 0}
    exit_sha = write_new(output / "EXIT.json", result)
    notify({"state": "CHILD_EXIT", "role": metadata["role"], "wait_returncode": exit_code,
            "exit_sha256": exit_sha, "stdout_bytes": stdout.stat().st_size,
            "stderr_bytes": stderr.stat().st_size}, descriptor)
    return exit_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=sorted(ROLES), required=True)
    parser.add_argument("--freeze-sha256", required=True)
    args = parser.parse_args()
    require(Path(sys.executable) == RUNTIME / "venv/bin/python"
            and Path(sys.prefix) == RUNTIME / "venv" and sys.flags.isolated
            and sys.dont_write_bytecode, "fixed isolated HOME runtime required")
    require(WORKSPACE.is_dir() and WORKSPACE.resolve() == WORKSPACE
            and WORKSPACE.stat().st_uid == os.getuid(), "owned RAM workspace required")
    entry_name, target_name, owned_name, freeze_name = ROLES[args.role]
    freeze_path = bounded("operations/" + freeze_name)
    require(checksum(freeze_path) == args.freeze_sha256, "launch freeze changed")
    freeze = json.loads(freeze_path.read_bytes())
    require(freeze.get("schema") == "hepta.research-owned-launch-freeze.v1"
            and freeze.get("role") == args.role
            and freeze.get("workspace_root") == str(WORKSPACE)
            and freeze.get("runtime_root") == str(RUNTIME)
            and freeze.get("output_directory") == target_name
            and freeze.get("qualification") == DISQUALIFIED, "launch identity or research scope differs")
    require(freeze.get("boot") == identity(os.getpid())["boot"], "preflight host boot changed")
    entry = bounded(entry_name)
    require(checksum(entry) == freeze["entry_sha256"], "entry bytes changed")
    require(checksum(Path(__file__).absolute()) == freeze["wrapper_sha256"], "wrapper bytes changed")
    argv = freeze["argv"]
    require(isinstance(argv, list) and all(isinstance(x, str) for x in argv)
            and argv[:4] == [str(RUNTIME / "venv/bin/python"), "-I", "-B", str(entry)],
            "frozen direct Python command required")
    immutable = freeze["immutable_inputs"]
    require(isinstance(immutable, dict) and immutable, "bound immutable inputs required")
    for name, item in immutable.items():
        path = bounded(name)
        require(path.stat().st_size == item["bytes"] and checksum(path) == item["sha256"],
                "immutable launch input changed: " + name)
    for name in (target_name, owned_name):
        require(not bounded(name).exists(), "exclusive output already exists")
    memory = next(int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines()
                  if line.startswith("MemAvailable:"))
    available = shutil.disk_usage(WORKSPACE).free
    require(memory >= 10 * 1024 ** 3 and available >= 8 * 1024 ** 3,
            "insufficient RAM workspace resources")
    environment = os.environ.copy()
    for key, name in (("TMPDIR", "tmp"), ("XDG_CACHE_HOME", "cache"),
                      ("CUDA_CACHE_PATH", "cuda-cache"), ("TRITON_CACHE_DIR", "triton-cache"),
                      ("TORCH_HOME", "torch-cache"), ("HF_HOME", "hf-cache")):
        directory = bounded(name)
        require(directory.is_dir(), "prepared cache directory required")
        environment[key] = str(directory)
    metadata = {"role": args.role, "operation_key": freeze["operation_key"],
                "freeze_sha256": args.freeze_sha256, "entry_sha256": freeze["entry_sha256"],
                "wrapper_sha256": freeze["wrapper_sha256"], "output_directory": target_name,
                "MemAvailable_bytes": memory, "tmpfs_available_bytes": available,
                "qualification": DISQUALIFIED, "independent_sample_increment": 0}
    code = run_owned(bounded(owned_name), argv, WORKSPACE, environment, metadata)
    return code if code >= 0 else 128 - code


if __name__ == "__main__":
    raise SystemExit(main())
