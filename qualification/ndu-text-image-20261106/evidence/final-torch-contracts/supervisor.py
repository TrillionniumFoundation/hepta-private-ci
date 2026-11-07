"""Final Torch interface verification only; never executes a content model."""
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

EXPECTED = "b0168395c1283abe40e4b762ae528e4ce2356c9a4b50407de8617f75066abc3a"
ROOT = Path("/home/qq/work/hepta-ndu-text-image-20261106-de511-final-contracts")
PYTHON = "/home/qq/work/hepta-r1-4835-20261105-w0-r1/venv/bin/python"
raw = sys.stdin.buffer.read(1024 * 1024 + 1)
if hashlib.sha256(raw).hexdigest() != EXPECTED:
    raise ValueError("Unexpected source bytes")
bundle = json.loads(raw)
ROOT.mkdir(parents=True, exist_ok=False)
source = ROOT / "source"
for item in bundle["files"]:
    relative = Path(item["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Invalid source member")
    data = item["content"].encode()
    if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise ValueError("Mismatched source member")
    path = source / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
env = dict(os.environ, PYTHONPATH=str(source / "scripts"), PYTHONDONTWRITEBYTECODE="1",
           OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")

def limit():
    resource.setrlimit(resource.RLIMIT_CPU, (30, 31))

argv = [PYTHON, "-m", "ndu_portfolio.qualify_text_image", "--torch-only", "--require-torch",
        "--output", str(ROOT / "result")]
before = resource.getrusage(resource.RUSAGE_CHILDREN)
wall = time.perf_counter()
with (ROOT / "stdout.log").open("xb") as out, (ROOT / "stderr.log").open("xb") as err:
    try:
        done = subprocess.run(argv, cwd=source, env=env, stdout=out, stderr=err,
                              timeout=60, preexec_fn=limit, check=False)
        code = done.returncode
    except subprocess.TimeoutExpired:
        code = 124
after = resource.getrusage(resource.RUSAGE_CHILDREN)
receipt = {"scope": "Final Torch interface tests only; no model, data acquisition, or training",
           "source_bundle_sha256": EXPECTED, "returncode": code, "argv": argv,
           "wall_seconds": time.perf_counter() - wall,
           "child_cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
           "energy_joules": None}
with (ROOT / "EXECUTION.json").open("x") as stream:
    json.dump(receipt, stream, indent=2, sort_keys=True); stream.write("\n")
print(json.dumps({"root": str(ROOT), "returncode": code, "scope": receipt["scope"]}))
raise SystemExit(code)
