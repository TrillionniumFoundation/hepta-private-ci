"""Open no media sources until repaired development and both independent gates pass."""

import argparse
import json
from pathlib import Path
import time

from ....closure_20261025.media.sources import save_json, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("development", "qualification", "allocation", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Never replace a prospective media confirmation protocol")
    development = json.loads(args.development.read_text())
    qualification = json.loads(args.qualification.read_text())
    asr_path, ingress_path = args.qualification.parent / "asr/summary.json", args.qualification.parent / "ingress/summary.json"
    asr, ingress = json.loads(asr_path.read_text()), json.loads(ingress_path.read_text())
    if (development.get("phase") != "development" or development.get("version") != "repair-v1"
            or not development.get("all_media_sample_gates_pass")
            or qualification.get("phase") != "independent_qualification" or not qualification.get("both_eligible")
            or asr.get("phase") != "independent_qualification"
            or asr.get("primary") != "consensus_or_single_v3" or not asr.get("primary_eligible")
            or asr.get("version") != "v3" or asr.get("source_recordings") != 300
            or ingress.get("phase") != "independent_qualification" or not ingress.get("qualification_pass")
            or ingress.get("qualification_accuracy", 0) < .85 or ingress.get("source_recordings") != 300):
        raise ValueError("Original media, independent ASR and independent ingress gates have not all passed")
    registration = args.development.parent / "registration.json"
    pins = dict(json.loads(registration.read_text())["frozen_candidate_sha256"])
    parent = Path(__file__).resolve().parent.parent
    qualification_registration = args.qualification.parent / "registration.json"
    combined_registration = json.loads(qualification_registration.read_text())
    qualification_protocol = Path(combined_registration["protocol_path"])
    if sha(qualification_protocol) != combined_registration["protocol_sha256"]:
        raise ValueError("Independent qualification protocol identity differs")
    asr_registration = json.loads((asr_path.parent / "registration.json").read_text())
    ingress_registration = json.loads((ingress_path.parent / "registration.json").read_text())
    if (asr_registration.get("selection_sha256") != sha(parent / "ENSEMBLE_SELECTION_V31.json")
            or asr_registration.get("source_allocation_sha256") != ingress_registration.get("source_allocation_sha256")
            or asr_registration.get("source_allocation_sha256") != combined_registration.get("source_allocation_sha256")
            or pins.get(ingress_registration.get("checkpoint_path")) != ingress.get("checkpoint_sha256")):
        raise ValueError("Actual development classifier and independent qualification identities disagree")
    added = [args.development, registration, args.qualification, qualification_registration, qualification_protocol,
             asr_path, asr_path.parent / "registration.json", asr_path.parent / "observers.json",
             ingress_path, ingress_path.parent / "registration.json", ingress_path.parent / "observations.json",
             parent / "ENSEMBLE_SELECTION_V31.json", parent / "ENSEMBLE_QUALIFICATION_SOURCES_V3.json",
             args.allocation, parent.parent / "sources.py"]
    for path in added:
        pins[str(path.resolve())] = sha(path)
    for path, expected in pins.items():
        if sha(path) != expected:
            raise ValueError("Actual candidate or independent qualification bytes changed before confirmation freeze")
    save_json(args.output, {"schema": "hepta.next.media-repair-confirmation.v1", "study": "media",
              "registered_unix_ns": time.time_ns(), "source_allocation_sha256": sha(args.allocation),
              "frozen_candidate_sha256": pins, "pairs": 128, "writers": 32, "speech_speakers": 32,
              "input_modes": ["image", "text", "audio", "video", "audio_video"], "outputs": 640,
              "source_inference_unit": "32 matched writer/speech-speaker clusters",
              "condition": "Predicted hard semantic commitment produces canonical finite-class output",
              "preserves_input_handwriting_style": False,
              "original_numeric_gates": {"joint_each_input_mode": .75, "audio_ingress": .85,
                                         "independent_ASR": .85, "conditional_audio": .8,
                                         "conditional_video": .9, "distinct_frames_per_event": 6},
              "clock": {"input_event_seconds": 1, "output_event_seconds": 2,
                        "output_total_seconds": 4, "output_frames": 20, "output_fps": 5},
              "primary_observer": "consensus_or_single_v3", "component_observers": ["base.en", "small.en"],
              "ASR_execution": "Verified cache of byte-identical actual events; original cold ASR process cost retained",
              "after_outcomes": "No model, parser, threshold, condition, source, observer or projection change using these outcomes",
              "human_perceptual_certificate_claimed": False, "foundation_model_claimed": False, "authority": "deny_all"})
    print(json.dumps({"protocol_sha256": sha(args.output), "pins": len(pins)}))


if __name__ == "__main__":
    main()
