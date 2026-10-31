"""Keep original encoder probabilities separate from the hard decoder commitment."""

import torch
from torch.nn import functional as F

from .....closure_20261025.media.network import ingress_state
from .....v7_media.corpus import speech_spectrum


@torch.inference_mode()
def generate_state(model, mode, observation, waveforms, clip, models):
    """Only observed tensors and model predictions enter; no target is available."""
    if mode == "text_image":
        state = model.encode(observation)
        probabilities = model.semantic_probabilities(state)
        belief = {"raw_encoder_probabilities": probabilities.tolist(),
                  "component_probabilities": {"text_image": probabilities.tolist()},
                  "hard_commitment_before_core": False}
    else:
        if mode not in {"audio", "video", "audio_video"}:
            raise ValueError("Unknown actual input route")
        estimates = {}
        if mode in {"audio", "audio_video"}:
            estimates["audio"] = models["audio_input"](speech_spectrum(waveforms)).softmax(-1).reshape(1, 2, 10)
        if mode in {"video", "audio_video"}:
            estimates["video"] = models["video_input"](clip).softmax(-1)
        probabilities = torch.stack(list(estimates.values())).mean(0)
        commitment = F.one_hot(probabilities.argmax(-1), 10).float()
        state = ingress_state(model, commitment)
        belief = {"raw_encoder_probabilities": probabilities.tolist(),
                  "component_probabilities": {name: value.tolist() for name, value in estimates.items()},
                  "decoder_commitment": commitment.argmax(-1).tolist(),
                  "hard_commitment_before_core": True,
                  "tradeoff": "Discrete encoder class is fixed for this decoding pass; later soft core corrections are forgone"}
    for action in ("refine_semantic", "couple"):
        state = model.step(state, action)
    belief["uncertainty_source"] = "Retained raw encoder probabilities, separate from the committed decoding state"
    belief["target_supplied"] = False
    return state, belief
