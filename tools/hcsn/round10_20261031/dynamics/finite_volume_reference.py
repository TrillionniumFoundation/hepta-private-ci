"""SciPy realization of the pinned v2 finite-volume/Erlang mathematical contract.

This independent scalar implementation is not a run of upstream PyTorch code.
Continuous boundary motion is approximated by a left hold and physical overlap
remap at every observation time. Both the physical and killed laws persist.
"""

import math

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import expm_multiply
from scipy.special import ndtr


def point_weights(value, centers, width):
    if value < centers[0] or value > centers[-1]:
        raise ValueError("Point must lie inside the represented cell-center interval")
    weight = np.maximum(0., 1-abs(centers-value)/width)
    return weight/weight.sum()


def generator(case, boundary, lower, cells, stages):
    width = (boundary-lower)/cells
    edges = np.linspace(lower, boundary, cells+1)
    centers = (edges[:-1]+edges[1:])/2
    reset = point_weights(case.reset, centers, width)
    diffusion = case.sigma**2/(2*width**2)
    up = diffusion+max(case.mu, 0)/width
    down = diffusion+max(-case.mu, 0)/width
    firing = 2*diffusion+max(case.mu, 0)/width
    size, gamma = cells+stages, stages/case.refractory
    q = sparse.lil_matrix((size, size))
    for j in range(cells):
        if j:
            q[j, j-1] = down
        if j+1 < cells:
            q[j, j+1] = up
        else:
            q[j, cells] = firing
    for j in range(cells, size):
        if j+1 < size:
            q[j, j+1] = gamma
        else:
            q[j, :cells] = gamma*reset
    q.setdiag(-np.asarray(q.sum(axis=1)).ravel())
    killed = q.copy()
    killed[cells-1, cells] = 0.
    augmented = sparse.lil_matrix((size+1, size+1))
    augmented[:size, :size] = q.T
    augmented[size, cells-1] = firing
    return dict(operator=augmented.tocsr(), killed=killed.T.tocsr(),
                centers=centers, edges=edges, width=width)


def remap(p, killed, old_edges, new_edges, cells):
    old_width = old_edges[1]-old_edges[0]
    left = np.maximum(old_edges[:-1, None], new_edges[None, :-1])
    right = np.minimum(old_edges[1:, None], new_edges[None, 1:])
    overlap = np.maximum(0., right-left)/old_width
    hit = np.maximum(0., old_edges[1:]-np.maximum(old_edges[:-1], new_edges[-1]))/old_width
    out, nohit = p.copy(), killed.copy()
    out[:cells], nohit[:cells] = p[:cells] @ overlap, killed[:cells] @ overlap
    jump_events = float(p[:cells] @ hit)
    out[cells] += jump_events
    # Old refractory phases persist. Newly marked events have no killed
    # destination: the no-event state is subnormalized, never repaired.
    return out, nohit, jump_events


def solve(case, cells, stages, steps, lower=-5.):
    case.validate()
    if cells < 4 or stages < 1 or steps < 1:
        raise ValueError("Positive resolution required")
    time_grid = sorted(set(np.linspace(0., case.times[-1], steps+1)) | set(case.times))
    flow = generator(case, case.boundaries[0], lower, cells, stages)
    p = np.r_[point_weights(case.initial, flow["centers"], flow["width"]), np.zeros(stages)]
    nohit, total = p.copy(), 0.
    max_mass_error, min_mass, max_subset_error = 0., float(p.min()), 0.
    history = []
    for start, end in zip(time_grid, time_grid[1:]):
        dt = end-start
        a = flow["operator"]*dt
        result = expm_multiply(a, np.r_[p, 0.], traceA=float(a.diagonal().sum()))
        k = flow["killed"]*dt
        nohit = expm_multiply(k, nohit, traceA=float(k.diagonal().sum()))
        p, total = result[:-1], total+float(result[-1])
        next_flow = generator(case, case.boundary(end), lower, cells, stages)
        p, nohit, jump = remap(p, nohit, flow["edges"], next_flow["edges"], cells)
        total += jump
        flow = next_flow
        max_mass_error = max(max_mass_error, abs(float(p.sum())-1))
        min_mass = min(min_mass, float(p.min()), float(nohit.min()))
        max_subset_error = max(max_subset_error, float(np.max(nohit-p)))
        history.append(dict(time=float(end), events=total, ever=1-float(nohit.sum()),
                            refractory=float(p[cells:].sum())))
    if max_mass_error > 2e-9 or min_mass < -2e-11 or max_subset_error > 2e-9:
        raise ArithmeticError("Finite generator/remap violated retained mass constraints")
    phase = float(p[cells:].sum())
    mean = float(p[:cells] @ flow["centers"]+phase*case.reset)
    second = float(p[:cells] @ flow["centers"]**2+phase*case.reset**2)
    return dict(cells=cells, stages=stages, requested_steps=steps,
                actual_intervals=len(time_grid)-1, lower=lower,
                metrics=dict(events=total, ever=1-float(nohit.sum()), refractory=phase,
                             mean=mean, second_moment=second, variance=second-mean**2),
                max_mass_error=max_mass_error, minimum_mass=min_mass,
                max_killed_subset_error=max_subset_error,
                final_probability=p.tolist(), final_killed=nohit.tolist(),
                final_centers=flow["centers"].tolist(), history=history)


def lower_domain_bound(case, lower):
    """Pathwise coupling bound before either process first reaches lower.

    At most floor(T/tau)+1 new events occur in the true fixed-delay process.
    A union bound uses the full horizon for the initial and every reset cycle.
    This bounds domain truncation only; it does not bound grid/Erlang errors.
    """
    horizon = case.times[-1]
    scale = case.sigma*math.sqrt(horizon)
    def down(start):
        gap = start-lower
        return float(ndtr((-gap-case.mu*horizon)/scale) +
                     math.exp(-2*case.mu*gap/case.sigma**2)*ndtr((-gap+case.mu*horizon)/scale))
    count_bound = math.floor(horizon/case.refractory)+1
    return min(1., down(case.initial)+count_bound*down(case.reset))
