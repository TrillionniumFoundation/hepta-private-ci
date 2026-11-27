"""Architecture, causality and independent numerical/gradient parity checks.

The upstream scan oracle below is adapted from the pinned Mamba source.
Copyright (c) 2023, Tri Dao, Albert Gu. Apache-2.0; see BASELINES.md.
"""

import math
import sys
from pathlib import Path

import pytest
import torch
from einops import rearrange, repeat
from torch.nn import functional as F

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from baseline import (
    BASELINE_NAMES,
    Mamba1CPU,
    SDPABlock,
    _SurrogateSpike,
    build_baseline,
    match_parameter_budget,
    parameter_count,
    profile_sdpa_operators,
    selective_scan_cpu,
)


@pytest.fixture(autouse=True)
def deterministic_small_cpu_tests():
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(74)
        yield


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_shapes_causality_and_real_parameter_gradients(name):
    model = build_baseline(name, width=8, depth=2)
    x = torch.randn(3, 7, 8, requires_grad=True)
    dt = torch.rand(3, 7) + 0.2
    sequence, aux = model(x, dt)
    assert sequence.shape == x.shape
    assert torch.isfinite(sequence).all()
    perturbed = x.detach().clone()
    perturbed[:, 4:] += 5.0 * torch.randn_like(perturbed[:, 4:])
    altered, _ = model(perturbed, dt)
    torch.testing.assert_close(sequence[:, :4], altered[:, :4], rtol=1e-5, atol=1e-6)
    (sequence * torch.randn_like(sequence)).sum().backward()
    assert torch.isfinite(x.grad).all() and x.grad.abs().sum() > 0
    for parameter_name, parameter in model.named_parameters():
        assert parameter.grad is not None, f"unused parameter: {parameter_name}"
        assert torch.isfinite(parameter.grad).all(), parameter_name
    assert aux["n_parameters"] == parameter_count(model)


def test_lif_hard_events_and_surrogate_derivative():
    margin = torch.tensor([-0.9, -0.1, 0.1, 0.9], requires_grad=True)
    spike = _SurrogateSpike.apply(margin)
    torch.testing.assert_close(spike, torch.tensor([0.0, 0.0, 1.0, 1.0]))
    spike.sum().backward()
    torch.testing.assert_close(margin.grad, 1.0 / (1.0 + 5.0 * margin.abs()).square())
    model = build_baseline("lif_snn", 4)
    with torch.no_grad():
        model.blocks[0].cell.input.weight.fill_(0.4)
        model.blocks[0].cell.input.bias.fill_(0.5)
    out, aux = model(torch.ones(2, 8, 4), torch.ones(2, 8))
    assert torch.all((out == 0) | (out == 1)) and aux["event_count"] > 0


def test_cfc_matches_independent_published_gate_formula_and_gradients():
    model = build_baseline("cfc", 5).double()
    cell = model.blocks[0].cell
    x = torch.randn(3, 6, 5, dtype=torch.float64, requires_grad=True)
    dt = (torch.rand(3, 6, dtype=torch.float64) + 0.05).requires_grad_()
    actual, _ = model(x, dt)
    hidden = torch.zeros_like(x[:, 0])
    expected = []
    for t in range(x.shape[1]):
        joint = torch.cat((x[:, t], hidden), dim=-1)
        # ncps 1.0.1 LeCun backbone; an independent formula, not cell.forward.
        features = 1.7159 * torch.tanh(
            0.666 * F.linear(joint, cell.backbone[0].weight, cell.backbone[0].bias)
        )
        first = torch.tanh(F.linear(features, cell.ff1.weight, cell.ff1.bias))
        second = torch.tanh(F.linear(features, cell.ff2.weight, cell.ff2.bias))
        a = F.linear(features, cell.time_a.weight, cell.time_a.bias)
        b = F.linear(features, cell.time_b.weight, cell.time_b.bias)
        gate = torch.sigmoid(a * dt[:, t, None] + b)
        hidden = first * (1.0 - gate) + second * gate
        expected.append(hidden)
    expected = torch.stack(expected, dim=1)
    torch.testing.assert_close(actual, expected, rtol=1e-12, atol=1e-12)
    leaves = (x, dt, *model.parameters())
    probe = torch.randn_like(actual)
    grad_actual = torch.autograd.grad((probe * actual).sum(), leaves, retain_graph=True)
    grad_expected = torch.autograd.grad((probe * expected).sum(), leaves)
    for a, b in zip(grad_actual, grad_expected):
        torch.testing.assert_close(a, b, rtol=1e-11, atol=1e-11)


def _upstream_selective_scan_ref(
    u,
    delta,
    A,
    B,
    C,
    D=None,
    z=None,
    delta_bias=None,
    delta_softplus=False,
    return_last_state=False,
):
    """Pinned upstream selective_scan_ref, with only signature/name/doc formatting changed.

    Source: state-spaces/mamba e0761ece1db07e0949dd88b4f4cd440420a19fd9,
    mamba_ssm/ops/selective_scan_interface.py; Git blob a41f1359c2463e69a2a8e52035749893f126769a.
    """
    dtype_in = u.dtype
    u = u.float()
    delta = delta.float()
    if delta_bias is not None:
        delta = delta + delta_bias[..., None].float()
    if delta_softplus:
        delta = F.softplus(delta)
    batch, dim, dstate = u.shape[0], A.shape[0], A.shape[1]
    is_variable_B = B.dim() >= 3
    is_variable_C = C.dim() >= 3
    if A.is_complex():
        if is_variable_B:
            B = torch.view_as_complex(
                rearrange(B.float(), "... (L two) -> ... L two", two=2)
            )
        if is_variable_C:
            C = torch.view_as_complex(
                rearrange(C.float(), "... (L two) -> ... L two", two=2)
            )
    else:
        B = B.float()
        C = C.float()
    x = A.new_zeros((batch, dim, dstate))
    ys = []
    deltaA = torch.exp(torch.einsum("bdl,dn->bdln", delta, A))
    if not is_variable_B:
        deltaB_u = torch.einsum("bdl,dn,bdl->bdln", delta, B, u)
    else:
        if B.dim() == 3:
            deltaB_u = torch.einsum("bdl,bnl,bdl->bdln", delta, B, u)
        else:
            B = repeat(B, "B G N L -> B (G H) N L", H=dim // B.shape[1])
            deltaB_u = torch.einsum("bdl,bdnl,bdl->bdln", delta, B, u)
    if is_variable_C and C.dim() == 4:
        C = repeat(C, "B G N L -> B (G H) N L", H=dim // C.shape[1])
    last_state = None
    for i in range(u.shape[2]):
        x = deltaA[:, :, i] * x + deltaB_u[:, :, i]
        if not is_variable_C:
            y = torch.einsum("bdn,dn->bd", x, C)
        else:
            if C.dim() == 3:
                y = torch.einsum("bdn,bn->bd", x, C[:, :, i])
            else:
                y = torch.einsum("bdn,bdn->bd", x, C[:, :, :, i])
        if i == u.shape[2] - 1:
            last_state = x
        if y.is_complex():
            y = y.real * 2
        ys.append(y)
    y = torch.stack(ys, dim=2)
    out = y if D is None else y + u * rearrange(D, "d -> d 1")
    if z is not None:
        out = out * F.silu(z)
    out = out.to(dtype=dtype_in)
    return out if not return_last_state else (out, last_state)


def test_mamba_scan_output_and_all_input_gradients_match_upstream():
    batch, channels, length, state = 2, 7, 9, 4
    tensors = [
        torch.randn(batch, channels, length),
        torch.randn(batch, channels, length),
        -torch.rand(channels, state),
        torch.randn(batch, state, length),
        torch.randn(batch, state, length),
        torch.randn(channels),
        torch.randn(batch, channels, length),
        torch.randn(channels),
    ]
    u, delta, A, B, C, D, z, bias = [v.requires_grad_() for v in tensors]
    actual = selective_scan_cpu(
        u.transpose(1, 2),
        delta.transpose(1, 2),
        A,
        B.transpose(1, 2),
        C.transpose(1, 2),
        D,
        z.transpose(1, 2),
        bias,
    ).transpose(1, 2)
    expected = _upstream_selective_scan_ref(u, delta, A, B, C, D, z, bias, True)
    torch.testing.assert_close(actual, expected, rtol=2e-6, atol=2e-6)
    probe = torch.randn_like(actual)
    grad_actual = torch.autograd.grad(
        (probe * actual).sum(), tensors, retain_graph=True
    )
    grad_expected = torch.autograd.grad((probe * expected).sum(), tensors)
    for a, b in zip(grad_actual, grad_expected):
        torch.testing.assert_close(a, b, rtol=5e-5, atol=5e-6)


def _official_mamba_forward_formula(module, hidden):
    """Upstream non-fused mixer path, expressed with its original B,D,L layout."""
    length = hidden.shape[1]
    xz = rearrange(
        module.in_proj.weight @ rearrange(hidden, "b l d -> d (b l)"),
        "d (b l) -> b d l",
        l=length,
    )
    x, z = xz.chunk(2, dim=1)
    x = F.silu(
        F.conv1d(
            x,
            module.conv1d.weight,
            module.conv1d.bias,
            padding=module.d_conv - 1,
            groups=module.d_inner,
        )[..., :length]
    )
    x_dbl = F.linear(rearrange(x, "b d l -> (b l) d"), module.x_proj.weight)
    delta, B, C = x_dbl.split((module.dt_rank, module.d_state, module.d_state), dim=-1)
    delta = rearrange(module.dt_proj.weight @ delta.t(), "d (b l) -> b d l", l=length)
    B = rearrange(B, "(b l) n -> b n l", l=length)
    C = rearrange(C, "(b l) n -> b n l", l=length)
    y = _upstream_selective_scan_ref(
        x,
        delta,
        -module.A_log.float().exp(),
        B,
        C,
        module.D.float(),
        z,
        module.dt_proj.bias.float(),
        True,
    )
    return F.linear(rearrange(y, "b d l -> b l d"), module.out_proj.weight)


def test_complete_mamba_mixer_matches_official_nonfused_path_and_gradients():
    model = Mamba1CPU(8, d_state=5)
    x = torch.randn(2, 9, 8, requires_grad=True)
    actual = model(x)
    expected = _official_mamba_forward_formula(model, x)
    torch.testing.assert_close(actual, expected, rtol=3e-6, atol=3e-7)
    leaves = (x, *model.parameters())
    probe = torch.randn_like(actual)
    grad_actual = torch.autograd.grad((probe * actual).sum(), leaves, retain_graph=True)
    grad_expected = torch.autograd.grad((probe * expected).sum(), leaves)
    for a, b in zip(grad_actual, grad_expected):
        torch.testing.assert_close(a, b, rtol=5e-5, atol=2e-6)


def test_sdpa_matches_explicit_causal_attention_output_and_gradients():
    model = SDPABlock(8, heads=2).double()
    x = torch.randn(2, 7, 8, dtype=torch.float64, requires_grad=True)
    dt = torch.ones(2, 7, dtype=torch.float64)
    actual = model(x, dt)
    projected = model.qkv(model.norm1(x)).view(2, 7, 3, 2, 4)
    q, k, v = projected.permute(2, 0, 3, 1, 4).unbind(0)
    scores = q @ k.transpose(-1, -2) / math.sqrt(4)
    future = torch.ones(7, 7, dtype=torch.bool).triu(diagonal=1)
    scores = scores.masked_fill(future, float("-inf"))
    attended = (scores.softmax(-1) @ v).transpose(1, 2).reshape(2, 7, 8)
    residual = x + model.proj(attended)
    expected = residual + model.ffn(model.norm2(residual))
    torch.testing.assert_close(actual, expected, rtol=1e-10, atol=1e-10)
    probe = torch.randn_like(actual)
    leaves = (x, *model.parameters())
    grad_actual = torch.autograd.grad((actual * probe).sum(), leaves, retain_graph=True)
    grad_expected = torch.autograd.grad((expected * probe).sum(), leaves)
    for a, b in zip(grad_actual, grad_expected):
        torch.testing.assert_close(a, b, rtol=1e-9, atol=1e-9)


def test_sdpa_runtime_reports_an_actual_attention_operator():
    model = build_baseline("transformer", 16)
    operations = profile_sdpa_operators(
        model, torch.randn(2, 16, 16), torch.ones(2, 16)
    )
    assert "aten::scaled_dot_product_attention" in operations
    assert any(name != "aten::scaled_dot_product_attention" for name in operations)


def test_capacity_matching_preserves_rng_and_uses_active_projection_weights():
    rng_before = torch.random.get_rng_state().clone()
    match = match_parameter_budget("two_gates", 8, 1700, candidates=range(4, 24))
    assert torch.equal(rng_before, torch.random.get_rng_state())
    model = build_baseline("two_gates", 8, hidden_width=match["hidden_width"])
    assert parameter_count(model) == match["n_parameters"]
    costs = [
        parameter_count(build_baseline("two_gates", 8, hidden_width=h))
        for h in range(4, 24)
    ]
    assert abs(parameter_count(model) - 1700) == min(
        abs(count - 1700) for count in costs
    )
    out, _ = model(torch.randn(3, 7, 8), torch.ones(3, 7))
    out.square().mean().backward()
    assert all(
        p.grad is not None and p.grad.abs().sum() > 0 for p in model.parameters()
    )


@pytest.mark.parametrize("name", BASELINE_NAMES)
def test_shared_head_training_decreases_fixed_sequence_loss(name):
    model = build_baseline(name, 6)
    head = torch.nn.Linear(6, 1)
    x = torch.randn(8, 6, 6)
    dt = torch.ones(8, 6)
    target = x[:, :, :2].mean(dim=(1, 2))
    optimizer = torch.optim.Adam([*model.parameters(), *head.parameters()], lr=0.02)
    losses = []
    for _ in range(30):
        optimizer.zero_grad()
        features, _ = model(x, dt)
        loss = F.mse_loss(head(features[:, -1]).squeeze(-1), target)
        losses.append(float(loss.detach()))
        loss.backward()
        optimizer.step()
    assert min(losses[-5:]) < 0.9 * losses[0], (name, losses[0], losses[-1])
