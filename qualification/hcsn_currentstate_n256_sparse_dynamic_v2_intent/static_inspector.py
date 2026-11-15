"""Stdlib-only inspection of the fail-closed N256 sparse dynamic source."""

import argparse
import ast
import hashlib
import json
from pathlib import Path


REQUIRED_FUNCTIONS = {
    "_numeric_modules",
    "_phase_packet_alpha",
    "_extended",
    "_action",
    "_advance",
    "_run_lane",
    "_validate_roster",
    "run",
}
REQUIRED_CLASSES = {"Packet", "DynamicState", "Capsule", "Counts"}
PHASE_SHA256 = "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect(source_path, admission_path, request_path, phase_path):
    source_path = Path(source_path)
    admission_path = Path(admission_path)
    request_path = Path(request_path)
    phase_path = Path(phase_path)
    source_text = source_path.read_text()
    admission_text = admission_path.read_text()
    source = ast.parse(source_text, filename=str(source_path))
    admission = ast.parse(admission_text, filename=str(admission_path))
    compile(source, str(source_path), "exec")
    compile(admission, str(admission_path), "exec")
    functions = {node.name for node in ast.walk(source) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    classes = {node.name for node in ast.walk(source) if isinstance(node, ast.ClassDef)}
    if not REQUIRED_FUNCTIONS <= functions or not REQUIRED_CLASSES <= classes:
        raise ValueError("required executable surface")
    top_level_imports = []
    for node in source.body:
        if isinstance(node, ast.Import):
            top_level_imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            top_level_imports.append(node.module or "")
    if any(name == "numpy" or name.startswith("scipy") for name in top_level_imports):
        raise ValueError("numeric import before admission")
    admission_imports = {
        node.module or ""
        for node in admission.body
        if isinstance(node, ast.ImportFrom)
    }
    if (
        "qualification.hcsn_currentstate_n256_execution_admission_bridge"
        not in admission_imports
    ):
        raise ValueError("v2 execution admission bridge is not bound")
    numeric = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "_numeric_modules")
    numeric_imports = []
    for node in ast.walk(numeric):
        if isinstance(node, ast.Import):
            numeric_imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            numeric_imports.append(node.module or "")
    if "numpy" not in numeric_imports or "scipy" not in numeric_imports or "scipy.sparse.linalg" not in numeric_imports:
        raise ValueError("lazy sparse runtime imports")
    if "scipy.linalg" in source_text or "expm(" in source_text:
        raise ValueError("dense matrix exponential forbidden")
    if "expm_multiply" not in source_text or "primitive.block_operator" not in source_text:
        raise ValueError("sparse candidate semantics")
    subscript_keys = {
        node.slice.value
        for node in ast.walk(source)
        if isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    }
    if "signed_content" not in subscript_keys or "content" in subscript_keys:
        raise ValueError("authentic signed-content interface")
    request = json.loads(request_path.read_text())
    if (
        request["numerical_execution_allowed"] is not False
        or request["execution_key"] is not None
        or request["provider_admission_sha256"] is not None
        or request["execution_freeze_sha256"] is not None
        or request["source_binding_sha256"] is not None
        or any(value is not None for value in request["required_external_freeze"].values())
    ):
        raise ValueError("fail-closed request")
    if request["input_bundle_sha256"] != "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95":
        raise ValueError("input bundle binding")
    if request["roster_identity"] != "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2":
        raise ValueError("roster binding")
    if request["schema"] != "hcsn-n256-sparse-dynamic-source-intent-v3":
        raise ValueError("request schema")
    if digest(phase_path) != PHASE_SHA256:
        raise ValueError("authentic phase identity")
    phase = json.loads(phase_path.read_text())
    packets = phase.get("packets")
    if (
        phase.get("schema") != "hcsn-n256-new-export-phase-v1"
        or phase.get("packet_count") != 8
        or not isinstance(packets, list)
        or len(packets) != 8
        or any("signed_content" not in item or "content" in item for item in packets)
    ):
        raise ValueError("authentic phase schema")
    return {
        "schema": "hcsn-n256-sparse-dynamic-source-inspection-v3",
        "status": "PASS_SOURCE_ONLY_ADMISSION_BRIDGE_HOLD_NUMERICAL",
        "source_sha256": digest(source_path),
        "admission_sha256": digest(admission_path),
        "request_sha256": digest(request_path),
        "functions": sorted(REQUIRED_FUNCTIONS),
        "classes": sorted(REQUIRED_CLASSES),
        "top_level_numeric_imports": 0,
        "dense_expm_references": 0,
        "authentic_phase_sha256": PHASE_SHA256,
        "authentic_phase_packets": len(packets),
        "dynamic_runs": 0,
        "matrix_exponential_actions": 0,
        "oracle_calls": 0,
        "serializer_calls": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "largegrid_qualification": False,
        "all_closed": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--admission", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            inspect(args.source, args.admission, args.request, args.phase),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
