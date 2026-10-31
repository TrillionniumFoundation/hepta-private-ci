"""Freeze all new generators before the shared, untouched 256-source evaluation."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
import torch

from ...abc_recovery.base_recovery import file_sha, write_json
from ...abc_next.compact_tree import decode_media, encode_media
from ...abc_next.settings import CACHE, MANIFEST, REPO, SEEDS, model_path, observers, OBSERVER_SHA
from ...v6.data import Observation, Target
from ...v6.neural import parameter_hash
from ...v6.observer import observe_tensors
from ...v7.data import VIEWS, make_batch
from ...v7.snapshot import Snapshot
from ...v7.sources import load_roles
from .objective import ARMS
from .train import PLAN, RUNS, fixed_run, source_pins as training_pins, verify as verify_training


ALL_ARMS = (*ARMS, "warm_mean")
METRICS = ("utility", "success", "joint_loss", "complete")
ALLOCATION = Path(__file__).parents[1] / "control/SOURCE_ALLOCATION.json"


def source_pins():
    pins = training_pins()
    for path in (Path(__file__), Path(__file__).with_name("analysis.py"),
                 Path(__file__).parents[2] / "abc_recovery/statistics.py"):
        pins[str(path.relative_to(REPO))] = file_sha(path)
    return pins


def allocation_identity():
    allocation = json.loads(ALLOCATION.read_text())
    manifest = json.loads(MANIFEST.read_text())
    selected = allocation["groups"]["control_and_generator_final"]
    ids = manifest["roles"]["test"]["source_ids"][1024:1536]
    identity = hashlib.sha256("\n".join(ids).encode()).hexdigest()
    if (selected["pair_start"] != 512 or selected["source_pairs"] != 256
            or len(set(ids)) != 512 or selected["ordered_source_ids_sha256"] != identity
            or any(r["individual_id_overlap"] or r["pixel_hash_overlap"] for r in allocation["disjointness"])
            or allocation["manifest_sha256"] != file_sha(MANIFEST)):
        raise ValueError("Prospective source allocation does not match the actual identities")
    return selected


def freeze(training_protocol, destination):
    protocol = json.loads(training_protocol.read_text())
    verify_training(protocol)
    result_path = Path(protocol["output"]) / "result.json"
    trained = json.loads(result_path.read_text())
    if trained["status"] != "completed" or trained["protocol_sha256"] != file_sha(training_protocol):
        raise ValueError("All new generator training must finish under its original freeze")
    expected = {(s, a) for s in SEEDS for a in ARMS}
    seen, models = set(), []
    for row in trained["models"]:
        key = row["seed"], row["arm"]
        if key not in expected or key in seen or file_sha(Path(row["model_path"])) != row["model_file_sha256"]:
            raise ValueError("Missing, duplicate or changed new generator")
        seen.add(key)
        models.append({"seed": row["seed"], "arm": row["arm"],
            "path": row["model_path"], "sha256": row["model_file_sha256"]})
    if seen != expected:
        raise ValueError("New generator census is incomplete")
    for seed in SEEDS:
        path = model_path(seed, "output_mean")
        models.append({"seed": seed, "arm": "warm_mean", "path": str(path), "sha256": file_sha(path)})
    identity = allocation_identity()
    write_json(destination, {"schema": "hepta.abc4.training-evaluation-freeze.v1",
        "frozen_unix_ns": time.time_ns(), "training_protocol": str(training_protocol.resolve()),
        "training_protocol_sha256": file_sha(training_protocol), "training_result_sha256": file_sha(result_path),
        "new_training_steps_per_model": protocol["steps"],
        "source_pins": source_pins(), "source_allocation_sha256": file_sha(ALLOCATION),
        "source_identity": identity, "manifest_sha256": file_sha(MANIFEST),
        "role": "test", "start": 512, "count": 256, "scenarios": 2,
        "seeds": SEEDS, "views": VIEWS, "arms": ALL_ARMS, "models": models,
        "observer_sha256": OBSERVER_SHA, "plan": PLAN, "gamma": 2.,
        "output": str(RUNS / "evaluation-001"),
        "primary": {"candidate": "risk_success", "reference": "mean",
            "endpoints": ["raw_joint_CE_gain", "exact_success_difference"],
            "nominal_confidence_each": .975,
            "gate": "CE lower endpoint > 0 AND success lower endpoint >= 0; zero tolerance margin"},
        "descriptive": "other training contrasts, secondary observer, view metrics and empirical tails",
        "bootstrap": {"replicates": 4000, "seed": 2026102519,
            "axes": "paired source and training-seed axes; all views/scenarios kept together",
            "fixed_five_seed_source_only_also_reported": True},
        "constraint_reference": "frozen warm mean is the optimization floor; final strong reference is separately trained mean continuation",
        "cost_scope": "training costs fully measured; evaluation is batched actual generation, not a resident single-request latency claim",
        "shared_final_sources_with_control": True, "shared_sources_add_no_independent_N": True,
        "outcome_dependent_selection_or_refitting_allowed": False,
        "formal_holdout_opened": False, "large_raw_archive_required": False})
    print(json.dumps({"protocol": str(destination), "sha256": file_sha(destination), "models": len(models)}), flush=True)


def verify(protocol):
    if (protocol["schema"] != "hepta.abc4.training-evaluation-freeze.v1"
            or protocol["source_pins"] != source_pins()
            or protocol["source_allocation_sha256"] != file_sha(ALLOCATION)
            or protocol["source_identity"] != allocation_identity()
            or protocol["manifest_sha256"] != file_sha(MANIFEST)
            or protocol["observer_sha256"] != OBSERVER_SHA
            or tuple(protocol["seeds"]) != SEEDS or tuple(protocol["arms"]) != ALL_ARMS
            or tuple(protocol["views"]) != VIEWS or tuple(protocol["plan"]) != PLAN
            or (protocol["role"], protocol["start"], protocol["count"], protocol["scenarios"]) != ("test", 512, 256, 2)):
        raise ValueError("Frozen evaluation identity changed")
    expected = {(s, a) for s in SEEDS for a in ALL_ARMS}
    actual = [(r["seed"], r["arm"]) for r in protocol["models"]]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("Frozen model census differs")
    training_path = Path(protocol["training_protocol"])
    if file_sha(training_path) != protocol["training_protocol_sha256"]:
        raise ValueError("Training protocol changed")
    original = json.loads(training_path.read_text())
    if file_sha(Path(original["output"]) / "result.json") != protocol["training_result_sha256"]:
        raise ValueError("Completed training identity changed")
    for row in protocol["models"]:
        if file_sha(Path(row["path"])) != row["sha256"]:
            raise ValueError("Frozen generator changed")


@torch.inference_mode()
def evaluate_model(row, protocol, corpus, judges, directory):
    directory.mkdir(parents=True, exist_ok=False)
    snapshot = Snapshot.load(row["path"], expected_file_sha256=row["sha256"])
    count, draws = protocol["count"], protocol["scenarios"]
    data = {f"{name}/{metric}": [] for name in judges for metric in METRICS}
    raw_hashes = {}
    for view_index, view in enumerate(protocol["views"]):
        batch_seed = 202610290000 + protocol["start"]
        batch = make_batch(corpus, protocol["role"], count, batch_seed,
                           view=view, offset=protocol["start"])
        observation = Observation(*(x.repeat_interleave(draws, 0) for x in
            (batch.observation.pixels, batch.observation.mask, batch.observation.text_tokens)))
        target = Target(*(x.repeat_interleave(draws, 0) for x in
            (batch.target.pixels, batch.target.text_tokens, batch.target.labels)))
        run = fixed_run(snapshot._model, observation, 202610300000 + row["seed"] * 1009 + view_index)
        bits, tokens, hashes = encode_media(run.pixels, run.tokens)
        path = directory / (view + ".npz")
        with path.open("xb") as stream:
            np.savez_compressed(stream, bits=bits, tokens=tokens, hashes=hashes)
            stream.flush(); os.fsync(stream.fileno())
        with np.load(path, allow_pickle=False) as saved:
            pixels, _, captions = decode_media(saved["bits"], saved["tokens"], saved["hashes"])
        raw_hashes[path.name] = file_sha(path)
        for name, judge in judges.items():
            scores = observe_tensors(judge, pixels, captions, target.pixels, target.labels)
            success = [r["caption_valid"] and all(r[k] == 0 for k in
                ("text_fact", "relation", "image_fact", "crossmodal_disagreement")) for r in scores]
            values = {"utility": [r["utility"] for r in scores], "success": success,
                "joint_loss": [r["joint_loss"] for r in scores], "complete": [bool(t.strip()) for t in captions]}
            for metric in METRICS:
                data[f"{name}/{metric}"].append(np.asarray(values[metric], dtype=np.float64).reshape(count, draws))
    arrays = {k: np.stack(v, axis=1) for k, v in data.items()}
    np.savez_compressed(directory / "data.npz", **arrays)
    snapshot.verify_integrity()
    report = {**row, "data_file": str(directory / "data.npz"),
        "data_sha256": file_sha(directory / "data.npz"), "raw_sha256": raw_hashes,
        "shape_per_metric": [count, len(protocol["views"]), draws],
        "rows": count * len(protocol["views"]) * draws}
    write_json(directory / "result.json", report)
    return report


def run(protocol_path):
    protocol = json.loads(protocol_path.read_text())
    verify(protocol)
    directory = Path(protocol["output"])
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "access-registration.json", {"unix_ns": time.time_ns(),
        "protocol_sha256": file_sha(protocol_path), "source_identity": protocol["source_identity"],
        "role": "test", "start": 512, "count": 256})
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    entries = []
    try:
        torch.set_num_threads(2)
        corpus = load_roles(CACHE, MANIFEST, roles=("test",))
        judges = observers()
        before = {k: parameter_hash(v) for k, v in judges.items()}
        for row in protocol["models"]:
            entries.append(evaluate_model(row, protocol, corpus, judges,
                directory / f"seed-{row['seed']}" / row["arm"]))
            print(json.dumps({"completed": len(entries), "seed": row["seed"], "arm": row["arm"]}), flush=True)
        verify(protocol)
        if before != {k: parameter_hash(v) for k, v in judges.items()}:
            raise ValueError("Offline observers changed")
        write_json(directory / "result.json", {"schema": "hepta.abc4.training-evaluation-result.v1",
            "status": "completed", "protocol_sha256": file_sha(protocol_path), "models": entries,
            "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
            "source_identity": protocol["source_identity"], "outcomes_used_for_selection": False})
    except BaseException as error:
        write_json(directory / "failure.json", {"error": repr(error), "completed_models": len(entries)})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "run"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--training-protocol", type=Path,
        default=Path(__file__).with_name("TRAINING_PROTOCOL.json"))
    args = parser.parse_args()
    freeze(args.training_protocol, args.protocol) if args.phase == "freeze" else run(args.protocol)
