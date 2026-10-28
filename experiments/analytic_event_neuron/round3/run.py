"""Execute the complete registered main study, retaining all outcomes and costs."""

import argparse
import json
from pathlib import Path
import shutil
import time

import numpy as np

from .. import task
from ..native_adapter import Native
from ..run import digest, save_data, write_json, write_rows
from ..round2.run import archive_scope
from ..round2.statistics import analysis_arrays
from ..transport import ArtifactTransport
from . import event_study, freeze


def execute_scope(run_dir, seed, law, native, protocol):
    from .audit import audit_scope

    run_dir = Path(run_dir)
    freeze.verify(run_dir)
    scope = f"seed_{seed}_{law}"
    directory = run_dir / "main" / "unpacked" / scope
    archive = run_dir / "main" / "archives" / (scope + ".tar.gz")
    analysis = run_dir / "main" / "analysis" / (scope + ".npz")
    report_dir = run_dir / "main" / "reports" / scope
    if any(path.exists() for path in (directory, archive, analysis, report_dir)):
        raise ValueError("Unindexed attempt retained; inspect before resuming: " + scope)
    directory.mkdir(parents=True, exist_ok=False)
    n = protocol["rows"]["confirmation" if law == "gaussian" else "each_mismatch"]
    data = task.build_dataset(protocol["data_offsets"][law] + seed, n, "confirmation", law)
    save_data(directory / "DATA.npz", data)
    write_json(directory / "DATASET.json", {"data_seed": data["seed"],
        "dataset_digest": task.dataset_digest(data), "npz_sha256": digest(directory / "DATA.npz")})
    shutil.copyfile(run_dir / "training" / f"seed_{seed}" / "MODELS.json", directory / "MODELS.json")
    models = json.loads((directory / "MODELS.json").read_text())
    transport = ArtifactTransport(directory / "transport", scope)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    calls, ticks, ipc = native.calls, native.original_sparse_ticks, native.wall_ns
    evaluated = event_study.confirm(models, data, native=native, transport=transport)
    transport_receipt = transport.save_receipts()
    execution = {"wall_ns": time.perf_counter_ns() - began,
        "parent_cpu_ns": time.process_time_ns() - cpu,
        "native_requests": native.calls - calls,
        "original_sparse_ticks": native.original_sparse_ticks - ticks,
        "native_ipc_wall_ns": native.wall_ns - ipc,
        "transport": transport_receipt, "evaluation": evaluated["accounting"]}
    for name in ("prediction", "control"):
        write_rows(directory / (name.upper() + ".jsonl"), evaluated[name]["rows"])
    write_json(directory / "SUMMARY.json", {name: evaluated[name]["summary"] for name in ("prediction", "control")})
    write_json(directory / "EXECUTION.json", execution)
    analysis.parent.mkdir(parents=True, exist_ok=True)
    arrays = analysis_arrays(evaluated["prediction"]["rows"], evaluated["control"]["rows"])
    for arm in sorted(models):
        selected = sorted((r for r in evaluated["control"]["rows"]
                           if r["arm"] == arm and "event_accounting" in r), key=lambda r: r["case"])
        if selected:
            for field in ("packet_bytes", "packets", "logical_unit_events", "refinement_packets", "precision_rebases"):
                arrays[f"{field}__{arm}"] = np.array([r["event_accounting"][field] for r in selected])
            arrays[f"uncertified_decisions__{arm}"] = np.array([
                sum(not s["event_certificate"]["certified"] for s in r["stages"]) for r in selected])
    np.savez_compressed(analysis, **arrays)
    calls, ticks, ipc = native.calls, native.original_sparse_ticks, native.wall_ns
    audit = audit_scope(directory, native=native)
    audit["native_replay_accounting"] = {"requests": native.calls - calls,
        "ticks": native.original_sparse_ticks - ticks, "ipc_wall_ns": native.wall_ns - ipc}
    write_json(directory / "AUDIT.json", audit)
    if not audit["passed"]:
        raise ValueError("Main confirmation replay failed: " + audit.get("error", "unknown"))
    report_dir.mkdir(parents=True, exist_ok=False)
    for name in ("SUMMARY.json", "EXECUTION.json", "AUDIT.json", "DATASET.json"):
        shutil.copy2(directory / name, report_dir / name)
    archived = archive_scope(directory, archive)
    freeze.verify(run_dir)
    return {"scope": scope, "seed": seed, "law": law, "data_seed": data["seed"],
        "unique_trajectories": n, "archive": str(archive.relative_to(run_dir)),
        "archive_receipt": archived, "analysis": str(analysis.relative_to(run_dir)),
        "analysis_sha256": digest(analysis), "audit_passed": audit["passed"],
        "scope_wall_ns_including_replay_and_archive": time.perf_counter_ns() - began}, directory


def confirm_all(run_dir, protocol, only_seed=None):
    run_dir = Path(run_dir)
    frozen = freeze.verify(run_dir)
    if protocol != json.loads((freeze.PROJECT / "PROTOCOL.json").read_text()):
        raise ValueError("Invocation protocol differs from the frozen registration")
    name = "RUN_INDEX.json" if only_seed is None else f"RUN_INDEX_seed_{only_seed}.json"
    index_path = run_dir / "main" / name
    index = json.loads(index_path.read_text()) if index_path.exists() else {
        "schema": "hepta.analytic-event.round3.main-index.v1", "source_commit": frozen["source_commit"],
        "scopes": [], "complete": False}
    seeds = protocol["training_seeds"] if only_seed is None else [only_seed]
    if any(seed not in protocol["training_seeds"] for seed in seeds):
        raise ValueError("Unregistered training seed")
    laws = [protocol["laws"]["primary"], *protocol["laws"]["mismatch"]]
    coordinates = [(entry["seed"], entry["law"]) for entry in index["scopes"]]
    allowed = {(seed, law) for seed in seeds for law in laws}
    if (index["source_commit"] != frozen["source_commit"]
            or len(coordinates) != len(set(coordinates)) or not set(coordinates).issubset(allowed)
            or any(entry["scope"] != f"seed_{entry['seed']}_{entry['law']}" for entry in index["scopes"])):
        raise ValueError("Mismatched or duplicated resumption index")
    with Native(run_dir / "native" / "analytic_event", run_dir / "native" / "BUILD_RECEIPT.json") as native:
        for seed in seeds:
            for law in laws:
                scope = f"seed_{seed}_{law}"
                prior = [x for x in index["scopes"] if x["scope"] == scope]
                if prior:
                    entry = prior[0]
                    if (digest(run_dir / entry["archive"]) != entry["archive_receipt"]["sha256"]
                            or digest(run_dir / entry["analysis"]) != entry["analysis_sha256"]):
                        raise ValueError("Previously completed evidence changed")
                    continue
                entry, unpacked = execute_scope(run_dir, seed, law, native, protocol)
                index["scopes"].append(entry)
                write_json(index_path, index)
                # Only our just-created, fully verified archival duplicate is removed.
                shutil.rmtree(unpacked)
                print(json.dumps({"phase": "main_confirmation", **entry}), flush=True)
    index["complete"] = len(index["scopes"]) == len(seeds) * len(laws)
    write_json(index_path, index)
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--only-seed", type=int)
    arguments = parser.parse_args()
    protocol = json.loads((freeze.PROJECT / "PROTOCOL.json").read_text())
    confirm_all(arguments.run_dir, protocol, arguments.only_seed)
