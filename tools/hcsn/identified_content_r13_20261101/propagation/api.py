"""Integration API: freeze the grid once; differentiate sigma, mu and reset_x."""

import numpy as np
import torch

from .bounds import choose_domain, graded_edges, upper_tail_bound
from .finite_volume import generator_numpy as _generator_numpy
from .finite_volume import generator_torch as _generator_torch
from .finite_volume import reset_numpy, reset_torch


def make_grid(inner_step=0.025, horizon=29.4, sigma_max=0.4,
              drift_upper=0.04875, tail_budget=1e-4, initial_cap=0.8,
              reset_cap=0.8, recovery_min=0.35, growth=1.2):
    """Return static edges; horizon bounds total elapsed history plus decisions.

    A fixed worst-case parameter box must define the grid before fitting. This
    bounds only domain truncation, not the FV spatial error on the selected mesh.
    """
    chosen = choose_domain(horizon, sigma_max, drift_upper, initial_cap,
                           reset_cap, recovery_min, tail_budget)
    return graded_edges(chosen["upper"], inner_step, reset_cap, growth)


def grid_certificate(edges, horizon=29.4, sigma_max=0.4, drift_upper=0.04875,
                     initial_cap=0.8, reset_cap=0.8, recovery_min=0.35):
    return {"n_active": len(edges)-1, "upper": float(edges[-1]),
        "total_time": horizon, "sigma_max": sigma_max, "drift_upper": drift_upper,
        "initial_cap": initial_cap, "reset_cap": reset_cap, "recovery_min": recovery_min,
        "upper_exit_probability_bound": upper_tail_bound(float(edges[-1]), horizon,
            sigma_max, drift_upper, initial_cap, reset_cap, recovery_min),
        "fv_spatial_error_bound": None,
        "scope": "Continuous upper-exit bound before conditioning; spatial and posterior errors separate."}


def generator_torch(sigma, mu, reset_x, edges, recovery=0.35, retention=0.75):
    """Return Q/prior/centers/reset on 2*(N+2) states, with first-order AD.

    reset_x is the full-HX-derived log(reset_asset/b), supplied by the caller.
    Its fixed physical width is .1 and its support is exactly [0,.8].
    """
    edge_tensor = torch.as_tensor(edges, dtype=sigma.dtype, device=sigma.device)
    reset = reset_torch(reset_x, 0.1, edge_tensor, 0.8)
    q = _generator_torch(mu, sigma, reset, edge_tensor, recovery, retention)
    phase_prior = torch.cat((reset, reset.new_zeros(2)))
    return {"Q": q, "prior": torch.cat((phase_prior/2, phase_prior/2)),
        "centers": (edge_tensor[:-1]+edge_tensor[1:])/2, "reset": reset,
        "edges": edge_tensor}


def generator_numpy(sigma, mu, reset_x, edges, recovery=0.35, retention=0.75):
    edges = np.asarray(edges, dtype=np.float64)
    reset = reset_numpy(reset_x, 0.1, edges, 0.8)
    q = _generator_numpy(mu, sigma, reset, edges, recovery, retention)
    phase_prior = np.r_[reset, np.zeros(2)]
    return {"Q": q, "prior": np.r_[phase_prior/2, phase_prior/2],
        "centers": (edges[:-1]+edges[1:])/2, "reset": reset, "edges": edges}
