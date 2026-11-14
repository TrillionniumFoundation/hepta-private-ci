import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_augmented_selector_interval"
EXPECTED_IDENTITY = (
    "hcsn-currentstate-augmented-selector-interval-source-only-20261114-c06d-v1"
)
EXPECTED_FILES = {
    ".github/workflows/hcsn-currentstate-augmented-selector-interval.yml": (
        "4b8dbb7038f1d5b18f89db5d655e34d67e8328a665247edcdf0fbfa0cc272bc8"
    ),
    "qualification/hcsn_currentstate_augmented_selector_interval/README.md": (
        "c20fc3505fbf2e5df820ef769a577a4892f74b103f878dedcd4a681e300af3f7"
    ),
    "qualification/hcsn_currentstate_augmented_selector_interval/REQUEST.json": (
        "31c505530a72b7f55ce0cedb7bde134f7212e60bf72429bf439703539d13726d"
    ),
    "qualification/hcsn_currentstate_augmented_selector_interval/__init__.py": (
        "b4e791afd095689d665fec716f19540b9bc9a04230d237e6d7cdc2f38003ae6b"
    ),
    "qualification/hcsn_currentstate_augmented_selector_interval/augmented_selector.py": (
        "eb8fdf0b5a56e9173b1b89fc9b8dcc93b579487dbf1011df0c8eeec0d88ed9ab"
    ),
    "qualification/hcsn_currentstate_augmented_selector_interval/test_augmented_selector.py": (
        "22aad3102354895b8af57c51f644d523549812b6f93c0d04d80f5a0a33b50338"
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
    if _sha256(Path(__file__)) != freeze["verifier_sha256"]:
        raise SystemExit("verify_source.py differs from frozen verifier")

    source = (PACKAGE / "augmented_selector.py").read_text(encoding="utf-8")
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
    required_markers = (
        "deterministic_delay_encoded: bool = False",
        "reset_encoded: bool = False",
        "authentic_n256_bundle_loaded: bool = False",
        "current_state_provider_qualified: bool = False",
    )
    if any(marker not in source for marker in required_markers):
        raise SystemExit("required fail-closed marker missing")
    if request["idempotency_key"] is not None:
        raise SystemExit("source-only request must not declare a compute key")
    if any(
        request[name] != 0
        for name in ("dynamic_calls", "model_calls", "optimizer_calls", "training_calls")
    ):
        raise SystemExit("source-only request declares numeric/model work")
    if request["status"] != "HOLD" or request["all_closed"]:
        raise SystemExit("global HOLD fail-closed state changed")
    print("PASS_CURRENTSTATE_AUGMENTED_SELECTOR_INTERVAL_SOURCE_ONLY")


if __name__ == "__main__":
    main()
