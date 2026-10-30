"""Identity-bound read-only reuse of control v1 and new prospective output roots."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
V1 = HERE.parent / "control"
HCSN = HERE.parents[1]
sys.path.insert(0, str(V1))
SOURCES = ("identity.py", "cohorts.py", "network.py", "training_v2.py", "execute_v2.py", "study_v2.py", "audit_v2.py", "protocol.json")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+".partial")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+"\n")
    temporary.replace(path)


def protocol():
    return json.loads((HERE / "protocol.json").read_text())


def freeze():
    target = HERE / "freeze.json"
    if target.exists():
        return verify()
    old = json.loads((V1 / "freeze.json").read_text())
    inherit = {"control/"+name: digest for name, digest in old["source_sha256"].items()}
    for name in ("freeze.json", "results.json", "analysis.json", "README.md", "PROSPECTIVE_REPAIR.md"):
        inherit["control/"+name] = sha(V1 / name)
    result = dict(created_utc=datetime.now(timezone.utc).isoformat(),
        status="Frozen before new development data, controller training or outcome generation",
        source_sha256={name: sha(HERE / name) for name in SOURCES},
        reused_v1_sha256=inherit, inherited_hcsn_sha256=old["inherited_sha256"],
        baseline_commit=old["baseline_commit"], original_v1_primary_gate=False)
    save(target, result)
    return result


def verify():
    frozen = json.loads((HERE / "freeze.json").read_text())
    for name, digest in frozen["source_sha256"].items():
        assert sha(HERE / name) == digest, name
    for name, digest in frozen["reused_v1_sha256"].items():
        assert sha(HERE.parent / name) == digest, name
    for name, digest in frozen["inherited_hcsn_sha256"].items():
        assert sha(HCSN / name) == digest, name
    return frozen
