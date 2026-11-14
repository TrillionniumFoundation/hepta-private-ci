import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_exact_generator_review"
EXPECTED_IDENTITY = "hcsn-currentstate-n256-exact-generator-review-20261114-c06d-v1"
EXPECTED_FILES = {
    ".github/workflows/hcsn-currentstate-n256-generator-review.yml": (
        "8801a1682bb20a3c94362fdd37a06fe60155ccfa3b7113fbe151fe7a3a900d81"
    ),
    "qualification/hcsn_currentstate_n256_exact_generator_review/README.md": (
        "bef6e7bc62bd6c6c06029b982ba0e6caa014664af409c68c32556598c8df3f27"
    ),
    "qualification/hcsn_currentstate_n256_exact_generator_review/REQUEST.json": (
        "e6af46b63a700a794997e7a620bb972bb2accd5ea032ffd8ba6c4c74ffb41908"
    ),
    "qualification/hcsn_currentstate_n256_exact_generator_review/__init__.py": (
        "bd3736e18a0715c48b1c5cbe9f832677c20ecaf4136a2ea6944d5913c6bcae69"
    ),
    "qualification/hcsn_currentstate_n256_exact_generator_review/generator_review.py": (
        "0beb616f348826e26591e60a4029b37b34091e257fbc5dd4c002409657c0e266"
    ),
    "qualification/hcsn_currentstate_n256_exact_generator_review/test_review.py": (
        "b759734399bd4a18e19c8948dcbb0c68964c0ad32a9441bfb245779c5aee81dd"
    ),
}
INPUT_FILES = {
    "qualification/hcsn_n256_new_export/evidence/attempt001/METADATA.json": (
        "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6"
    ),
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.json": (
        "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c"
    ),
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_PHASE.json": (
        "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548"
    ),
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.npz.b64": (
        "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb"
    ),
}
PARENT_LOADER = {
    "qualification/hcsn_currentstate_n256_stdlib_loader/loader.py": (
        "f61b3b4e52f3f44de3e095f9f96ba440cef4c74e2d9e71a53b4e9d509d3c1188"
    )
}


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    request = json.loads((PACKAGE / "REQUEST.json").read_text())
    freeze = json.loads((PACKAGE / "SOURCE_FREEZE.json").read_text())
    if request != freeze["request"]:
        raise SystemExit("REQUEST.json differs from frozen request")
    if request["identity"] != EXPECTED_IDENTITY:
        raise SystemExit("unexpected request identity")
    if freeze["bound_files"] != EXPECTED_FILES:
        raise SystemExit("frozen file map differs from verifier map")
    if freeze["input_originals"] != INPUT_FILES:
        raise SystemExit("frozen input-original map differs from verifier map")
    if freeze["parent_loader"] != PARENT_LOADER:
        raise SystemExit("frozen parent-loader map differs from verifier map")
    for relative, expected in {**EXPECTED_FILES, **INPUT_FILES, **PARENT_LOADER}.items():
        observed = _sha256(ROOT / relative)
        if observed != expected:
            raise SystemExit(f"sha256 mismatch for {relative}: {observed}")
    if _sha256(Path(__file__)) != freeze["verifier_sha256"]:
        raise SystemExit("verify_source.py differs from frozen verifier")

    source = (PACKAGE / "generator_review.py").read_text()
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    imported.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    if imported & {"numpy", "scipy", "torch", "subprocess", "socket"}:
        raise SystemExit("generator review imports a forbidden runtime")
    forbidden_markers = (
        "expm_multiply",
        "n256_sparse_dynamic_intent",
        "n256_independent_oracle_intent",
    )
    if any(marker in source for marker in forbidden_markers):
        raise SystemExit("generator review references a numeric provider")
    required_markers = (
        "independent_exact_rational_reconstruction: bool = True",
        "dynamic_calls: int = 0",
        "matrix_exponential_calls: int = 0",
        "numerical_reference_records: int = 0",
        "provider_admitted: bool = False",
        "largegrid_qualification: bool = False",
    )
    if any(marker not in source for marker in required_markers):
        raise SystemExit("required scope or fail-closed marker missing")
    if request["idempotency_key"] is not None or request["provider_admitted"]:
        raise SystemExit("review must not declare provider execution admission")
    zero = (
        "dynamic_calls",
        "matrix_exponential_calls",
        "numerical_reference_records",
        "candidate_calls",
        "oracle_calls",
        "model_calls",
        "optimizer_calls",
        "training_calls",
    )
    if any(request[name] != 0 for name in zero):
        raise SystemExit("review declares numeric/model work")
    if not request["local_initial_red_preserved"]:
        raise SystemExit("initial local RED is not preserved")
    if request["status"] != "HOLD" or request["all_closed"]:
        raise SystemExit("global HOLD fail-closed state changed")
    print("PASS_CURRENTSTATE_N256_EXACT_GENERATOR_REVIEW")


if __name__ == "__main__":
    main()
