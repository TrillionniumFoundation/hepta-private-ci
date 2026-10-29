"""Train one frozen-protocol arm without opening held wording or outcomes."""

import argparse
import json
import os
from pathlib import Path
import platform
import resource
import sys
import time

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "memory-cell-adapters"))

from corpus import POLICIES, bits
from structure_models import ARMS, Structure, canonical, digest, fit
from tensor_cell import TensorCell


def phases():
    values = [list(row) for row in POLICIES]
    result = []
    for number, changes in enumerate((((0, 0, 3), (1, 0, 3)), ((4, 1, 2),), ((2, 2, 5),)), 1):
        for entity, field, increment in changes:
            values[entity][field] = (values[entity][field] + increment) % 16
        result.append({"phase": number, "changed_entities": sorted({x[0] for x in changes}),
                       "policies": [list(row) for row in values]})
    return result


def run(args):
    began, cpu = time.perf_counter(), time.process_time()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    if hasattr(os, "sched_setaffinity"):
        available = sorted(os.sched_getaffinity(0))
        os.sched_setaffinity(0, {available[0]})
    protocol = json.loads(args.protocol.read_bytes())
    data = json.loads((args.fixture / "development.json").read_bytes())
    identity = json.loads((args.fixture / "development-encoder.json").read_bytes())["base_encoder_sha"]
    with np.load(args.fixture / "development_features.npz", allow_pickle=False) as archive:
        selected = [i for i, row in enumerate(data["train"]) if row["role"] == "semantic"]
        features = np.concatenate([archive["semantic"], archive["train"][selected]])
        canonical_features = archive["semantic"].copy()
    entities = np.asarray(list(range(8)) + [data["train"][i]["entity"] for i in selected], dtype=np.int64)
    x = torch.from_numpy(features)
    addresses = torch.from_numpy(entities)
    parent_path = args.fixture / "models" / f"seed-{args.seed}" / "semantic"
    parent_manifest = json.loads((parent_path / "manifest.json").read_bytes())
    parent = TensorCell.load(parent_path, identity)
    structure = Structure(parent, args.arm)
    with torch.no_grad():
        parent_raw = parent(torch.from_numpy(canonical_features))
        initial = structure(torch.from_numpy(canonical_features), torch.arange(8))
        initial_error = float((initial - parent_raw).abs().max())
    initial_typed_equal = torch.equal(initial.sigmoid() >= 0.5, parent_raw.sigmoid() >= 0.5)
    if not torch.allclose(initial, parent_raw, rtol=1e-5, atol=1e-5) or not initial_typed_equal:
        raise ValueError("comparator changed the initial parent function")
    args.output.mkdir(parents=True, exist_ok=False)
    records = []
    for phase in phases():
        target = torch.tensor([bits(phase["policies"][i]) for i in entities], dtype=torch.float32)
        stage_cpu, stage_wall = time.process_time(), time.perf_counter()
        route = structure.propose_routes(x, target, addresses)
        budget = protocol["cpu_budget_seconds_per_phase"] if args.regime == "cpu_budget" else None
        steps = protocol["maximum_steps"] if budget is not None else protocol["matched_steps"]
        receipt = fit(structure, x, target, addresses, seed=args.seed + phase["phase"],
                      steps=steps, batch_size=protocol["batch_size"],
                      learning_rate=protocol["learning_rate"], cpu_budget_seconds=budget,
                      budget_started=stage_cpu)
        source_digest = digest(canonical(phase))
        for cell in structure.cells:
            cell.source_ids.add(source_digest)
        checkpoint = args.output / f"phase-{phase['phase']}"
        storage = structure.save(checkpoint)
        reload_start = time.perf_counter()
        restored = Structure.load(checkpoint, identity)
        with torch.no_grad():
            before = structure(x, addresses)
            after = restored(x, addresses)
            reload_error = float((before - after).abs().max())
        if reload_error != 0:
            raise ValueError("checkpoint restore changed predictions")
        records.append({"phase": phase["phase"], "source_sha256": source_digest,
                        "source_records": phase, "selector": route, "fit": receipt,
                        "storage": storage, "restored_max_abs_error": reload_error,
                        "restore_and_compare_wall_seconds": time.perf_counter() - reload_start,
                        "phase_cpu_seconds": time.process_time() - stage_cpu,
                        "phase_wall_seconds": time.perf_counter() - stage_wall})
        structure = restored
    report = {"schema": "hepta.structure-stream-training.v1", "arm": args.arm,
              "regime": args.regime, "seed": args.seed, "pid": os.getpid(),
              "initial_parent_max_abs_error": initial_error,
              "initial_typed_outputs_equal": initial_typed_equal,
              "base_encoder_sha": identity, "parent_parameter_sha256": parent.parameter_digest(),
              "counts": structure.counts(), "phases": records,
              "training_features_sha256": digest(features.astype("<f4").tobytes()),
              "training_addresses_sha256": digest(entities.astype("<i8").tobytes()),
              "protocol_sha256": digest(args.protocol.read_bytes()), "held_file_opened": False,
              "environment": {"python": platform.python_version(), "torch": torch.__version__,
                              "numpy": np.__version__, "platform": platform.platform(),
                              "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None},
              "common_parent_training": parent_manifest["training_history"],
              "total_cpu_seconds": time.process_time() - cpu,
              "total_wall_seconds": time.perf_counter() - began,
              "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "stored_bytes": sum(p.stat().st_size for p in args.output.rglob("*") if p.is_file())}
    (args.output / "TRAINING.json").write_bytes(canonical(report))
    print(json.dumps({"arm": args.arm, "regime": args.regime, "seed": args.seed,
                      "counts": report["counts"], "cpu_seconds": report["total_cpu_seconds"]}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--arm", choices=ARMS, required=True)
    parser.add_argument("--regime", choices=("matched_exposure", "cpu_budget"), required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
