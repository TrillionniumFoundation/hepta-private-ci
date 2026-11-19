"""Retain original completed fits and account for the original owner window."""

import hashlib
import io
import json
from pathlib import Path
import resource
import tarfile
import time

ROOT = Path("/home/qian-qi/work/hepta-upstream-raw-function-learning-20261119-2e9b")
SOURCE = ROOT / "source/qualification/cell-upstream-raw-function-learning-20261119"
OUTPUT = ROOT / "training-publication-1"
MODES = ("document_evidence", "native_feedback")
FROZEN_SHA = "237ae92fc94d6ae411671c671190314049ded5cdc0d5dae254d57c9d8bb67be6"
PROTOCOL_SHA = "e5907ac5c963919d1a947df5274bb6e4a84565ab52f0478eabca91334b3739b5"
COMMIT = "2b85ea867e2749d4dc3bbb75ac16c9b5f9344f82"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    raw = value if isinstance(value, bytes) else canonical(value) + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(raw)
    return sha(raw)


def main():
    start, cpu = time.perf_counter(), time.process_time()
    OUTPUT.mkdir(exist_ok=False)
    assert sha((ROOT / "WEIGHTS_FROZEN.json").read_bytes()) == FROZEN_SHA
    assert sha((SOURCE / "prepared/PROTOCOL.json").read_bytes()) == PROTOCOL_SHA
    freeze = read(ROOT / "WEIGHTS_FROZEN.json")
    protocol = read(SOURCE / "prepared/PROTOCOL.json")
    owner = read(ROOT / "owned-training-1/COMPLETE.json")
    assert owner["status"] == "COMPLETE" and owner["actual_optimizer_updates"] == 64
    assert owner["actual_new_generations"] == 0 and owner["source_commit"] == COMMIT
    assert all(
        row["wait_returncode"] == 0 and not row["timed_out"]
        for row in owner["stage_exits"]
    )
    witness = read(ROOT / "publication-training-metadata-1/OWNER_TERMINAL.json")
    assert (
        witness["status"]["state"] == "exited" and witness["status"]["exit_code"] == 0
    )
    assert witness["status"]["output_complete"]
    files = {}

    def add(name, path, expected=None):
        path = Path(path)
        assert not path.is_symlink() and path.is_file(), path
        raw = path.read_bytes()
        if expected is not None:
            assert sha(raw) == expected, path
        assert name not in files
        files[name] = (path, raw)

    add("original/WEIGHTS_FROZEN.json", ROOT / "WEIGHTS_FROZEN.json", FROZEN_SHA)
    add(
        "original/OWNER_TERMINAL.json",
        ROOT / "publication-training-metadata-1/OWNER_TERMINAL.json",
    )
    add("original/DEPLOYMENT.json", ROOT / "DEPLOYMENT.json")
    for folder in (
        ROOT / "owned-training-1",
        ROOT / "monitor-training-1",
        ROOT / "retained/training",
    ):
        for path in sorted(folder.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                add("original/" + path.relative_to(ROOT).as_posix(), path)
    for name, expected in protocol["candidate_files"].items():
        add("execution-source/" + name, SOURCE / name, expected)
    for path in sorted((SOURCE / "prepared").iterdir()):
        if path.is_file():
            add("execution-source/prepared/" + path.name, path)
    for index, (path, expected) in enumerate(
        sorted(protocol["original_input_files"].items())
    ):
        add("bound-inputs/" + f"{index:03d}-" + Path(path).name, path, expected)
    add("postprocess/collect_training.py", Path(__file__))
    arms = {}
    keys = (
        "model_forwards",
        "model_backwards",
        "head_positions",
        "supervised_positions",
        "input_tokens",
        "padded_positions",
    )
    for mode in MODES:
        folder = ROOT / "retained/training" / mode
        fit = read(folder / "TRAINING.json")
        manifest = read(folder / "manifest.json")
        initial = read(folder / "INITIALIZATION.json")
        steps = [
            json.loads(line)
            for line in (folder / "STEPS.jsonl").read_bytes().splitlines()
        ]
        assert len(steps) == fit["steps"] == 32 and fit["status"] == "COMPLETE"
        assert (
            initial["optimizer_state_entries"] == 0
            and initial["resumed_existing_adapter"]
        )
        assert (
            initial["parameter_before"]
            == manifest["parameter_before"]
            == freeze["arms"][mode]["parameter_before"]
        )
        assert (
            sha((folder / "manifest.json").read_bytes())
            == freeze["arms"][mode]["manifest_sha256"]
        )
        assert (
            sha((folder / "TRAINING.json").read_bytes())
            == freeze["arms"][mode]["training_sha256"]
        )
        for key in keys:
            assert sum(row[key] for row in steps) == fit["cost"][key], (mode, key)
        inner_keys = {key for row in steps for key in row["inner_checkpoint_counts"]}
        counts = {
            key: sum(row["inner_checkpoint_counts"].get(key, 0) for row in steps)
            for key in inner_keys
        }
        assert counts == fit["cost"]["inner_checkpoint_counts"]
        by_task = {}
        for row in steps:
            by_task.setdefault(row["task_id"], []).append(row)
        arms[mode] = {
            "model_digest": fit["model_digest"],
            "parameter_before": manifest["parameter_before"],
            "parameter_after": manifest["parameter_after"],
            "manifest_sha256": sha((folder / "manifest.json").read_bytes()),
            "training_sha256": sha((folder / "TRAINING.json").read_bytes()),
            "actual_optimizer_updates": len(steps),
            "initial_optimizer_state_entries": 0,
            "cost": fit["cost"],
            "adapter_files": manifest["adapter_files"],
            "losses_by_task": {
                task: {
                    "steps": [row["step"] for row in rows],
                    "losses": [row["loss"] for row in rows],
                    "gradient_norm_before_clip": [
                        row["gradient_norm_before_clip"] for row in rows
                    ],
                }
                for task, rows in by_task.items()
            },
        }
    assert (
        freeze["arms"][MODES[0]]["step_shapes"]
        == freeze["arms"][MODES[1]]["step_shapes"]
    )
    assert (
        arms[MODES[0]]["cost"]["inner_checkpoint_counts"]
        == arms[MODES[1]]["cost"]["inner_checkpoint_counts"]
    )
    summary = {
        "schema": "hepta.raw-function-completed-training-evidence.v1",
        "status": "TWO_REAL_MATCHED_FITS_FROZEN",
        "execution_source_commit": COMMIT,
        "protocol_sha256": PROTOCOL_SHA,
        "weights_frozen_sha256": FROZEN_SHA,
        "weights_frozen_at_ns": freeze["created_at_ns"],
        "designated_candidate": "native_feedback",
        "control": "document_evidence",
        "arms": arms,
        "actual_total_optimizer_updates": 64,
        "actual_new_generations": 0,
        "actual_native_children": 0,
        "evaluation_started": False,
        "matched_fields": [
            "parent loaded parameters",
            "empty optimizer state",
            "original information digests",
            "target IDs",
            "optimizer steps",
            "padded complete-sequence F/B",
            "actual inner recompute counts",
        ],
        "unmatched_fields_reported": [
            "unpadded input positions",
            "wall time",
            "CPU time",
            "host-window energy",
        ],
        "physical_total_compute_equal": False,
        "full_system_cost_known": False,
        "old_NoUpdate_unchanged": True,
        "scientific_gain_claim": False,
        "native_adoption": False,
    }
    write(OUTPUT / "READOUT.json", summary)
    costs = {
        "schema": "hepta.raw-function-training-cost-ledger.v1",
        "execution_source_commit": COMMIT,
        "owner_window": owner,
        "original_child_fit_costs": {mode: arms[mode]["cost"] for mode in MODES},
        "model_F_B_counts_are_outer_calls_not_total_recomputed_work": True,
        "cold_loading_and_parameter_audit_in_original_owner_and_stage_wall": True,
        "CPU_energy_scope": "Whole-host two packages over 59 samples, including unrelated activity; no claim of model-only energy.",
        "gpu_energy_joules": None,
        "network_energy_joules": None,
        "monetary_cost": None,
        "full_system_cost_known": False,
        "nested_windows_not_additive": True,
        "earlier_experiments_and_failures_retained_in_their_original_cost_ledgers_not_erased_or_double_added": True,
        "collection_self_wall_seconds_so_far": time.perf_counter() - start,
        "collection_self_cpu_seconds_so_far": time.process_time() - cpu,
        "collection_new_generations": 0,
        "collection_new_native_children": 0,
    }
    write(OUTPUT / "COST_LEDGER.json", costs)
    add("READOUT.json", OUTPUT / "READOUT.json")
    add("COST_LEDGER.json", OUTPUT / "COST_LEDGER.json")
    index = {
        "schema": "hepta.original-evidence-index.v1",
        "entries": [
            {
                "member": name,
                "original_path": str(path),
                "bytes": len(raw),
                "sha256": sha(raw),
            }
            for name, (path, raw) in sorted(files.items())
        ],
        "derived_pycache_omitted": True,
    }
    write(OUTPUT / "INDEX.json", index)
    archive = OUTPUT / "TRAINING_EVIDENCE.tar.xz"
    with tarfile.open(archive, "w:xz", preset=6) as stream:
        for name, (_, raw) in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(raw), 0o444, 0
            stream.addfile(info, io.BytesIO(raw))
    with tarfile.open(archive, "r:xz") as stream:
        assert stream.getnames() == sorted(files)
        for item in index["entries"]:
            raw = stream.extractfile(item["member"]).read()
            assert len(raw) == item["bytes"] and sha(raw) == item["sha256"]
    final = {
        "status": "COMPLETE",
        "archive_path": str(archive),
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": sha(archive.read_bytes()),
        "member_count": len(files),
        "uncompressed_bytes": sum(len(raw) for _, raw in files.values()),
        "index_sha256": sha((OUTPUT / "INDEX.json").read_bytes()),
        "readout_sha256": sha((OUTPUT / "READOUT.json").read_bytes()),
        "cost_ledger_sha256": sha((OUTPUT / "COST_LEDGER.json").read_bytes()),
        "wall_seconds": time.perf_counter() - start,
        "self_cpu_seconds": time.process_time() - cpu,
        "new_model_calls": 0,
        "new_native_children": 0,
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    write(OUTPUT / "ARCHIVE.json", final)
    print(json.dumps(final, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
