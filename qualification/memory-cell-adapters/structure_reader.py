"""Fresh-process structure reads from persisted tensors and value-free routing."""

import json
import os
from pathlib import Path
import resource
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import torch

from runtime_contract import canonical, decode_bits, digest
from tensor_cell import TensorCell, unique_parameter_count


def run(request):
    began, cpu = time.perf_counter_ns(), time.process_time()
    if set(request) != {"model_root", "encoder_sha", "canonical_features_path"}:
        raise ValueError("structure reader accepts only model, encoder and feature identities")
    torch.set_num_threads(1)
    root = Path(request["model_root"])
    routing = json.loads((root / "structure-routing.json").read_bytes())
    allowed = {"schema", "assignments", "static_assignments", "split_admitted", "merge_admitted"}
    if not set(routing).issubset(allowed) or not (allowed - {"schema"}).issubset(routing):
        raise ValueError("runtime routing manifest contains unexpected or missing fields")
    for name in ("assignments", "static_assignments"):
        if (not isinstance(routing[name], list) or len(routing[name]) != 8 or
                any(type(value) is not int or value not in (0, 1) for value in routing[name])):
            raise ValueError("invalid entity-to-child assignments")
    if any(type(routing[name]) is not bool for name in ("split_admitted", "merge_admitted")):
        raise ValueError("admission flags must be boolean")
    with np.load(request["canonical_features_path"], allow_pickle=False) as archive:
        if set(archive.files) != {"semantic", "skill"}:
            raise ValueError("canonical feature artifact contains unexpected fields")
        features = {kind: archive[kind].copy() for kind in archive.files}
    if any(x.shape != (8, 384) or x.dtype != np.float32 or not np.isfinite(x).all()
           for x in features.values()):
        raise ValueError("invalid canonical feature contract")
    started = time.perf_counter_ns()
    names = ("dynamic-0", "dynamic-1", "static-0", "static-1", "rank-8", "merged")
    cells = {}
    shared_head = None
    for name in names:
        cell = TensorCell.load(root / name, request["encoder_sha"], shared_head=shared_head)
        if not cell.head_frozen:
            raise ValueError("structure checkpoints must use a frozen head")
        if [(s.name, s.kind, s.size) for s in cell.config.outputs] != [("bits", "binary", 12)]:
            raise ValueError("unexpected structure output schema")
        if cell.config.input_dim != 384:
            raise ValueError("unexpected structure input dimension")
        shared_head = cell.head
        cells[name] = cell
    load_wall_ns = time.perf_counter_ns() - started
    groups = {"dynamic": (cells["dynamic-0"], cells["dynamic-1"]),
              "static": (cells["static-0"], cells["static-1"]),
              "rank8": (cells["rank-8"],), "merged": (cells["merged"],)}
    calls = {name: 0 for name in names}
    outputs = {}
    with torch.no_grad():
        for arm, models in groups.items():
            records = []
            start = time.perf_counter_ns()
            for entity in range(8):
                if arm in ("dynamic", "static"):
                    key = "assignments" if arm == "dynamic" else "static_assignments"
                    model = models[routing[key][entity]]
                else:
                    model = models[0]
                bits = model.predict(features["semantic"][entity : entity + 1])["bits"][0]
                calls[model.config.cell_id] += 1
                records.append({"entity": entity, "cell_id": model.config.cell_id,
                                "bits": bits.tolist(), "value": decode_bits(bits)})
            outputs[arm] = {"rows": records, "model_calls": 8,
                            "parameter_counts": unique_parameter_count(models),
                            "prediction_wall_ns": time.perf_counter_ns() - start}
    return {"schema": "hepta.memory.structure-reader.v1", "pid": os.getpid(),
            "base_encoder_sha": request["encoder_sha"], "routing_sha256": digest(routing),
            "split_calibration_admitted": routing["split_admitted"],
            "merge_calibration_admitted": routing["merge_admitted"], "candidates": outputs,
            "parameter_sha256": {name: cell.parameter_digest() for name, cell in cells.items()},
            "source_ids_sha256": {name: digest(sorted(cell.source_ids)) for name, cell in cells.items()},
            "shared_head_restored": len({id(cell.head) for cell in cells.values()}) == 1,
            "all_loaded_unique_parameters": unique_parameter_count(cells.values()), "model_calls": calls,
            "training_modules_loaded": sorted(set(sys.modules) & {"corpus", "train", "score"}),
            "cost": {"model_load_wall_ns": load_wall_ns, "model_load_count": len(cells),
                     "body_wall_ns": time.perf_counter_ns() - began,
                     "body_cpu_seconds": time.process_time() - cpu,
                     "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                     "loaded_feature_array_bytes": sum(x.nbytes for x in features.values()),
                     "serialized_checkpoint_bytes": sum(p.stat().st_size for name in names
                                                        for p in (root / name).iterdir() if p.is_file())},
            "quality_threshold_applied": False, "native_runtime": False}


def main():
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        raise ValueError("oversized structure-reader request")
    sys.stdout.buffer.write(canonical(run(json.loads(raw))) + b"\n")


if __name__ == "__main__":
    main()
