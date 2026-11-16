"""Unchanged log-normal-CDF forward with a stable exact first derivative.

For z<=0, phi(z)/Phi(z)=sqrt(2/pi)/erfcx(-z/sqrt(2)). This avoids
subtracting huge, rounded log densities in the native backward. FP32 remains
FP32; no probability or derivative is clipped. Only first-order reverse-mode
autodiff is supported by this primitive. Higher-order derivatives are blocked.
"""

import math

import torch
from torch.autograd.function import once_differentiable


class _LogNormalCDF(torch.autograd.Function):
    @staticmethod
    def forward(ctx, value):
        ctx.save_for_backward(value)
        return torch.special.log_ndtr(value)

    @staticmethod
    @once_differentiable
    def backward(ctx, grad_output):
        value, = ctx.saved_tensors
        negative = value <= 0
        # Both unselected branches get safe inputs. In particular erfcx is
        # never evaluated at a large negative argument where it overflows.
        left = torch.where(negative, value, torch.zeros_like(value))
        right = torch.where(negative, torch.zeros_like(value), value)
        left_ratio = math.sqrt(2/math.pi)/torch.special.erfcx(-left/math.sqrt(2))
        right_ratio = torch.exp(-.5*right.square()-.5*math.log(2*math.pi)
                                -torch.special.log_ndtr(right))
        ratio = torch.where(negative, left_ratio, right_ratio)
        if not bool(torch.isfinite(ratio).all()):
            raise FloatingPointError("normal-CDF Mills ratio is unresolved in the input dtype")
        gradient = grad_output*ratio
        if not bool(torch.isfinite(gradient).all()):
            raise FloatingPointError("normal-CDF first derivative has a nonfinite upstream product")
        return gradient


def log_normal_cdf(value):
    if value.dtype not in (torch.float32, torch.float64) or not bool(torch.isfinite(value).all()):
        raise FloatingPointError("normal-CDF scores must be finite FP32/FP64 tensors")
    return _LogNormalCDF.apply(value)
