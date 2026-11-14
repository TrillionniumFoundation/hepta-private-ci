"""P0 research-only CPU/f64 implicit-BP bridge for the scalar regenerative QVI.

This is the stationary Brownian threshold model in stopping.py: it is NOT
He--Xiong's coupled bond/equity fixed point, a real hard-FIRE derivative, or
an FP32/GPU/production implementation. Forward uses an independent Brent root;
backward uses the implicit smooth-fit derivative on the same root branch.
"""

import math

import torch

from .stopping import Stop, regenerative_boundary_independent


class UnresolvedBP(ValueError):
    """Explicit refusal of unsupported or numerically ambiguous gradients."""


class ScalarQVISmoothFit(torch.autograd.Function):
    """Return b(theta); theta=(drift, diffusion, discount, cost, reset, refractory)."""

    @staticmethod
    def forward(ctx, drift, diffusion, discount, cost, reset, refractory):
        params = (drift, diffusion, discount, cost, reset, refractory)
        if any(not isinstance(x, torch.Tensor) or x.numel() != 1
               or x.dtype != torch.float64 or x.device.type != 'cpu'
               for x in params):
            raise UnresolvedBP('requires six scalar CPU float64 tensors')
        if not all(bool(torch.isfinite(x).item()) for x in params):
            raise UnresolvedBP('nonfinite parameters refused')
        values = [float(x.detach().item()) for x in params]
        try:
            p = Stop(*values)
            k = p.kappa
            b = regenerative_boundary_independent(p)
            magnitude = math.hypot(p.drift, math.sqrt(2*p.discount) * p.diffusion)
            q = math.exp(-p.discount * p.refractory - k * (b - p.reset))
            # Psi(b)=k(b-cost)-1+q=0; Psi_b=k(1-q).
            psi_k = (b - p.cost) - (b - p.reset) * q
            psi_b = k * (1 - q)
            dk = (-k / magnitude, -p.diffusion * k*k / magnitude,
                  1 / magnitude)
            gradient = (
                -psi_k * dk[0] / psi_b,
                -psi_k * dk[1] / psi_b,
                -(psi_k * dk[2] - p.refractory * q) / psi_b,
                k / psi_b,
                -k * q / psi_b,
                p.discount * q / psi_b,
            )
        except (ValueError, OverflowError, ZeroDivisionError, ArithmeticError) as error:
            raise UnresolvedBP('scalar QVI/root unresolved') from error
        if not (math.isfinite(b) and b > p.cost and b > p.reset
                and math.isfinite(k) and k > 0 and math.isfinite(magnitude)
                and magnitude > 0 and 0 <= q < 1 and
                math.isfinite(psi_b) and psi_b > 1e-10 and
                all(math.isfinite(v) for v in gradient)):
            raise UnresolvedBP('ill-conditioned boundary implicit gradient')
        # An independent residual check also catches a lost root under roundoff.
        residual = math.fsum((k*(b-p.cost), q, -1))
        if abs(residual) > 2e-11:
            raise UnresolvedBP('Brent root fails finite-precision smooth-fit residual')
        ctx.first_derivatives = gradient
        return drift.new_tensor(b)

    @staticmethod
    def backward(ctx, grad_output):
        # This custom Function only certifies first-order implicit gradients.
        return tuple(grad_output * derivative for derivative in ctx.first_derivatives)


def scalar_qvi_features(states, drift, diffusion, discount, cost, reset, refractory):
    """(policy value, continue-minus-immediate-FIRE, signed state margin).

    One active boundary is fixed for the whole vector. A true event/reset is a
    separate discontinuous operation; this function never emits hard spikes.
    Refuse positions within 1e-9 relative distance of b rather than claiming
    the branch choice and its gradient are certified there.
    """
    if (not isinstance(states, torch.Tensor) or states.ndim != 1 or
            states.numel() == 0 or states.dtype != torch.float64 or
            states.device.type != 'cpu' or
            not bool(torch.isfinite(states).all())):
        raise UnresolvedBP('requires nonempty finite CPU float64 states')
    b = ScalarQVISmoothFit.apply(drift, diffusion, discount, cost, reset, refractory)
    if bool((torch.abs(states - b) <= 1e-9*(1 + torch.abs(b))).any()):
        raise UnresolvedBP('branch near free boundary is ambiguous')
    d = torch.sqrt(drift*drift + 2*discount*diffusion*diffusion)
    k = torch.where(drift >= 0, 2*discount/(d+drift), (d-drift)/(diffusion*diffusion))
    q = torch.exp(-discount*refractory-k*(b-reset))
    continuation = torch.exp(k*(states-b))/k
    immediate = states-cost+q/k
    value = torch.where(states < b, continuation, immediate)
    advantage = value-immediate
    if not all(bool(torch.isfinite(t).all()) for t in (value, advantage, states-b)):
        raise UnresolvedBP('nonfinite differentiable value features')
    if bool((advantage < -1e-9*torch.maximum(torch.ones_like(value),value.abs())).any()):
        raise UnresolvedBP('QVI obstacle inequality violated')
    return value, advantage, states-b
