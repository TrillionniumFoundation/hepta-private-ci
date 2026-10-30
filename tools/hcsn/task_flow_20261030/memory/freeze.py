"""Bind new scientific inputs before tests or training; old evidence is read-only."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LOCAL = ("protocol.json", "models.py", "reference.py", "data.py", "training.py", "run.py", "validate.py", "freeze.py")
DEPENDENCIES = (
    "benchmarks/data.py", "benchmarks/models.py", "benchmarks/snn_models.py",
    "next/common.py", "next/ridge/models.py", "next/sequence/challenge.py",
    "next/sequence/models.py", "next/sequence/with_operators.py", "benchmarks/v2_models.py",
    "next/full_kernel/__init__.py", "next/full_kernel/kernel.py", "next/full_kernel/baseline_table.npz",
    "third/memory/models.py", "third/memory/reference.py", "third/memory/data.py",
    "third/memory/execution.py", "third/confirmation/data.py", "third/confirmation/contract.py",
    "third/memory/protocol.json", "next/sequence/protocol.json", "next/ridge/protocol.json",
    "next/sequence/challenge_protocol.json", "next/ridge/challenge_protocol.json", "next/ridge/development_protocol.json")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory():
    paths = [HERE / name for name in LOCAL] + [ROOT / name for name in DEPENDENCIES]
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def verify():
    result = json.loads((HERE / "freeze.json").read_text())
    if result["source_sha256"] != inventory():
        raise RuntimeError("Frozen source changed; preserve old records and create an explicit amendment")
    return result


if __name__ == "__main__":
    path = HERE / "freeze.json"
    if path.exists():
        verify()
    else:
        result = dict(created_utc=datetime.now(timezone.utc).isoformat(), source_sha256=inventory(),
                      data_and_training_outcomes_constructed=False)
        path.write_text(json.dumps(result, indent=2) + "\n")
    print("SOURCE_FROZEN", sha(path))
