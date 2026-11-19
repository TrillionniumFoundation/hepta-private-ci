import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_non_substochastic_signed_interval"
EXPECTED_IDENTITY = (
    "hcsn-currentstate-n256-nonsubstochastic-signed-interval-source-only-"
    "20261114-c06d-v1"
)
EXPECTED_FILES = {
    ".github/workflows/hcsn-currentstate-n256-nonsubstochastic-signed-interval.yml": (
        "03221ca68675dc3f2c31c4677521c7f4c189690950462f991db5aeeeec4aa904"
    ),
    "qualification/hcsn_currentstate_n256_non_substochastic_signed_interval/README.md": (
        "2539b0e076c8eb1bd11244b0a48aa9efe43bd67f7110b1bf5611829c91731eeb"
    ),
    "qualification/hcsn_currentstate_n256_non_substochastic_signed_interval/REQUEST.json": (
        "e3054cad5776f26a4a9d3a4cebd5d8c16f8b3bfd1affa3498550ccf4a9f36cbe"
    ),
    "qualification/hcsn_currentstate_n256_non_substochastic_signed_interval/__init__.py": (
        "043d8565e4376338a4e469160c3a3be27e5b4522df09708dd1e49f9e9635de8b"
    ),
    "qualification/hcsn_currentstate_n256_non_substochastic_signed_interval/signed_interval.py": (
        "0609297f789485f38970491fcc10d0855be823d2a3b4ad23bc0ddfa16a327fdd"
    ),
    "qualification/hcsn_currentstate_n256_non_substochastic_signed_interval/test_signed_interval.py": (
        "c3e2fea145d4a5e13e10053bffcf60936c8fedde5c2f082b07940def211e7673"
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
    for relative, expected in EXPECTED_FILES.items():
        observed = _sha256(ROOT / relative)
        if observed != expected:
            raise SystemExit(f"sha256 mismatch for {relative}: {observed}")
    observed_verifier = _sha256(Path(__file__))
    if observed_verifier != freeze["verifier_sha256"]:
        raise SystemExit("verify_source.py differs from frozen verifier")

    source = (PACKAGE / "signed_interval.py").read_text(encoding="utf-8")
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
    forbidden_imports = {"decimal", "numpy", "scipy", "torch", "subprocess", "socket"}
    if imported & forbidden_imports:
        raise SystemExit("candidate imports a forbidden runtime")
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    if "float" in names or "eval" in names or "exec" in names:
        raise SystemExit("candidate uses a forbidden conversion or execution primitive")
    if "authentic_n256_bundle_loaded: bool = False" not in source:
        raise SystemExit("authentic N256 fail-closed marker missing")
    if "current_state_provider_qualified: bool = False" not in source:
        raise SystemExit("provider fail-closed marker missing")
    if request["idempotency_key"] is not None:
        raise SystemExit("source-only request must not declare a compute key")
    if any(request[name] != 0 for name in (
        "dynamic_calls",
        "model_calls",
        "optimizer_calls",
        "training_calls",
    )):
        raise SystemExit("source-only request declares numeric/model work")
    if request["status"] != "HOLD" or request["all_closed"]:
        raise SystemExit("global HOLD fail-closed state changed")
    print("PASS_N256_NON_SUBSTOCHASTIC_SIGNED_INTERVAL_SOURCE_ONLY")


if __name__ == "__main__":
    main()
