"""Actual conditional head comparison, without opening image/audio holdouts."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch.nn import functional as F

from ...abc_next.temporal.speech import write_pcm
from ...closure_20261025.media.sources import save_json, sha
from ...v7_media.corpus import spectrum_waveform
from ...v7_media.models import AcousticDecoder
from .observers import FrozenSpeechObservers
from .waveform import WaveformStudent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("student", "legacy", "assets", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    save_json(args.output / "registration.json", {"schema": "hepta.next.conditional-waveform-probe.v1",
              "student_sha256": sha(args.student), "legacy_sha256": sha(args.legacy),
              "source_sha256": sha(__file__), "all_classes": 10,
              "pairing": "digit,(digit+1)%10", "sample_rate": 8000,
              "samples_per_event": 16000, "primary": "small.en", "secondary": "base.en",
              "new_confirmation_opened": False, "head_comparison_not_independent_source_trial": True})
    student = WaveformStudent().eval().requires_grad_(False)
    student.load_state_dict(torch.load(args.student, map_location="cpu", weights_only=True)["state_dict"])
    vae = AcousticDecoder().eval().requires_grad_(False)
    vae.load_state_dict(torch.load(args.legacy, map_location="cpu", weights_only=True)["state_dict"])
    with torch.inference_mode():
        outputs = {"student": student(torch.eye(10)),
                   "legacy_vae": F.pad(spectrum_waveform(vae.decode(torch.eye(10)), 23617), (0, 8000))}
    observers = FrozenSpeechObservers(args.assets)
    rows = []
    for index in range(10):
        expected = [index, (index + 1) % 10]
        for arm, signals in outputs.items():
            path = args.output / f"{arm}-{index:02d}.wav"
            write_pcm(path, 8000, (signals[expected].numpy().reshape(-1) * 32767).round().astype("<i2"))
            observed = observers.observe(path, carrier=arm == "student")
            row = {"arm": arm, "case": index, "waveform_sha256": sha(path),
                   "observed_without_target": observed, "expected_after_observation": expected,
                   "pair_correct": {k: v == expected for k, v in observed["predictions"].items()},
                   "digits_correct": {k: sum(a == b for a, b in zip(v, expected)) if v else 0
                                      for k, v in observed["predictions"].items()}}
            rows.append(row)
            save_json(args.output / f"{arm}-{index:02d}.json", row)
            print(json.dumps({"arm": arm, "case": index, "predictions": observed["predictions"]}), flush=True)
    save_json(args.output / "summary.json", {"status": "completed", "cases_per_arm": 10,
              "accuracy": {arm: {model: {"pair": sum(r["pair_correct"][model] for r in rows if r["arm"] == arm) / 10,
                                         "digit": sum(r["digits_correct"][model] for r in rows if r["arm"] == arm) / 20}
                                  for model in observers.models} for arm in outputs},
              "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
              "head_census_only": True, "human_perceptual_qualification": False,
              "new_confirmation_opened": False})


if __name__ == "__main__":
    main()
