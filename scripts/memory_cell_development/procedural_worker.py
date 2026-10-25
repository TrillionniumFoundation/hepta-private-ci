"""One fixed fit or fresh-process parameter-only read; CPU bounded."""

import json
from pathlib import Path
import resource
import sys

import torch

from parametric_model import SourceMemoryCell
from parametric_worker import run
from procedural_support import save, sha


request = json.load(sys.stdin)
resource.setrlimit(resource.RLIMIT_CPU, (180, 185))
torch.set_num_threads(2)
if request["mode"] == "train":
    raw = Path(request["training_spec"]).read_bytes()
    assert sha(raw) == request["training_spec_sha256"]
    protocol = json.loads(raw)
    cell = SourceMemoryCell(
        request["model"], rank=protocol["rank"], seed=request["seed"]
    )
    cell.reset(protocol["scope"])
    receipt = cell.fit_sources(
        protocol["facts"],
        protocol["steps"],
        protocol["learning_rate"],
        protocol["templates"],
    )
    directory = Path(request["checkpoint"])
    manifest = cell.save(directory)
    save(directory.parent / "training.json", receipt)
    result = dict(
        manifest_sha256=manifest,
        receipt=receipt,
        checkpoint=str(directory),
        process_cpu_seconds=resource.getrusage(resource.RUSAGE_SELF).ru_utime
        + resource.getrusage(resource.RUSAGE_SELF).ru_stime,
    )
else:
    assert request["mode"] == "read"
    result = run(request["payload"])
print(json.dumps(result, sort_keys=True, allow_nan=False))
