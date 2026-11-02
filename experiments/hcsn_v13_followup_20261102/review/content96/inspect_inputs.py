"""Read-only schema inspection of the already authorized fixed replay evidence."""
import json
from pathlib import Path
import numpy as np

base = Path("experiments/hcsn_v13_followup_20261102/joint_core/results/content_evaluation002")
for name in ("RESULT.json", "AGGREGATES.json", "START.json"):
    value = json.loads((base / name).read_text())
    print(name, {key: (f"list[{len(item)}]" if isinstance(item, list) else
                      list(item) if isinstance(item, dict) else item)
                 for key, item in value.items() if key != "publication_gate"})
    if name == "RESULT.json":
        print("first row", value["rows"][0])
        print("first contrast", value["contrasts"][0])
path = sorted(base.glob("*.npz"))[0]
with np.load(path, allow_pickle=False) as raw:
    print("raw", path.name)
    for key in raw.files:
        value = raw[key]
        print(key, value.shape, str(value.dtype), value.reshape(-1)[:14].tolist())
