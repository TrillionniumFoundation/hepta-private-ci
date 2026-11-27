import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_stdlib_loader"
EXPECTED_IDENTITY = (
    "hcsn-currentstate-n256-stdlib-loader-source-only-20261114-c06d-v1"
)
EXPECTED_FILES = {
    ".github/workflows/hcsn-currentstate-n256-stdlib-loader.yml": (
        "fc741f2fb37bd7ed5c65acf37cc94db5bfff2df6fcbbe5d10c486bb0e748bb60"
    ),
    "qualification/hcsn_currentstate_n256_stdlib_loader/README.md": (
        "047b74df4071994798458fcca933ce4b52d2a6d416529441c93f5458adf10309"
    ),
    "qualification/hcsn_currentstate_n256_stdlib_loader/REQUEST.json": (
        "156b68d147d570075b66fb8f68f3ea452c27a4e15c873d16c9386a988eaa6305"
    ),
    "qualification/hcsn_currentstate_n256_stdlib_loader/__init__.py": (
        "3479629f17374a9ce7a591ca318bb657c56a2f129923428da62471dccdf84fd5"
    ),
    "qualification/hcsn_currentstate_n256_stdlib_loader/loader.py": (
        "f61b3b4e52f3f44de3e095f9f96ba440cef4c74e2d9e71a53b4e9d509d3c1188"
    ),
    "qualification/hcsn_currentstate_n256_stdlib_loader/test_loader.py": (
        "eab8d6706ed767d29ea7253d21b3e56229e6ca2f479834b8aed40fe287e68286"
    ),
}
INPUT_FILES = {
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


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    request = json.loads((PACKAGE / "REQUEST.json").read_text(encoding="utf-8"))
    freeze = json.loads((PACKAGE / "SOURCE_FREEZE.json").read_text(encoding="utf-8"))
    if request != freeze["request"]:
        raise SystemExit("REQUEST.json differs from frozen request")
    if request["identity"] != EXPECTED_IDENTITY:
        raise SystemExit("unexpected request identity")
    if freeze["bound_files"] != EXPECTED_FILES:
        raise SystemExit("frozen file map differs from verifier map")
    if freeze["input_originals"] != INPUT_FILES:
        raise SystemExit("frozen input-original map differs from verifier map")
    for relative, expected in {**EXPECTED_FILES, **INPUT_FILES}.items():
        observed = _sha256(ROOT / relative)
        if observed != expected:
            raise SystemExit(f"sha256 mismatch for {relative}: {observed}")
    if _sha256(Path(__file__)) != freeze["verifier_sha256"]:
        raise SystemExit("verify_source.py differs from frozen verifier")

    source = (PACKAGE / "loader.py").read_text(encoding="utf-8")
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
    forbidden = {"decimal", "numpy", "scipy", "torch", "subprocess", "socket"}
    if imported & forbidden:
        raise SystemExit("loader imports a forbidden runtime")
    provider_markers = (
        "expm_multiply",
        "hcsn_currentstate_n256_candidate",
        "hcsn_currentstate_n256_oracle",
    )
    if any(token in source for token in provider_markers):
        raise SystemExit("loader references a numeric provider")
    required_markers = (
        "authentic_n256_bundle_loaded: bool = True",
        "independent_stdlib_decode: bool = True",
        "candidate_or_oracle_imported: bool = False",
        "dynamic_calls: int = 0",
        "matrix_exponential_calls: int = 0",
        "reference_records_emitted: int = 0",
        "largegrid_qualification: bool = False",
    )
    if any(marker not in source for marker in required_markers):
        raise SystemExit("required scope or fail-closed marker missing")
    if request["idempotency_key"] is not None:
        raise SystemExit("input-only request must not declare a compute key")
    if any(
        request[name] != 0
        for name in ("dynamic_calls", "model_calls", "optimizer_calls", "training_calls")
    ):
        raise SystemExit("input-only request declares numeric/model work")
    if request["numerical_reference_records"] != 0:
        raise SystemExit("input-only request declares reference records")
    if not request["local_initial_red_preserved"]:
        raise SystemExit("initial local RED is not preserved")
    if request["status"] != "HOLD" or request["all_closed"]:
        raise SystemExit("global HOLD fail-closed state changed")
    print("PASS_CURRENTSTATE_N256_STDLIB_LOADER_SOURCE_AND_INPUTS")


if __name__ == "__main__":
    main()
