"""Freeze the actual qualified candidate and reports before QMNIST confirmation."""

import argparse
import json
from pathlib import Path
import time

from ...closure_20261025.media.sources import sha, save_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("development", "qualification", "allocation", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    development = json.loads(args.development.read_text())
    qualification = json.loads(args.qualification.read_text())
    if (development.get("phase") != "development" or not development.get("all_media_sample_gates_pass")
            or qualification.get("phase") != "independent_qualification"
            or qualification.get("primary") != "base.en" or not qualification.get("primary_eligible")
            or qualification.get("source_recordings") != 300):
        raise ValueError("Candidate lacks unchanged development and independent observer qualification gates")
    registration = args.development.parent / "registration.json"
    pins = dict(json.loads(registration.read_text())["frozen_candidate_sha256"])
    added = [args.development, registration, args.qualification,
             args.qualification.parent / "registration.json", args.qualification.parent / "observers.json",
             Path(__file__).with_name("EVENT_SELECTION_V2.json"), args.allocation,
             Path(__file__).resolve().parents[1] / "sources.py"]
    for path in added:
        pins[str(path.resolve())] = sha(path)
    for path, expected in pins.items():
        if sha(path) != expected:
            raise ValueError("Executed development candidate changed before final freeze")
    protocol = {"schema": "hepta.next.media-confirmation.v1", "study": "media",
                "registered_unix_ns": time.time_ns(), "source_allocation_sha256": sha(args.allocation),
                "frozen_candidate_sha256": pins, "pairs": 128, "writers": 32,
                "speech_speakers": 32, "input_modes": ["image", "text", "audio", "video", "audio_video"],
                "outputs": 640, "source_inference_unit": "32 matched writer/speech-speaker clusters",
                "conditions": "hard predicted semantics from the same public neural state",
                "original_numeric_gates": {"joint_each_input_mode": .75, "audio_ingress": .85,
                                           "independent_ASR": .85, "conditional_audio": .8,
                                           "conditional_video": .9, "distinct_frames_per_event": 6},
                "clock": {"input_event_seconds": 1, "output_event_seconds": 2,
                          "output_total_seconds": 4, "output_frames": 20, "output_fps": 5},
                "after_outcomes": "Retain every source; no parameter, parser, threshold, mode or observer change using this confirmation",
                "human_perceptual_certificate_claimed": False, "foundation_model_claimed": False,
                "authority": "deny_all"}
    save_json(args.output, protocol)
    print(json.dumps({"protocol_sha256": sha(args.output), "pins": len(pins)}))


if __name__ == "__main__":
    main()
