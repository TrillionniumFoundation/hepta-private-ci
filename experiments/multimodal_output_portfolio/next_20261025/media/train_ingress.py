"""Fit actual waveform ingress on selected official-training speakers only."""

import argparse
import json
from pathlib import Path
import time

import torch
from torch.nn import functional as F

from ...closure_20261025.media.coherent import MelSpeech
from ...closure_20261025.media.sources import save_json, sha
from ...v7_media.corpus import speech_spectrum
from ...v7_media.models import weights_sha256
from .audio_sources import load_audio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sources", "allocation", "initial", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    specification = {"schema": "hepta.next.audio-ingress-training.v1", "seed": 23417,
                     "steps": 2000, "learning_rate": .0008, "batch_size": 32,
                     "allocation_sha256": sha(args.allocation), "initial_sha256": sha(args.initial),
                     "source_sha256": {str(p.resolve()): sha(p) for p in
                                       (Path(__file__), Path(__file__).with_name("audio_sources.py"))},
                     "training_role": "fit", "selection_role": "qualification",
                     "confirmation_opened": False, "audit_model_gradient": False}
    save_json(args.output / "registration.json", specification)
    allocation = json.loads(args.allocation.read_text())
    if allocation["allocator_sha256"] != sha(Path(__file__).with_name("audio_sources.py")):
        raise ValueError("Changed source allocator")
    rows = allocation["roles"]["fit"]
    sounds = load_audio(args.sources, rows)
    labels = torch.tensor([row["label"] for row in rows])
    model = MelSpeech()
    model.load_state_dict(torch.load(args.initial, map_location="cpu", weights_only=True)["state_dict"])
    with torch.no_grad():
        features = torch.cat([model.front_end(speech_spectrum(sounds[start:start + 64])) for start in range(0, len(sounds), 64)])
    del sounds
    before = weights_sha256(model)
    rng = torch.Generator().manual_seed(specification["seed"])
    torch.manual_seed(specification["seed"])
    model.train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=specification["learning_rate"], weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, specification["steps"], eta_min=.00008)
    losses, gradient_max = [], 0.
    for step in range(specification["steps"]):
        ids = torch.randint(len(labels), (specification["batch_size"],), generator=rng)
        x = torch.roll(features[ids], int(torch.randint(-3, 4, (), generator=rng)), -1).clone()
        x += .025 * torch.randn(x.shape, generator=rng)
        f, t = int(torch.randint(37, (), generator=rng)), int(torch.randint(61, (), generator=rng))
        x[:, :, f:f + 4] = 0
        x[:, :, :, t:t + 4] = 0
        optimizer.zero_grad(set_to_none=True)
        loss = F.cross_entropy(model.features(x), labels[ids])
        loss.backward()
        gradient_max = max(gradient_max, sum(float(p.grad.abs().sum()) for p in model.parameters() if p.grad is not None))
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.)
        optimizer.step()
        scheduler.step()
        losses.append(float(loss.detach()))
        if step % 400 == 0 or step + 1 == specification["steps"]:
            print(json.dumps({"step": step + 1, "audio_ingress_ce": losses[-1]}), flush=True)
    model.eval().requires_grad_(False)
    path = args.output / "audio-input.pt"
    torch.save({"state_dict": model.state_dict(), "architecture": "MelSpeech",
                "weights_sha256": weights_sha256(model)}, path)
    # Fixed-steps model closes before the speaker-disjoint selection role opens.
    selection = allocation["roles"]["qualification"]
    sounds = load_audio(args.sources, selection)
    with torch.inference_mode():
        predictions = torch.cat([model(speech_spectrum(sounds[start:start + 64])).argmax(-1)
                                 for start in range(0, len(sounds), 64)]).tolist()
    accuracy = sum(pred == row["label"] for pred, row in zip(predictions, selection)) / len(selection)
    save_json(args.output / "summary.json", {"status": "completed", "checkpoint": str(path),
              "checkpoint_sha256": sha(path), "parameters_sha256": weights_sha256(model),
              "initial_parameters_sha256": before, "gradient_abs_sum_max": gradient_max,
              "losses": losses, "qualification_accuracy": accuracy,
              "qualification_gate_min": .85, "qualification_pass": accuracy >= .85,
              "qualification_predictions": predictions, "qualification_sources": selection,
              "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
              "confirmation_opened": False})


if __name__ == "__main__":
    main()
