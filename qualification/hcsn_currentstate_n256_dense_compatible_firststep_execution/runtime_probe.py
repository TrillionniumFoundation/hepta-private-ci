"""Zero-import probe for the exact hosted wheel installation identities."""

import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
HEAD = "research/hcsn-n256-dense-compatible-runtime-probe-20261121-c06d"
BASE = "research/hcsn-n256-dense-compatible-firststep-opened-20261121-c06d"
RECEIPT_SHA256 = "3a1b962a600ba9983c420a84d9be34fc19095d016b6450578389967bd420e042"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    receipt = HERE / "RUNTIME_PROBE.json"
    if sha(receipt.read_bytes()) != RECEIPT_SHA256:
        raise ValueError("runtime probe receipt identity")
    value = json.loads(receipt.read_text())
    if value["maximum_probes"] != 1 or value["source_red_run"] != 44905572946:
        raise ValueError("runtime probe contract")
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        raise ValueError("runtime probe event identity")
    if os.environ.get("GITHUB_HEAD_REF") != HEAD or os.environ.get("GITHUB_BASE_REF") != BASE:
        raise ValueError("runtime probe branch identity")
    if sys.version_info[:3] != (3, 12, 16):
        raise ValueError("runtime probe Python identity")
    command = [
        sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
        "--no-cache-dir", "--only-binary=:all:", "-r",
        "qualification/hcsn_currentstate_n256_firststep_dense_oracle_hosted/requirements.txt",
    ]
    completed = subprocess.run(command, capture_output=True, check=False, timeout=300)
    if completed.returncode:
        print("HCSN_RUNTIME_PROBE_PIP_STDOUT:" + completed.stdout.hex(), flush=True)
        print("HCSN_RUNTIME_PROBE_PIP_STDERR:" + completed.stderr.hex(), flush=True)
        raise RuntimeError(f"pip install exit {completed.returncode}")
    result = {}
    for name in ("numpy", "scipy"):
        distribution = importlib.metadata.distribution(name)
        result[name] = {
            "version": distribution.version,
            "record_sha256": sha(distribution.read_text("RECORD").encode()),
            "init_sha256": sha(Path(distribution.locate_file(f"{name}/__init__.py")).read_bytes()),
        }
    if any(name in sys.modules for name in ("numpy", "scipy", "torch")):
        raise ValueError("runtime probe imported numerical module")
    print("HCSN_RUNTIME_PROBE_RESULT:" + json.dumps({
        "schema": "hcsn-n256-dense-compatible-runtime-probe-result-v1",
        "identity": value["identity"], "runtime": result,
        "numerical_imports": 0, "model_calls": 0, "dynamic_steps": 0,
        "expm_actions": 0, "torch_calls": 0, "optimizer_steps": 0,
        "historical_negative_and_unknown_preserved": True,
        "production_adoption": False, "all_closed": False,
    }, allow_nan=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
