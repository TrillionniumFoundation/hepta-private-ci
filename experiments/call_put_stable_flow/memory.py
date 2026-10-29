"""Exact conditional propagation of a leaky rank-one associative memory.

This is a new 2026-10-29 implementation, not recovered prior-run code.
The exactness claim holds with key, value, leak and write rate fixed over
the interval. A boundary controller can change these between intervals;
the resulting coupled neural system is not solved analytically.
"""

import torch

from .numerics import phi1


def exact_delta_step(
    memory: torch.Tensor,
    key: torch.Tensor,
    value: torch.Tensor,
    leak: torch.Tensor,
    write: torch.Tensor,
    dt: torch.Tensor,
) -> torch.Tensor:
    """Solve M'=-leak*M+write*(value-M*key)*key^T for arbitrary keys.

    Shapes are [..., value_dim, key_dim], [..., key_dim], [..., value_dim]
    and broadcast-compatible [...] for scalar rates/time. The caller must
    supply finite nonnegative rates/time. No division by ||key||^2 is used,
    so zero keys and near-zero keys have the same well-defined contract.
    """
    norm2 = key.square().sum(dim=-1)
    interval = write * dt
    decay = torch.exp(-leak * dt)
    erase = interval * phi1(-interval * norm2)
    insert = interval * phi1(-(leak + write * norm2) * dt)
    previous = torch.matmul(memory, key.unsqueeze(-1)).squeeze(-1)
    correction = insert.unsqueeze(-1) * value - (decay * erase).unsqueeze(-1) * previous
    return decay[..., None, None] * memory + correction.unsqueeze(-1) * key.unsqueeze(
        -2
    )


def memory_read(memory: torch.Tensor, query: torch.Tensor) -> torch.Tensor:
    """Content-addressed read at the current time, with no token bypass."""
    return torch.matmul(memory, query.unsqueeze(-1)).squeeze(-1)
