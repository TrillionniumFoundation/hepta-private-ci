"""Old-source physical-codec smoke before opening joint confirmation sources."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time

import torch

from ...abc_recovery.base_recovery import file_sha, write_json
from ...closure_20261025.media import carrier_media
from ...v6.data import render_tokens
from ...v7.data import make_batch
from ...v7.sources import load_roles
from ...v7_media.corpus import speech_spectrum
from ..media.audio_sources import load_audio
from .evaluate import load_model
from .model import make_task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("shared", "training", "audio-root", "audio-allocation", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    started = time.perf_counter_ns()
    results = json.loads((args.training / "RESULTS.json").read_text())
    corpus = load_roles(args.shared / "abc2-assets/mnist",
                        args.shared / "abc2-runs/source-recovery-001/source-manifest.json", roles=("train",))
    audio_allocation = json.loads(args.audio_allocation.read_text())
    audio_rows = [next(row for row in audio_allocation["roles"]["fit"] if row["label"] == digit)
                  for digit in range(10)]
    audio = speech_spectrum(load_audio(args.audio_root, audio_rows))
    labels = torch.arange(10)
    observed = []
    for arm, record in results["arms"].items():
        path = Path(record["checkpoint"])
        if file_sha(path) != record["checkpoint_sha256"]:
            raise ValueError("Training checkpoint changed before smoke")
        model = load_model(path)
        # All six checkpoints restore. Two matched seed-17 arms exercise the
        # four physical input/output paths; the other seed schemas are equal.
        if record["seed"] != 17:
            continue
        for case, route in enumerate(("image", "text", "audio", "video")):
            batch = make_batch(corpus, "train", 1, 239301 + case, view="clean", offset=case)
            rng = torch.Generator().manual_seed(239401 + case)
            task = make_task(batch, route, audio, labels, rng)
            with torch.inference_mode():
                state = model.encode(task, torch.randn((1, 96), generator=rng))
                output = model.sample(state, rng, greedy=True)
            shapes = {"tokens": (1, 8), "image": (1, 1, 28, 56),
                      "waveform": (1, 2, 16000), "video": (1, 20, 1, 28, 28)}
            if any(tuple(output[key].shape) != shape or not torch.isfinite(output[key]).all()
                   for key, shape in shapes.items()):
                raise ValueError("Actual joint output shape or finiteness failed")
            directory = args.output / arm / route
            identity = hashlib.sha256((arm + ":" + route).encode()).hexdigest()
            media = carrier_media.write_media(directory, render_tokens(output["tokens"][0]), output["image"][0],
                      output["waveform"][0], output["video"][0],
                      {"request_sha256": identity, "state_sha256": identity},
                      shutil.which("ffmpeg"), shutil.which("ffprobe"))
            decoded = carrier_media.read_media({name: row["path"] for name, row in media["files"].items()})
            observed.append({"arm": arm, "route": route, "source_ids": batch.source_ids,
                             "semantic_digits": output["semantic_digits"].tolist(),
                             "clock": decoded["clock"], "physical_media": media,
                             "shape_and_finite": True})
    write_json(args.output / "RESULTS.json", {"status": "completed", "restored_checkpoints": len(results["arms"]),
               "actual_bundles": len(observed), "observed": observed,
               "wall_ns": time.perf_counter_ns() - started,
               "purpose": "Executable shape/codec/readback contract on old train sources; no quality selection",
               "new_evaluation_sources_opened": False, "external_asr_loaded": False})
    print(json.dumps({"status": "completed", "actual_bundles": len(observed)}), flush=True)


if __name__ == "__main__":
    main()
