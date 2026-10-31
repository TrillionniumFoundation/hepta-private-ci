"""Quantify two frozen ASRs and physical anti-hallucination controls."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np
import torch

from ..sources import save_json, sha, speech_role
from ..wave_reference import WaveReference


WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "speech-python", "voice-assets", "asr-assets", "waveform-profile", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    protocol = Path(__file__).with_name("protocol.json")
    config = json.loads(protocol.read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter_ns()
    source_paths = [Path(__file__).resolve(), protocol.resolve(), args.waveform_profile.resolve(),
                    Path(__file__).resolve().parents[1] / "wave_worker.py",
                    Path(__file__).resolve().parents[1] / "wave_reference.py",
                    Path(__file__).resolve().parents[1] / "sources.py"]
    pins = {str(path): sha(path) for path in source_paths}
    save_json(args.output / "registration.json", {"config": config, "source_sha256": pins,
              "archive_sha256": sha(args.archive), "started_unix_ns": time.time_ns()})
    torch.set_num_threads(1)
    waveforms, labels, metadata = speech_role(args.archive, "validation")
    if len(labels) != config["real_recordings"]:
        raise ValueError("Wrong old validation source count")
    save_json(args.output / "real-sources.json", metadata)
    worker = WaveReference(args.speech_python, args.voice_assets, args.asr_assets, args.output / "worker", args.waveform_profile)
    save_json(args.output / "worker-load.json", worker.load_receipt)
    real_rows, generated_rows, negatives = [], [], {}

    def observe(sound, expected, identity):
        pcm = (sound.numpy().reshape(-1) * 32767).round().astype("<i2").tobytes()
        worker.predict_pcm16(pcm)
        measured = worker.last_observation
        candidates = {"primary_whisper": measured["whisper_event_digits"], "secondary_vosk": measured["vosk_event_digits"]}
        row = {"identity": identity, "actual_pcm_sha256": hashlib.sha256(pcm).hexdigest(),
               "observed_without_target": measured, "expected_after_observation": expected,
               "digit_correct": {name: sum(x == y for x, y in zip(value, expected)) for name, value in candidates.items()},
               "pair_correct": {name: value == expected for name, value in candidates.items()}}
        return row
    try:
        permutation = torch.randperm(len(labels), generator=torch.Generator().manual_seed(config["seed"])).tolist()
        for index in range(150):
            ids = permutation[2 * index:2 * index + 2]
            sound = torch.zeros(2, worker.samples_per_event)
            sound[:, :8000] = waveforms[ids]
            row = observe(sound, labels[ids].tolist(), {"role": "old_validation", "indices": ids})
            save_json(args.output / f"real-{index:03d}.json", row)
            real_rows.append(row)
            if (index + 1) % 25 == 0:
                print(json.dumps({"real_pairs": index + 1}), flush=True)
        baseline = None
        for digit in range(10):
            expected = [digit, (digit + 1) % 10]
            sound, receipt = worker.generate(torch.eye(10)[expected], args.output / f"generated-{digit}")
            row = observe(sound, expected, {"role": "all_class_conditional_probe", "condition": expected})
            row["synthesis"] = receipt
            save_json(args.output / f"conditional-{digit:02d}.json", row)
            generated_rows.append(row)
            if digit == 0:
                baseline = (sound.clone(), row)
        sound, baseline_row = baseline
        if baseline_row["pair_correct"]["primary_whisper"]:
            silence, missing, excised = torch.zeros_like(sound), sound.clone(), sound.clone()
            missing[1] = 0
            removed = []
            for segment in baseline_row["observed_without_target"]["whisper"]["segments"]:
                for word in segment["words"]:
                    tokens = re.findall(r"[a-z]+|[0-9]+", word["word"].lower())
                    if tokens in (["zero"], ["0"]) and word["start"] < 2:
                        left, right = max(0, int((word["start"] - .08) * 8000)), min(16000, int((word["end"] + .08) * 8000))
                        excised[0, left:right] = 0
                        removed.append([left, right])
            wrong, wrong_receipt = worker.generate(torch.eye(10)[[9, 1]], args.output / "wrong-digit-neural")
            for name, changed in {"silence": silence, "swapped_events": sound.flip(0),
                                  "wrong_digit": wrong, "missing_second_event": missing,
                                  "excised_first_digit_word": excised}.items():
                row = observe(changed, [0, 1], {"negative": name})
                row["rejected"] = not row["pair_correct"]["primary_whisper"]
                if name == "excised_first_digit_word":
                    row["removed_actual_sample_intervals"] = removed
                    row["rejected"] = row["rejected"] and bool(removed)
                if name == "wrong_digit":
                    row["synthesis"] = wrong_receipt
                save_json(args.output / ("negative-" + name + ".json"), row)
                negatives[name] = row["rejected"]
        worker_receipt = worker.close()
        worker = None
        if any(sha(path) != expected for path, expected in pins.items()):
            raise RuntimeError("Frozen observer qualification source changed")
        accuracy = {role: {name: sum(row["digit_correct"][name] for row in rows) / (2 * len(rows))
                          for name in ("primary_whisper", "secondary_vosk")}
                    for role, rows in (("real_validation", real_rows), ("generated_carrier", generated_rows))}
        controls_pass = len(negatives) == 5 and all(negatives.values())
        save_json(args.output / "summary.json", {"status": "completed", "accuracy": accuracy,
                  "real_recordings": 300, "generated_pairs": 10, "negative_controls": negatives,
                  "general_real_audio_asr_qualified": accuracy["real_validation"]["primary_whisper"] >= config["real_audio_min"],
                  "bounded_output_profile_qualified": accuracy["generated_carrier"]["primary_whisper"] >= config["generated_profile_min"] and controls_pass,
                  "all_required_observer_qualification_pass": accuracy["real_validation"]["primary_whisper"] >= config["real_audio_min"] and accuracy["generated_carrier"]["primary_whisper"] >= config["generated_profile_min"] and controls_pass,
                  "worker": worker_receipt, "wall_ns": time.perf_counter_ns() - started,
                  "test_opened": False, "source_sha256": pins})
    finally:
        if worker is not None:
            worker.close()


if __name__ == "__main__":
    main()
