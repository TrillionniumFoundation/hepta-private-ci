"""Freeze auditable source bytes before development, without importing JAX."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify():
    record = json.loads((HERE/"freeze.json").read_text())
    for name, digest in record["source_sha256"].items():
        if sha(ROOT/name) != digest:
            raise RuntimeError("Frozen source changed: "+name)
    return record


def main():
    target = HERE/"freeze.json"
    if target.exists():
        print(json.dumps(verify(), indent=2))
        return
    paths = sorted(HERE.glob("*.py"))+[HERE/"protocol.json"]
    paths += [ROOT/p for p in ("next/ridge/models.py", "next/common.py", "benchmarks/data.py",
              "benchmarks/models.py", "next/full_kernel/kernel.py", "next/full_kernel/baseline_table.npz")]
    record = dict(frozen_at_utc=datetime.now(timezone.utc).isoformat(),
                  source_sha256={str(p.relative_to(ROOT)): sha(p) for p in paths},
                  no_new_development_data_constructed=True,
                  no_confirmation_data_constructed=True)
    target.write_text(json.dumps(record, indent=2)+"\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
