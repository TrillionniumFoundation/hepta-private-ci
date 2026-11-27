import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_hit_delay_reset_interval"
EXPECTED_IDENTITY = (
    "hcsn-currentstate-hit-delay-reset-interval-source-only-20261114-c06d-v1"
)
EXPECTED_FILES = {
    ".github/workflows/hcsn-currentstate-hit-delay-reset-interval.yml": (
        "90df95152fd92c9049573128d77fb525b36fbbb918b0a6e24aca487bd0451b35"
    ),
    "qualification/hcsn_currentstate_hit_delay_reset_interval/DEVELOPMENT_RED.md": (
        "ca89323d93ca7d92b5269186a5aa536c1977839508dd1ca05d65bc66f806037f"
    ),
    "qualification/hcsn_currentstate_hit_delay_reset_interval/README.md": (
        "e3aec9a3bf4dc90a7175978dee7e9afebee6742e346c821336f1014be11af972"
    ),
    "qualification/hcsn_currentstate_hit_delay_reset_interval/REQUEST.json": (
        "02d7fd9393521cd79884b476442df84c0510a21c4ee6fb9592f189746db5915d"
    ),
    "qualification/hcsn_currentstate_hit_delay_reset_interval/__init__.py": (
        "7cab9965b38a168dcca23a1f10befecb9770fa88e1956a246596e9d90b945812"
    ),
    "qualification/hcsn_currentstate_hit_delay_reset_interval/hit_delay_reset.py": (
        "c2c682f04d49fa787711293657054b2d5c47784a1ab08d7bba5310d5cf4bc8e0"
    ),
    "qualification/hcsn_currentstate_hit_delay_reset_interval/test_hit_delay_reset.py": (
        "42fdd8492bfc6826d3a388e5aa832e405f3eff35fe5eeb9825bbb0027a70c695"
    ),
}
PARENT_FILES = {
    "qualification/hcsn_currentstate_augmented_selector_interval/augmented_selector.py": (
        "eb8fdf0b5a56e9173b1b89fc9b8dcc93b579487dbf1011df0c8eeec0d88ed9ab"
    ),
    "qualification/hcsn_currentstate_scheduled_reset_interval/scheduled_reset.py": (
        "3d21fff0b4fcc0b401238f8d11fc44305332348872998f880a4992769b0b1d81"
    ),
    "qualification/hcsn_currentstate_n256_non_substochastic_signed_interval/signed_interval.py": (
        "0609297f789485f38970491fcc10d0855be823d2a3b4ad23bc0ddfa16a327fdd"
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
    for relative, expected in PARENT_FILES.items():
        observed = _sha256(ROOT / relative)
        if observed != expected:
            raise SystemExit(f"parent sha256 mismatch for {relative}: {observed}")
    expected_parent_requests = {
        "parent_augmented_selector_sha256": tuple(PARENT_FILES.values())[0],
        "parent_scheduled_reset_sha256": tuple(PARENT_FILES.values())[1],
        "parent_signed_interval_sha256": tuple(PARENT_FILES.values())[2],
    }
    if any(request[name] != expected for name, expected in expected_parent_requests.items()):
        raise SystemExit("request does not bind all parent sources")
    if _sha256(Path(__file__)) != freeze["verifier_sha256"]:
        raise SystemExit("verify_source.py differs from frozen verifier")

    source = (PACKAGE / "hit_delay_reset.py").read_text(encoding="utf-8")
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
        "same_ctmc_hit_flux_encoded: bool = True",
        "one_deterministic_delay_release_encoded: bool = True",
        "third_or_later_cycle_encoded: bool = False",
        "arbitrary_history_encoded: bool = False",
        "authentic_n256_bundle_loaded: bool = False",
        "current_state_provider_qualified: bool = False",
    )
    if any(marker not in source for marker in required_markers):
        raise SystemExit("required scope or fail-closed marker missing")
    if request["idempotency_key"] is not None:
        raise SystemExit("source-only request must not declare a compute key")
    if any(
        request[name] != 0
        for name in ("dynamic_calls", "model_calls", "optimizer_calls", "training_calls")
    ):
        raise SystemExit("source-only request declares numeric/model work")
    if request["status"] != "HOLD" or request["all_closed"]:
        raise SystemExit("global HOLD fail-closed state changed")
    print("PASS_CURRENTSTATE_HIT_DELAY_RESET_INTERVAL_SOURCE_ONLY")


if __name__ == "__main__":
    main()
