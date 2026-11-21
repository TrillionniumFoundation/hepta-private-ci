"""Verify frozen source bytes without importing numerical modules."""

import hashlib
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    for relative, expected in freeze["source_sha256"].items():
        path = ROOT / relative if relative.startswith(".github/") else HERE / relative
        if sha(path) != expected:
            raise ValueError(f"source identity: {relative}")
    parent_candidate = ROOT / "qualification/hcsn_currentstate_n256_dense_compatible_firststep_intent/candidate.py"
    if sha(parent_candidate) != freeze["parent_candidate_sha256"]:
        raise ValueError("parent candidate identity")
    activation = HERE / "EXECUTE.json"
    if activation.exists():
        if sha(activation) != freeze["activation_sha256"]:
            raise ValueError("activation identity")
        value = json.loads(activation.read_text())
        if value != freeze["activation_contract"]:
            raise ValueError("activation contract")
    opened = HERE / "EXECUTION_OPEN.json"
    if opened.exists():
        if sha(opened) != freeze["execution_open_sha256"]:
            raise ValueError("opened activation identity")
        if json.loads(opened.read_text()) != freeze["execution_open_contract"]:
            raise ValueError("opened activation contract")
    newly_opened = HERE / "EXECUTION_OPENED.json"
    if newly_opened.exists():
        if sha(newly_opened) != freeze["execution_opened_sha256"]:
            raise ValueError("newly opened activation identity")
        if json.loads(newly_opened.read_text()) != freeze["execution_opened_contract"]:
            raise ValueError("newly opened activation contract")
    if any(name in sys.modules for name in ("numpy", "scipy", "torch")):
        raise ValueError("source verifier imported numerical module")
    print("PASS_FROZEN_N256_DENSE_COMPATIBLE_FIRSTSTEP_EXECUTION_SOURCE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
