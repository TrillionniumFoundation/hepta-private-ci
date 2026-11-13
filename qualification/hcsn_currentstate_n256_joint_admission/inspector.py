"""Stdlib-only inspection of the fail-closed joint N256 admission contract."""

import argparse
import ast
import hashlib
import json
from pathlib import Path


EXPECTED_BINDINGS = {
    "candidate_source_sha256": (
        "hcsn_currentstate_n256_sparse_dynamic_intent/sparse_dynamic.py"
    ),
    "oracle_source_sha256": (
        "hcsn_currentstate_n256_independent_oracle_intent/independent_oracle.py"
    ),
    "serializer_source_sha256": (
        "hcsn_currentstate_n256_canonical_serializer_intent/canonical_serializer.py"
    ),
    "resource_snapshot_source_freeze_sha256": (
        "hcsn_currentstate_n256_resource_snapshot/SOURCE_FREEZE.json"
    ),
}
LANE_REQUESTS = {
    "candidate": "hcsn_currentstate_n256_sparse_dynamic_intent/REQUEST.json",
    "oracle": "hcsn_currentstate_n256_independent_oracle_intent/REQUEST.json",
    "serializer": "hcsn_currentstate_n256_canonical_serializer_intent/REQUEST.json",
}


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect(package_root, qualification_root):
    package_root = Path(package_root)
    qualification_root = Path(qualification_root)
    request_path = package_root / "REQUEST.json"
    admission_path = package_root / "admission.py"
    request = json.loads(request_path.read_text())
    source = ast.parse(admission_path.read_text(), filename=str(admission_path))
    compile(source, str(admission_path), "exec")
    imports = []
    for node in ast.walk(source):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    forbidden = ("numpy", "scipy", "torch")
    if any(
        name == prefix or name.startswith(prefix + ".")
        for name in imports
        for prefix in forbidden
    ):
        raise ValueError("joint admission must remain stdlib-only")
    if request["numerical_execution_allowed"] is not False:
        raise ValueError("joint numerical execution unexpectedly enabled")
    if request["execution_key"] is not None or request["joint_admission_sha256"] is not None:
        raise ValueError("joint execution identity or admission unexpectedly frozen")
    if any(value is not None for value in request["required_external_freeze"].values()):
        raise ValueError("external joint freeze unexpectedly resolved")
    for name, relative in EXPECTED_BINDINGS.items():
        if request[name] != _digest(qualification_root / relative):
            raise ValueError(f"{name} does not bind the frozen source")
    lanes = {
        name: json.loads((qualification_root / relative).read_text())
        for name, relative in LANE_REQUESTS.items()
    }
    shared = ("input_bundle_sha256", "roster_identity")
    for name in shared:
        if any(lane[name] != request[name] for lane in lanes.values()):
            raise ValueError(f"{name} is not shared across all three lanes")
    if lanes["oracle"]["candidate_source_sha256"] != request["candidate_source_sha256"]:
        raise ValueError("oracle candidate source binding mismatch")
    if lanes["serializer"]["candidate_source_sha256"] != request["candidate_source_sha256"]:
        raise ValueError("serializer candidate source binding mismatch")
    if lanes["serializer"]["oracle_source_sha256"] != request["oracle_source_sha256"]:
        raise ValueError("serializer oracle source binding mismatch")
    key_bindings = {
        "candidate_reserved_idempotency_key": "candidate",
        "oracle_reserved_idempotency_key": "oracle",
        "serializer_reserved_idempotency_key": "serializer",
    }
    for request_name, lane_name in key_bindings.items():
        if request[request_name] != lanes[lane_name]["reserved_idempotency_key"]:
            raise ValueError(f"{request_name} mismatch")
    if request["historical_resource_red_6295_unchanged"] is not True:
        raise ValueError("historical resource RED must remain explicit")
    if request["resource_snapshot_is_observation_only"] is not True:
        raise ValueError("resource snapshot must not be promoted to allocation")
    return {
        "schema": "hcsn-n256-joint-admission-static-audit-v1",
        "status": "RED_JOINT_ADMISSION_HOLD",
        "request_sha256": _digest(request_path),
        "admission_source_sha256": _digest(admission_path),
        "bound_sources": dict(EXPECTED_BINDINGS),
        "bound_lane_requests": dict(LANE_REQUESTS),
        "new_idempotency_keys": 0,
        "current_joint_admission_files": 0,
        "n256_dynamic_runs": 0,
        "matrix_exponential_actions": 0,
        "candidate_oracle_calls": 0,
        "n256_serializer_calls": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "largegrid_qualification": False,
        "all_closed": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--qualification-root", required=True)
    arguments = parser.parse_args()
    print(
        json.dumps(
            inspect(arguments.package_root, arguments.qualification_root),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
