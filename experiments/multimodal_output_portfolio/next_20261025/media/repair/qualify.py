"""One fresh cohort independently assesses both frozen ingress and ASR ensemble."""

import argparse
import gc
import json
from pathlib import Path
import sys
import time

import torch

from ....closure_20261025.media.sources import save_json, sha
from ....v7_media.corpus import speech_spectrum
from ....v7_media.models import weights_sha256
from ..audio_sources import load_audio
from ..qualify_ensemble_v31 import main as qualify_frozen_asr
from .model import load_ingress


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "sources", "allocation", "selection", "assets", "model",
                 "development", "old-development", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    protocol = json.loads(args.protocol.read_text())
    pins = protocol["frozen_candidate_sha256"]
    for path, expected in pins.items():
        if sha(path) != expected:
            raise ValueError("Actual frozen qualification dependency changed before new source inference")
    for path in (args.allocation, args.selection, args.model, args.development, args.old_development):
        if pins.get(str(path.resolve())) != sha(path):
            raise ValueError("Actual qualification argument is not prospectively bound")
    if (protocol["source_allocation_sha256"] != sha(args.allocation)
            or protocol["observer_selection_sha256"] != sha(args.selection)
            or protocol["classifier_checkpoint_sha256"] != sha(args.model)):
        raise ValueError("Qualification arguments differ from the prospective protocol")
    development = json.loads(args.development.read_text())
    if development.get("phase") != "development" or not development.get("all_media_sample_gates_pass"):
        raise ValueError("Repaired actual development execution did not qualify")
    for name in ("base.en", "small.en"):
        manifest = args.assets / ("whisper-" + name) / "manifest.json"
        if pins.get(str(manifest.resolve())) != sha(manifest):
            raise ValueError("Actual ASR manifest argument differs before source inference")
        for item in json.loads(manifest.read_text())["sources"]:
            path = manifest.parent / item["path"]
            if pins.get(str(path.resolve())) != sha(path):
                raise ValueError("Actual ASR asset argument differs before source inference")
    allocation = json.loads(args.allocation.read_text())
    rows = allocation["recordings"]
    if len(rows) != 300 or len({row["speaker"] for row in rows}) != 147:
        raise ValueError("Fixed source census changed")
    for row in rows:
        path = args.sources / row["path"]
        if pins.get(str(path.resolve())) != row["sha256"] or sha(path) != row["sha256"]:
            raise ValueError("Actual new recording argument differs from prospective identity")
    save_json(args.output / "registration.json", {"schema": "hepta.next.media-repair-qualification.v1",
              "protocol_path": str(args.protocol.resolve()), "protocol_sha256": sha(args.protocol),
              "classifier_checkpoint_sha256": sha(args.model), "ASR_selection_sha256": sha(args.selection),
              "source_allocation_sha256": sha(args.allocation), "started_unix_ns": time.time_ns(),
              "new_media_confirmation_opened": False})
    ingress_output = args.output / "ingress"
    ingress_output.mkdir()
    ingress_wall, ingress_cpu = time.perf_counter_ns(), time.process_time_ns()
    model = load_ingress(args.model)
    before = weights_sha256(model)
    save_json(ingress_output / "registration.json", {"schema": "hepta.next.independent-ingress-qualification.v1",
              "checkpoint_path": str(args.model.resolve()), "checkpoint_sha256": sha(args.model),
              "source_allocation_sha256": sha(args.allocation), "source_allocation_path": str(args.allocation.resolve()),
              "qualification_protocol_sha256": sha(args.protocol), "gate_min": .85,
              "target_supplied_to_inference": False})
    sounds = load_audio(args.sources, rows)
    with torch.inference_mode():
        predictions = torch.cat([model(speech_spectrum(sounds[start:start + 32])).argmax(-1)
                                 for start in range(0, len(sounds), 32)]).tolist()
    if weights_sha256(model) != before:
        raise ValueError("Independent inference changed classifier parameters")
    observations = [{"source": source, "predicted_digit_without_target": prediction,
                     "expected_after_observation": source["label"], "correct": prediction == source["label"]}
                    for source, prediction in zip(rows, predictions)]
    accuracy = sum(row["correct"] for row in observations) / 300
    save_json(ingress_output / "observations.json", observations)
    save_json(ingress_output / "summary.json", {"status": "completed", "phase": "independent_qualification",
              "checkpoint_sha256": sha(args.model), "source_recordings": 300, "source_speakers": 147,
              "qualification_accuracy": accuracy, "qualification_gate_min": .85, "qualification_pass": accuracy >= .85,
              "wall_ns": time.perf_counter_ns() - ingress_wall, "cpu_ns": time.process_time_ns() - ingress_cpu,
              "target_supplied_to_inference": False, "model_frozen_before_new_source_scores": True,
              "new_media_confirmation_opened": False})
    del model, sounds
    gc.collect()
    original_argv = sys.argv
    sys.argv = ["qualify_ensemble_v31", "--sources", str(args.sources), "--allocation", str(args.allocation),
                "--selection", str(args.selection), "--assets", str(args.assets),
                "--development", str(args.old_development), "--output", str(args.output / "asr")]
    try:
        qualify_frozen_asr()
    finally:
        sys.argv = original_argv
    asr = json.loads((args.output / "asr/summary.json").read_text())
    if any(sha(path) != expected for path, expected in pins.items()):
        raise ValueError("Frozen qualification dependency changed during execution")
    save_json(args.output / "summary.json", {"status": "completed", "phase": "independent_qualification",
              "source_recordings": 300, "source_speakers": 147,
              "ingress_accuracy": accuracy, "ingress_eligible": accuracy >= .85,
              "ASR_primary": asr["primary"], "ASR_accuracy": asr["accuracy"], "ASR_eligible": asr["primary_eligible"],
              "both_eligible": accuracy >= .85 and asr["primary_eligible"],
              "original_gates_unchanged": True, "new_media_confirmation_opened": False,
              "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu})


if __name__ == "__main__":
    main()
