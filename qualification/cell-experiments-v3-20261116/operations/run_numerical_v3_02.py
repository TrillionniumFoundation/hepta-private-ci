"""Run the frozen tiny-Qwen implementation tests once on the pinned CPU runtime."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import zipfile

ROOT = Path("/home/qq/hepta-cell-experiments-v3-20261116-0c078a")
ARCHIVE = Path("/home/qq/hepta-cell-experiments-v3-qwen-source-02-20261116-0c078a.zip")
DIGEST = "38a6f8bbc8a602befcd45ebd919bbcb2eca12d9f105798b29d72b2eb051c42d7"
if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != DIGEST:
    raise ValueError("source archive changed")
candidate = ROOT / "candidate-qwen-numeric-02"
candidate.mkdir(exist_ok=False)
with zipfile.ZipFile(ARCHIVE) as source:
    for member in source.infolist():
        if member.filename.startswith("/") or ".." in Path(member.filename).parts:
            raise ValueError("unsafe source member")
    source.extractall(candidate)
argv = ["/home/qq/hepta-smollm2-weight-research-20261103/ci-env/bin/python",
        "-B", "-m", "unittest", "cell_experiments.test_causal_train_v3", "-v"]
env = dict(os.environ, PYTHONPATH=str(candidate / "scripts"),
           OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2")
runtime = subprocess.run([argv[0], "-c", "import json,torch,transformers,peft,safetensors,tokenizers,numpy; print(json.dumps({k:v.__version__ for k,v in dict(torch=torch,transformers=transformers,peft=peft,safetensors=safetensors,tokenizers=tokenizers,numpy=numpy).items()}))"], capture_output=True, text=True, timeout=60, env=env)
if runtime.returncode:
    raise RuntimeError(runtime.stderr)
versions = json.loads(runtime.stdout)
expected = {"torch":"2.9.1+cpu","transformers":"4.57.3","peft":"0.18.0","safetensors":"0.7.0","tokenizers":"0.22.2","numpy":"1.26.4"}
if versions != expected:
    raise ValueError("numerical runtime versions changed")
start = time.perf_counter()
with (ROOT / "NUMERICAL_TESTS_02.log").open("xb") as stream:
    result = subprocess.run(argv, cwd=candidate, env=env, stdout=stream,
                            stderr=subprocess.STDOUT, timeout=300)
receipt = {"argv": argv, "runtime": versions, "prior_import_failure_job": "1a1e6d7935b-392-3c55", "exit_code": result.returncode,
           "wall_seconds": time.perf_counter() - start, "source_archive_sha256": DIGEST,
           "log_sha256": hashlib.sha256((ROOT / "NUMERICAL_TESTS_02.log").read_bytes()).hexdigest(),
           "scope": "tiny-random-model numerical tests; not experiment fits or capability evidence"}
with (ROOT / "NUMERICAL_TESTS_02.json").open("x") as stream:
    json.dump(receipt, stream, sort_keys=True, indent=2)
print(json.dumps(receipt))
print((ROOT / "NUMERICAL_TESTS_02.log").read_text()[-3500:])
raise SystemExit(result.returncode)
