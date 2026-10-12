"""Amortized LQ control: BOTH backends prepare once and serve many initial states.

Only identical coefficient content/horizon/cost/noise profiles may share a cache.
Cell initial states vary; no general nonlinear Cell or reasoning claim is made.
The dense control uses one multi-RHS solve, not repeated per-Cell factorizations.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time

import torch

from riccati_lq import Problem, hamiltonian, riccati

BACKENDS = ("riccati", "dense_map")
FIELDS = ("A", "B", "Q", "R", "G", "S")


def seal(data):
    """Content identity, including tensor shape/dtype, not object identity."""
    h = hashlib.sha256()
    for name, value in sorted(data.items()):
        if name == "seal":
            continue
        h.update(name.encode() + b"\0")
        if isinstance(value, torch.Tensor):
            h.update(str((value.dtype, tuple(value.shape))).encode())
            h.update(value.detach().cpu().contiguous().numpy().tobytes())
        else:
            h.update(json.dumps(value, sort_keys=True, allow_nan=False).encode())
        h.update(b"\0")
    return h.hexdigest()


def prepare(problem, backend):
    """Preserve the established solver; cache gains or exact zero-noise maps."""
    started = time.perf_counter()
    _, n, _ = problem.validate()
    if backend not in BACKENDS:
        raise ValueError("unregistered reusable backend")
    cache = dict(backend=backend, coefficients=seal({k: getattr(problem, k) for k in FIELDS}))
    if backend == "riccati":
        p, gains, offsets, receipt = riccati(problem)
        cache.update(gains=torch.stack(gains), p0=p[0], offset=offsets[0])
    else:
        xmap, umap, receipt = hamiltonian(problem, torch.eye(n, dtype=torch.float64))
        p0 = xmap[-1].T @ problem.G @ xmap[-1]
        for k in range(len(umap)):
            p0 = p0 + xmap[k].T @ problem.Q[k] @ xmap[k] + umap[k].T @ problem.R[k] @ umap[k]
        cache.update(xmap=xmap, umap=umap, p0=(p0+p0.T)/2, offset=0.0)
    cache["seal"] = seal(cache)
    return cache, dict(backend=backend, solver=receipt,
        tensor_payload_bytes=sum(v.numel()*v.element_size() for v in cache.values() if isinstance(v, torch.Tensor)),
        preparation_seconds=time.perf_counter()-started, cache_sha256=cache["seal"])


@torch.no_grad()
def apply(problem, cache, initials):
    """Batched nominal paths and expected quadratic values; no kernel solving here.

    Hash checks occur once per batch and are included in measured latency.
    For nonzero additive noise Riccati's nominal path is not a realized path;
    its expected value includes the scalar noise offset. Dense maps reject noise.
    """
    t, n, _ = problem.validate()
    if (cache.get("backend") not in BACKENDS or cache.get("seal") != seal(cache)
            or cache.get("coefficients") != seal({k: getattr(problem, k) for k in FIELDS})):
        raise ValueError("stale or modified prepared controller")
    if (not isinstance(initials, torch.Tensor) or initials.ndim != 2
            or not 1 <= len(initials) <= 256 or initials.shape[1] != n
            or initials.dtype != torch.float64 or initials.device.type != "cpu"
            or initials.requires_grad or not torch.isfinite(initials).all()):
        raise ValueError("bounded detached CPU double initial-state batch required")
    if cache["backend"] == "riccati":
        xs, us = [initials.clone()], []
        for k in range(t):
            us.append(-xs[-1] @ cache["gains"][k].T)
            xs.append(xs[-1] @ problem.A[k].T + us[-1] @ problem.B[k].T)
        x, u = torch.stack(xs, dim=1), torch.stack(us, dim=1)
    else:
        x = torch.einsum("tij,bj->bti", cache["xmap"], initials)
        u = torch.einsum("tij,bj->bti", cache["umap"], initials)
    values = .5 * ((initials @ cache["p0"]) * initials).sum(1) + cache["offset"]
    if not all(torch.isfinite(v).all() for v in (x, u, values)):
        raise ValueError("nonfinite reusable control output")
    return x, u, values


def benchmark(output):
    """Predeclared 27 cases, five cold and seven hot timings; no winner selection."""
    output.mkdir(exist_ok=False, parents=True)
    plan = dict(schema="hepta.ndu.shared-lq.v1", seeds=[7, 19, 31], horizons=[4, 16, 32],
        batch_sizes=[1, 16, 256], cold_repeats=5, hot_repeats=7, tolerance=1e-8,
        state_dimension=4, control_dimension=2, backends=BACKENDS,
        common_zero_noise_profile=True, both_backends_share_preparation=True,
        identity_and_validation_costs_included=True, production_accepted=False,
        independent_task_evidence=False, new_encoder_reader_calls=0)
    (output/"plan.json").write_text(json.dumps(plan, indent=2)+"\n")
    records = []
    for seed in plan["seeds"]:
        for horizon in plan["horizons"]:
            rng = torch.Generator().manual_seed(seed)
            a = .9*torch.eye(4, dtype=torch.float64)+.1*torch.randn(4,4, generator=rng, dtype=torch.float64)
            b = .3*torch.randn(4,2, generator=rng, dtype=torch.float64)
            problem = Problem(a.repeat(horizon,1,1), b.repeat(horizon,1,1),
                torch.eye(4, dtype=torch.float64).repeat(horizon,1,1),
                torch.eye(2, dtype=torch.float64).repeat(horizon,1,1),
                2*torch.eye(4, dtype=torch.float64), torch.zeros(horizon,4,1, dtype=torch.float64))
            all_initials = torch.randn(256,4, generator=rng, dtype=torch.float64)
            data = {k: getattr(problem,k).tolist() for k in FIELDS} | dict(initials=all_initials.tolist())
            (output/f"problem-{seed}-{horizon}.json").write_text(json.dumps(data)+"\n")
            for count in plan["batch_sizes"]:
                row = dict(seed=seed, horizon=horizon, cells=count, status="started", timings={})
                begun = time.perf_counter()
                initials = all_initials[:count]
                try:
                    prepared = {key: prepare(problem,key)[0] for key in BACKENDS}
                    outputs = {key: apply(problem,prepared[key],initials) for key in BACKENDS}
                    error = max(float((a-b).abs().max()) for a,b in zip(outputs["riccati"],outputs["dense_map"],strict=True))
                    if error > plan["tolerance"]:
                        raise ValueError("shared backends disagree on full paths or values")
                    # Independent path-cost evaluation; do not check value against itself.
                    x,u,value = outputs["riccati"]
                    cost = .5*torch.einsum("bi,ij,bj->b",x[:,-1],problem.G,x[:,-1])
                    for k in range(horizon):
                        cost += .5*(torch.einsum("bi,ij,bj->b",x[:,k],problem.Q[k],x[:,k])
                            + torch.einsum("bi,ij,bj->b",u[:,k],problem.R[k],u[:,k]))
                    cost_error = float((cost-value).abs().max())
                    if cost_error > plan["tolerance"]:
                        raise ValueError("shared value differs from actual quadratic trajectory cost")
                    samples = {key:dict(cold=[],hot=[],preparation=[]) for key in BACKENDS}
                    for repeat in range(plan["cold_repeats"]):
                        order = BACKENDS if (repeat+seed+count)%2 == 0 else BACKENDS[::-1]
                        for key in order:
                            stamp = time.perf_counter()
                            cache,receipt = prepare(problem,key)
                            apply(problem,cache,initials)
                            samples[key]["cold"].append(time.perf_counter()-stamp)
                            samples[key]["preparation"].append(receipt["preparation_seconds"])
                            samples[key]["tensor_payload_bytes"] = receipt["tensor_payload_bytes"]
                            samples[key]["solves_per_prepare"] = receipt["solver"]["solves"]
                    for repeat in range(plan["hot_repeats"]):
                        for key in (BACKENDS if repeat%2 == 0 else BACKENDS[::-1]):
                            stamp = time.perf_counter()
                            apply(problem,prepared[key],initials)
                            samples[key]["hot"].append(time.perf_counter()-stamp)
                    for key,sample in samples.items():
                        row["timings"][key] = sample | dict(
                            median_cold_seconds=statistics.median(sample["cold"]),
                            median_hot_seconds=statistics.median(sample["hot"]),
                            median_hot_seconds_per_cell=statistics.median(sample["hot"])/count)
                    row.update(status="succeeded", maximum_difference=error, cost_error=cost_error,
                        caches_unchanged=all(seal(c)==c["seal"] for c in prepared.values()))
                    if not row["caches_unchanged"]:
                        raise ValueError("batch evaluation mutated prepared controller")
                except Exception as exc:
                    row.update(status="failed", error_type=type(exc).__name__, error=str(exc)[:512])
                row["elapsed_seconds_including_checks"] = time.perf_counter()-begun
                records.append(row)
                with (output/"cases.jsonl").open("a") as stream:
                    stream.write(json.dumps(row,allow_nan=False)+"\n");stream.flush()
    report = plan | dict(planned=27,recorded=len(records),failed=sum(r["status"]=="failed" for r in records),
        cases=records, timing_claim="measured backend comparison, no presumed acceleration",
        serialized_bytes_and_peak_memory_not_equal_to_tensor_payload=True)
    (output/"summary.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    if report["failed"]:
        raise RuntimeError("shared-controller failures retained in full census")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    print(json.dumps(benchmark(parser.parse_args().output), allow_nan=False))
