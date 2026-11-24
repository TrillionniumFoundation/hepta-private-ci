"""Explicit feature substitutions, with different objectives kept distinguishable.

HX equity uses the financial coordinate V_HX=b_HX*exp(margin). Only active
population contributes; refractory and escaped population have zero HX feature.
This feature is NOT the value of the regenerative finite process. The frozen
curve cache is inference-only for fixed financial parameters and fixed nodes.
"""

from dataclasses import dataclass, fields

import torch

from qualification.hcsn.tensor import HXParams, hx_boundary, hx_equity
from qualification.hcsn.tensor import prepare_hx_equity, prepared_hx_equity


def policy_call(model, state, drift, *, generator_event=None):
    """Reproduce the finite-policy Call; optionally reuse an already built G/k."""
    c, p = model.config, state.density[:, 0]
    if generator_event is None:
        generator, event, _ = model._generator(drift.to(p))
    else:
        generator, event = generator_event
    reward = torch.cat((c.gain*(state.boundary[:, None]+model.centers)-c.maintenance,
                        p.new_zeros(len(p), c.stages+1)), -1)-c.spike_cost*event
    value = torch.linalg.solve(c.discount*torch.eye(p.shape[-1], dtype=p.dtype,
                                                   device=p.device)-generator,
                               reward[..., None]).squeeze(-1)
    return (p*value).sum(-1)


def financial_parameters(params, like, *, gradient=False):
    """Use exactly the node dtype/device; optional new financial gradient leaves."""
    values = {f.name: torch.as_tensor(getattr(params, f.name), dtype=like.dtype,
                                     device=like.device) for f in fields(params)}
    if gradient:
        values = {name: value.detach().clone().requires_grad_() for name, value in values.items()}
    return HXParams(**values)


def hx_curve(nodes, params=None, *, method="direct"):
    """Full existing HX equity divided by its own financial default boundary."""
    par = financial_parameters(HXParams() if params is None else params, nodes)
    if method == "direct":
        return hx_equity(nodes, par)/hx_boundary(par)
    if method == "prepared":
        context = prepare_hx_equity(par, like=nodes)
        return prepared_hx_equity(nodes, context)/context.boundary
    raise ValueError("HX method must be direct or prepared")


@dataclass(frozen=True)
class FrozenHXCurve:
    """An explicit detached cache, bound to immutable parameter values and nodes."""

    nodes: torch.Tensor
    values: torch.Tensor
    parameters: tuple

    @classmethod
    def build(cls, nodes, params=None):
        par = HXParams() if params is None else params
        if nodes.requires_grad or any(isinstance(getattr(par, f.name), torch.Tensor)
                                      and getattr(par, f.name).requires_grad for f in fields(par)):
            raise ValueError("a frozen curve cannot retain trainable nodes or parameters")
        if any(torch.as_tensor(getattr(par, f.name)).ndim != 0 for f in fields(par)):
            raise ValueError("this frozen curve cache requires scalar financial parameters")
        with torch.no_grad():
            values = hx_curve(nodes, par, method="prepared").detach().clone()
        return cls(nodes.detach().clone(), values,
                   tuple((f.name, float(getattr(par, f.name))) for f in fields(par)))

    def apply(self, model, state):
        if (self.nodes.dtype != model.centers.dtype or self.nodes.device != model.centers.device
                or not torch.equal(self.nodes, model.centers)):
            raise ValueError("frozen HX grid/dtype/device identity changed")
        return (state.density[:, 0, :model.config.bins]*self.values).sum(-1)


def hx_active_feature(model, state, params=None, *, method="direct"):
    """Active-cell equity feature; phase/reset semantics are not inferred from HX."""
    return (state.density[:, 0, :model.config.bins]*hx_curve(model.centers, params,
                                                         method=method)).sum(-1)


def replace_call(features, replacement):
    """Functional ablation after step: this does not avoid the original Call cost."""
    if (features.ndim != 2 or replacement.shape != (len(features),)
            or not bool(torch.isfinite(replacement).all())):
        raise ValueError("finite [batch] Call replacement required")
    return torch.cat((features[:, :-1], replacement[:, None].to(features)), -1)
