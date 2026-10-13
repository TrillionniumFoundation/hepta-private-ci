"""Finite-episode research planning over existing, equivalent Cell equations.

One fixed bank and known request layout; no model selection, durable cache,
production owner, generic NDU solver or independent timing attestation.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import platform
from pathlib import Path
import time

import torch

from bounded_cell_execution import DEFAULT_SCRATCH_BYTES, _checked_comparison, _finite, _fold
from bounded_multicell_probe import METHODS, probe_bounded
from development_tensors import MAX_ELEMENTS, parameter_digest
from shared_cell_execution import _validate_request

MAX_FOLDED_BYTES = 64 * 1024 * 1024


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _runtime():
    files = ("cell_execution_plan.py", "bounded_cell_execution.py", "bounded_multicell_probe.py",
             "shared_cell_execution.py", "development_tensors.py")
    return _digest({"python": platform.python_version(), "torch": torch.__version__,
                    "platform": platform.platform(), "machine": platform.machine(),
                    "threads": torch.get_num_threads(), "interop_threads": torch.get_num_interop_threads(),
                    "sources": {n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
                                for n in files}})


def _binding(bank, features, fids, cids, scope_digest):
    if (type(scope_digest) is not str or len(scope_digest) != 64
            or any(c not in "0123456789abcdef" for c in scope_digest)):
        raise ValueError("caller scope digest required")
    _validate_request(bank, features, fids, cids, MAX_ELEMENTS)
    return _digest({"parameters": parameter_digest(bank), "generation": bank.generation,
                    "cells": bank.cell_ids, "awake": bank.awake, "scope": scope_digest,
                    "shape": list(features.shape), "dtype": str(features.dtype),
                    "feature_indices": fids.tolist(), "cell_indices": cids.tolist()})


@dataclass(frozen=True)
class MethodCost:
    method: str
    startup_ns: int
    per_pass_ns: int
    compiled_bytes: int


@dataclass(frozen=True)
class CostProfile:
    binding: str
    runtime: str
    methods: tuple[MethodCost, ...]
    calibration_wall_ns: int
    calibration_record_sha256: str
    scratch_bytes: int = DEFAULT_SCRATCH_BYTES

    def validate(self):
        for value in (self.binding, self.runtime, self.calibration_record_sha256):
            if (type(value) is not str or len(value) != 64
                    or any(c not in "0123456789abcdef" for c in value)):
                raise ValueError("invalid profile digest")
        if (type(self.methods) is not tuple or len(self.methods) != len(METHODS)
                or any(type(c) is not MethodCost for c in self.methods)
                or tuple(c.method for c in self.methods) != METHODS
                or type(self.calibration_wall_ns) is not int or self.calibration_wall_ns < 1
                or type(self.scratch_bytes) is not int or self.scratch_bytes != DEFAULT_SCRATCH_BYTES):
            raise ValueError("invalid fixed cost profile")
        for c in self.methods:
            if (any(type(v) is not int or not 0 <= v <= 10**15
                    for v in (c.startup_ns, c.per_pass_ns, c.compiled_bytes))
                    or c.per_pass_ns < 1
                    or (c.method != "full_folded_checked" and c.compiled_bytes != 0)):
                raise ValueError("invalid method work estimate")
        return self


def calibrate(bank, features, fids, cids, *, scope_digest):
    """Pay for all four calibration paths; never use later measured times to pick.

    The largest of four observations is an empirical estimate, NOT a statistical
    upper confidence bound. Different input values with the same layout may have
    different costs. Every warmup and dense compilation is included in startup.
    """
    start = time.perf_counter_ns()
    if torch.is_grad_enabled():
        raise ValueError("serving calibration requires disabled autograd")
    binding, runtime = _binding(bank, features, fids, cids, scope_digest), _runtime()
    observation = probe_bounded(bank, features, fids, cids)
    costs = []
    for method in METHODS:
        startup = observation["warmup"][method]["wall_ns"]
        compiled = 0
        if method == "full_folded_checked":
            item = observation["full_folded_compilation"]
            startup += item["wall_ns"]
            compiled = item["additional_tensor_bytes"] + item["index_lookup_bytes"]
        per_pass = max(t["wall_ns"] for t in observation["trials"] if t["method"] == method)
        costs.append(MethodCost(method, startup, per_pass, compiled))
    if _binding(bank, features, fids, cids, scope_digest) != binding or _runtime() != runtime:
        raise ValueError("calibration context changed")
    profile = CostProfile(binding, runtime, tuple(costs), time.perf_counter_ns()-start,
                          _digest(observation)).validate()
    return profile, observation


def choose(profile, *, passes, compiled_byte_budget):
    """Known finite work only; no hypothetical infinite reuse or future labels.

    The budget limits extra compiled matrices plus lookup, NOT total process
    memory or per-batch scratch. A zero budget permits shared/expanded/tiled.
    An estimate cannot grant a hard wall-time deadline or production authority.
    """
    profile.validate()
    if (type(passes) is not int or not 1 <= passes <= 32
            or type(compiled_byte_budget) is not int
            or not 0 <= compiled_byte_budget <= MAX_FOLDED_BYTES):
        raise ValueError("invalid finite episode budget")
    estimates = {c.method: c.startup_ns + passes*c.per_pass_ns for c in profile.methods
                 if c.compiled_bytes <= compiled_byte_budget}
    method = min(estimates, key=lambda name: (estimates[name], METHODS.index(name)))
    return {"method": method, "passes": passes, "compiled_byte_budget": compiled_byte_budget,
            "estimated_wall_ns": estimates[method], "feasible_estimates_ns": estimates,
            "profile_sha256": _digest(asdict(profile)),
            "estimate_scope": "startup_and_passes_excludes_common_binding_and_snapshot_preparation",
            "production_authorized": False}


def execute(bank, features, fids, cids, profile, *, passes, compiled_byte_budget, scope_digest):
    """Execute ONLY the preselected path, never time all paths and pick hindsight.

    Bank/inputs are copied once. Dense matrices live only for this finite episode
    and are compiled only when selected. Parameters/layout/runtime must match the
    earlier profile, including Cell generations. Caller scope is not authority.
    No partial receipt on a failed operation; return the last output only, rather
    than retaining every pass's tensor. There is no background model execution.
    """
    total = time.perf_counter_ns()
    if torch.is_grad_enabled():
        raise ValueError("episode requires disabled autograd")
    profile.validate()
    if (_binding(bank, features, fids, cids, scope_digest) != profile.binding
            or _runtime() != profile.runtime):
        raise ValueError("stale cost profile or mismatched execution context")
    plan = choose(profile, passes=passes, compiled_byte_budget=compiled_byte_budget)
    method = plan["method"]
    fixed = deepcopy(bank).requires_grad_(False)
    x, f, c = features.detach().clone(), fids.clone(), cids.clone()
    batches = []
    for start in range(0, len(c), 32):
        unique, inverse = torch.unique(f[start:start+32], sorted=True, return_inverse=True)
        batches.append((x[unique], inverse, c[start:start+32]))
    folded, compilation_ns, compiled_bytes = None, 0, 0
    if method == "full_folded_checked":
        active = torch.unique(c, sorted=True)
        compiled_bytes = len(active)*(fixed.width*fixed.classes+fixed.width+1)*x.element_size() + len(fixed.cell_ids)*8
        if compiled_bytes > compiled_byte_budget:
            raise ValueError("actual compiled storage exceeds pre-action budget")
        t = time.perf_counter_ns()
        tensors = _fold(fixed, active)
        lookup = torch.full((len(fixed.cell_ids),), -1, dtype=torch.long)
        lookup[active] = torch.arange(len(active))
        folded = (*tensors, lookup)
        compilation_ns = time.perf_counter_ns()-t
    t = time.perf_counter_ns()
    _checked_comparison(fixed, *batches[0], method, folded, profile.scratch_bytes)
    warmup_ns = time.perf_counter_ns()-t
    times, output, max_tile_scratch = [], None, 0
    for _ in range(passes):
        t = time.perf_counter_ns()
        result = []
        for batch in batches:
            logits, work = _checked_comparison(fixed, *batch, method, folded, profile.scratch_bytes)
            result.append(logits)
            if work is not None:
                max_tile_scratch = max(max_tile_scratch, work["explicit_scratch_upper_bytes"])
        output = torch.cat(result)
        _finite(output)
        times.append(time.perf_counter_ns()-t)
    if _binding(bank, features, fids, cids, scope_digest) != profile.binding or _runtime() != profile.runtime:
        raise ValueError("execution context changed before result")
    report = {"schema": "hepta.stem.finite-compute-episode.v1", "plan": plan,
        "actual_compilation_ns": compilation_ns, "actual_warmup_ns": warmup_ns,
        "actual_pass_wall_ns": times, "compiled_numeric_bytes": compiled_bytes,
        "maximum_tile_scratch_bytes": max_tile_scratch,
        "episode_total_wall_ns": time.perf_counter_ns()-total,
        "prior_calibration_wall_ns": profile.calibration_wall_ns,
        "current_encoder_calls": 0, "executed_methods": [method],
        "output_rows": len(c), "returned_passes": 1, "compiled_bytes_retained_after_episode": 0,
        "timing_is_estimate_not_deadline": True, "production_authorized": False}
    return output, report
