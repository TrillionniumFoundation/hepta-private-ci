"""Fail-closed future admission for the frozen dense-oracle source."""

import hashlib
import json
from pathlib import Path


class AdmissionError(ValueError):
    """Raised before numerical dependencies or authentic inputs are opened."""


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_admission(request_path, admission_path, source_path):
    request_path = Path(request_path)
    request = json.loads(request_path.read_text())
    if request.get("oracle_source_sha256") != _digest(source_path):
        raise AdmissionError("dense oracle source identity")
    if request.get("n256_numerical_execution_allowed") is not True:
        raise AdmissionError("N256 numerical execution is not admitted")
    admission = json.loads(Path(admission_path).read_text())
    exact = {
        "schema": "hcsn-n256-firststep-dense-oracle-admission-v1",
        "request_sha256": _digest(request_path),
        "oracle_source_sha256": _digest(source_path),
        "dynamic_steps": 1,
        "dense_expm_actions": 2,
        "coordinate_denominator": 69728,
    }
    if any(admission.get(name) != expected for name, expected in exact.items()):
        raise AdmissionError("future admission binding")
    for name in (
        "unique_execution_key",
        "runtime_sha256",
        "host_snapshot_sha256",
        "ancestor_cgroup_snapshot_sha256",
        "allocation_sha256",
        "calendar_sha256",
    ):
        value = admission.get(name)
        if not isinstance(value, str) or not value:
            raise AdmissionError(f"future admission {name}")
    if admission.get("historical_negative_and_unknown_preserved") is not True:
        raise AdmissionError("historical negative or UNKNOWN erased")
    return admission
