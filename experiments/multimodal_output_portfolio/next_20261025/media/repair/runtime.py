"""Predict once, then render a consistent finite-class canonical semantic state."""

from pathlib import Path
import time

import torch
from torch.nn import functional as F

from ....closure_20261025.media.network import ingress_state
from ....closure_20261025.media.sources import sha
from ..runtime import load_components as original_components
from ..runtime import render_state as original_render
from .model import load_ingress


def load_components(shared, restored, student, audio_input, original_audio_input):
    models, pins = original_components(shared, restored, student, original_audio_input)
    models["audio_input"] = load_ingress(audio_input)
    pins[str(Path(audio_input).resolve())] = sha(audio_input)
    return models, pins


@torch.inference_mode()
def render_state(generator, student, motion, state, directory, request_id, vae=None, seed=23117):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    posterior = generator.semantic_probabilities(state)
    commitment = F.one_hot(posterior.argmax(-1), 10).float()
    canonical = ingress_state(generator, commitment)
    for action in ("refine_semantic", "couple"):
        canonical = generator.step(canonical, action)
    projection_wall, projection_cpu = time.perf_counter_ns() - started, time.process_time_ns() - cpu
    result = original_render(generator, student, motion, canonical, directory, request_id, vae=vae, seed=seed)
    return {**result, "execution_wall_ns": projection_wall + result["execution_wall_ns"],
            "python_cpu_ns": projection_cpu + result["python_cpu_ns"],
            "input_public_semantic_posterior": posterior.tolist(),
            "semantic_commitment": commitment.argmax(-1).tolist(),
            "projection_wall_ns": projection_wall,
            "semantic_projection": "Predicted hard digit semantics re-enter the shared generator; no target is supplied",
            "preserves_input_handwriting_style": False,
            "scope": "Finite-class canonical multimodal output, not natural image/video preservation"}
