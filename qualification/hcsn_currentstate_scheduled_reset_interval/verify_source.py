import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_scheduled_reset_interval"
EXPECTED_IDENTITY = (
    "hcsn-currentstate-scheduled-reset-interval-source-only-20261114-c06d-v1"
)
EXPECTED_FILES = {
    ".github/workflows/hcsn-currentstate-scheduled-reset-interval.yml": (
        "dde7c03b992f6c7fbefa13888339f2705117db3b4a7b206aea881e6e912e1a99"
    ),
    "qualification/hcsn_currentstate_scheduled_reset_interval/DEVELOPMENT_RED.md": (
        "1a76fecffc69d832bb6d65597c2ab0399a35e147fefc8ff52bb279809f3bebc3"
    ),
    "qualification/hcsn_currentstate_scheduled_reset_interval/README.md": (
        "923d79dceaa86535127fe3e2c51afe7acf563891dee1642d065e4dfc4bdc68e6"
    ),
    "qualification/hcsn_currentstate_scheduled_reset_interval/REQUEST.json": (
        "478dd0cb35b8f39fbc269b73c41391964dbebc666f8122a014e454591df34962"
    ),
    "qualification/hcsn_currentstate_scheduled_reset_interval/__init__.py": (
        "e7c38e98bba91cf20254277f0c27b98915e0fce68bc2de015d43e4121b524b8c"
    ),
    "qualification/hcsn_currentstate_scheduled_reset_interval/scheduled_reset.py": (
        "3d21fff0b4fcc0b401238f8d11fc44305332348872998f880a4992769b0b1d81"
    ),
    "qualification/hcsn_currentstate_scheduled_reset_interval/test_scheduled_reset.py": (
        "86e8305df2074c9e244b28accd57ac1f0970318133040b964de37350a15de9d7"
    ),
}
PARENT_FILES = {
    "qualification/hcsn_currentstate_augmented_selector_interval/augmented_selector.py": (
        "eb8fdf0b5a56e9173b1b89fc9b8dcc93b579487dbf1011df0c8eeec0d88ed9ab"
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
    if request["parent_augmented_selector_sha256"] != next(iter(PARENT_FILES.values())):
        raise SystemExit("request does not bind the augmented-selector parent")
    if request["parent_signed_interval_sha256"] != tuple(PARENT_FILES.values())[1]:
        raise SystemExit("request does not bind the signed-interval parent")
    if _sha256(Path(__file__)) != freeze["verifier_sha256"]:
        raise SystemExit("verify_source.py differs from frozen verifier")

    source = (PACKAGE / "scheduled_reset.py").read_text(encoding="utf-8")
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
        "hit_specific_deterministic_delay_encoded: bool = False",
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
    print("PASS_CURRENTSTATE_SCHEDULED_RESET_INTERVAL_SOURCE_ONLY")


if __name__ == "__main__":
    main()
