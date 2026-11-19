"""Post-run custody cross-check: NPZ/current-state bytes and raw BDF meshes."""

import gzip
import hashlib
import json
import os
import resource
import time
from pathlib import Path

import numpy as np

from qualification.hcsn_currentstate_n256_firststep_serializer_v2 import serializer as wire


def run(directory):
    root = Path(__file__).resolve().parents[2]
    directory = Path(directory)
    freeze = json.loads((directory / "SOURCE_FREEZE.json").read_text())
    for name, expected in freeze["sources"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError("executed frozen source changed")
    state_coordinates = 0
    minimum_probability = 1.
    resets_checked = 0
    for lane in ("warm", "coarse", "cold"):
        states = np.load(directory / lane / "STATES.npz")["values"]
        result = json.loads((directory / lane / "RESULT.json").read_text())
        for index, record in enumerate(result["capsules"]):
            raw = gzip.decompress((directory / lane / record["path"]).read_bytes())
            if hashlib.sha256(raw).hexdigest() != record["sha256"]:
                raise ValueError("actual capsule digest")
            envelope = wire.decode(raw, 32*1024**2)
            blocks = {block.name: block.tensor for block in envelope.blocks}
            current = b"".join(blocks[name].payload for name in ("active", "upper", "mass", "discounted_hit", "occupation"))
            if current != np.asarray(states[index], dtype="<f8").tobytes():
                raise ValueError("metric NPZ is not the full saved wire state")
            state_coordinates += len(current)//8
            for name in ("active", "upper"):
                values = np.frombuffer(blocks[name].payload, dtype="<f8").reshape(blocks[name].shape)
                minimum_probability = min(minimum_probability, float(values[0].min()))
            for packet in envelope.packets:
                if blocks["reset_" + packet.identity].payload != blocks["physics_reset"].payload:
                    raise ValueError("fixed-physics event reset changed")
                resets_checked += 1
                alpha = np.frombuffer(packet.alpha.payload, dtype="<f8").reshape(packet.alpha.shape)
                minimum_probability = min(minimum_probability, float(alpha[0].min()))
    references = {}
    for name in ("coarse", "fine"):
        location = directory / ("reference_" + name)
        result = json.loads((location / "RESULT.json").read_text())
        arrays = np.load(location / "REFERENCE.npz")
        rows, previous = 0, {}
        for generation in (1, 2):
            for index, item in enumerate(x for x in result["segments"] if x["generation"] == generation):
                times, values = arrays[f"g{generation-1}_s{index}_t"], arrays[f"g{generation-1}_s{index}_y"]
                if (len(times) != item["accepted_mesh_points"] or values.shape != (1295, len(times))
                        or np.any(np.diff(times) <= 0) or not np.isfinite(values).all()
                        or times[0] != item["left"] or times[-1] != item["right"]):
                    raise ValueError("original BDF mesh shape/bounds/finite state")
                if generation in previous and not np.array_equal(previous[generation], values[:, 0]):
                    raise ValueError("BDF segment state was not continued")
                previous[generation] = values[:, -1]
                if "successfully reached the end" not in item["message"]:
                    raise ValueError("BDF solver status")
                rows += values.size
        references[name] = {"segments": len(result["segments"]), "mesh_state_coordinates_checked": rows,
            "nfev": sum(x["nfev"] for x in result["segments"]),
            "njev": sum(x["njev"] for x in result["segments"]), "nlu": sum(x["nlu"] for x in result["segments"])}
    return {"status": "PASS", "frozen_source_files_checked": len(freeze["sources"]),
        "NPZ_wire_state_coordinates_exact": state_coordinates, "event_reset_snapshots_checked": resets_checked,
        "observed_minimum_probability_coordinate": minimum_probability,
        "raw_BDF_meshes": references, "model_calls": 0, "exponential_actions": 0, "optimizer_steps": 0,
        "scope": "post-run custody verification; unchanged precommitted numerical gates",
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


if __name__ == "__main__":
    import sys
    os.sched_setaffinity(0, {8})
    wall, cpu = time.perf_counter(), time.process_time()
    result = run(sys.argv[1])
    result["reader_body_cost"] = {"wall_seconds": time.perf_counter()-wall,
        "cpu_seconds": time.process_time()-cpu, "whole_process_peak_RSS_KiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "scope": "body excludes imports; RSS is whole process"}
    target = Path(sys.argv[1]) / "CUSTODY_REVIEW.json"
    target.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(target.read_text())
