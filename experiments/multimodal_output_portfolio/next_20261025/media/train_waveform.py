"""Train a phase-preserving waveform student from a named frozen TTS teacher."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
from scipy.signal import resample_poly
import torch
from torch.nn import functional as F

from ...abc_next.temporal.speech import SpeechBackend, read_pcm, write_pcm
from ...closure_20261025.media.sources import save_json, sha
from ...v7_media.models import weights_sha256
from .observers import WORDS
from .waveform import WaveformStudent, waveform_distance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("teacher", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    config = {"schema": "hepta.next.waveform-distillation.v1", "seed": 23117,
              "teacher": "frozen Piper en_US-ljspeech-medium",
              "teacher_manifest_sha256": sha(args.teacher / "manifest.json"),
              "condition_count": 10, "text_pattern": "The digit is {word}.",
              "sample_rate": 8000, "samples_per_event": 16000,
              "steps": 2000, "learning_rate": .003,
              "loss": "mean square actual phase-preserving waveform, no ASR or audit gradient",
              "generator_type": "finite 10-condition neural waveform student; not unrestricted speech",
              "source_sha256": {str(p.resolve()): sha(p) for p in
                                (Path(__file__), Path(__file__).with_name("waveform.py"))},
              "confirmation_opened": False}
    save_json(args.output / "registration.json", config)
    teacher = SpeechBackend(args.teacher)
    save_json(args.output / "teacher-load.json", teacher.load_receipt)
    targets, receipts = [], []
    for digit, word in enumerate(WORDS):
        path = args.output / f"teacher-{digit}.wav"
        receipt = teacher.synthesize(config["text_pattern"].format(word=word), path)
        rate, pcm = read_pcm(path)
        waveform = resample_poly(pcm.astype(np.float64) / 32768, 8000, rate).astype(np.float32)
        if len(waveform) > 15360:
            waveform = np.interp(np.linspace(0, len(waveform) - 1, 15360), np.arange(len(waveform)), waveform).astype(np.float32)
        targets.append(np.pad(waveform, (0, 16000 - len(waveform))))
        receipts.append(receipt)
    target = torch.from_numpy(np.stack(targets))
    save_json(args.output / "teacher-synthesis.json", receipts)
    torch.save({"waveforms": target, "sample_rate": 8000}, args.output / "training-targets.pt")
    torch.manual_seed(config["seed"])
    model = WaveformStudent()
    before = weights_sha256(model)
    optimizer = torch.optim.Adam(model.parameters(), lr=config["learning_rate"])
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, config["steps"], eta_min=.00003)
    inputs, losses, gradient_max = torch.eye(10), [], 0.
    for step in range(config["steps"]):
        optimizer.zero_grad(set_to_none=True)
        output = model(inputs)
        loss = waveform_distance(output, target).mean()
        loss.backward()
        gradient_max = max(gradient_max, sum(float(p.grad.abs().sum()) for p in model.parameters()))
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.)
        optimizer.step()
        scheduler.step()
        losses.append(float(loss.detach()))
        if step % 400 == 0 or step + 1 == config["steps"]:
            print(json.dumps({"step": step + 1, "mse": losses[-1]}), flush=True)
    model.eval().requires_grad_(False)
    with torch.inference_mode():
        output = model(inputs)
        snr = 10 * torch.log10(target.square().mean(-1) / waveform_distance(output, target).clamp_min(1e-12))
    for digit in range(10):
        write_pcm(args.output / f"student-{digit}.wav", 8000,
                  (output[digit].numpy() * 32767).round().astype("<i2"))
    path = args.output / "waveform-student.pt"
    torch.save({"state_dict": model.state_dict(), "architecture": "WaveformStudent",
                "weights_sha256": weights_sha256(model)}, path)
    save_json(args.output / "summary.json", {"status": "completed", "checkpoint": str(path),
              "checkpoint_sha256": sha(path), "initial_parameters_sha256": before,
              "parameters_sha256": weights_sha256(model), "gradient_abs_sum_max": gradient_max,
              "parameter_count": sum(p.numel() for p in model.parameters()),
              "losses": losses, "teacher_snr_db_by_digit": snr.tolist(),
              "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
              "teacher_retrieval_at_inference": False, "ASR_loaded_during_training": False,
              "confirmation_opened": False})


if __name__ == "__main__":
    main()
