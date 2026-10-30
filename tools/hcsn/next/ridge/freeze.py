"""Freeze sources and prospective protocol before constructing test datasets."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def main():
    if (HERE/"results.json").exists() or (HERE/"freeze.json").exists():
        raise RuntimeError("Refuse to overwrite an existing confirmation freeze")
    development=json.loads((HERE/"development_results.json").read_text())
    validation=json.loads((HERE/"validation.json").read_text())
    if not development["complete"] or not development["sanity_targets_passed"]:raise RuntimeError("Development incomplete or failed")
    if development["confirmation_test_constructed"]:raise RuntimeError("Development inspected test")
    if not validation["passed"]:raise RuntimeError("Validation failed")
    names=["next/ridge/"+name for name in ("models.py","run.py","protocol.json","validate.py",
        "challenge.py","challenge_protocol.json","freeze.py","audit.py","development_protocol.json","develop.py")]
    names += ["next/common.py","next/sequence/run.py","next/sequence/challenge.py",
        "benchmarks/models.py","benchmarks/snn_models.py","benchmarks/data.py",
        "next/full_kernel/kernel.py","next/full_kernel/tables.py","next/full_kernel/baseline_table.npz"]
    source={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}
    model_digest=source["next/ridge/models.py"]
    if development["source_sha256"]["models.py"]!=model_digest or validation["source_sha256"]["models.py"]!=model_digest:
        raise RuntimeError("Model changed after development or validation")
    result=dict(frozen_at_utc=datetime.now(timezone.utc).isoformat(),source_sha256=source,
        development_sanity_passed=True,state_gradient_validation_passed=True,
        confirmation_test_constructed_before_freeze=False,
        development_results_sha256=hashlib.sha256((HERE/"development_results.json").read_bytes()).hexdigest(),
        validation_sha256=hashlib.sha256((HERE/"validation.json").read_bytes()).hexdigest())
    (HERE/"freeze.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))


if __name__=="__main__":main()
