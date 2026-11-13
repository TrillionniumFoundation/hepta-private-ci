"""Stdlib-only inspection of the independent N256 oracle source intent."""

import argparse
import ast
import hashlib
import json
from pathlib import Path

REQUIRED_FUNCTIONS = {
    "_numeric_modules", "_read_bundle", "_birth_death_operator",
    "_extended_generator", "_stream_action", "_seed_state",
    "_advance_segment", "_coordinate_stream", "_run_lane", "run_oracle",
}
REQUIRED_CLASSES = {"OraclePacket", "OracleState", "OracleCounts"}
FORBIDDEN_IMPORT_FRAGMENTS = (
    "hcsn_currentstate_n256_sparse_dynamic_intent",
    "hcsn_currentstate_n256_engineering",
    "sparse_dynamic",
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _imports(tree):
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    return names


def inspect(source_path, admission_path, request_path):
    source_path = Path(source_path)
    admission_path = Path(admission_path)
    request_path = Path(request_path)
    source_text = source_path.read_text()
    source = ast.parse(source_text, filename=str(source_path))
    admission = ast.parse(admission_path.read_text(), filename=str(admission_path))
    compile(source, str(source_path), "exec")
    compile(admission, str(admission_path), "exec")
    functions = {node.name for node in ast.walk(source) if isinstance(node, ast.FunctionDef)}
    classes = {node.name for node in ast.walk(source) if isinstance(node, ast.ClassDef)}
    if not REQUIRED_FUNCTIONS <= functions or not REQUIRED_CLASSES <= classes:
        raise ValueError("required independent oracle surface")
    imports = _imports(source)
    if any(fragment in name for name in imports for fragment in FORBIDDEN_IMPORT_FRAGMENTS):
        raise ValueError("candidate or engineering implementation import forbidden")
    top_level_imports = _imports(ast.Module(body=[node for node in source.body if isinstance(node, (ast.Import, ast.ImportFrom))], type_ignores=[]))
    if any(name == "numpy" or name.startswith("scipy") for name in top_level_imports):
        raise ValueError("numerical import before admission")
    numeric = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "_numeric_modules")
    numeric_imports = _imports(numeric)
    if "numpy" not in numeric_imports or "scipy" not in numeric_imports or "scipy.sparse.linalg" not in numeric_imports:
        raise ValueError("lazy independent numerical imports")
    if "scipy.linalg" in source_text or "expm(" in source_text:
        raise ValueError("dense matrix exponential forbidden")
    required_tokens = (
        "expm_multiply", "escaped_upper", "lower_hit", "discounted_hit",
        "occupation", "reset_rate", "DELAY", "WARM_TIMES", "COARSE_TIMES",
        "COLD_TIMES", "value_hex",
    )
    if any(token not in source_text for token in required_tokens):
        raise ValueError("incomplete independent oracle source surface")
    request = json.loads(request_path.read_text())
    if request["numerical_execution_allowed"] is not False or request["execution_key"] is not None or request["admission_sha256"] is not None:
        raise ValueError("fail-closed oracle request")
    if any(value is not None for value in request["required_external_freeze"].values()):
        raise ValueError("external freeze unexpectedly resolved")
    if request["candidate_source_sha256"] != "0f686be417338f7aa102a8386171798b06a63689acdd043a69e95212655bf3f9":
        raise ValueError("candidate source binding")
    if request["input_bundle_sha256"] != "17086fb6ba83211e8626c7ac9c22183f6c9c9a7dc615772b5a32d2c14ecb8e95":
        raise ValueError("input bundle binding")
    if request["roster_identity"] != "e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2":
        raise ValueError("roster binding")
    return {
        "schema": "hcsn-n256-independent-oracle-source-inspection-v1",
        "status": "PASS_SOURCE_ONLY_HOLD_NUMERICAL",
        "source_sha256": digest(source_path),
        "admission_sha256": digest(admission_path),
        "request_sha256": digest(request_path),
        "functions": sorted(REQUIRED_FUNCTIONS),
        "classes": sorted(REQUIRED_CLASSES),
        "candidate_imports": 0,
        "top_level_numeric_imports": 0,
        "dense_expm_references": 0,
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
    parser.add_argument("--source", required=True)
    parser.add_argument("--admission", required=True)
    parser.add_argument("--request", required=True)
    arguments = parser.parse_args()
    print(json.dumps(inspect(arguments.source, arguments.admission, arguments.request), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
