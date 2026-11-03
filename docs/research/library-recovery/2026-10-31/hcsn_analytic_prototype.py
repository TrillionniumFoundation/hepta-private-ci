#!/usr/bin/env python3
"""Minimal He--Xiong-inspired continuous free-boundary neural cell.

This implements a *new, simplified, perpetual optimal-stopping specialization*
with an analytic continuation (call-like) value, stopping (put-like) option,
and free boundary. It is NOT the full He--Xiong 2012 finite-maturity
rollover-equity formula (their equations (11), (12), and (A7)).

Equations: dV/V=(r-delta)dt + sigma*dW, V>0, r,delta,sigma,K>0.
Continuation equation: (L-r)C+delta*V-r*K=0 in V>V_B.
Boundary: C(V_B)=C'(V_B)=0.
Perpetual-put-style option P=C-(V-K).

Use: python hcsn_analytic_prototype.py
Dependencies: PyTorch CPU/GPU, Python 3.9+
"""
from __future__ import annotations
import math
import torch
from torch import nn
from torch.nn import functional as F


def analytic_free_boundary(v: torch.Tensor, k: torch.Tensor,
                           r: torch.Tensor, delta: torch.Tensor,
                           sigma: torch.Tensor):
    """Returns C, P, signed log margin, V_B, C_V, -P_V (broadcasting)."""
    if not torch.is_floating_point(v):
        raise TypeError("v must be floating point")
    if (not torch.all(v > 0)) or (not torch.all(k > 0)) or \
       (not torch.all(r > 0)) or (not torch.all(delta > 0)) or \
       (not torch.all(sigma > 0)):
        raise ValueError("v, k, r, delta and sigma must be strictly positive")
    sig2 = sigma.square()
    q = r - delta - 0.5 * sig2
    disc_sqrt = torch.sqrt(q.square() + 2 * r * sig2)
    # Numerically stable quadratic root: rationalize when q < 0.
    beta = torch.where(q >= 0,
                       (q + disc_sqrt) / sig2,
                       (2 * r) / (disc_sqrt - q))
    vb = (beta / (1.0 + beta)) * k
    log_ratio = torch.log(v) - torch.log(vb)
    active = log_ratio > 0
    # exp( -beta * log(V/V_B)) stays finite by clamping to continuation side
    option = (k - vb) * torch.exp(-beta * log_ratio.clamp(min=0))
    call = torch.where(active, v - k + option, torch.zeros_like(v))
    put = torch.where(active, option, k - v)
    # Derivative-value gates: C_V - P_V = 1. These gates are C^0, not C^1.
    active_gate = torch.where(active,
                              -torch.expm1(-(beta + 1) * log_ratio.clamp(min=0)),
                              torch.zeros_like(v))
    risk_gate = 1.0 - active_gate
    return call, put, log_ratio, vb, active_gate, risk_gate


class HCSNCell(nn.Module):
    """Simple differentiable recurrent cell using analytic boundary response.

    State h evolves by a stable exponential leak; V = K*exp(h). The learned
    state update is an engineering approximation, not a solution to the
    original firm's stationary GBM valuation problem.
    """
    def __init__(self, in_dim=2, hidden_dim=16):
        super().__init__()
        self.in_proj = nn.Linear(in_dim, hidden_dim)
        self.rec_proj = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.out_proj = nn.Linear(3*hidden_dim, hidden_dim)
        self.readout = nn.Linear(hidden_dim, 1)
        self.raw_k = nn.Parameter(torch.tensor(0.0))
        self.raw_r = nn.Parameter(torch.tensor(-2.2))
        self.raw_delta = nn.Parameter(torch.tensor(-3.0))
        self.raw_sigma = nn.Parameter(torch.tensor(-1.1))
        self.raw_leak = nn.Parameter(torch.tensor(0.0))

    def forward(self, seq, dt=1.0):
        if seq.ndim != 3:
            raise ValueError("Expected [batch, time, features]")
        batch, steps, _ = seq.shape
        h = seq.new_zeros(batch, self.in_proj.out_features)
        k = F.softplus(self.raw_k) + 0.1
        r = F.softplus(self.raw_r) + 0.005
        delta = F.softplus(self.raw_delta) + 0.005
        sigma = F.softplus(self.raw_sigma) + 0.01
        # Rate is positive and leak is in (0, 1) for positive dt.
        leak_rate = F.softplus(self.raw_leak) + 0.01
        retain = torch.exp(-leak_rate * dt)
        summaries = []
        for t in range(steps):
            proposal = torch.tanh(self.in_proj(seq[:,t]) + self.rec_proj(h))
            h = retain*h + (1.0-retain)*proposal
            v = k * torch.exp(h.clamp(min=-8., max=8.))
            c, p, margin, _, _, _ = analytic_free_boundary(v,k,r,delta,sigma)
            features = torch.cat((c/k, p/k, margin), dim=-1)
            summaries.append(torch.tanh(self.out_proj(features)))
        aggregate = torch.stack(summaries,1).mean(1) + summaries[-1]
        return self.readout(aggregate).squeeze(-1)


def numerical_sanity_checks():
    torch.set_default_dtype(torch.float64)
    k = torch.tensor(1.0,requires_grad=True)
    r = torch.tensor(0.05,requires_grad=True)
    d = torch.tensor(0.03,requires_grad=True)
    sig = torch.tensor(0.2,requires_grad=True)
    _,_,_,vb,_,_ = analytic_free_boundary(torch.tensor(1.0),k,r,d,sig)
    v_b = vb.detach()
    beta = (r-d-sig.square()/2+torch.sqrt((r-d-sig.square()/2)**2 +2*r*sig.square()))/sig.square()
    samples = torch.tensor([0.20, float(v_b)*0.99, float(v_b),
                            float(v_b)*1.01, 0.9, 1.5], requires_grad=True)
    c,p,m,b,g_c,g_p = analytic_free_boundary(samples,k,r,d,sig)
    dc = torch.autograd.grad(c.sum(),samples,create_graph=True)[0]
    dp = torch.autograd.grad(p.sum(),samples,create_graph=True)[0]
    assert torch.allclose(g_c,dc,atol=2e-12)
    assert torch.allclose(g_p,-dp,atol=2e-12)
    assert torch.max(torch.abs(g_c+g_p-1)) < 2e-12
    cb,pb,_,_,_,_ = analytic_free_boundary(v_b,k,r,d,sig)
    assert float(cb.detach().abs()) < 2e-12
    assert float((pb-(k-v_b)).detach().abs()) < 2e-12
    # Verify stationary HJB on the continuation interval with exact C''.
    vt = torch.tensor([float(v_b)*1.02, 0.9, 1.4, 2.0], requires_grad=True)
    C,_,_,_,_,_ = analytic_free_boundary(vt,k,r,d,sig)
    C1 = torch.autograd.grad(C.sum(),vt,create_graph=True)[0]
    C2 = torch.autograd.grad(C1.sum(),vt,create_graph=True)[0]
    residual = ((r-d)*vt*C1+0.5*sig.square()*vt.square()*C2
                +d*vt-r*k-r*C)
    assert float(residual.detach().abs().max()) < 1e-10
    # Check actual propagation to all parameters, including delta and sigma.
    loss = (c + 0.3*p +0.2*m).square().sum()
    grads = torch.autograd.grad(loss,(k,r,d,sig),allow_unused=False)
    assert all(bool(torch.isfinite(z).all()) for z in grads)
    assert all(float(z.abs()) > 1e-7 for z in grads)
    print(f"beta={float(beta.detach()):.6f}; boundary={float(v_b):.6f}")
    print(f"max stationary-HJB residual={float(residual.detach().abs().max()):.2e}")
    print(f"at boundary C={float(cb.detach()):.4g}, P={float(pb.detach()):.6f}; complementarity passed")
    print("input and parameter autograd checks: PASSED")


def trainability_smoke_test():
    torch.set_default_dtype(torch.float32)
    torch.manual_seed(21)
    batch,steps=128,24
    x = torch.randn(batch,steps,2)
    y = (x[:,12:,0].mean(dim=1)-x[:,:12,0].mean(dim=1) > 0).float()
    net = HCSNCell(in_dim=2,hidden_dim=12)
    opt = torch.optim.Adam(net.parameters(),lr=0.02)
    with torch.no_grad():
        loss_before=float(F.binary_cross_entropy_with_logits(net(x), y))
    for _ in range(30):
        opt.zero_grad(set_to_none=True)
        z=net(x)
        loss=F.binary_cross_entropy_with_logits(z,y)
        loss.backward()
        assert all(p.grad is None or bool(torch.isfinite(p.grad).all()) for p in net.parameters())
        opt.step()
    with torch.no_grad():
        pred = net(x)
        loss_after=float(F.binary_cross_entropy_with_logits(pred,y))
        accuracy=float(((pred>0)==(y>0.5)).float().mean())
    print(f"synthetic training smoke test: loss {loss_before:.4f} -> {loss_after:.4f}, "
          f"in-sample accuracy {accuracy:.1%}")
    print("CAUTION: smoke test only; not a generalization or performance benchmark.")


if __name__ == '__main__':
    numerical_sanity_checks()
    trainability_smoke_test()
