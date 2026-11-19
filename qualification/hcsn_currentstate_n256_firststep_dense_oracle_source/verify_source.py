"""Static verifier for the unexecuted independent dense-oracle source."""

import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parent
REPOSITORY = ROOT.parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    request = json.loads((ROOT / "REQUEST.json").read_text())
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    development_red = json.loads((ROOT / "DEVELOPMENT_RED.json").read_text())
    source = ROOT / "dense_oracle.py"
    admission = ROOT / "admission.py"
    tree = ast.parse(source.read_text(), filename=str(source))
    compile(tree, str(source), "exec")
    forbidden = ("candidate", "engineering", "n128", "sparse_dynamic")
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    if any(token in module for module in imports for token in forbidden):
        raise ValueError("dense oracle imports candidate lineage")
    top_imports = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    if any(
        name in ("numpy", "scipy")
        for node in top_imports
        for name in (
            [alias.name.split(".")[0] for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module.split(".")[0]]
        )
    ):
        raise ValueError("numerical dependency imported before admission")
    run = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_warm_first_step"
    )
    first_calls = [
        node.value.func.id
        for node in run.body[:2]
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
    ]
    if first_calls != ["require_admission"]:
        raise ValueError("admission is not first executable call")
    bindings = request["bindings"]
    exact_bindings = {
        "parent_gap_request_sha256": digest(REPOSITORY / "qualification/hcsn_currentstate_n256_firststep_oracle_gap/REQUEST.json"),
        "authentic_input_adapter_sha256": digest(REPOSITORY / "qualification/hcsn_currentstate_n256_independent_oracle_v2_intent/adapter.py"),
        "serializer_v2_sha256": digest(REPOSITORY / "qualification/hcsn_currentstate_n256_firststep_serializer_v2/serializer.py"),
        "metadata_sha256": digest(REPOSITORY / "qualification/hcsn_n256_new_export/evidence/attempt001/METADATA.json"),
    }
    if bindings != exact_bindings or request["oracle_source_sha256"] != digest(source):
        raise ValueError("dense oracle source binding")
    if freeze["request_sha256"] != digest(ROOT / "REQUEST.json"):
        raise ValueError("request freeze")
    if freeze["oracle_source_sha256"] != digest(source):
        raise ValueError("oracle source freeze")
    if freeze["admission_source_sha256"] != digest(admission):
        raise ValueError("admission source freeze")
    if freeze["tests_sha256"] != digest(ROOT / "test_source.py"):
        raise ValueError("tests freeze")
    if freeze["development_red_sha256"] != digest(ROOT / "DEVELOPMENT_RED.json"):
        raise ValueError("development RED freeze")
    if development_red["preserved"] is not True or any(
        development_red[field] != 0
        for field in (
            "n256_serializer_calls",
            "dynamic_steps",
            "matrix_exponential_actions",
            "torch_calls",
            "optimizer_steps",
        )
    ):
        raise ValueError("development RED is not preserved")
    if set(request["required_future_admission"].values()) != {None}:
        raise ValueError("future admission unexpectedly populated")
    exact_zero = (
        "n256_serializer_calls",
        "dynamic_steps",
        "matrix_exponential_actions",
        "torch_calls",
        "optimizer_steps",
    )
    if any(request[field] != 0 or freeze[field] != 0 for field in exact_zero):
        raise ValueError("source freeze claims N256 execution")
    if request["n256_numerical_execution_allowed"] is not False:
        raise ValueError("source freeze admits execution")
    if any(request[field] is not False for field in ("largegrid_qualification", "production_adoption", "all_closed")):
        raise ValueError("source freeze grants qualification")
    print(json.dumps({
        "status": request["status"],
        "identity": request["identity"],
        "oracle_source_sha256": digest(source),
        "n256_serializer_calls": 0,
        "dynamic_steps": 0,
        "matrix_exponential_actions": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "all_closed": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
