"""Seal registered scientific inputs before generating confirmation fixtures."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .study import PRIMARY, SECONDARY, checkpoint_path, verify_freeze


def freeze(root):
    root = Path(root).resolve()
    destination = root / "FROZEN_MANIFEST.json"
    if destination.exists():
        raise FileExistsError("a frozen study is immutable; use a new version")
    if any((root / "evidence").glob("confirmation*")):
        raise ValueError("confirmation evidence already exists")
    tests = json.loads((root / "evidence" / "TEST_RECEIPT.json").read_text())
    if tests["returncode"] != 0:
        raise ValueError("implementation test suite must pass before freeze")
    current_sources = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in root.glob("*.py")}
    if (not tests.get("source_unchanged_during_tests")
            or current_sources != tests.get("source_hashes_at_test")):
        raise ValueError("test receipt does not bind the current Python source snapshot")
    registry = json.loads((root / "evidence" / "REGISTERED_CHECKPOINTS.json").read_text())
    keys = sorted({(mode, ablation) for mode, ablation, _, _ in
                   list(PRIMARY.values()) + list(SECONDARY.values())})
    expected = {str(checkpoint_path(root / "evidence", mode, ablation, seed).relative_to(root))
                for mode, ablation in keys for seed in range(11, 16)}
    if len(expected) != 60 or expected != {entry["path"] for entry in registry["entries"]}:
        raise ValueError("registered checkpoint identity mismatch")
    for entry in registry["entries"]:
        checkpoint_bytes = (root / entry["path"]).read_bytes()
        if hashlib.sha256(checkpoint_bytes).hexdigest() != entry["sha256"]:
            raise ValueError("checkpoint changed after registration")
        record = json.loads(checkpoint_bytes)
        if (record["configuration"]["mode"] != entry["mode"]
                or record["configuration"]["n_grid"] != 15
                or record["metadata"]["seed"] != entry["seed"]
                or record["metadata"]["ablation"] != entry["ablation"]
                or record["metadata"]["epochs"] != 100
                or record["metadata"]["control_refinement"]["epochs"] != 30):
            raise ValueError("checkpoint model/training identity differs from registration")
    timestamp = datetime.now(timezone.utc).isoformat()
    protocol_path = root / "PROTOCOL.json"
    protocol = json.loads(protocol_path.read_text())
    protocol.update({"status": "frozen_before_confirmation", "frozen": True,
                     "freeze_utc": timestamp, "freeze_manifest": destination.name,
                     "unresolved_before_freeze": []})
    protocol_path.write_text(json.dumps(protocol, indent=2, ensure_ascii=False) + "\n")
    inputs = list(root.glob("*.py"))
    inputs += [root / name for name in ("PROTOCOL.json", "SOURCE_BASELINE.json", "DEVIATIONS.json",
                                        "CONTRACT.md", "DYNAMICS.md", "TASK.md", "REVIEW.md", "requirements.txt")]
    inputs += [root / "evidence" / name for name in
               ("REGISTERED_CHECKPOINTS.json", "ENVIRONMENT.json", "TEST_RECEIPT.json",
                "numerical_audit.json", "joint_control_audit.json", "temperature_correction_validation.json")]
    inputs += [root / entry["path"] for entry in registry["entries"]]
    inputs += [root.parent / name for name in ("analytic.py", "reference.py", "native_adapter.py", "__init__.py")]
    files = {str(path.relative_to(root) if path.is_relative_to(root) else Path("..") / path.name):
             hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(inputs)}
    manifest = {"schema": "hepta.round7.freeze.v1", "freeze_utc": timestamp,
                "confirmation_started": False, "registered_checkpoints": 60,
                "formal_training_attempts": 65, "predeclared_exclusions": 5,
                "source_parent_commit": "bf88335edc41d40d57d8e84716dd1d2e8cd13a68",
                "files": files,
                "meaning": "This immutable pre-confirmation seal records inputs; outputs are separate evidence."}
    destination.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    checked = verify_freeze(root)
    return {"freeze_utc": timestamp, "files": len(files), "sha256": checked["sha256"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).parent))
    args = parser.parse_args()
    print(json.dumps(freeze(args.root), indent=2))


if __name__ == "__main__":
    main()
