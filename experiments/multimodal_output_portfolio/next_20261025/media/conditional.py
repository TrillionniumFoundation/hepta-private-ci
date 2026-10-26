"""Keep the original conditional acoustic/video gates as an explicit census."""

from pathlib import Path

import torch

from ...closure_20261025.media.network import ingress_state
from ...closure_20261025.media.sources import save_json
from .runtime import render_state, observe_bundle
from .selected_event import score_selected_observation


def run_conditionals(models, audit, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    rows, audio_correct, frame_correct = [], 0, 0
    for digit in range(10):
        expected = [digit, (digit + 1) % 10]
        public_condition = torch.eye(10)[expected][None]
        with torch.inference_mode():
            state = ingress_state(models["generator"], public_condition)
            for action in ("refine_semantic", "couple"):
                state = models["generator"].step(state, action)
        generation = render_state(models["generator"], models["student"], models["motion"], state,
                                  directory / f"case-{digit:02d}", f"public-conditional-{digit}")
        observed = observe_bundle({k: v["path"] for k, v in generation["output"]["files"].items()},
                                  models["image_audit"], audit)
        score = score_selected_observation(observed, expected)
        audio_correct += sum(a == b for a, b in zip(observed["speech"]["predictions"]["base.en"], expected))
        frame_correct += sum(a == b for a, b in zip(observed["video_digits"], [x for d in expected for x in [d] * 10]))
        row = {"public_condition": expected, "generation": generation, "observation": observed, "score": score}
        save_json(directory / f"row-{digit:02d}.json", row)
        rows.append(row)
    result = {"conditional_cases": 10, "audio_digit_correct": audio_correct,
              "audio_digit_count": 20, "audio_accuracy": audio_correct / 20,
              "video_frame_correct": frame_correct, "video_frame_count": 200,
              "video_accuracy": frame_correct / 200,
              "audio_gate_min": .8, "video_gate_min": .9,
              "pass": audio_correct / 20 >= .8 and frame_correct / 200 >= .9,
              "independent_sources_added": 0}
    save_json(directory / "summary.json", result)
    return result
