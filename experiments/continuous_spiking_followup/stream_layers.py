"""One-token implementations of the immutable study001 recurrence equations.

The Mamba adaptation follows the existing equation-verified CPU reference.
Copyright (c) 2023, Tri Dao, Albert Gu. Apache-2.0; see the study001 BASELINES.md.
These routines retain recurrent state or causal KV caches, never input prefixes.
"""

import math

import torch
from torch.nn import functional as F

from experiments.continuous_spiking_network.cell import ContinuousSpikingBlock
from experiments.continuous_spiking_network.kernels import reset_at_interval_end_mean


def initial_layers(model, batch_size, steps=0):
    """Allocate the actual state schema, including a specified KV-cache length."""
    backbone = model.backbone
    anchor = next(model.parameters())
    if isinstance(backbone, ContinuousSpikingBlock):
        return [
            {
                name: anchor.new_zeros(batch_size, layer.width)
                for name in ("content", "voltage", "adaptation", "event")
            }
            for layer in backbone.layers
        ]
    result = []
    for block in backbone.blocks:
        width = backbone.hidden_width
        if backbone.name == "lif_snn":
            state = {
                "membrane": anchor.new_zeros(batch_size, width),
                "spike": anchor.new_zeros(batch_size, width),
            }
        elif backbone.name == "mamba1":
            mixer = block.mixer
            state = {
                "conv": anchor.new_zeros(batch_size, mixer.d_inner, mixer.d_conv - 1),
                "ssm": torch.zeros(
                    batch_size,
                    mixer.d_inner,
                    mixer.d_state,
                    device=anchor.device,
                    dtype=torch.float32,
                ),
            }
        elif backbone.name == "transformer":
            state = {
                name: anchor.new_zeros(
                    batch_size, block.heads, steps, width // block.heads
                )
                for name in ("key", "value")
            }
        else:
            state = {"hidden": anchor.new_zeros(batch_size, width)}
        result.append(state)
    return result


def _continuous_step(layer, x, duration, state):
    content, voltage = state["content"], state["voltage"]
    adaptation, previous_event = state["adaptation"], state["event"]
    diffusion = F.softplus(layer.raw_diffusion) + 1e-4
    boundary = (
        F.softplus(layer.raw_boundary) + 1e-4
        if layer.boundary_mode == "direct"
        else layer.fixed_boundary
    )
    signal = layer.norm(x)
    gates = layer.channel_gates(torch.cat((signal, content), dim=-1)).sigmoid()
    if layer.mode == "single":
        recovery_gate, regeneration_gate = gates, torch.zeros_like(gates)
    else:
        recovery_gate, regeneration_gate = gates.chunk(2, dim=-1)
    recovery = F.softplus(layer.raw_recovery) * recovery_gate
    regeneration = F.softplus(layer.raw_regeneration) * regeneration_gate
    if layer.mode == "single":
        regeneration = torch.zeros_like(regeneration)
    drift = (
        layer.drift_bias
        + layer.drift_input(signal).tanh()
        - recovery * voltage
        + regeneration * previous_event
        - adaptation
    )
    pre_reset_mean = voltage + duration * drift
    if layer.mode == "ordinary":
        event = torch.sigmoid(
            (duration * drift - (boundary - voltage))
            / (diffusion * duration.clamp_min(1e-8).sqrt())
        ) * (duration > 0)
        voltage = (1 - event) * pre_reset_mean
    else:
        voltage, terms = reset_at_interval_end_mean(
            voltage, boundary, drift, diffusion, duration
        )
        event = terms["cdf"]
    if layer.mode != "no_adaptation":
        adaptation = (
            adaptation * torch.exp(-F.softplus(layer.raw_adaptation_decay) * duration)
            + F.softplus(layer.raw_adaptation) * event
        )
    candidate = torch.tanh(layer.content_input(signal) + layer.content_state(content))
    write = 1 - (1 - event) * torch.exp(-F.softplus(layer.raw_content_rate) * duration)
    content = (1 - write) * content + write * candidate
    next_state = {
        "content": content,
        "voltage": voltage,
        "adaptation": adaptation,
        "event": torch.where(duration > 0, event, previous_event),
    }
    aux = {
        "content": content,
        "voltage": voltage,
        "adaptation": adaptation,
        "event_probability": event,
        "recovery": recovery,
        "regeneration": regeneration,
        "drift": drift,
        "pre_reset_mean": pre_reset_mean,
        "diffusion": diffusion,
        "boundary": boundary,
        "margin": boundary - voltage,
    }
    return x + layer.output(content), next_state, aux


def _mamba_step(block, x, state):
    mixer = block.mixer
    u, z = mixer.in_proj(block.norm(x)).chunk(2, dim=-1)
    window = torch.cat((state["conv"], u.unsqueeze(-1)), dim=-1)
    u = F.silu(
        F.conv1d(
            window, mixer.conv1d.weight, mixer.conv1d.bias, groups=mixer.d_inner
        ).squeeze(-1)
    )
    delta, b, c = mixer.x_proj(u).split(
        (mixer.dt_rank, mixer.d_state, mixer.d_state), dim=-1
    )
    delta = F.softplus(
        F.linear(delta, mixer.dt_proj.weight).float() + mixer.dt_proj.bias.float()
    )
    step = delta.unsqueeze(-1)
    a = -mixer.A_log.float().exp()
    ssm = torch.exp(step * a[None]) * state["ssm"] + step * b.float().unsqueeze(
        1
    ) * u.float().unsqueeze(-1)
    y = (ssm * c.float().unsqueeze(1)).sum(-1) + u.float() * mixer.D.float()
    y = (y * F.silu(z)).to(u.dtype)
    return x + mixer.out_proj(y), {"conv": window[..., 1:].clone(), "ssm": ssm}


def _attention_step(block, x, state):
    batch, width = x.shape
    qkv = block.qkv(block.norm1(x)).reshape(
        batch, 1, 3, block.heads, width // block.heads
    )
    query, key, value = qkv.permute(2, 0, 3, 1, 4).unbind(0)
    key = torch.cat((state["key"], key), dim=2)
    value = torch.cat((state["value"], value), dim=2)
    # This query is the LAST position. Every cached key is causal; is_causal=True
    # with a one-token query would incorrectly mask all but the first key.
    y = F.scaled_dot_product_attention(
        query, key, value, dropout_p=0.0, is_causal=False
    )
    x = x + block.proj(y.transpose(1, 2).reshape(batch, width))
    return x + block.ffn(block.norm2(x)), {"key": key, "value": value}


def advance_backbone(model, x, dt, elapsed, states):
    """Consume exactly one new observation per active row."""
    backbone, next_states = model.backbone, []
    duration = dt[:, None]
    if isinstance(backbone, ContinuousSpikingBlock):
        aux = {}
        for layer, state in zip(backbone.layers, states, strict=True):
            x, next_state, aux = _continuous_step(layer, x, duration, state)
            next_states.append(next_state)
        return x, next_states, aux
    x = backbone.input_proj(x)
    if backbone.name == "transformer":
        frequency = torch.exp(
            torch.arange(0, backbone.hidden_width, 2, device=dt.device, dtype=dt.dtype)
            * (-math.log(10000.0) / backbone.hidden_width)
        )
        phase = elapsed[:, None] * frequency
        x = (
            x
            + torch.stack((phase.sin(), phase.cos()), dim=-1).flatten(-2)[
                :, : backbone.hidden_width
            ]
        )
    event_count = x.new_zeros(())
    for block, state in zip(backbone.blocks, states, strict=True):
        if backbone.name == "mamba1":
            x, next_state = _mamba_step(block, x, state)
        elif backbone.name == "transformer":
            x, next_state = _attention_step(block, x, state)
        elif backbone.name == "lif_snn":
            x, pair = block.cell.step(x, (state["membrane"], state["spike"]), duration)
            next_state = dict(zip(("membrane", "spike"), pair, strict=True))
            event_count = event_count + x.sum()
        else:
            if backbone.name == "cfc":
                x, hidden = block.cell(x, state["hidden"], duration)
            else:
                x, hidden = block.cell.step(x, state["hidden"], duration)
            next_state = {"hidden": hidden}
        next_states.append(next_state)
    return (
        backbone.output_proj(x),
        next_states,
        {
            "architecture": backbone.name,
            "event_count": event_count,
        },
    )
