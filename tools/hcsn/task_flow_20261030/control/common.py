"""Frozen identities and compact local execution receipts."""
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
SOURCES = ["common.py", "data.py", "adapter.py", "oracle.py", "learn.py", "owner.py", "study.py", "audit.py", "protocol.json"]
INHERITED = ["third/memory/reference.py", "third/memory/checkpoints/memory_full_mass_seed29.npz",
             "benchmarks/data.py", "next/full_kernel/baseline_table.npz"]
ACTIONS = ("STOP", "SKIP", "READ", "FIRE")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def protocol():
    return json.loads((HERE / "protocol.json").read_text())


def freeze():
    destination = HERE / "freeze.json"
    if destination.exists():
        return verify()
    record = dict(created_utc=datetime.now(timezone.utc).isoformat(),
                  status="Frozen before new data generation or model outcome evaluation",
                  baseline_commit=protocol()["baseline_commit"],
                  source_sha256={p: sha(HERE / p) for p in SOURCES},
                  inherited_sha256={p: sha(ROOT / p) for p in INHERITED})
    save(destination, record)
    return record


def verify():
    record = json.loads((HERE / "freeze.json").read_text())
    for path, digest in record["source_sha256"].items():
        assert sha(HERE / path) == digest, ("changed frozen source", path)
    for path, digest in record["inherited_sha256"].items():
        assert sha(ROOT / path) == digest, ("changed inherited source", path)
    return record
