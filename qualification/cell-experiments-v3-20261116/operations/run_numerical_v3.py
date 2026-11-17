"""Run the frozen tiny-Qwen implementation tests once on the pinned CPU runtime."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import zipfile

ROOT = Path("/home/qq/hepta-cell-experiments-v3-20261116-0c078a")
ARCHIVE = Path("/home/qq/hepta-cell-experiments-v3-qwen-source-01-20261116-0c078a.zip")
DIGEST = "6d471456bfcf6e7a9ade52ea995317f9c0894571d9bd5ebe96dcb845d68e58ad"
if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != DIGEST:
    raise ValueError("source archive changed")
candidate = ROOT / "candidate-qwen-numeric-01"
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
start = time.perf_counter()
with (ROOT / "NUMERICAL_TESTS_01.log").open("xb") as stream:
    result = subprocess.run(argv, cwd=candidate, env=env, stdout=stream,
                            stderr=subprocess.STDOUT, timeout=300)
receipt = {"argv": argv, "exit_code": result.returncode,
           "wall_seconds": time.perf_counter() - start, "source_archive_sha256": DIGEST,
           "log_sha256": hashlib.sha256((ROOT / "NUMERICAL_TESTS_01.log").read_bytes()).hexdigest(),
           "scope": "tiny-random-model numerical tests; not experiment fits or capability evidence"}
with (ROOT / "NUMERICAL_TESTS_01.json").open("x") as stream:
    json.dump(receipt, stream, sort_keys=True, indent=2)
print(json.dumps(receipt))
print((ROOT / "NUMERICAL_TESTS_01.log").read_text()[-3500:])
raise SystemExit(result.returncode)
