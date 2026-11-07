"""Task-specific bounded supervisor; source arrives as a hash-pinned stdin bundle."""

import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time

BUNDLE_SHA = "12241add5ffcb665c054db6ec5bc7012bad278fab171ed7175a7d14a8ab32462"
ROOT = Path("/home/qq/work/hepta-ndu-text-image-20261106-de511")
PYTHON = "/home/qq/work/hepta-r1-4835-20261105-w0-r1/venv/bin/python"
MODEL_ROOT = "/home/qq/work/hepta-r1-4835-20261105-w0-r1/models"


def write(path, data):
    with path.open("x") as stream:
        json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


raw = sys.stdin.buffer.read(1024 * 1024 + 1)
if hashlib.sha256(raw).hexdigest() != BUNDLE_SHA:
    raise ValueError("Unexpected source bundle")
bundle = json.loads(raw)
ROOT.mkdir(parents=True, exist_ok=False)
source = ROOT / "source"
source.mkdir()
memory = {k: int(v.split()[0]) * 1024 for k, v in
          (line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())}
preflight = {"mem_available_bytes": memory["MemAvailable"], "disk_free_bytes": shutil.disk_usage(ROOT).free,
             "source_bundle_sha256": BUNDLE_SHA, "cpu_quota_percent": 200, "memory_max_bytes": 12 * 1024**3,
             "threads": 2, "cpu_seconds_per_probe": 180, "wall_seconds_per_probe": 240}
write(ROOT / "PREFLIGHT.json", preflight)
if memory["MemAvailable"] < 16 * 1024**3 or preflight["disk_free_bytes"] < 2 * 1024**3:
    raise RuntimeError("Insufficient current host headroom")
manifest = []
for item in bundle["files"]:
    relative = Path(item["path"])
    if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".py":
        raise ValueError("Invalid source member")
    path = source / relative
    content = item["content"].encode()
    if len(content) != item["bytes"] or hashlib.sha256(content).hexdigest() != item["sha256"]:
        raise ValueError("Source member identity differs")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)
    manifest.append({k: item[k] for k in ("path", "sha256", "bytes")})
write(ROOT / "SOURCE_MANIFEST.json", manifest)
env = dict(os.environ, PYTHONPATH=str(source / "scripts") + ":" + str(source),
           PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="2", MKL_NUM_THREADS="2",
           HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")


def source_seal():
    return {item["path"]: hashlib.sha256((source / item["path"]).read_bytes()).hexdigest() for item in manifest}


def child_limit():
    resource.setrlimit(resource.RLIMIT_CPU, (180, 181))


commands = [("torch-contracts", [PYTHON, "-m", "unittest", "ndu_semantic_state.test_torch_adapter", "-v"], 60),
            ("real-content", [PYTHON, "-m", "ndu_portfolio.real_content", "--model-dir", MODEL_ROOT + "/vlm",
                              "--image", MODEL_ROOT + "/task/input.jpg", "--output", str(ROOT / "probe")], 240)]
receipt = {"status": "STARTED", "source_before": source_seal(), "stages": []}
write(ROOT / "STARTED.json", receipt)
start = time.perf_counter()
for label, command, timeout in commands:
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    wall = time.perf_counter()
    row = {"label": label, "argv": command, "source_before": source_seal()}
    with (ROOT / (label + ".stdout")).open("xb") as out, (ROOT / (label + ".stderr")).open("xb") as err:
        try:
            done = subprocess.run(command, cwd=source, env=env, stdout=out, stderr=err,
                                  timeout=timeout, check=False, preexec_fn=child_limit)
            row["returncode"] = done.returncode
        except subprocess.TimeoutExpired:
            row["returncode"] = 124
            row["timeout"] = True
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    row.update(wall_seconds=time.perf_counter() - wall,
               child_cpu_seconds=(after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime),
               source_after=source_seal())
    row["source_unchanged"] = row["source_before"] == row["source_after"] == receipt["source_before"]
    receipt["stages"].append(row)
    write(ROOT / (label + ".receipt.json"), row)
    if row["returncode"] != 0 or not row["source_unchanged"]:
        break
receipt["status"] = "SUCCEEDED" if len(receipt["stages"]) == 2 and all(
    row["returncode"] == 0 and row["source_unchanged"] for row in receipt["stages"]) else "FAILED"
receipt["wall_seconds"] = time.perf_counter() - start
receipt["source_after"] = source_seal()
receipt["energy_joules"] = None
receipt["scope"] = "Explicit CPU content-gradient qualification only; no controller experiment or adoption."
write(ROOT / "EXECUTION.json", receipt)
print(json.dumps({"status": receipt["status"], "root": str(ROOT),
                  "stages": [{"label": s["label"], "returncode": s["returncode"], "child_cpu_seconds": s["child_cpu_seconds"]}
                             for s in receipt["stages"]]}))
raise SystemExit(0 if receipt["status"] == "SUCCEEDED" else 1)
