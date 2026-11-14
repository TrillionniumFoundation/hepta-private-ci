import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_second_feedback_interval"
EXPECTED_IDENTITY = (
    "hcsn-currentstate-second-feedback-interval-source-only-20261114-c06d-v1"
)
EXPECTED_FILES = {
    ".github/workflows/hcsn-currentstate-second-feedback-interval.yml": (
        "98a44bc9dacc30ea1c81eb53d0fef38897d9fa81ecea18cc5e58d8f67b2dbbf6"
    ),
    "qualification/hcsn_currentstate_second_feedback_interval/README.md": (
        "7e948d343fed1fd4be436d6abd193575081ade7118cdac25b151382b39bf4cff"
    ),
    "qualification/hcsn_currentstate_second_feedback_interval/REQUEST.json": (
        "24ca54b4a3d33e005b27d95cd4de359f6e84301350a3704f9dfadc6c89260796"
    ),
    "qualification/hcsn_currentstate_second_feedback_interval/__init__.py": (
        "e51bd108cf9fa59648408f18df0ac5826e130a6c5bc30f4cd9cb506b8d2bf1a2"
    ),
    "qualification/hcsn_currentstate_second_feedback_interval/second_feedback.py": (
        "a63b99cf3ed302eff16f1c7e003eaab5b8ff4d7a5bc7026c82ab88ebc2caf720"
    ),
    "qualification/hcsn_currentstate_second_feedback_interval/test_second_feedback.py": (
        "6c96c7616157daa95d3353ebf63afa8562ce0a5ae96499dbdb249da16459ff8c"
    ),
}
PARENT_FILES = {
    "qualification/hcsn_currentstate_hit_delay_reset_interval/hit_delay_reset.py": (
        "c2c682f04d49fa787711293657054b2d5c47784a1ab08d7bba5310d5cf4bc8e0"
    ),
    "qualification/hcsn_currentstate_scheduled_reset_interval/scheduled_reset.py": (
        "3d21fff0b4fcc0b401238f8d11fc44305332348872998f880a4992769b0b1d81"
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
    if request["parent_hit_delay_reset_sha256"] != tuple(PARENT_FILES.values())[0]:
        raise SystemExit("request does not bind the hit-delay-reset parent")
    if request["parent_scheduled_reset_sha256"] != tuple(PARENT_FILES.values())[1]:
        raise SystemExit("request does not bind the interval propagator parent")
    if _sha256(Path(__file__)) != freeze["verifier_sha256"]:
        raise SystemExit("verify_source.py differs from frozen verifier")

    source = (PACKAGE / "second_feedback.py").read_text(encoding="utf-8")
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
        "two_deterministic_delay_releases_encoded: bool = True",
        "third_segment_second_feedback_encoded: bool = True",
        "fourth_or_later_segment_encoded: bool = False",
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
    print("PASS_CURRENTSTATE_SECOND_FEEDBACK_INTERVAL_SOURCE_ONLY")


if __name__ == "__main__":
    main()
