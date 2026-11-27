"""Fail-closed source, input, and workflow verifier for this static lane."""

import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FORBIDDEN = {"numpy", "scipy", "torch", "jax", "tensorflow"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    request = json.loads((HERE / "REQUEST.json").read_text())
    if request != json.loads(json.dumps(request, sort_keys=True)):
        raise ValueError("request JSON")
    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    observed = {path: sha(ROOT / path) for path in freeze["files"]}
    if observed != freeze["files"]:
        raise ValueError("source freeze mismatch")
    inherited = {
        "qualification/hcsn_currentstate_n256_canonical_serializer_intent/canonical_serializer.py": "3107fb296043de8f3e3c78e13aa940aea38aa64c16dfe68d342d2adb0c7aa97a",
        "qualification/hcsn_currentstate_n256_sparse_dynamic_intent/sparse_dynamic.py": freeze["old_sparse_source_sha256"],
    }
    if {path: sha(ROOT / path) for path in inherited} != inherited:
        raise ValueError("inherited source identity")
    old_source = (ROOT / "qualification/hcsn_currentstate_n256_sparse_dynamic_intent/sparse_dynamic.py").read_text()
    if 'item["content"]' not in old_source:
        raise ValueError("historical unexecuted gap changed")
    phase = json.loads((ROOT / "qualification/hcsn_n256_new_export/evidence/attempt001/N256_PHASE.json").read_text())
    if not all("signed_content" in item and "content" not in item for item in phase["packets"]):
        raise ValueError("authentic phase schema")
    for name in ("builder.py", "cold_audit.py"):
        tree = ast.parse((HERE / name).read_text())
        imports = {node.names[0].name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)}
        imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        if imports & FORBIDDEN:
            raise ValueError("numeric/model dependency")
    workflow = (ROOT / ".github/workflows/hcsn-n256-authentic-t0-capsule.yml").read_text()
    if (
        workflow.count("hcsn_currentstate_n256_t0_capsule_v1.builder ") != 1
        or workflow.count("hcsn_currentstate_n256_t0_capsule_v1.cold_audit ") != 1
    ):
        raise ValueError("single execution budget")
    print(json.dumps({"status": "PASS_SOURCE_FREEZE", "files": len(observed), "old_sparse_gap_preserved": True, "model_calls": 0, "optimizer_calls": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
