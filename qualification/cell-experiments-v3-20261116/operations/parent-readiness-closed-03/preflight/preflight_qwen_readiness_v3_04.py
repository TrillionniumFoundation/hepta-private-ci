"""Read-only host observations immediately before the exclusive model operation."""

import hashlib
import importlib.util
import os
import shutil
import sys
import zipfile
import json
from pathlib import Path
import subprocess
import time


ROOT = Path("/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a")
WORKSPACE = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
HELPER = WORKSPACE / "operations/run_qwen_readiness_v3_03.py"
HELPER_SHA = "9d1d462d219cbdf83e37f041b55b1f36e23cc407135b89adf0507a7ef0fdbf75"
OUTPUT = WORKSPACE / "readiness-preflight-03"


def main():
    assert Path(sys.executable) == ROOT / "venv/bin/python" and Path(sys.prefix) == ROOT / "venv"
    assert sys.flags.isolated and sys.dont_write_bytecode
    assert WORKSPACE.resolve() == WORKSPACE and WORKSPACE.stat().st_uid == os.getuid()
    assert hashlib.sha256(HELPER.read_bytes()).hexdigest() == HELPER_SHA
    spec = importlib.util.spec_from_file_location("readiness_preflight03", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bindings = module.workspace_evidence()
    OUTPUT.mkdir(mode=0o700, exist_ok=False)
    module.OUTPUT = OUTPUT
    ready, materials, recovery, distributions = module.recovery_evidence()
    assert recovery[module.ENVIRONMENT_PATH] == "7f9368b38843ab1fbf158108e75008a04bf8d3b57c1e73a3e523d4bac832fac9"
    copies = []
    for row in materials["files"]:
        original = ROOT / "materials-recovered" / row["path"]
        copy = WORKSPACE / "materials-recovered" / row["path"]
        assert original.resolve() == original and copy.resolve() == copy
        assert original.stat().st_size == copy.stat().st_size == row["bytes"]
        assert module.file_hash(original) == module.file_hash(copy) == row["sha256"]
        copies.append({key: row[key] for key in ("path", "bytes", "sha256")})
    manifest = module.read_json(WORKSPACE / "operations/QWEN_SOURCE_02.json", module.SOURCE_MANIFEST_SHA)
    assert module.file_hash(WORKSPACE / "qwen-source-02.zip") == module.SOURCE_SHA
    with zipfile.ZipFile(WORKSPACE / "qwen-source-02.zip") as package:
        assert package.testzip() is None
        names = package.namelist()
        assert len(names) == len(set(names)) == 119 and set(names) == set(manifest["files"])
        assert not module.FORBIDDEN_MEMBERS.intersection(names)
        assert all(hashlib.sha256(package.read(name)).hexdigest() == manifest["files"][name] for name in names)
        assert sum(name.startswith("scripts/cell_experiments/") for name in names) == 64
    assert not any(Path("/proc", str(pid)).exists() for pid in (1555758, 1555742))
    memory = next(int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:"))
    assert memory >= 10 * 1024**3 and shutil.disk_usage(WORKSPACE).free >= 8 * 1024**3
    ready_path = ROOT / "operations/recovery-03/ENVIRONMENT_READY.json"
    raw = ready_path.read_bytes()
    ready = json.loads(raw)
    if (ready.get("status"), ready.get("recovery_id"), ready.get("model_loaded"),
            ready.get("training_started")) != ("READY", "recovery-03", False, False):
        raise ValueError("completed unused environment receipt required")
    verification = []
    for row in ready["verification_files"]:
        path = ROOT / row["path"]
        if path.is_symlink() or not path.is_file():
            raise ValueError("regular verification file required")
        contents = path.read_bytes()
        observed = {"path": row["path"], "bytes": len(contents),
                    "sha256": hashlib.sha256(contents).hexdigest()}
        if observed != row:
            raise ValueError("environment evidence changed")
        verification.append(observed)
    for name in ("candidate-qwen-03", "probe-qwen-parent-03", "owned-qwen-parent-03"):
        if (WORKSPACE / name).exists() or (WORKSPACE / name).is_symlink():
            raise ValueError("exclusive operation path already exists: " + name)
    commands = []
    for query in (("--query-gpu=index,name,memory.free,memory.total", "--format=csv,noheader,nounits"),
                  ("--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits")):
        argv = ["/usr/bin/nvidia-smi", *query]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
        commands.append({"argv": argv, "exit_code": result.returncode,
                         "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode != 0:
            raise ValueError("GPU prelaunch observation failed")
    devices = [line.split(",") for line in commands[0]["stdout"].splitlines() if line.strip()]
    zero = [row for row in devices if row[0].strip() == "0"]
    if len(zero) != 1 or int(zero[0][2].strip()) < 4096:
        raise ValueError("at least 4 GiB free on physical GPU 0 required")
    desktop = []
    for line in commands[1]["stdout"].splitlines():
        if not line.strip():
            continue
        pid, remainder = line.split(",", 1)
        process, memory = remainder.rsplit(",", 1)
        pid, process = int(pid.strip()), process.strip()
        known_chrome = pid == 9243 and process.startswith("/opt/google/chrome/chrome --type=gpu-process ")
        known_telegram = pid == 10568 and process == "/home/qian-qi/.local/opt/Telegram/Telegram"
        if not (known_chrome or known_telegram):
            raise ValueError("additional GPU compute process observed; do not start")
        desktop.append({"pid": pid, "process_name": process, "used_memory_mib": int(memory.strip())})
    report = {"schema": "hepta.qwen-readiness-host-preflight.v3", "status": "PASS",
              "observed_at_ns": time.time_ns(), "environment_ready_sha256": hashlib.sha256(raw).hexdigest(),
              "verification_files": verification, "gpu_commands": commands,
              "exclusive_directories_absent": ["candidate-qwen-03", "probe-qwen-parent-03", "owned-qwen-parent-03"],
              "model_started": False, "training_started": False,
              "observed_desktop_gpu_processes_preserved": desktop,
              "additional_compute_process_observed": False,
              "device_isolation_claimed": False,
              "visibility_limit": "observed process identity and available memory; desktop GPU use remains present"}
    assert "torch" not in sys.modules
    report.update(helper_sha256=HELPER_SHA, checker_sha256=module.file_hash(Path(__file__)),
                  runtime_root=str(ROOT), workspace_root=str(WORKSPACE), workspace_bindings=bindings,
                  recovery_bindings=recovery, source_archive_sha256=module.SOURCE_SHA,
                  source_manifest_sha256=module.SOURCE_MANIFEST_SHA, source_members_checked=119,
                  core_members_checked=64, source_and_destination_materials=copies,
                  saved_dependency_distribution_count=len(distributions), MemAvailable_bytes=memory,
                  tmpfs_available_bytes=shutil.disk_usage(WORKSPACE).free,
                  original_02_pids_currently_absent=[1555758,1555742], original_02_exit_code=None,
                  original_02_capture_complete=False, torch_imported=False,
                  model_calls_added=0, training_steps_added=0, new_C=False, independent_sample_increment=0)
    module.write_new(OUTPUT / "RESULT.json", report)
    print(json.dumps({"status":"PASS", "output":str(OUTPUT),
                      "result_sha256":module.file_hash(OUTPUT / "RESULT.json"),
                      "source_members":119, "core_members":64, "material_files":len(copies),
                      "MemAvailable_bytes":memory, "tmpfs_available_bytes":report["tmpfs_available_bytes"],
                      "gpu_commands":commands, "model_calls_added":0}), flush=True)


if __name__ == "__main__":
    main()
