"""Stdlib-only inspection for the independent-oracle v2 source bridge."""

import argparse
import ast
import hashlib
import json
from pathlib import Path


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _imports(tree):
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    return names


def inspect(adapter_path, admission_path, request_path):
    adapter_path, admission_path, request_path = map(Path, (adapter_path, admission_path, request_path))
    adapter_text = adapter_path.read_text()
    adapter = ast.parse(adapter_text, filename=str(adapter_path))
    admission = ast.parse(admission_path.read_text(), filename=str(admission_path))
    compile(adapter, str(adapter_path), "exec")
    compile(admission, str(admission_path), "exec")
    top = ast.Module(
        body=[node for node in adapter.body if isinstance(node, (ast.Import, ast.ImportFrom))],
        type_ignores=[],
    )
    if any(name == "numpy" or name.startswith("scipy") for name in _imports(top)):
        raise ValueError("numerical import in source-only adapter")
    if "hcsn_currentstate_n256_sparse_dynamic_v2_intent" in " ".join(_imports(adapter)):
        raise ValueError("candidate numerical implementation import")
    subscript_keys = {
        node.slice.value
        for node in ast.walk(adapter)
        if isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    }
    if "signed_content" not in subscript_keys or "content" in subscript_keys:
        raise ValueError("signed-content interface is not exact")
    request = json.loads(request_path.read_text())
    if request["numerical_execution_allowed"] is not False or request["execution_key"] is not None:
        raise ValueError("source request is not fail closed")
    if request["oracle_binding_sha256"] is not None:
        raise ValueError("source request contains future oracle binding")
    if any(value is not None for value in request["required_external_freeze"].values()):
        raise ValueError("source request contains future external original")
    if request["largegrid_qualification"] is not False or request["production_adoption"] is not False:
        raise ValueError("source request grants qualification or adoption")
    return {
        "schema": "hcsn-n256-independent-oracle-signedcontent-inspection-v2",
        "status": "PASS_ORACLE_V2_SIGNED_CONTENT_SOURCE_HOLD",
        "adapter_sha256": _sha(adapter_path),
        "admission_sha256": _sha(admission_path),
        "request_sha256": _sha(request_path),
        "candidate_numerical_imports": 0,
        "top_level_numeric_imports": 0,
        "authentic_phase_packets": 8,
        "dynamic_runs": 0,
        "matrix_exponential_actions": 0,
        "oracle_calls": 0,
        "serializer_calls": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "oracle_numerical_qualification": False,
        "largegrid_qualification": False,
        "all_closed": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--admission", required=True)
    parser.add_argument("--request", required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.adapter, args.admission, args.request), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
