"""Qualify a named new audio domain before any new confirmation source opens."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from ...abc_next.temporal.speech import write_pcm
from ...closure_20261025.media.sources import save_json, sha
from .audio_sources import load_audio
from .observers import FrozenSpeechObservers
from .waveform import WaveformStudent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sources", "allocation", "assets", "student", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    torch.set_num_threads(1)
    config = {"schema": "hepta.next.speech-candidate-qualification.v1", "seed": 23517,
              "qualification_recordings": 300, "real_digit_accuracy_min": .85,
              "output_digit_accuracy_min": .80, "primary": "small.en", "secondary": "base.en",
              "source_allocation_sha256": sha(args.allocation), "student_sha256": sha(args.student),
              "source_sha256": {str(p.resolve()): sha(p) for p in
                                (Path(__file__), Path(__file__).with_name("observers.py"),
                                 Path(__file__).with_name("audio_sources.py"), Path(__file__).with_name("waveform.py"))},
              "domain": "Speaker-disjoint Speech Commands digits; separate from old FSDD qualification",
              "real_event_seconds": 1, "generated_event_seconds": 2,
              "confirmation_opened": False, "target_supplied_to_asr": False}
    save_json(args.output / "registration.json", config)
    allocation = json.loads(args.allocation.read_text())
    sources = allocation["roles"]["qualification"]
    sounds = load_audio(args.sources, sources)
    permutation = torch.randperm(len(sources), generator=torch.Generator().manual_seed(config["seed"]))
    observers = FrozenSpeechObservers(args.assets)
    save_json(args.output / "observers.json", observers.receipt)
    rows = []

    def observe(name, signal, expected, carrier):
        pcm = (signal.detach().numpy().reshape(-1) * 32767).round().astype("<i2")
        path = args.output / (name + ".wav")
        write_pcm(path, 8000, pcm)
        observed = observers.observe(path, carrier=carrier)
        result = {"waveform_sha256": sha(path), "observed": observed, "expected_after_observation": expected,
                  "pair_correct": {k: v == expected for k, v in observed["predictions"].items()},
                  "digits_correct": {k: sum(a == b for a, b in zip(v, expected)) if v else 0
                                     for k, v in observed["predictions"].items()}}
        return result

    for index in range(len(sources) // 2):
        ids = permutation[2 * index:2 * index + 2].tolist()
        expected = [sources[i]["label"] for i in ids]
        row = observe(f"real-{index:03d}", sounds[ids], expected, False)
        row["sources"] = [sources[i] for i in ids]
        rows.append(row)
        save_json(args.output / f"real-{index:03d}.json", row)
        if len(rows) % 25 == 0:
            print(json.dumps({"speech_commands_qualification_pairs": len(rows)}), flush=True)
    model = WaveformStudent().eval().requires_grad_(False)
    model.load_state_dict(torch.load(args.student, map_location="cpu", weights_only=True)["state_dict"])
    with torch.inference_mode():
        generated = model(torch.eye(10))
    conditional, negatives = [], []
    for digit in range(10):
        expected = [digit, (digit + 1) % 10]
        row = observe(f"conditional-{digit:02d}", generated[expected], expected, True)
        conditional.append(row)
        save_json(args.output / f"conditional-{digit:02d}.json", row)
    baseline = generated[[0, 1]]
    changed = {"silence": torch.zeros_like(baseline), "swapped_events": baseline.flip(0),
               "wrong_digit": generated[[9, 1]], "missing_second": torch.stack((baseline[0], torch.zeros_like(baseline[1]))),
               "repeated_first": baseline[[0, 0]]}
    for name, sound in changed.items():
        row = observe("negative-" + name, sound, [0, 1], True)
        row["name"] = name
        negatives.append(row)
        save_json(args.output / ("negative-" + name + ".json"), row)
    accuracy = {role: {name: {"pair": sum(row["pair_correct"][name] for row in values) / len(values),
                              "digit": sum(row["digits_correct"][name] for row in values) / (2 * len(values))}
                       for name in observers.models}
                for role, values in (("real", rows), ("generated", conditional))}
    gates = {"real_primary_eligible": accuracy["real"]["small.en"]["digit"] >= .85,
             "generated_primary": accuracy["generated"]["small.en"]["digit"] >= .80,
             "nonvacuous_negatives": conditional[0]["pair_correct"]["small.en"]
                                     and all(not row["pair_correct"]["small.en"] for row in negatives)}
    save_json(args.output / "summary.json", {"status": "completed", "accuracy": accuracy,
              "gates": gates, "all_gates_pass": all(gates.values()),
              "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
              "confirmation_opened": False, "previous_failed_domains_retained": True})


if __name__ == "__main__":
    main()
