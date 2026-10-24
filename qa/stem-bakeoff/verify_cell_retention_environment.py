"""Verify fixed package metadata without importing a model or opening any corpus."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import time


def verify(contract, output, *, expected_contract_sha256):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    path = Path(contract)
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_contract_sha256:
        raise ValueError("reviewed environment contract differs")
    plan = json.loads(payload)
    if (plan.get("schema") != "hepta.cell-retention.environment-contract.v1"
            or plan.get("status") != "FROZEN_BEFORE_NEW_ENCODER_OUTPUTS"
            or plan.get("authority") != "DENY_ALL" or plan.get("model_execution_by_verifier") is not False):
        raise ValueError("explicit fixed environment contract required")
    source = Path(__file__).parent
    protocol = source / "cell_field_retention_experiment_protocol.json"
    if hashlib.sha256(protocol.read_bytes()).hexdigest() != plan["protocol_sha256"]:
        raise ValueError("reviewed experiment protocol changed")
    observed = {name: importlib.metadata.version(name) for name in plan["packages"]}
    if (platform.python_version() != plan["python_version"] or observed != plan["packages"]
            or str(Path(sys.executable).absolute()) != plan["python_executable"]):
        raise ValueError("actual interpreter/package versions differ from pre-encoding freeze")
    head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    receipt = {"schema": "hepta.cell-retention.environment-receipt.v1",
        "contract_sha256": expected_contract_sha256, "protocol_sha256": plan["protocol_sha256"],
        "source_commit_observed": head, "python_executable": sys.executable,
        "python_version": platform.python_version(), "packages": observed,
        "platform": platform.platform(), "prefix": sys.prefix,
        "model_or_corpus_opened": False, "package_changes": False,
        "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
        "authority": "DENY_ALL"}
    with Path(output).open("xb") as stream:
        stream.write(json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("contract", "output", "expected-contract-sha256"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(verify(**vars(parser.parse_args())), indent=2))
