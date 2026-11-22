"""Three explicitly different content laws on the same held finite generator.

legacy_observation writes .35 at every observation. event_mask writes .35 only
at a declared physical mark. continuous_write is a NEW process, not a numerical
repair of either event law: p'=pG, q'=qG-k*qD+k*m*pD, with active-state D.
For a held mark, e=q-mp satisfies e'=e(G-kD). Two small exponentials therefore
give exactly the same flow as the larger coupled block generator. Exactness is
only for the declared finite held process, not moving-boundary diffusion.
"""

import math

import torch

from qualification.hcsn_adaptive.batched_flow import FlowState
from qualification.hcsn_confirmatory_v1.semantic_program import shared_encoder_prior
from qualification.hcsn_prepared.model import PreparedSequenceModel
from qualification.hcsn_scale.model import ModelConfig


LAWS = ("legacy_observation", "event_mask", "continuous_write")
WRITE_RATE = -math.log(0.65) / 0.1


def continuous_content_transition(
    density, mark, transition, killed_transition, event_integral, killed_event_integral
):
    """Held-input exact state and integrated marked-event output; row vectors."""
    probability, content = density[:, :1], density[:, 1:]
    residual = content - mark[:, :, None] * probability
    next_p = probability @ transition
    next_q = mark[:, :, None] * next_p + residual @ killed_transition
    count = probability @ event_integral
    signed = mark[:, :, None] * count + residual @ killed_event_integral
    return torch.cat((next_p, next_q), 1), torch.cat((count, signed), 1).squeeze(-1)


def make_clock_model():
    """Frozen semantic parameters, independent of every training/final label."""
    model = PreparedSequenceModel(ModelConfig("hcsn", 4, 4, 0.1))
    shared_encoder_prior(model, "association")
    with torch.no_grad():
        model.encoder.drive.weight[0, :2] = torch.tensor(
            [0.2, -0.1], dtype=torch.float64
        )
        model.boundary.weight[0, :2] = torch.tensor([0.3, 0.15], dtype=torch.float64)
    return model.eval()


def _operators(model, inputs, intervals, write_rate):
    durations = model._validate_windows(inputs, intervals)
    batch, steps, _ = inputs.shape
    encoder, c = model.encoder, model.encoder.config
    flat = inputs.reshape(-1, 4)
    boundary = model.config.boundary_scale * model.boundary(flat).tanh().squeeze(-1)
    marks = encoder.writer(flat).tanh()
    drift = c.base_drift + c.drift_scale * encoder.drive(flat).squeeze(-1).tanh()
    generator, event, _ = encoder._generator(drift)
    size, total = generator.shape[-1], len(flat)
    active = torch.cat((flat.new_ones(c.bins), flat.new_zeros(c.stages + 1)))
    rewards = torch.stack((event, active.expand_as(event)), -1)
    augmented = torch.cat(
        (torch.cat((generator, rewards), -1), flat.new_zeros(total, 2, size + 2)), -2
    )
    action = torch.matrix_exp(augmented * durations.reshape(-1, 1, 1))
    killed = generator - write_rate * torch.diag(active)
    killed_aug = torch.cat(
        (torch.cat((killed, event[..., None]), -1), flat.new_zeros(total, 1, size + 1)),
        -2,
    )
    killed_action = torch.matrix_exp(killed_aug * durations.reshape(-1, 1, 1))
    return (
        boundary.reshape(batch, steps),
        marks.reshape(batch, steps, -1),
        action.reshape(batch, steps, size + 2, size + 2),
        killed_action.reshape(batch, steps, size + 1, size + 1),
        durations,
    )


def execute_sequence(model, data, law, write_rate=WRITE_RATE):
    """Finite batch; caller chunks larger datasets and charges all preparation.

    Output terminal density and cumulative marked events have exact held-process
    meanings. No right-endpoint quadrature is substituted for these quantities.
    All three arms prepare both kernels, so this is not an efficiency comparison.
    """
    if law not in LAWS or not math.isfinite(write_rate) or write_rate <= 0:
        raise ValueError("declared content law and finite positive rate required")
    inputs = torch.as_tensor(data["x"], dtype=torch.float64)
    intervals = torch.as_tensor(data["dt"], dtype=torch.float64)
    writes = torch.as_tensor(data["write_mask"], dtype=torch.float64)
    if writes.shape != intervals.shape or not bool(
        ((writes == 0) | (writes == 1)).all()
    ):
        raise ValueError("a physical binary write mask is required for every arm")
    boundary, marks, actions, killed, durations = _operators(
        model, inputs, intervals, write_rate
    )
    encoder, c = model.encoder, model.encoder.config
    initial = encoder.initial_state(len(inputs))
    density, previous = initial.density, initial.boundary
    counts = inputs.new_zeros(len(inputs), 1 + c.content_size)
    occupation = inputs.new_zeros(len(inputs))
    max_mass_error, max_content_excess, min_probability = 0.0, 0.0, 1.0
    size = density.shape[-1]
    for t in range(inputs.shape[1]):
        state = FlowState(density, previous, 0, c)
        remapped, _, jump, _ = encoder._remap(state, boundary[:, t])
        transition = actions[:, t, :size, :size]
        event_integral = actions[:, t, :size, size : size + 1]
        occupation = occupation + (remapped[:, 0] * actions[:, t, :size, size + 1]).sum(
            -1
        )
        if law == "continuous_write":
            density, increments = continuous_content_transition(
                remapped,
                marks[:, t],
                transition,
                killed[:, t, :size, :size],
                event_integral,
                killed[:, t, :size, size : size + 1],
            )
        else:
            fraction = inputs.new_full((len(inputs), 1, 1), c.write_fraction)
            if law == "event_mask":
                fraction = fraction * writes[:, t, None, None]
            content = (1 - fraction) * remapped[:, 1:, : c.bins] + fraction * marks[
                :, t, :, None
            ] * remapped[:, :1, : c.bins]
            written = torch.cat(
                (remapped[:, :1], torch.cat((content, remapped[:, 1:, c.bins :]), -1)),
                1,
            )
            density = written @ transition
            increments = (written @ event_integral).squeeze(-1)
        counts = counts + jump + increments
        encoder.validate_state(
            FlowState(density, boundary[:, t], 0, c),
            len(inputs),
            density.dtype,
            density.device,
        )
        p = density[:, :1]
        max_mass_error = max(
            max_mass_error, float((p.sum(-1) - 1).abs().max().detach())
        )
        max_content_excess = max(
            max_content_excess, float((density[:, 1:].abs() - p).max().detach())
        )
        min_probability = min(min_probability, float(p.min().detach()))
        previous = boundary[:, t]
    if not bool(torch.isfinite(counts).all()) or not bool(
        torch.isfinite(occupation).all()
    ):
        raise FloatingPointError("nonfinite cumulative observables")
    return {
        "density": density,
        "counts": counts,
        "occupation_integral": occupation,
        "boundary": previous,
        "time_micros": (durations.sum(1) * 1e6).round().to(torch.int64),
        "invariants": {
            "max_mass_error": max_mass_error,
            "max_content_excess": max_content_excess,
            "min_probability": min_probability,
        },
    }
