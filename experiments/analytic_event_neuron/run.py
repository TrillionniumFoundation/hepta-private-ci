"""Train, freeze, and execute the registered study with complete archived readbacks."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import sys
import tarfile
import time

import numpy as np

from . import experiment, statistics, task, train
from .native_adapter import Native
from .transport import ArtifactTransport

PROJECT = Path(__file__).resolve().parent


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def write_rows(path, rows):
    with Path(path).open("x") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")


def save_data(path, data):
    np.savez_compressed(path, **data)


def load_data(path):
    with np.load(path, allow_pickle=False) as archive:
        return {key: archive[key].item() if archive[key].ndim == 0 else archive[key]
                for key in archive.files}


def train_all(run_dir, native, protocol):
    run_dir.mkdir(parents=True, exist_ok=True)
    native_dir = run_dir / "native"
    native_dir.mkdir(exist_ok=True)
    shutil.copy2(native.binary, native_dir / "analytic_event")
    write_json(native_dir / "BUILD_RECEIPT.json", native.receipt)
    for seed in protocol["training_seeds"]:
        directory = run_dir / "training" / f"seed_{seed}"
        if directory.exists():
            raise ValueError("Training output exists; do not silently refit or replace a run")
        directory.mkdir(parents=True)
        training = task.build_dataset(10000 + seed, protocol["rows"]["train"], "train")
        development = task.build_dataset(20000 + seed, protocol["rows"]["development"], "development")
        save_data(directory / "TRAIN.npz", training)
        save_data(directory / "DEVELOPMENT.npz", development)
        began = time.perf_counter_ns()
        before_calls, before_ticks = native.calls, native.original_sparse_ticks
        models, receipt = train.fit_models(training, development, seed, native)
        receipt["total_training_wall_ns"] = time.perf_counter_ns() - began
        receipt["native_requests"] = native.calls - before_calls
        receipt["original_sparse_ticks"] = native.original_sparse_ticks - before_ticks
        write_json(directory / "MODELS.json", models)
        write_json(directory / "TRAINING.json", receipt)
        print(json.dumps({"phase": "training", "seed": seed, "models": list(models),
                          "optimizer_success": receipt["optimizer_success"],
                          "parameters": receipt["fitted_filter_parameters"]}), flush=True)


def freeze(run_dir, protocol, source_commit):
    if (run_dir / "FREEZE.json").exists():
        raise ValueError("Freeze is immutable; choose a new run directory")
    for seed in protocol["training_seeds"]:
        path = run_dir / "training" / f"seed_{seed}" / "MODELS.json"
        if "native" not in json.loads(path.read_text()):
            raise ValueError("The original native comparison must be trained")
        if "feedback_chain" in protocol and not (run_dir / "feedback_training" / f"seed_{seed}" / "MODELS.json").is_file():
            raise ValueError("The original feedback-chain heads must be trained before freeze")
    sources = sorted(path for path in PROJECT.iterdir()
                     if path.is_file() and path.suffix in (".py", ".rs", ".json", ".md", ".txt"))
    trained = sorted(path for parent in (run_dir / "training", run_dir / "native", run_dir / "feedback_training")
                     for path in parent.rglob("*") if path.is_file())
    receipt = {"schema": "hepta.analytic-event.freeze.v1",
               "created_utc": datetime.now(timezone.utc).isoformat(),
               "preconfirmation_source_commit": source_commit,
               "environment": {"python": sys.version, "platform": platform.platform(),
                               "packages": {name: importlib.metadata.version(name) for name in ("numpy", "scipy", "Pillow")}},
               "protocol_sha256": digest(PROJECT / "PROTOCOL.json"),
               "source_sha256": {str(path.relative_to(PROJECT)): digest(path) for path in sources},
               "trained_files_sha256": {str(path.relative_to(run_dir)): digest(path) for path in trained},
               "confirmation_generated_before_freeze": False}
    write_json(run_dir / "FREEZE.json", receipt)
    return receipt


def verify_freeze(run_dir, native=None):
    receipt = json.loads((run_dir / "FREEZE.json").read_text())
    for name, expected in receipt["source_sha256"].items():
        if digest(PROJECT / name) != expected:
            raise ValueError("Executable or registered source changed after freeze: " + name)
    for name, expected in receipt["trained_files_sha256"].items():
        if digest(run_dir / name) != expected:
            raise ValueError("Trained evidence changed after freeze: " + name)
    if native is not None and digest(native.binary) != receipt["trained_files_sha256"]["native/analytic_event"]:
        raise ValueError("Runtime binary differs from frozen training binary")
    return receipt


def archive_scope(directory, archive_path):
    """Verify every compressed member before removing only our unpacked copy."""
    files = sorted(path for path in directory.rglob("*") if path.is_file())
    manifest = {str(path.relative_to(directory)): digest(path) for path in files}
    write_json(directory / "ARCHIVE_MANIFEST.json", manifest)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz", compresslevel=6) as archive:
        for path in [*files, directory / "ARCHIVE_MANIFEST.json"]:
            archive.add(path, arcname=str(path.relative_to(directory)), recursive=False)
    checked = {}
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            if not member.isfile() or member.name == "ARCHIVE_MANIFEST.json":
                continue
            hasher = hashlib.sha256()
            stream = archive.extractfile(member)
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(block)
            checked[member.name] = hasher.hexdigest()
    if checked != manifest:
        raise ValueError("Archived bytes differ from the fully audited files")
    result = {"sha256": digest(archive_path), "file_count": len(manifest) + 1,
              "compressed_bytes": archive_path.stat().st_size, "all_member_hashes_verified": True}
    shutil.rmtree(directory)
    return result


def confirm(run_dir, native, protocol, resume=False):
    from .evidence_audit import audit_scope

    frozen = verify_freeze(run_dir, native)
    index_path = run_dir / "RUN_INDEX.json"
    if index_path.exists():
        if not resume:
            raise ValueError("Confirmation already started; pass --resume to retain and resume identical frozen models")
        index = json.loads(index_path.read_text())
        if index["freeze_sha256"] != digest(run_dir / "FREEZE.json"):
            raise ValueError("Cannot resume a different freeze")
    else:
        index = {"schema": "hepta.analytic-event.run.v1", "started_utc": datetime.now(timezone.utc).isoformat(),
                 "freeze_sha256": digest(run_dir / "FREEZE.json"), "scopes": [],
                 "preconfirmation_source_commit": frozen["preconfirmation_source_commit"]}
    write_json(index_path, index)
    for seed in protocol["training_seeds"]:
        models_path = run_dir / "training" / f"seed_{seed}" / "MODELS.json"
        models = json.loads(models_path.read_text())
        for law, offset in (("gaussian", 30000), ("drift_shift", 40000), ("student_t", 50000)):
            completed = [entry for entry in index["scopes"] if entry["training_seed"] == seed and entry["law"] == law]
            if completed:
                if (digest(run_dir / completed[0]["archive_path"]) != completed[0]["archive"]["sha256"]
                        or digest(run_dir / completed[0]["analysis_path"]) != completed[0]["analysis_sha256"]):
                    raise ValueError("Previously completed evidence has changed")
                continue
            started = time.perf_counter_ns()
            scope = f"seed_{seed}_{law}"
            directory = run_dir / "unpacked" / scope
            orphan_archive = run_dir / "archives" / (scope + ".tar.gz")
            if orphan_archive.exists():
                if not resume:
                    raise ValueError("Unindexed archive exists; explicit resume required")
                retained_archive = run_dir / "interrupted" / (scope + "_" + str(time.time_ns()) + ".tar.gz")
                retained_archive.parent.mkdir(exist_ok=True)
                orphan_archive.rename(retained_archive)
                index.setdefault("retained_interrupted_attempts", []).append(str(retained_archive.relative_to(run_dir)))
                write_json(index_path, index)
            if directory.exists():
                if not resume:
                    raise ValueError("Partial evidence exists; explicit resume required")
                retained = run_dir / "interrupted" / (scope + "_" + str(time.time_ns()))
                retained.parent.mkdir(exist_ok=True)
                directory.rename(retained)
                index.setdefault("retained_interrupted_attempts", []).append(str(retained.relative_to(run_dir)))
                write_json(index_path, index)
            directory.mkdir(parents=True, exist_ok=False)
            count = protocol["rows"]["confirmation" if law == "gaussian" else "each_mismatch"]
            data = task.build_dataset(offset + seed, count, "confirmation", law)
            save_data(directory / "DATA.npz", data)
            write_json(directory / "DATASET.json", {"dataset_digest": task.dataset_digest(data),
                       "npz_sha256": digest(directory / "DATA.npz"), "data_seed": offset + seed})
            shutil.copyfile(models_path, directory / "MODELS.json")
            transport = ArtifactTransport(directory / "transport", scope)
            before_calls, before_ticks, before_native_ns = native.calls, native.original_sparse_ticks, native.wall_ns
            prediction = experiment.evaluate_prediction(models, data, native)
            control = experiment.evaluate_control(models, data, native, transport.observer, transport.deliver)
            execution = {"evaluation_wall_ns": time.perf_counter_ns() - started,
                         "native_requests": native.calls - before_calls,
                         "original_sparse_ticks": native.original_sparse_ticks - before_ticks,
                         "native_roundtrip_ns": native.wall_ns - before_native_ns,
                         "actual_transport": transport.save_receipts(),
                         "private_target_first_read_after_final_delivery": control["private_target_first_read_after_final_delivery"]}
            write_rows(directory / "PREDICTION.jsonl", prediction["rows"])
            write_rows(directory / "CONTROL.jsonl", control["rows"])
            summary = {"prediction": prediction["summary"], "control": control["summary"]}
            write_json(directory / "SUMMARY.json", summary)
            write_json(directory / "EXECUTION.json", execution)
            arrays = statistics.analysis_arrays(prediction["rows"], control["rows"])
            analysis_path = Path("analysis") / (scope + ".npz")
            (run_dir / "analysis").mkdir(exist_ok=True)
            np.savez_compressed(run_dir / analysis_path, **arrays)
            audit_started = time.perf_counter_ns()
            audit = audit_scope(directory, native=native)
            audit["independent_audit_wall_ns"] = time.perf_counter_ns() - audit_started
            write_json(directory / "AUDIT.json", audit)
            if not audit.get("passed", False):
                raise RuntimeError("Independent evidence audit failed; all unpacked evidence is retained")
            write_json(run_dir / "scope_summaries" / (scope + ".json"),
                       {"summary": summary, "execution": execution, "audit": audit})
            archive_path = Path("archives") / (scope + ".tar.gz")
            archived = archive_scope(directory, run_dir / archive_path)
            entry = {"scope": scope, "training_seed": seed, "law": law, "data_seed": offset + seed,
                     "analysis_path": str(analysis_path), "analysis_sha256": digest(run_dir / analysis_path),
                     "archive_path": str(archive_path), "archive": archived,
                     "scope_wall_ns_including_audit_and_archive": time.perf_counter_ns() - started}
            index["scopes"].append(entry)
            write_json(index_path, index)
            print(json.dumps({"phase": "confirmation", **entry}), flush=True)
    index["completed_utc"] = datetime.now(timezone.utc).isoformat()
    index["complete"] = len(index["scopes"]) == 15
    write_json(index_path, index)
    verify_freeze(run_dir, native)
    write_json(run_dir / "RESULTS.json", statistics.summarize(run_dir, protocol))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("train", "freeze", "confirm", "summarize", "retention"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--native", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    protocol = json.loads((PROJECT / "PROTOCOL.json").read_text())
    if args.phase == "freeze":
        if not args.source_commit:
            parser.error("freeze requires the published source commit")
        print(json.dumps(freeze(args.run_dir, protocol, args.source_commit)), flush=True)
    elif args.phase == "summarize":
        verify_freeze(args.run_dir)
        write_json(args.run_dir / "RESULTS.json", statistics.summarize(args.run_dir, protocol))
    elif args.phase == "retention":
        from .retention import evaluate_retention
        verify_freeze(args.run_dir)
        evaluate_retention(args.run_dir, protocol)
    else:
        if args.native is None or args.receipt is None:
            parser.error("training and confirmation require the verified native executable and receipt")
        with Native(args.native, args.receipt) as native:
            if args.phase == "train":
                train_all(args.run_dir, native, protocol)
            else:
                confirm(args.run_dir, native, protocol, resume=args.resume)


if __name__ == "__main__":
    main()
