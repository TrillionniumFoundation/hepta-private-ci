"""Independent jump-path sampler for a supplied finite CTMC generator.

Consumes Q and explicit counted edges; it never reimplements neural rate rules.
Only ordinary off-diagonal jumps are counted. Self events invisible in Q require
an additional marked-process rate and are deliberately rejected by this API.
"""
from __future__ import annotations

import numpy as np


def sample_ctmc(q, initial_probability, horizon, paths=32768, seed=81001,
                counted_edges=(), return_traces=False, max_jumps=100000):
    q = np.asarray(q, dtype=float)
    p = np.asarray(initial_probability, dtype=float)
    if q.ndim != 2 or q.shape[0] != q.shape[1] or p.shape != (len(q),):
        raise ValueError("Q must be square and initial probability a matching vector")
    if horizon < 0 or not np.isfinite(q).all() or not np.isfinite(p).all():
        raise ValueError("Finite rates/probabilities and nonnegative horizon required")
    n = len(q)
    off = q.copy();np.fill_diagonal(off,0)
    if off.min() < -1e-12 or np.max(np.abs(q.sum(axis=1)))>1e-9:
        raise ValueError("Invalid row generator")
    if p.min() < -1e-12 or abs(p.sum()-1)>1e-9:
        raise ValueError("Invalid initial probability")
    rates = -q.diagonal()
    transitions = np.divide(off,rates[:,None],out=np.zeros_like(off),where=rates[:,None]>0)
    cumulative = transitions.cumsum(axis=1)
    cumulative[rates>0,-1] = 1.0
    marks = np.zeros_like(q,dtype=bool)
    for source,destination in counted_edges:
        if source == destination:
            raise ValueError("Self events need an explicit marked-process implementation")
        marks[source,destination] = True
    rng = np.random.default_rng(seed)
    state = rng.choice(n,size=paths,p=p)
    clock = np.zeros(paths)
    count = np.zeros(paths,dtype=np.int64)
    jumps = np.zeros(paths,dtype=np.int64)
    active = np.ones(paths,dtype=bool)
    traces = [[] for _ in range(paths)] if return_traces else None
    rounds = 0
    while active.any():
        rounds += 1
        if rounds > max_jumps:
            raise RuntimeError("Jump cap exceeded")
        ids = np.flatnonzero(active)
        local_rates = rates[state[ids]]
        wait = np.full(len(ids),np.inf)
        positive = local_rates>0
        wait[positive] = rng.exponential(1/local_rates[positive])
        reaches = clock[ids]+wait <= horizon
        active[ids[~reaches]] = False
        chosen = ids[reaches]
        if not len(chosen):
            continue
        source = state[chosen].copy()
        uniform = rng.random(len(chosen))
        destination = (uniform[:,None]>cumulative[source]).sum(axis=1)
        clock[chosen] += wait[reaches]
        marked = marks[source,destination]
        count[chosen] += marked
        jumps[chosen] += 1
        state[chosen] = destination
        if return_traces:
            for row,i,j,event in zip(chosen,source,destination,marked):
                traces[row].append({"time":float(clock[row]),"source":int(i),
                                    "destination":int(j),"spike":bool(event)})
    return {"state":state,"count":count,"jumps":jumps,"traces":traces,
            "empirical_probability":np.bincount(state,minlength=n)/paths,
            "count_mean":float(count.mean()),
            "count_standard_error":float(count.std(ddof=1)/np.sqrt(paths)),
            "repeat_fraction":float(np.mean(count>=2))}
