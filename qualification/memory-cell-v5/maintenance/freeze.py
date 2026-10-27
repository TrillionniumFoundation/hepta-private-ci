"""Create source and selected-model seals before any independent held execution."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import re

from v5.contracts import file_identity
from v5.joint_cases import GATES, PROJECT, SEEDS, verify_freeze


def write_exclusive(path, document):
    with path.open("x") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")


def source_freeze(commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("source commit must be a full Git identity")
    protocol = json.loads((PROJECT / "PROTOCOL.json").read_bytes())
    if protocol["formal_seeds"] != list(SEEDS):
        raise ValueError("protocol formal seeds differ")
    files = set(PROJECT.glob("*.py"))
    for directory in ("v5", "legacy_v3", "maintenance", "tests", "validation"):
        files.update((PROJECT / directory).glob("*.py"))
    files.update(PROJECT / name for name in ("PROTOCOL.json", "VENDOR.json", "V5B_PREDECLARATION.md"))
    files.update(path for path in (PROJECT / "assets").rglob("*") if path.is_file())
    if any(path.is_symlink() for path in files):
        raise ValueError("linked source or asset")
    seal = file_identity(PROJECT / "held/SEAL.json")
    if seal["sha256"] != protocol["main_held"]["seal_sha256"]:
        raise ValueError("independent held seal differs from the protocol")
    document = {"schema": "hepta.memory.v5.source-freeze.v1", "frozen": True,
                "created_utc": datetime.now(timezone.utc).isoformat(), "source_commit": commit,
                "source_files": {path.relative_to(PROJECT).as_posix(): file_identity(path) for path in sorted(files)},
                "held_seal_sha256": seal["sha256"], "seeds": list(SEEDS), "gates": GATES,
                "assets_binding_sha256": file_identity(PROJECT / "assets/ASSETS.json")["sha256"],
                "python_version": platform.python_version(), "held_body_read_by_freezer": False,
                "remote_commit_verification": "Caller must verify this commit and source blobs before starting formal training"}
    write_exclusive(PROJECT / "FREEZE.json", document)
    verify_freeze(PROJECT / "FREEZE.json")
    return {"source_commit": commit, "source_files": len(files), "freeze": file_identity(PROJECT / "FREEZE.json")}


def seal_selected(training_root):
    frozen, freeze_identity = verify_freeze(PROJECT / "FREEZE.json")
    root = Path(training_root).resolve()
    routers = {}
    mapping = {}
    for seed in SEEDS:
        directory = root / f"seed-{seed}" / "selected"
        manifest = json.loads((directory / "manifest.json").read_bytes())
        candidate = manifest["candidate"]
        training = manifest["training_identity"]
        if training["seed"] != seed or training["source_commit"] != frozen["source_commit"]:
            raise ValueError("selected training identity differs from the freeze")
        receipt = directory.parent / "candidate-diagnostics" / candidate["name"] / "RECEIPT.json"
        routers[str(seed)] = {
            "files": {name: file_identity(directory / name) for name in ("manifest.json", *manifest["files"])},
            "candidate": candidate, "training_identity": training,
            "selection_receipt_sha256": file_identity(receipt)["sha256"],
            "primary_sha256": file_identity(directory.parent / "PRIMARY.json")["sha256"],
            "candidates_sha256": file_identity(directory.parent / "CANDIDATES.json")["sha256"],
            "training_source_sha256": file_identity(root / "SOURCE.json")["sha256"],
        }
        mapping[str(seed)] = str(directory)
    document = {"schema": "hepta.memory.v5.selected-before-held.v1", "source_commit": frozen["source_commit"],
                "freeze_sha256": freeze_identity["sha256"], "routers": routers,
                "assets_binding_sha256": frozen["assets_binding_sha256"], "held_opened": False,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "remote_delivery_before_held_required": True}
    write_exclusive(PROJECT / "SELECTED_MODELS.json", document)
    write_exclusive(PROJECT / "ROUTERS.json", mapping)
    return {"selected_seal": file_identity(PROJECT / "SELECTED_MODELS.json"), "models": len(routers),
            "next_step": "Verify immutable remote delivery of the selection seal and model bytes before opening held"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    freezing = actions.add_parser("source")
    freezing.add_argument("--commit", required=True)
    sealing = actions.add_parser("selection")
    sealing.add_argument("--training", type=Path, required=True)
    args = parser.parse_args()
    result = source_freeze(args.commit) if args.action == "source" else seal_selected(args.training)
    print(json.dumps(result, sort_keys=True))
