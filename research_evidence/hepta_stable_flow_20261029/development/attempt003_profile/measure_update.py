"""Single-update engineering timing on independent development-only data."""
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from experiments.call_put_stable_flow.data import generate
from experiments.call_put_stable_flow.models import ARMS, build_model
from experiments.call_put_stable_flow.study import _sources, _train_update

torch.set_num_threads(1)
output = Path(__file__).resolve().parent
raw = generate("selective_copy", 32, 393001)
np.savez_compressed(output / "train_only.npz", **raw)
data = {name: torch.from_numpy(value) for name, value in raw.items()}
result = {"new_execution": True, "development_only": True,
          "formal_validation_or_test_read": False, "source_sha256": _sources(),
          "profile_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "rows": []}
for arm in ARMS:
    model = build_model(arm, 394001)
    optimizer = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=0.003)
    start = time.process_time()
    loss, norm = _train_update(model, optimizer, data, torch.arange(32), {})
    row = {"arm": arm, "one_update_cpu_seconds": time.process_time() - start,
           "loss": loss, "gradient_norm": norm}
    result["rows"].append(row)
    print(json.dumps(row), flush=True)
with (output / "profile.json").open("x") as stream:
    json.dump(result, stream, indent=2)
