"""Package and verify the exact new Hepta source/data/evidence bytes.

Verification uses only the Python standard library and never reruns science.
The package's completion status is distinct from a positive scientific result.
"""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import time


EVIDENCE = "research_evidence/hepta_stable_flow_20261029"
SOURCE_ROOTS = (
    "experiments/call_put_stable_flow",
    "experiments/call_put_stable_flow_appendix",
    "experiments/call_put_stable_flow_analysis",
)
MANIFEST = "HEPTA_NEW_EXECUTION_MANIFEST.json"


def encoded(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(root, path):
    path = checked(root, path.relative_to(root).as_posix())
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def safe_name(name):
    p = PurePosixPath(name)
    require(
        bool(p.parts)
        and not p.is_absolute()
        and ".." not in p.parts
        and str(p) == name
        and "\\" not in name
        and "\x00" not in name,
        "Noncanonical or unsafe archive path",
    )
    return name


def checked(root, name):
    """Reject links at every component, including ancestors of a regular file."""
    safe_name(name)
    path = root
    for component in PurePosixPath(name).parts:
        path = path / component
        require(not path.is_symlink(), "Symlink in evidence path: " + name)
    require(path.resolve().is_relative_to(root.resolve()), "Evidence path escapes root")
    return path


def excluded(name, phase):
    parts = PurePosixPath(name).parts
    if "__pycache__" in parts or name.endswith((".pyc", ".pyo")):
        return True
    if name.startswith(EVIDENCE + "/releases/"):
        return True
    if phase == "preregistration":
        for prefix in (
            "formal_run001/candidates/",
            "formal_run001/predictions/",
            "formal_run001/orchestration/",
            "trained_numerics_appendix001/execution/",
            "inference_cost_appendix001/execution/",
        ):
            if name.startswith(EVIDENCE + "/" + prefix):
                return True
    return False


def inventory(root, phase):
    files = []
    for prefix in (*SOURCE_ROOTS, EVIDENCE):
        directory = checked(root, prefix)
        require(directory.is_dir(), "Missing source or evidence root: " + prefix)
        for path in sorted(directory.rglob("*")):
            name = safe_name(path.relative_to(root).as_posix())
            if excluded(name, phase):
                continue
            path = checked(root, name)
            if path.is_file():
                files.append(
                    {"path": name, "bytes": path.stat().st_size, "sha256": sha(path)}
                )
    return sorted(files, key=lambda row: row["path"])


def bound(root, path, expected, message):
    path = checked(root, path.relative_to(root).as_posix())
    require(path.is_file() and sha(path) == expected, message)


def completion_gates(root, phase):
    study = checked(root, EVIDENCE + "/formal_run001")
    protocol = read(root, study / "protocol.json")
    bound(
        root,
        study / "protocol.json",
        read(root, study / "freeze_seal.json")["protocol_sha256"],
        "Formal protocol changed",
    )
    require(
        len(protocol["candidates"]) == protocol["candidate_count"] == 60,
        "Expected exactly 60 registered candidates",
    )
    for name, digest in protocol["source_sha256"].items():
        bound(
            root,
            root / SOURCE_ROOTS[0] / safe_name(name),
            digest,
            "Frozen core source changed",
        )
        bound(
            root,
            study / "source_snapshot" / name,
            digest,
            "Frozen source snapshot changed",
        )
    data = read(root, study / "data_manifest.json")
    require(len(data["splits"]) == 6, "Expected all six data splits")
    for name, entry in data["splits"].items():
        bound(
            root,
            study / "data" / safe_name(name + ".npz"),
            entry["file_sha256"],
            "Raw split changed",
        )
    result = {
        "formal_protocol_sha256": sha(study / "protocol.json"),
        "candidate_count": 60,
        "data_splits": 6,
        "frozen_core_files": len(protocol["source_sha256"]),
    }
    if phase == "preregistration":
        require(
            not (study / "selection.json").exists()
            and not (study / "results.json").exists(),
            "Preregistration release must precede selection and test scoring",
        )
        result["meaning"] = (
            "Frozen source/data/protocol bytes; training may be in progress and is excluded"
        )
        return result
    training = read(root, study / "all_training_complete_seal.json")["complete_sha256"]
    require(
        set(training) == {row["id"] for row in protocol["candidates"]},
        "Incomplete candidate seal",
    )
    checkpoints = 0
    for name, digest in training.items():
        folder = study / "candidates" / safe_name(name)
        bound(root, folder / "complete.json", digest, "Training receipt changed")
        receipt = read(root, folder / "complete.json")
        require(
            receipt["status"] == "complete"
            and receipt["updates"] >= 384
            and receipt["training_cpu_seconds"] >= 30,
            "Incomplete training budget",
        )
        require(
            set(receipt["checkpoints"])
            == {"step0", "cpu15", "cpu30", "update192", "update384"},
            "Missing budget checkpoint",
        )
        for checkpoint in receipt["checkpoints"].values():
            bound(
                root,
                folder / safe_name(checkpoint["file"]),
                checkpoint["sha256"],
                "Checkpoint bytes changed",
            )
            checkpoints += 1
    bound(
        root,
        study / "selection.json",
        read(root, study / "selection_seal.json")["selection_sha256"],
        "Selection changed after sealing",
    )
    selection = read(root, study / "selection.json")
    require(
        selection["all_training_complete_sha256"] == training
        and len(selection["selected"]) == 60,
        "Selection is not bound to complete training",
    )
    scored = read(root, study / "results.json")
    require(
        len(scored["results"]) == 60 and len(scored["step0"]) == 30,
        "Missing selected or step-zero scores",
    )
    tasks = sorted({row["task"] for row in protocol["candidates"]})
    expected_aliases = {
        (task, arm, seed, regime)
        for task in tasks
        for arm in protocol["arms"]
        for seed in protocol["seeds"]
        for regime in protocol["selection_checkpoints"]
    }

    def identity(row):
        return row["task"], row["arm"], row["seed"], row["regime"]

    selected = {identity(row): row for row in selection["selected"]}
    require(
        set(selected) == expected_aliases and len(selected) == 60,
        "Selected aliases missing or duplicated",
    )
    require(
        {identity(row) for row in scored["results"]} == expected_aliases,
        "Scored aliases missing or duplicated",
    )
    require(
        {(row["task"], row["arm"], row["seed"]) for row in scored["step0"]}
        == {
            (task, arm, seed)
            for task in tasks
            for arm in protocol["arms"]
            for seed in protocol["seeds"]
        },
        "Step-zero score identities missing or duplicated",
    )
    for row in scored["results"]:
        require(
            all(
                row.get(key) == value for key, value in selected[identity(row)].items()
            ),
            "Score is not bound to its exact selected checkpoint and validation record",
        )
        bound(
            root,
            study / safe_name(row["prediction_file"]),
            row["prediction_sha256"],
            "Prediction bytes changed",
        )
    numerical = read(
        root, root / EVIDENCE / "trained_numerics_appendix001/execution/summary.json"
    )
    require(
        numerical["registered_aliases"] == 24
        and numerical["dop_aliases"] == 8
        and numerical["execution_errors"] == 0
        and numerical["primary_scores_or_selection_modified"] is False
        and numerical["test_data_or_scores_read"] is False,
        "Numerical appendix execution/coverage is incomplete",
    )
    runtime = read(
        root, root / EVIDENCE / "inference_cost_appendix001/execution/summary.json"
    )
    require(
        runtime["status"] == "complete" and runtime["alias_count"] == 20,
        "Inference-cost appendix coverage is incomplete",
    )
    review_path = root / EVIDENCE / "independent_review/final_scientific_audit.json"
    review = read(root, review_path)
    require(
        review["status"] == "complete" and review["artifact_integrity_passed"] is True,
        "Independent final artifact audit is incomplete",
    )
    require(bool(review["bound_artifacts"]), "Final audit must bind actual artifacts")
    for entry in review["bound_artifacts"]:
        bound(
            root,
            root / safe_name(entry["path"]),
            entry["sha256"],
            "Final audit artifact binding changed",
        )
    result.update(
        {
            "checkpoint_count": checkpoints,
            "selected_aliases": 60,
            "prediction_files": 60,
            "step0_scores": 30,
            "numerical_aliases": 24,
            "numerical_dop_aliases": 8,
            "runtime_aliases": 20,
            "independent_final_audit_sha256": sha(review_path),
            "meaning": "Complete registered training and scoring bytes; scientific advantage and numerical gates may fail",
        }
    )
    return result


def verify_archive(archive_path):
    with tarfile.open(archive_path, mode="r|gz") as archive:
        first = archive.next()
        require(
            first is not None and first.name == MANIFEST and first.isfile(),
            "Manifest must be first",
        )
        require(first.size < 20_000_000, "Manifest exceeds bounded size")
        manifest = json.load(archive.extractfile(first))
        require(
            manifest["schema"] == "hepta-new-execution-evidence-v1"
            and manifest["phase"] in ("preregistration", "complete")
            and manifest["source_roots"] == list(SOURCE_ROOTS)
            and manifest["evidence_root"] == EVIDENCE,
            "Unknown archive scope or schema",
        )
        identity = manifest.pop("identity_sha256")
        require(
            hashlib.sha256(encoded(manifest)).hexdigest() == identity,
            "Manifest identity changed",
        )
        manifest["identity_sha256"] = identity
        entries = manifest["files"]
        expected = {safe_name(row["path"]): row for row in entries}
        require(
            all(
                any(
                    name.startswith(prefix + "/")
                    for prefix in (*SOURCE_ROOTS, EVIDENCE)
                )
                and not excluded(name, manifest["phase"])
                for name in expected
            ),
            "Manifest member outside the declared evidence scope",
        )
        require(len(expected) == len(entries), "Duplicate declared file")
        seen = set()
        # Streaming iteration starts at the already consumed first member.
        for member in archive:
            if member.name == MANIFEST and member is first:
                continue
            name = safe_name(member.name)
            require(
                member.isfile() and name in expected and name not in seen,
                "Unexpected member, duplicate or link",
            )
            require(
                member.size == expected[name]["bytes"], "Archive member size mismatch"
            )
            with archive.extractfile(member) as stream:
                require(
                    hashlib.file_digest(stream, "sha256").hexdigest()
                    == expected[name]["sha256"],
                    "Archive member hash mismatch",
                )
            seen.add(name)
        require(seen == set(expected), "Archive is missing declared evidence")
    return {
        "status": "verified_bytes_no_scientific_rerun",
        "phase": manifest["phase"],
        "files": len(entries),
        "uncompressed_bytes": sum(row["bytes"] for row in entries),
        "manifest_identity_sha256": identity,
        "completion_gates": manifest["completion_gates"],
    }


def verify_tree(root):
    manifest = read(root, root / MANIFEST)
    identity = manifest.pop("identity_sha256")
    require(
        hashlib.sha256(encoded(manifest)).hexdigest() == identity,
        "Manifest identity changed",
    )
    for row in manifest["files"]:
        path = checked(root, row["path"])
        require(
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_size == row["bytes"],
            "Extracted member missing or size changed",
        )
        bound(root, path, row["sha256"], "Extracted member hash changed")
    require(
        inventory(root, manifest["phase"]) == manifest["files"],
        "Extracted in-scope inventory differs or contains extra evidence",
    )
    require(
        completion_gates(root, manifest["phase"]) == manifest["completion_gates"],
        "Extracted scientific completion bindings changed",
    )
    return {
        "status": "relocated_tree_verified",
        "files": len(manifest["files"]),
        "manifest_identity_sha256": identity,
    }


def create(root, output, phase):
    require(not output.exists(), "Never overwrite an evidence release")
    gates = completion_gates(root, phase)
    files = inventory(root, phase)
    manifest = {
        "schema": "hepta-new-execution-evidence-v1",
        "phase": phase,
        "new_execution": True,
        "historical_missing_raw_evidence_included": False,
        "source_roots": list(SOURCE_ROOTS),
        "evidence_root": EVIDENCE,
        "completion_gates": gates,
        "files": files,
    }
    manifest["identity_sha256"] = hashlib.sha256(encoded(manifest)).hexdigest()
    manifest_bytes = encoded(manifest) + b"\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        output.open("xb") as raw,
        gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz,
    ):
        with tarfile.open(fileobj=gz, mode="w|", format=tarfile.PAX_FORMAT) as archive:
            for row in [{"path": MANIFEST, "bytes": len(manifest_bytes)}, *files]:
                info = tarfile.TarInfo(row["path"])
                info.size, info.mode, info.mtime = row["bytes"], 0o644, 0
                stream = (
                    io.BytesIO(manifest_bytes)
                    if row["path"] == MANIFEST
                    else checked(root, row["path"]).open("rb")
                )
                with stream:
                    archive.addfile(info, stream)
    verified = verify_archive(output)
    require(
        inventory(root, phase) == files and completion_gates(root, phase) == gates,
        "Evidence changed during packaging; retained archive must not be published",
    )
    receipt = {
        **verified,
        "archive": output.name,
        "archive_bytes": output.stat().st_size,
        "archive_sha256": sha(output),
        "created_unix": time.time(),
        "packager_sha256": sha(Path(__file__)),
    }
    with output.with_suffix(output.suffix + ".receipt.json").open(
        "x", encoding="utf-8"
    ) as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    with output.with_suffix(output.suffix + ".manifest.json").open("xb") as stream:
        stream.write(manifest_bytes)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("create")
    pack.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    pack.add_argument("--output", type=Path, required=True)
    pack.add_argument("--phase", choices=("preregistration", "complete"), required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--archive", type=Path, required=True)
    tree = commands.add_parser("verify-tree")
    tree.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "create":
        result = create(args.root.resolve(), args.output.resolve(), args.phase)
    elif args.command == "verify":
        result = verify_archive(args.archive)
    else:
        result = verify_tree(args.root.resolve())
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
