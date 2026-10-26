"""Cross-check frozen tensor graphs on old selection public states only."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from ...abc_next.sensor_run import load_sensor
from ...abc_next.value import features, load_controller
from ...abc_recovery.base_recovery import file_sha, write_json
from ...closure_20261025.control.registry import load_model
from ...v7.data import VIEWS
from .compiled import CompiledTeacher, TIE_MARGIN


@torch.inference_mode()
def run(asset, output):
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    records = []
    sensor = load_sensor(asset / "abc3-runs/public-sensor-001/sensor.pt")
    for seed in (17, 29, 43):
        model = load_model(asset, seed)
        teacher = load_controller(asset / f"abc3-runs/controllers-001/seed-{seed}/output_ndu/controller.pt")
        candidate = CompiledTeacher(model._model, sensor, teacher)
        folder = asset / f"abc4-control-runs/development-001/seed-{seed}/selection"
        table = torch.load(folder / "data.pt", map_location="cpu", weights_only=True)
        full = table["features"].flatten(0, 1)
        old = (teacher.one(features(full, teacher.mode)), teacher.two(features(full, teacher.mode)))
        new = candidate.heads(full)
        differences, mismatches = [], []
        for horizon, original, compiled in zip((1, 2), old, new):
            differences.append(float((original - compiled).abs().max()))
            if horizon == 1:
                original = original.clone(); compiled = compiled.clone()
                original[:, 1] = float("inf"); compiled[:, 1] = float("inf")
            ordered = compiled.sort(-1).values
            near = ordered[:, 1] - ordered[:, 0] <= TIE_MARGIN
            choices = torch.where(near, original.argmin(-1), compiled.argmin(-1))
            mismatches.append(int((choices != original.argmin(-1)).sum()))
        visual_error, sensor_error, panel_rows = 0., 0., 0
        for view in VIEWS:
            with np.load(folder / (view + ".npz"), allow_pickle=False) as archive:
                bits = archive["pixels_bits"][:5, :16].reshape(-1, 196)
            pixels = torch.from_numpy(np.unpackbits(bits, axis=1, count=1568).copy()).reshape(-1, 1, 28, 56).float()
            panels = torch.stack((pixels[:, :, :, :28], pixels[:, :, :, 28:]), 1).flatten(0, 1)
            visual = model._model.pixel_encoder(torch.cat((panels, torch.ones_like(panels)), 1)).reshape(-1, 96)
            semantic = sensor(panels, torch.ones_like(panels)).softmax(-1).reshape(-1, 2, 10)
            a, b = candidate.readers(pixels)
            visual_error = max(visual_error, float((visual - a).abs().max()))
            sensor_error = max(sensor_error, float((semantic - b).abs().max()))
            panel_rows += len(pixels)
        rejected = 0
        for bad in (torch.full((1, 763), float("nan")), torch.zeros(1, 762), torch.zeros(2, 763)):
            try: candidate.choose(bad, 1)
            except ValueError: rejected += 1
        if max(differences) > 1e-5 or max(visual_error, sensor_error) > 1e-5 or any(mismatches) or rejected != 3:
            raise ValueError("Compiled function qualification failed")
        records.append({"seed": seed, "mode": teacher.mode, "hidden": teacher.hidden, "public_nodes": len(full),
            "one_two_max_absolute_moment_error": differences, "one_two_action_mismatches": mismatches,
            "actual_media_rows": panel_rows, "visual_max_absolute_error": visual_error,
            "sensor_max_absolute_error": sensor_error, "invalid_input_rejections": rejected,
            "historical_data_sha256": file_sha(folder / "data.pt")})
    result = {"status": "passed", "records": records, "new_sources_opened": False,
        "scope": "Empirical parity on all old selection public nodes and deterministic archived-media subset, plus declared invalid-input rejection. Not a global floating-point equivalence proof.",
        "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
        "source_sha256": {p.name: file_sha(p) for p in Path(__file__).parent.glob("*.py")}}
    if output.exists(): raise FileExistsError("Never overwrite qualification evidence")
    write_json(output, result); print(json.dumps(result))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--asset-root", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(); run(a.asset_root, a.output)
