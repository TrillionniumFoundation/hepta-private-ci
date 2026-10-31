"""Qualify fixed new speech observers on old validation recordings only."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from ...abc_next.temporal.speech import write_pcm
from ...closure_20261025.media.sources import save_json, sha, speech_role
from .observers import FrozenSpeechObservers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("fsdd", "assets", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    torch.set_num_threads(1)
    config = {"schema": "hepta.next.speech-observer-qualification.v1",
              "source_role": "old FSDD validation indices 5..9, 300 recordings",
              "pairing_seed": 23017, "waveform_event_samples": 8000,
              "eligibility_digit_accuracy_min": .85,
              "primary": "small.en", "secondary": "base.en",
              "lexical_parser": "strict whole transcript; no target or lexical correction",
              "timestamps": "Actual PCM event boundaries, ASR word timing reported but not a physical clock",
              "source_sha256": {str(p.resolve()): sha(p) for p in
                                (Path(__file__), Path(__file__).with_name("observers.py"))},
              "assets": {name: sha(args.assets / ("whisper-" + name) / "manifest.json")
                         for name in ("base.en", "small.en")},
              "fsdd_sha256": sha(args.fsdd), "test_sources_opened": False}
    save_json(args.output / "registration.json", config)
    signals, labels, metadata = speech_role(args.fsdd, "validation")
    save_json(args.output / "sources.json", metadata)
    observers = FrozenSpeechObservers(args.assets)
    save_json(args.output / "observers.json", observers.receipt)
    permutation = torch.randperm(len(labels), generator=torch.Generator().manual_seed(config["pairing_seed"]))
    rows = []
    for index in range(len(labels) // 2):
        ids = permutation[2 * index:2 * index + 2]
        pcm = (signals[ids].numpy().reshape(-1) * 32767).round().astype("<i2")
        path = args.output / f"pair-{index:03d}.wav"
        write_pcm(path, 8000, pcm)
        observed = observers.observe(path)
        expected = labels[ids].tolist()
        row = {"index": index, "recordings": [metadata[i] for i in ids.tolist()],
               "waveform_sha256": sha(path), "observed": observed,
               "expected_after_observation": expected,
               "pair_correct": {name: prediction == expected for name, prediction in observed["predictions"].items()},
               "digits_correct": {name: sum(a == b for a, b in zip(prediction, expected)) if prediction else 0
                                  for name, prediction in observed["predictions"].items()}}
        save_json(args.output / f"row-{index:03d}.json", row)
        rows.append(row)
        if len(rows) % 25 == 0:
            print(json.dumps({"old_validation_pairs": len(rows)}), flush=True)
    accuracy = {name: {"pair": sum(row["pair_correct"][name] for row in rows) / len(rows),
                       "digit": sum(row["digits_correct"][name] for row in rows) / (2 * len(rows))}
                for name in observers.models}
    save_json(args.output / "summary.json", {"status": "completed", "pairs": len(rows),
              "accuracy": accuracy,
              "primary_eligible": accuracy["small.en"]["digit"] >= .85,
              "secondary_eligible": accuracy["base.en"]["digit"] >= .85,
              "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
              "old_qualification_not_replaced": True, "new_confirmation_opened": False})


if __name__ == "__main__":
    main()
