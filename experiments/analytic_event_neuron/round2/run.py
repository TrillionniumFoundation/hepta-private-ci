"""Second-round train/freeze/confirm driver with complete retained execution evidence."""

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import sys
import tarfile
import time

import numpy as np

from .. import task, train
from ..native_adapter import Native
from ..run import digest, load_data, save_data, write_json, write_rows
from ..transport import ArtifactTransport
from . import audit, evaluation, statistics

PROJECT = Path(__file__).resolve().parent
REPO = PROJECT.parents[2]
BASE = PROJECT.parent


def train_all(run_dir, native, protocol):
    from .pulse import fit_event_models

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    binary_dir = run_dir / "native"
    binary_dir.mkdir(exist_ok=True)
    shutil.copy2(native.binary, binary_dir / "analytic_event")
    write_json(binary_dir / "BUILD_RECEIPT.json", native.receipt)
    write_json(binary_dir / "REUSE_RECEIPT.json", {
        "original_build_commit": protocol["base_commit"],
        "binary_sha256": digest(native.binary),
        "current_session_fresh_build": False,
        "source": "Verified prior native archive; original exact-source build receipt retained",
    })
    for seed in protocol["training_seeds"]:
        directory = run_dir / "training" / f"seed_{seed}"
        directory.mkdir(parents=True, exist_ok=False)
        training = task.build_dataset(protocol["data_offsets"]["train"] + seed,
                                      protocol["rows"]["train"], "train")
        development = task.build_dataset(protocol["data_offsets"]["development"] + seed,
                                         protocol["rows"]["development"], "development")
        save_data(directory / "TRAIN.npz", training)
        save_data(directory / "DEVELOPMENT.npz", development)
        started, cpu = time.perf_counter_ns(), time.process_time_ns()
        calls, ticks, rpc = native.calls, native.original_sparse_ticks, native.wall_ns
        models, receipt = train.fit_models(training, development, seed, native)
        write_json(directory / "BASE_TRAINING.json", receipt)
        additions, selection = fit_event_models(models, development, driver_training_receipt=receipt)
        models.update(additions)
        receipt["baseline_models_sha256"] = receipt["model_sha256"]
        receipt["model_sha256"] = train._digest(models)
        receipt["event_driver_receipt_file"] = "BASE_TRAINING.json"
        receipt.update(total_training_wall_ns=time.perf_counter_ns() - started,
                       total_training_parent_cpu_ns=time.process_time_ns() - cpu,
                       native_requests=native.calls - calls,
                       original_sparse_ticks=native.original_sparse_ticks - ticks,
                       native_roundtrip_ns=native.wall_ns - rpc,
                       second_round_event_selection=selection)
        if not receipt["optimizer_success"] or not receipt["native_baseline_trained"]:
            raise RuntimeError("Training qualification failed; retain this attempt")
        write_json(directory / "MODELS.json", models)
        write_json(directory / "TRAINING.json", receipt)
        print(json.dumps({"phase": "training", "seed": seed, "arms": list(models),
                          "filter_parameters": receipt["fitted_filter_parameters"]}), flush=True)


def source_paths():
    old = [path for path in BASE.iterdir()
           if path.is_file() and path.suffix in {".py", ".rs", ".md", ".json", ".txt"}]
    new = [path for path in PROJECT.iterdir()
           if path.is_file() and path.suffix in {".py", ".rs", ".md", ".json", ".txt"}]
    return sorted(old + new)


def freeze(run_dir, protocol, source_commit):
    run_dir = Path(run_dir)
    if (run_dir / "FREEZE.json").exists():
        raise ValueError("Freeze is immutable")
    for seed in protocol["training_seeds"]:
        models = json.loads((run_dir / "training" / f"seed_{seed}" / "MODELS.json").read_text())
        if not {"native", "event_feedback", "event_direct", "event_no_residual"}.issubset(models):
            raise ValueError("Required trained controls are missing")
        if not (run_dir / "feedback_training" / f"seed_{seed}" / "MODELS.json").is_file():
            raise ValueError("Feedback training must precede freeze")
    if not (run_dir / "retention_prepared" / "PREPARED.json").is_file():
        raise ValueError("All causal retention checkpoints must precede confirmation")
    artifacts = sorted(path for parent in (run_dir / "training", run_dir / "native",
        run_dir / "feedback_training", run_dir / "retention_prepared")
        for path in parent.rglob("*") if path.is_file())
    receipt = {
        "schema": "hepta.analytic-event.round2.freeze.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "base_commit": protocol["base_commit"], "source_commit": source_commit,
        "protocol_sha256": digest(PROJECT / "PROTOCOL.json"),
        "sources_sha256": {str(path.relative_to(REPO)): digest(path) for path in source_paths()},
        "artifacts_sha256": {str(path.relative_to(run_dir)): digest(path) for path in artifacts},
        "environment": {"python": sys.version, "platform": platform.platform(),
            "packages": {name: importlib.metadata.version(name) for name in ("numpy", "scipy", "Pillow")}},
        "confirmation_generated_before_freeze": False,
        "prior_confirmation_not_used_as_new_development": True,
    }
    write_json(run_dir / "FREEZE.json", receipt)
    return receipt


def verify_freeze(run_dir, native=None):
    run_dir = Path(run_dir)
    frozen = json.loads((run_dir / "FREEZE.json").read_text())
    for key, root in (("sources_sha256", REPO), ("artifacts_sha256", run_dir)):
        for name, expected in frozen[key].items():
            path = (root / name).resolve()
            if not path.is_relative_to(root.resolve()) or digest(path) != expected:
                raise ValueError("Frozen bytes changed: " + name)
    if native is not None and digest(native.binary) != frozen["artifacts_sha256"]["native/analytic_event"]:
        raise ValueError("Native binary differs from training")
    return frozen


def archive_scope(directory, archive_path):
    """Verify every member, leaving deletion until after durable index publication."""
    files = sorted(path for path in directory.rglob("*") if path.is_file()
                   and path.name != "ARCHIVE_MANIFEST.json")
    manifest = {str(path.relative_to(directory)): digest(path) for path in files}
    write_json(directory / "ARCHIVE_MANIFEST.json", manifest)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz", compresslevel=6) as archive:
        for path in [*files, directory / "ARCHIVE_MANIFEST.json"]:
            archive.add(path, arcname=str(path.relative_to(directory)), recursive=False)
    import hashlib

    with tarfile.open(archive_path, "r:gz") as archive:
        checked = {member.name: hashlib.sha256(archive.extractfile(member).read()).hexdigest()
                   for member in archive if member.isfile() and member.name != "ARCHIVE_MANIFEST.json"}
    if checked != manifest:
        raise ValueError("Archive member mismatch")
    return {"sha256": digest(archive_path), "file_count": len(manifest) + 1,
            "compressed_bytes": archive_path.stat().st_size, "all_member_hashes_verified": True}


def execute_scope(run_dir, scope, data, models_path, native):
    directory = Path(run_dir) / "unpacked" / scope
    directory.mkdir(parents=True, exist_ok=False)
    save_data(directory / "DATA.npz", data)
    write_json(directory / "DATASET.json", {"dataset_digest": task.dataset_digest(data),
        "npz_sha256": digest(directory / "DATA.npz"), "data_seed": int(data["seed"])})
    shutil.copyfile(models_path, directory / "MODELS.json")
    models = json.loads(Path(models_path).read_text())
    transport = ArtifactTransport(directory / "transport", scope)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    calls, ticks, rpc = native.calls, native.original_sparse_ticks, native.wall_ns
    prediction = evaluation.evaluate_prediction(models, data, native)
    control = evaluation.evaluate_control(models, data, native, transport.observer, transport.deliver)
    execution = {"evaluation_wall_ns": time.perf_counter_ns() - started,
        "evaluation_parent_cpu_ns": time.process_time_ns() - cpu,
        "native_requests": native.calls - calls, "original_sparse_ticks": native.original_sparse_ticks - ticks,
        "native_roundtrip_ns": native.wall_ns - rpc, "actual_transport": transport.save_receipts(),
        "private_target_first_read_after_final_delivery": control["private_target_first_read_after_final_delivery"]}
    write_rows(directory / "PREDICTION.jsonl", prediction["rows"])
    write_rows(directory / "CONTROL.jsonl", control["rows"])
    summary = {"prediction": prediction["summary"], "control": control["summary"]}
    write_json(directory / "SUMMARY.json", summary)
    write_json(directory / "EXECUTION.json", execution)
    arrays = statistics.analysis_arrays(prediction["rows"], control["rows"])
    analysis_path = Path(run_dir) / "analysis" / (scope + ".npz")
    analysis_path.parent.mkdir(exist_ok=True)
    np.savez_compressed(analysis_path, **arrays)
    audited = audit.audit_scope(directory, native=native)
    write_json(directory / "AUDIT.json", audited)
    if not audited.get("passed"):
        raise RuntimeError("Independent replay failed: " + str(audited))
    write_json(Path(run_dir) / "scope_summaries" / (scope + ".json"),
               {"summary": summary, "execution": execution, "audit": audited})
    return directory, analysis_path, audited


def confirm(run_dir, native, protocol):
    run_dir = Path(run_dir)
    frozen = verify_freeze(run_dir, native)
    index_path = run_dir / "RUN_INDEX.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {
        "schema": "hepta.analytic-event.round2.run.v1", "scopes": [],
        "freeze_sha256": digest(run_dir / "FREEZE.json"), "source_commit": frozen["source_commit"],
        "started_utc": datetime.now(timezone.utc).isoformat(),
    }
    if index["freeze_sha256"] != digest(run_dir / "FREEZE.json"):
        raise ValueError("Run/freeze mismatch")
    write_json(index_path, index)
    for seed in protocol["training_seeds"]:
        for law in [protocol["laws"]["primary"], *protocol["laws"]["mismatch"]]:
            scope = f"seed_{seed}_{law}"
            previous = [row for row in index["scopes"] if row["scope"] == scope]
            if previous:
                row = previous[0]
                if digest(run_dir / row["archive_path"]) != row["archive"]["sha256"] or digest(
                        run_dir / row["analysis_path"]) != row["analysis_sha256"]:
                    raise ValueError("Completed evidence changed")
                continue
            if (run_dir / "unpacked" / scope).exists() or (run_dir / "archives" / (scope + ".tar.gz")).exists():
                raise ValueError("Unindexed attempt retained; inspect and recover before resuming: " + scope)
            started = time.perf_counter_ns()
            seed_data = protocol["data_offsets"][law] + seed
            count = protocol["rows"]["confirmation" if law == "gaussian" else "each_mismatch"]
            data = task.build_dataset(seed_data, count, "confirmation", law)
            directory, analysis_path, audited = execute_scope(run_dir, scope, data,
                run_dir / "training" / f"seed_{seed}" / "MODELS.json", native)
            archive_path = Path("archives") / (scope + ".tar.gz")
            archived = archive_scope(directory, run_dir / archive_path)
            entry = {"scope": scope, "training_seed": seed, "law": law, "data_seed": seed_data,
                "analysis_path": str(analysis_path.relative_to(run_dir)), "analysis_sha256": digest(analysis_path),
                "archive_path": str(archive_path), "archive": archived,
                "scope_wall_ns_including_audit_and_archive": time.perf_counter_ns() - started,
                "audit_passed": audited["passed"]}
            index["scopes"].append(entry)
            write_json(index_path, index)
            try:
                shutil.rmtree(directory)
            except OSError as error:
                index.setdefault("cleanup_only_incidents", []).append({"scope": scope, "error": str(error)})
                write_json(index_path, index)
            print(json.dumps({"phase": "confirmation", **entry}), flush=True)
    index.update(complete=len(index["scopes"]) == len(protocol["training_seeds"]) * 3,
                 completed_utc=datetime.now(timezone.utc).isoformat())
    write_json(index_path, index)
    verify_freeze(run_dir, native)
    write_json(run_dir / "RESULTS.json", statistics.summarize(run_dir, protocol))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("train", "freeze", "confirm", "verify"))
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    protocol = json.loads((PROJECT / "PROTOCOL.json").read_text())
    if args.phase == "freeze":
        if not args.source_commit:
            parser.error("freeze requires --source-commit")
        print(json.dumps(freeze(args.run_dir, protocol, args.source_commit)))
    elif args.phase == "verify":
        result = audit.audit_freeze(args.run_dir, REPO)
        print(json.dumps(result))
        if not result["passed"]:
            raise SystemExit(1)
    else:
        with Native(BASE / "evidence/native/analytic_event", BASE / "evidence/native/BUILD_RECEIPT.json") as native:
            if args.phase == "train":
                train_all(args.run_dir, native, protocol)
            else:
                confirm(args.run_dir, native, protocol)


if __name__ == "__main__":
    main()
