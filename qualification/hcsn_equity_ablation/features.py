"""One population trajectory shared by all arms; original Call is always computed."""

from dataclasses import asdict
import time

import numpy as np
import torch

from qualification.hcsn_adaptive.features import tensor_digest
from qualification.hcsn_history.call_adapters import replace_call


ARMS = ("finite_policy", "drop_call", "full_hx")


@torch.no_grad()
def extract_arms(model, observations, intervals, curve):
    x, dt = np.asarray(observations), np.asarray(intervals)
    if (x.ndim != 3 or x.shape[2] != model.config.input_size or not 1 <= len(x) <= model.config.max_batch
            or x.shape[1] < 1 or dt.shape != x.shape[:2] or not np.isfinite(x).all()
            or not np.isfinite(dt).all() or not np.all(dt == model.config.dt)):
        raise ValueError("declared finite fixed-dt synthetic observations required")
    inputs = torch.as_tensor(x, dtype=model.drive.weight.dtype, device=model.drive.weight.device)
    state, totals = None, {}
    backend_wall = hx_wall = assembly_wall = max_mass = max_balance = 0.0
    peak_bytes = 0
    started = time.perf_counter()
    for step in range(x.shape[1]):
        before = time.perf_counter()
        features, state, diag = model.step(inputs[:, step], state, dt=model.config.dt,
                                           boundary_override=0.0)
        backend_wall += time.perf_counter()-before
        before = time.perf_counter()
        equity = curve.apply(model, state)
        hx_wall += time.perf_counter()-before
        before = time.perf_counter()
        current = {"finite_policy": features,
                   "drop_call": replace_call(features, features.new_zeros(len(x))),
                   "full_hx": replace_call(features, equity)}
        for arm, value in current.items():
            totals[arm] = totals.get(arm, torch.zeros_like(value))+value
        assembly_wall += time.perf_counter()-before
        peak_bytes = max(peak_bytes, state.tensor_bytes())
        max_mass = max(max_mass, float(diag["mass_error"].abs().max()))
        max_balance = max(max_balance, float(diag["content_balance_error"].abs().max()))
    result = {arm: torch.cat((current[arm], totals[arm]/x.shape[1]), 1) for arm in ARMS}
    if not all(bool(torch.isfinite(value).all()) for value in result.values()):
        raise FloatingPointError("nonfinite Call-arm features")
    return result, {"wall_seconds": time.perf_counter()-started,
                    "shared_backend_wall_seconds": backend_wall, "incremental_hx_apply_wall_seconds": hx_wall,
                    "posthoc_assembly_wall_seconds": assembly_wall, "encoder_events_shared_once": int(x.shape[0]*x.shape[1]),
                    "state_sha256": tensor_digest(state.density), "boundary_sha256": tensor_digest(state.boundary),
                    "time_micros": state.time_micros, "peak_state_tensor_bytes": peak_bytes,
                    "feature_sha256": {arm: tensor_digest(value) for arm, value in result.items()},
                    "max_mass_error": max_mass, "max_content_balance_error": max_balance,
                    "flow_config": asdict(model.config), "original_call_solve_always_paid": True,
                    "boundary": "fixed absolute log boundary 0", "drift": "same sample-dependent input drive",
                    "feature_aggregation": "last + mean; same readout parameter mask"}, state
