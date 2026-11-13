import hashlib
import json
from pathlib import Path

BASE = Path("/tmp/hepta-36fa-vsc-shared-read-order-review-v1")
INVENTORY = Path("/tmp/hepta-36fa-source-repair-canonical-packet-v1/CANONICAL_CLEAN_INVENTORY.expected.json")
INVENTORY_SHA256 = "13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9"
inventory_bytes = INVENTORY.read_bytes()
assert hashlib.sha256(inventory_bytes).hexdigest() == INVENTORY_SHA256
tracked = {r["path"]: r for r in json.loads(inventory_bytes)["files"]}
fixed = json.loads((BASE / "SOURCE_REFERENCES.json").read_text())
for item in fixed["source_references"]:
    raw = Path(item["local_file"]).read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    row = tracked[item["path"]]
    assert len(raw) == item["bytes"] == row["bytes"]
    assert hashlib.sha256(raw).hexdigest() == item["sha256"] == row["sha256"]
    assert blob == item["git_blob"] == row["working_blob"] == row["index_blob"]
print(json.dumps({"reference_count": len(fixed["source_references"]), "all_exact_cc57": True,
                  "Rust_or_gate_execution": False, "H_calls": 0}, sort_keys=True))

