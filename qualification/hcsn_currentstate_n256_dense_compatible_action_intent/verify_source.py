"""Verify the execution-disabled dense-compatible action-boundary intent."""

import ast
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FREEZE = HERE / "SOURCE_FREEZE.json"

BASE_BINDINGS = {
    "qualification/hcsn_currentstate_n256_sparse_dynamic_v2_intent/sparse_dynamic.py":
        "6d3fea2b230bc7abc28df3d4d3c8f28ceaa163d9961ef2db8a7e369eee1f4816",
    "qualification/hcsn_currentstate_n256_firststep_dense_oracle_source/dense_oracle.py":
        "a3aa6a95cd55d254d9fa911d10768d1ec827e2374265a5b0474e0d6243929bfa",
    "qualification/hcsn_currentstate_n256_firststep_candidate_compare/compare.py":
        "473f7e05269a6768885b539e2f8af83ed892a7b835b68772fe42e4f0912d7f2b",
    "qualification/hcsn_currentstate_n256_firststep_candidate_compare/REQUEST.json":
        "178a1427357a654338e6259d3716684629fc9fd66677800252313a8b5f1bac1c",
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def imported_roots(path):
    roots = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def verify():
    freeze = json.loads(FREEZE.read_text())
    if freeze["schema"] != "hcsn-n256-dense-compatible-action-source-freeze-v1":
        raise ValueError("source freeze schema")
    if freeze["base_source_commit"] != "c0fb79ba896d3d4fb30a58ea40ce33d757ac9658":
        raise ValueError("base source commit")
    for relative, expected in freeze["source_sha256"].items():
        if digest(ROOT / relative) != expected:
            raise ValueError(f"intent source identity: {relative}")
    request = json.loads((HERE / "REQUEST.json").read_text())
    design = json.loads((HERE / "DESIGN.json").read_text())
    if request["execution_allowed"] is not False or request["idempotency_key"] is not None:
        raise ValueError("intent must remain execution-disabled and keyless")
    zero_fields = (
        "numerical_calls", "model_calls", "dynamic_steps",
        "matrix_exponential_actions", "torch_calls", "optimizer_steps",
    )
    if any(request[name] != 0 for name in zero_fields):
        raise ValueError("source-only counters must remain zero")
    red = request["historical_sparse_red"]
    if red["result"] != "RED" or red["mismatch_count"] != 1291:
        raise ValueError("historical sparse RED was not preserved")
    gate = design["required_bitwise_gate"]
    if gate != {
        "coordinates": 69728,
        "comparison": "exact-FP64-bytes",
        "allowed_mismatches": 0,
        "tolerance": None,
        "ulp_allowance": None,
        "postprocessing_rescue": False,
    }:
        raise ValueError("bitwise gate changed")
    if "sparse expm_multiply qualification" not in design["forbidden_claims"]:
        raise ValueError("sparse qualification exclusion missing")
    for relative, expected in BASE_BINDINGS.items():
        if digest(ROOT / relative) != expected:
            raise ValueError(f"base binding changed: {relative}")
    local_roots = set()
    for name in ("verify_source.py", "test_source.py"):
        local_roots.update(imported_roots(HERE / name))
    forbidden = {"numpy", "scipy", "torch", "jax", "tensorflow"}
    if local_roots & forbidden:
        raise ValueError(f"numerical import in source-only intent: {sorted(local_roots & forbidden)}")
    return {
        "status": "PASS_SOURCE_ONLY_HOLD",
        "bound_base_files": len(BASE_BINDINGS),
        "execution_allowed": False,
        "numerical_calls": 0,
    }


def main():
    print(json.dumps(verify(), sort_keys=True))


if __name__ == "__main__":
    main()
