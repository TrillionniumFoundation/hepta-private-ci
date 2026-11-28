"""Matrix-free killed Brownian transport on the fixed uniform HCSN grid.

NumPy uses SciPy's Gaussian CDF. Torch tensors use native differentiable Torch
operations on their input device. Shapes are (..., atoms) for mass, (...,) for
log-boundary shift, and (atoms,) for grid. Uniformity is a model precondition.
"""
import math


class _ArrayOps:
    def __init__(self, sample):
        self.torch = type(sample).__module__.split(".")[0] == "torch"
        if self.torch:
            import torch
            self.xp = torch
            self.cdf = torch.special.ndtr
            self.cat = lambda xs: torch.cat(xs, dim=-1)
            self.rfft = lambda x, n: torch.fft.rfft(x, n=n, dim=-1)
            self.irfft = lambda x, n: torch.fft.irfft(x, n=n, dim=-1)
            self.reverse = lambda x: x.flip((-1,))
            self.arange = lambda low, high: torch.arange(
                low, high, dtype=sample.dtype, device=sample.device
            )
        else:
            import numpy as np
            from scipy import fft, special
            self.xp = np
            self.cdf = special.ndtr
            self.cat = lambda xs: np.concatenate(xs, axis=-1)
            self.rfft = lambda x, n: fft.rfft(x, n=n, axis=-1)
            self.irfft = lambda x, n: fft.irfft(x, n=n, axis=-1)
            self.reverse = lambda x: np.flip(x, axis=-1)
            self.arange = lambda low, high: np.arange(low, high, dtype=sample.dtype)

    def probability(self, lower, upper):
        # Evaluate on the nearer Gaussian tail when both endpoints are positive.
        return self.xp.where(
            lower > 0, self.cdf(-lower) - self.cdf(-upper),
            self.cdf(upper) - self.cdf(lower)
        )


def transported_mass(mass, shift, grid, *, sigma, a, dt):
    """Return live destination-bin mass and first-hit mass before reset.

    The grid is positive and equally spaced, and old minus new log-boundary is
    shared by its atoms. The drift is a*sigma**2 as in the pinned HCSN law.
    This map is piecewise differentiable, including the gradient of the shift
    used by a receiving layer. Contact with a fixed atom is a one-sided case.
    """
    k = grid.shape[0]
    if k < 3 or mass.shape[-1] != k or mass.shape[:-1] != shift.shape:
        raise ValueError("grid, shift and mass shapes must match")
    if sigma <= 0 or dt <= 0:
        raise ValueError("sigma and dt must be positive")
    op = _ArrayOps(mass)
    xp = op.xp
    h = (grid[-1] - grid[0]) / (k - 1)
    scale = sigma * math.sqrt(dt)
    drift = a * sigma**2 * dt
    raw = grid + shift[..., None]
    zero = xp.zeros_like(raw)
    x = xp.maximum(raw, zero)
    live = xp.where(raw > 0, mass, zero)
    image_weight = xp.exp(-2 * a * x)
    weighted = live * image_weight

    # Direct Toeplitz and reflected Hankel terms become two circular
    # convolutions after reversing the reflected mass. Embed without aliasing.
    n = 1 << (2 * k - 2).bit_length()
    offsets = op.arange(1-k, k) * h
    def spectrum(centers):
        band = op.probability((centers - h/2) / scale, (centers + h/2) / scale)
        padding = xp.zeros_like(band[..., :n-(2*k-1)])
        circular = op.cat((band[..., k-1:], padding, band[..., :k-1]))
        return op.rfft(circular, n)

    direct = spectrum(offsets - shift[..., None] - drift)
    reflected = spectrum(offsets + (k-1)*h + 2*grid[0] + shift[..., None] - drift)
    interior = op.irfft(op.rfft(live, n) * direct -
                        op.rfft(op.reverse(weighted), n) * reflected, n)[..., 1:k-1]
    # The first and last bins have distinct endpoints at 0 and +infinity.
    left_cut = (grid[0] + grid[1]) / 2
    right_cut = (grid[-2] + grid[-1]) / 2
    mu, image_mu = x + drift, -x + drift
    left = (live*op.probability(-mu/scale, (left_cut-mu)/scale)
            - weighted*op.probability(-image_mu/scale, (left_cut-image_mu)/scale)).sum(-1)
    right = (live*op.cdf((mu-right_cut)/scale)
             - weighted*op.cdf((image_mu-right_cut)/scale)).sum(-1)
    passage = op.cdf(-mu/scale) + image_weight*op.cdf(image_mu/scale)
    hit = (mass*xp.where(raw > 0, passage, xp.ones_like(x))).sum(-1)
    # The original dense reference clips individual roundoff-sized negative
    # probabilities; clip after contraction to preserve nonnegative live bins.
    bins = op.cat((left[..., None], interior, right[..., None]))
    return xp.maximum(bins, xp.zeros_like(bins)), hit
