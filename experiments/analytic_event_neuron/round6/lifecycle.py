"""Immutable preparation, freeze and expected-identity confirmation checks."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil

from ..round4.runtime_evidence import write_json
from ..round5.selection_study import environment_snapshot
from ..runtime import digest
from .registration import REGISTRATION


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OLD_FREEZE = HERE.parent / "round5/evidence/selection_registered_001/FREEZE.json"
PRIMARY_FILES = ("__init__.py", "broker.py", "continuation.py", "data.py", "learning.py",
                 "study.py", "registration.py", "lifecycle.py", "summary.py",
                 "CONTRACT.md", "BROKER_CONTRACT.md")
PREPARED_FILES = ("TRAIN.npz", "DEVELOPMENT.npz", "MODELS.json", "TRAINING_ROWS.json.gz",
                  "TRAINING_RECEIPT.json", "train.zip", "development.zip",
                  "train.manifest.json", "development.manifest.json")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def environment():
    return {**environment_snapshot(), "Pillow": importlib.metadata.version("Pillow")}


def sources():
    old = json.loads(OLD_FREEZE.read_text())["sources_sha256"]
    for relative, expected in old.items():
        if sha(REPO / relative) != expected:
            raise ValueError("Inherited frozen source changed: " + relative)
    result = dict(old)
    for name in PRIMARY_FILES:
        path = HERE / name
        result[str(path.relative_to(REPO))] = sha(path)
    return dict(sorted(result.items()))


def artifacts(run_dir):
    root = Path(run_dir).resolve()
    result = {}
    for name in ("prepared", "native"):
        directory = root / name
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise ValueError("Prepared evidence roots must be real directories")
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise ValueError("Prepared evidence may not contain symlinks")
            if path.is_file():
                result[str(path.relative_to(root))] = sha(path)
    return result


def prepared_layout(run_dir):
    """Require the nine artifacts; record harmless empty transport directories."""
    root = Path(run_dir).resolve()
    prepared = root / "prepared"
    if prepared.is_symlink() or not prepared.is_dir():
        raise ValueError("Prepared evidence root must be a real directory")
    if {p.name for p in prepared.iterdir()} != {f"seed_{s}" for s in REGISTRATION["seeds"]}:
        raise ValueError("Incomplete or additional prepared seed inventory")
    empty_directories = []
    for seed in REGISTRATION["seeds"]:
        directory = prepared / f"seed_{seed}"
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Each prepared seed must be a real directory")
        entries = {p.name: p for p in directory.iterdir()}
        if not set(PREPARED_FILES).issubset(entries):
            raise ValueError("Missing prepared artifact")
        for name in PREPARED_FILES:
            if entries[name].is_symlink() or not entries[name].is_file():
                raise ValueError("Each prepared artifact must be a real file")
        for name in set(entries) - set(PREPARED_FILES):
            transient = entries[name]
            if name != "working_case" or transient.is_symlink() or not transient.is_dir():
                raise ValueError("Unexpected prepared artifact inventory")
            for path in [transient, *transient.rglob("*")]:
                if path.is_symlink() or not path.is_dir():
                    raise ValueError("Unarchived working evidence remains")
                empty_directories.append(str(path.relative_to(root)))
    return sorted(empty_directories)


def install_native(run_dir, binary, receipt):
    root = Path(run_dir).resolve()
    original = json.loads(Path(receipt).read_text())
    if (sha(binary) != REGISTRATION["native_binary_sha256"]
            or original.get("binary_sha256") != REGISTRATION["native_binary_sha256"]
            or original.get("source_commit") != REGISTRATION["native_original_source_commit"]
            or not all(original.get(key) is True for key in (
                "fresh_build", "original_source_git_blob_verified", "dependency_lock_subset_verified"))):
        raise ValueError("Exact recovered binary and original historical build receipt required")
    for name, expected in original["adapter_source_sha256"].items():
        if sha(HERE.parent / name) != expected:
            raise ValueError("Current adapter differs from historical binary build")
    directory = root / "native"
    directory.mkdir(parents=True, exist_ok=False)
    shutil.copy2(binary, directory / "analytic_event")
    shutil.copy2(receipt, directory / "BUILD_RECEIPT.json")
    (directory / "analytic_event").chmod(0o755)
    write_json(directory / "REUSE.json", {
        "schema": "hepta.native-artifact-reuse.v6", "new_build": False,
        "original_build_receipt_sha256": sha(receipt), "binary_sha256": sha(binary),
        "source_commit": original["source_commit"], "new_execution_identity": str(root),
        "created_utc": datetime.now(timezone.utc).isoformat()})


def begin_preparation(run_dir):
    root = Path(run_dir).resolve()
    if any((root / name).exists() for name in ("prepared", "PREPARING.json", "PREPARED.json", "FREEZE.json", "confirmation")):
        raise ValueError("A new preparation identity is required")
    if sha(root / "native/analytic_event") != REGISTRATION["native_binary_sha256"]:
        raise ValueError("Registered native executable is missing or changed")
    record = {"schema": "hepta.acquired-feedback.preparing.v6",
              "created_utc": datetime.now(timezone.utc).isoformat(),
              "registration": REGISTRATION, "registration_sha256": digest(REGISTRATION),
              "sources_sha256": sources(), "environment": environment(),
              "initial_native_sha256": artifacts(root), "confirmation_constructed": False}
    write_json(root / "PREPARING.json", record)
    return record


def verify_preparing(run_dir):
    root = Path(run_dir).resolve()
    record = json.loads((root / "PREPARING.json").read_text())
    if (record["registration"] != REGISTRATION or record["registration_sha256"] != digest(REGISTRATION)
            or record["sources_sha256"] != sources() or record["environment"] != environment()):
        raise ValueError("Preparation source, environment or registration changed")
    for relative, expected in record["initial_native_sha256"].items():
        if sha(root / relative) != expected:
            raise ValueError("Native preparation identity changed")
    return record


def prepare_manifest(run_dir):
    root = Path(run_dir).resolve()
    if (root / "FREEZE.json").exists() or (root / "confirmation").exists():
        raise ValueError("Preparation cannot be finalized after freeze/confirmation")
    start = verify_preparing(root)
    empty_directories = prepared_layout(root)
    for seed in REGISTRATION["seeds"]:
        directory = root / "prepared" / f"seed_{seed}"
        receipt = json.loads((directory / "TRAINING_RECEIPT.json").read_text())
        if (receipt["seed"] != seed or receipt["namespace"] != "registered"
                or receipt["train_rows"] != 256 or receipt["development_rows"] != 128
                or receipt["prior_confirmation_used"] is not False
                or receipt["dynamics"]["prior_parameters_changed"] is not True):
            raise ValueError("Preparation did not execute the registered fits")
        for arm in REGISTRATION["learned_readouts"]:
            fit = receipt["fits"][arm]
            if fit["parameter_l2_change"] <= 0 or len(fit["candidates"]) != 15:
                raise ValueError("Incomplete actual readout training/selection")
    record = {**start, "schema": "hepta.acquired-feedback.prepared.v6",
              "prepared_utc": datetime.now(timezone.utc).isoformat(),
              "preparing_sha256": sha(root / "PREPARING.json"),
              "empty_transport_directories_at_preparation": empty_directories,
              "empty_directories_are_nonsemantic": True,
              "artifacts_sha256": artifacts(root)}
    write_json(root / "PREPARED.json", record)
    return record


def verify_prepared(run_dir):
    root = Path(run_dir).resolve()
    verify_preparing(root)
    prepared_layout(root)
    record = json.loads((root / "PREPARED.json").read_text())
    if (record["preparing_sha256"] != sha(root / "PREPARING.json")
            or record["artifacts_sha256"] != artifacts(root)
            or record["sources_sha256"] != sources()
            or record["environment"] != environment()
            or record["registration_sha256"] != digest(REGISTRATION)
            or record["registration"] != REGISTRATION
            or record["confirmation_constructed"] is not False):
        raise ValueError("Prepared source, byte inventory or environment changed")
    return record


def freeze(run_dir, review_path):
    root = Path(run_dir).resolve()
    if (root / "confirmation").exists():
        raise ValueError("Confirmation must not precede freeze")
    prepared = verify_prepared(root)
    review_path = Path(review_path).resolve()
    if not review_path.is_relative_to(root):
        raise ValueError("The passed review must be retained inside its research run")
    review = json.loads(review_path.read_text())
    if (review.get("passed") is not True
            or review.get("prepared_sha256") != sha(root / "PREPARED.json")
            or review.get("sources_sha256") != prepared["sources_sha256"]):
        raise ValueError("An independent passed review bound to prepared bytes is required")
    result = {"schema": "hepta.acquired-feedback.freeze.v6",
              "created_utc": datetime.now(timezone.utc).isoformat(),
              "prepared_sha256": sha(root / "PREPARED.json"),
              "review_sha256": sha(review_path), "review_path": str(review_path.relative_to(root)),
              "registration_sha256": digest(REGISTRATION),
              "sources_sha256": prepared["sources_sha256"],
              "artifacts_sha256": prepared["artifacts_sha256"],
              "environment": prepared["environment"], "confirmation_constructed": False,
              "production_promotion": False}
    write_json(root / "FREEZE.json", result)
    return result


def verify(run_dir, expected_freeze_sha256):
    root = Path(run_dir).resolve()
    if (not isinstance(expected_freeze_sha256, str) or len(expected_freeze_sha256) != 64
            or sha(root / "FREEZE.json") != expected_freeze_sha256):
        raise ValueError("An independently expected exact freeze identity is required")
    frozen = json.loads((root / "FREEZE.json").read_text())
    prepared = verify_prepared(root)
    for name in ("sources_sha256", "artifacts_sha256", "environment", "registration_sha256"):
        if frozen[name] != prepared[name]:
            raise ValueError("Freeze differs from preparation: " + name)
    if frozen["prepared_sha256"] != sha(root / "PREPARED.json"):
        raise ValueError("Prepared index differs from its freeze")
    review_path = (root / frozen["review_path"]).resolve()
    if not review_path.is_relative_to(root) or sha(review_path) != frozen["review_sha256"]:
        raise ValueError("Passed independent review differs from its freeze")
    return frozen


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("begin", "prepare-manifest", "freeze", "verify"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--expected-freeze-sha256")
    args = parser.parse_args()
    if args.operation == "begin":
        result = begin_preparation(args.run_dir)
    elif args.operation == "prepare-manifest":
        result = prepare_manifest(args.run_dir)
    elif args.operation == "freeze":
        result = freeze(args.run_dir, args.review)
    else:
        result = verify(args.run_dir, args.expected_freeze_sha256)
    print(json.dumps({"schema": result["schema"], "source_files": len(result["sources_sha256"])}))
