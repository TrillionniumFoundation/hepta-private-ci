"""Positive fitted-flux FV generator, with an absorbing half-cell boundary.

The finite generator is the executable model. Matrix exponentiation does not
make it an exact continuum diffusion. Upper reflection is admitted only with
an independently declared domain-tail budget; reset support stays fixed.
"""

import numpy as np
from scipy.special import ndtr
import torch


def bernoulli_numpy(z):
    """Analytic z/expm1(z) extension; stable series avoids cancellation at zero."""
    z = np.asarray(z, dtype=np.float64)
    small = abs(z) < 1e-3
    safe = np.where(small, 1.0, z)
    if np.any(abs(safe) > 50):
        raise ValueError("Peclet number outside the audited |z|<=50 domain")
    series = 1-z/2+z*z/12-z**4/720+z**6/30240-z**8/1209600
    return np.where(small, series, safe/np.expm1(safe))


def bernoulli_torch(z):
    small = z.abs() < 1e-3
    safe = torch.where(small, torch.ones_like(z), z)
    if bool((safe.abs() > 50).any()):
        raise ValueError("Peclet number outside the audited |z|<=50 domain")
    series = 1-z/2+z.square()/12-z.pow(4)/720+z.pow(6)/30240-z.pow(8)/1209600
    return torch.where(small, series, safe/torch.expm1(safe))


def sg_rates_numpy(mu, sigma, edges):
    edges = np.asarray(edges, dtype=np.float64)
    widths, centers = np.diff(edges), (edges[:-1]+edges[1:])/2
    if edges[0] != 0 or np.any(widths <= 0) or sigma <= 0:
        raise ValueError("Need increasing positive cells from zero and sigma>0")
    distance, diffusion = np.diff(centers), sigma*sigma/2
    peclet = mu*distance/diffusion
    up = diffusion/(widths[:-1]*distance)*bernoulli_numpy(-peclet)
    down = diffusion/(widths[1:]*distance)*bernoulli_numpy(peclet)
    kill = diffusion/(widths[0]*centers[0])*bernoulli_numpy(mu*centers[0]/diffusion)
    return up, down, float(kill)


def sg_rates_torch(mu, sigma, edges):
    edges = torch.as_tensor(edges, dtype=sigma.dtype, device=sigma.device)
    widths, centers = edges.diff(), (edges[:-1]+edges[1:])/2
    if bool((widths <= 0).any()) or float(edges[0]) != 0 or float(sigma.detach()) <= 0:
        raise ValueError("Need increasing positive cells from zero and sigma>0")
    distance, diffusion = centers.diff(), sigma.square()/2
    peclet = mu*distance/diffusion
    up = diffusion/(widths[:-1]*distance)*bernoulli_torch(-peclet)
    down = diffusion/(widths[1:]*distance)*bernoulli_torch(peclet)
    kill = diffusion/(widths[0]*centers[0])*bernoulli_torch(mu*centers[0]/diffusion)
    return up, down, kill


def reset_numpy(mean, sd, edges, support_upper=0.8):
    edges = np.asarray(edges, dtype=np.float64)
    if sd <= 0 or support_upper <= 0 or edges[-1] < support_upper:
        raise ValueError("Grid must cover the declared fixed reset support")
    clipped = np.minimum(edges, support_upper)
    cdf = ndtr((clipped-mean)/sd)
    mass = np.diff(cdf)
    normalizer = float(ndtr((support_upper-mean)/sd)-ndtr(-mean/sd))
    if normalizer <= 0:
        raise ValueError("Reset normalization is unresolved in floating-point precision")
    return mass/normalizer


def reset_torch(mean, sd, edges, support_upper=0.8):
    edges = torch.as_tensor(edges, dtype=mean.dtype, device=mean.device)
    clipped = torch.minimum(edges, edges.new_tensor(support_upper))
    mass = torch.special.ndtr((clipped-mean)/sd).diff()
    normalizer = torch.special.ndtr((support_upper-mean)/sd)-torch.special.ndtr(-mean/sd)
    if float(normalizer.detach()) <= 0:
        raise ValueError("Reset normalization is unresolved in floating-point precision")
    return mass/normalizer


def generator_numpy(mu, sigma, reset_prob, edges, recovery=0.35, retention=0.75):
    reset_prob = np.asarray(reset_prob, dtype=np.float64)
    n, width = len(reset_prob), len(reset_prob)+2
    if recovery <= 0 or not 0 <= retention <= 1 or len(edges) != n+1:
        raise ValueError("Invalid recovery, retention, or grid size")
    if reset_prob.min() < 0 or abs(reset_prob.sum()-1) > 1e-12:
        raise ValueError("Reset law must be a probability vector")
    up, down, kill = sg_rates_numpy(mu, sigma, edges)
    off = np.zeros((2*width, 2*width))
    for bit in range(2):
        start = bit*width
        for i in range(n-1):
            off[start+i, start+i+1] = up[i]
            off[start+i+1, start+i] = down[i]
        off[start, start+n] = kill
        off[start+n, start+n+1] = 2/recovery
        for other in range(2):
            chance = retention*(bit == other)+(1-retention)/2
            off[start+n+1, other*width:other*width+n] = 2/recovery*chance*reset_prob
    return off-np.diag(off.sum(axis=1))


def generator_torch(mu, sigma, reset_prob, edges, recovery=0.35, retention=0.75):
    n, width = len(reset_prob), len(reset_prob)+2
    up, down, kill = sg_rates_torch(mu, sigma, edges)
    off = sigma.new_zeros((2*width, 2*width))
    for bit in range(2):
        start = bit*width
        index = torch.arange(n-1, device=sigma.device)+start
        off[index, index+1], off[index+1, index] = up, down
        off[start, start+n] = kill
        off[start+n, start+n+1] = 2/recovery
        for other in range(2):
            chance = retention*(bit == other)+(1-retention)/2
            off[start+n+1, other*width:other*width+n] = 2/recovery*chance*reset_prob
    return off-torch.diag(off.sum(dim=1))
