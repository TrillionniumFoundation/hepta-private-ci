"""Fixed v4 graph with explicit frozen/shared and private parameter ownership.

A checkpoint must establish its own task capability. Freezing random weights
or switching a temporal kernel does not confer semantic qualification.
"""

import hashlib

import torch

from scripts.joint_generation_v4_codecs import flush_mean
from scripts.joint_generation_v4_io import (
    DeliveryObservation,
    framed_media,
    packet_bytes,
    read_packet,
)
from scripts.joint_generation_v4_model import public_packet
from .native import load_generator


FIXED_GRAPH = ("text", "image")
PRIVATE_PREFIXES = (
    "adapters.text.",
    "adapters.image.",
    "emissions.text.",
    "emissions.image.",
)
KERNELS = ("dual", "ordinary")


def shared_digest(model):
    """Bind all frozen parameters, including the selected temporal kernel."""
    tensors = {
        name: value
        for name, value in model.state_dict().items()
        if not name.startswith(PRIVATE_PREFIXES)
    }
    return hashlib.sha256(
        packet_bytes({"mode": model.mode, "boundary": model.boundary}, tensors)
    ).hexdigest()


def private_training_parameters(model):
    """Freeze the shared checkpoint and return only modality-private tensors."""
    parameters = []
    for name, parameter in model.named_parameters():
        private = name.startswith(PRIVATE_PREFIXES)
        parameter.requires_grad_(private)
        parameter.grad = None
        if private:
            parameters.append(parameter)
    if not parameters:
        raise ValueError("Checkpoint has no supported private parameters")
    return parameters


def load_with_kernel(raw, *, kernel):
    """Switch parameter-matched laws; each kernel needs separate qualification."""
    if kernel not in KERNELS:
        raise ValueError("Unsupported temporal kernel")
    metadata, tensors = read_packet(raw)
    original = load_generator(raw)
    if original.mode not in KERNELS:
        raise ValueError("Unsupported source temporal kernel")
    metadata["mode"] = kernel
    return load_generator(packet_bytes(metadata, tensors))


def forward_graph(model, public):
    """The exact action graph shared by training, adaptation and decoding."""
    state = model.encode(public)
    for action in FIXED_GRAPH:
        state = model.advance(state, action, public)
    return state


def deliver(model, public):
    """Decode both actual modalities, never a teacher-forced response."""
    with torch.no_grad():
        state = forward_graph(model, public)
        task = hashlib.sha256(public_packet(public)).digest()
        owner = DeliveryObservation(9, 0, 30_000_000, 30_000_000, task)
        state = model.advance(state, "stop", public)
        _, _, framed = flush_mean(model, state, owner)
    cursors, media = framed_media(framed)
    return {
        "text": media[3].decode("utf-8"),
        "image": media[0],
        "cursors": cursors,
        "framed_sha256": hashlib.sha256(framed).hexdigest(),
    }
