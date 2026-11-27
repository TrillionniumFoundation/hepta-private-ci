"""Validate the explicit v2 source binding, then run the original v1 checks."""

import hashlib
import json
from pathlib import Path
import runpy
import tempfile
import types


ROOT = Path(__file__).parent
PREFIX = "qualification/hcsn_currentstate_n256_fp64_rounding/"
WORKFLOW = ".github/workflows/hcsn-currentstate-n256-fp64-rounding.yml"
PREDECESSOR_SHA256 = (
    "840f3b4bedd74d2dc8bbff08e2b7004a6a04ae3e67e4260ad7e6a3813f63ef69"
)
CURRENT_IDENTITY = "hcsn-n256-fp64-rounding-current-source-20261116-v2"
HISTORICAL_VERIFIER = PREFIX + "history/verify_source_v1.py"
HISTORICAL_WORKFLOW = PREFIX + "history/rounding_workflow_formatted_v1.yml"
TEST_MODULE = "qualification.hcsn_currentstate_n256_fp64_rounding.test_source_freeze"


def verify_current(root):
    repository = root.parents[1]
    predecessor_path = root / "SOURCE_FREEZE.json"
    predecessor_bytes = predecessor_path.read_bytes()
    if hashlib.sha256(predecessor_bytes).hexdigest() != PREDECESSOR_SHA256:
        raise SystemExit("historical source freeze changed")
    predecessor = json.loads(predecessor_bytes)
    current_path = root / "CURRENT_SOURCE_FREEZE.json"
    current_bytes = current_path.read_bytes()
    current = json.loads(current_bytes)
    expected_predecessor = {
        "path": PREFIX + "SOURCE_FREEZE.json",
        "sha256": PREDECESSOR_SHA256,
        "identity": predecessor["identity"],
    }
    if (
        current.get("schema") != "hepta.source-freeze-successor.v2"
        or current.get("identity") != CURRENT_IDENTITY
        or current.get("predecessor") != expected_predecessor
        or current.get("scope") != predecessor["scope"]
        or current.get("forbidden_source_tokens")
        != predecessor["forbidden_source_tokens"]
    ):
        raise SystemExit("current source freeze boundary mismatch")

    expected_paths = set(predecessor["files"]) | {
        PREFIX + "SOURCE_FREEZE.json",
        HISTORICAL_VERIFIER,
        HISTORICAL_WORKFLOW,
        PREFIX + "test_source_freeze.py",
    }
    if set(current["files"]) != expected_paths:
        raise SystemExit("current source freeze inventory mismatch")
    for path, digest in predecessor["files"].items():
        if path not in {WORKFLOW, PREFIX + "verify_source.py"}:
            if current["files"][path] != digest:
                raise SystemExit(f"original source pin changed: {path}")
    if current["files"][PREFIX + "SOURCE_FREEZE.json"] != PREDECESSOR_SHA256:
        raise SystemExit("historical source freeze pin changed")
    original_verifier_hash = predecessor["files"][PREFIX + "verify_source.py"]
    if current["files"][HISTORICAL_VERIFIER] != original_verifier_hash:
        raise SystemExit("historical verifier pin changed")

    formatted_workflow = (repository / HISTORICAL_WORKFLOW).read_bytes()
    if (
        hashlib.sha256(formatted_workflow + b"\n").hexdigest()
        != predecessor["files"][WORKFLOW]
    ):
        raise SystemExit("historical workflow is not the exact newline predecessor")
    original_module = (
        b"qualification.hcsn_currentstate_n256_fp64_rounding.test_fp64_round\n"
    )
    if formatted_workflow.count(original_module) != 2:
        raise SystemExit("historical workflow test invocations changed")
    approved_workflow = formatted_workflow.replace(
        original_module,
        original_module.rstrip(b"\n") + b" " + TEST_MODULE.encode() + b"\n",
    )
    if (repository / WORKFLOW).read_bytes() != approved_workflow:
        raise SystemExit("workflow differs from the approved source-freeze successor")

    # Keep the original source identities and run the historical checks against
    # those exact bytes, rather than against current display representations.
    trusted_repository = ROOT.resolve().parents[1]
    restore = runpy.run_path(str(
        trusted_repository / "qa/repository-consolidation/20261115/restore_raw_evidence.py"
    ))
    inventory = restore["entries"](trusted_repository)
    with tempfile.TemporaryDirectory(prefix="hepta-rounding-source-") as location:
        historical_repository = Path(location)
        for path, digest in current["files"].items():
            try:
                raw = restore["read_frozen_source"](
                    repository, path, digest, inventory, require_current_view=True
                )
            except (OSError, ValueError, KeyError) as error:
                if path == HISTORICAL_VERIFIER:
                    raise SystemExit("historical verifier pin changed") from error
                if path in predecessor["files"] and path not in {WORKFLOW, PREFIX + "verify_source.py"}:
                    raise SystemExit(f"original source pin changed: {path}") from error
                raise SystemExit(f"current source freeze mismatch: {path}") from error
            destination = historical_repository / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
        historical_root = historical_repository / PREFIX
        historical_current = historical_root / current_path.name
        historical_current.write_bytes(current_bytes)

        # Run the exact V1 module with the already-approved V2 complete binding.
        historical_verifier = historical_repository / HISTORICAL_VERIFIER
        original_source = historical_verifier.read_bytes()
        original = types.ModuleType("rounding_source_freeze_v1")
        original.__file__ = str(historical_root / "verify_source.py")
        exec(compile(original_source, HISTORICAL_VERIFIER, "exec"), original.__dict__)
        original.FREEZE = historical_current
        original.main()
    print("PASS_N256_FP64_ROUNDING_CURRENT_SOURCE_V2")


if __name__ == "__main__":
    verify_current(ROOT)
