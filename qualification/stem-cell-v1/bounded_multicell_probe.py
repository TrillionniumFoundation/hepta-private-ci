"""Common-validation, four-way Cell inference probe; no new runtime or trainer.

V6's folded timing omitted checks required on the shared path. Keep those
historical measurements, but do not use them as equal-validation speed claims.
This probe charges the same request preflight to every timed batch.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import statistics
import time

import torch

from bounded_cell_execution import (
    DEFAULT_SCRATCH_BYTES, _checked_comparison, _finite, _fold, tile_plan,
)
from development_tensors import MAX_ELEMENTS, parameter_digest
from shared_cell_execution import _validate_request

METHODS = ("expanded_checked", "shared_checked", "full_folded_checked", "tiled_folded")
MAX_ERROR = 1e-4


def probe_bounded(bank, features, fids, cids, *, repeats=4,
                  maximum_scratch_bytes=DEFAULT_SCRATCH_BYTES):
    """Fixed timing protocol; no task labels, model selection or claimed speedup.

    Full folding compiles only the actually referenced Cell union, with its
    separate 64 MiB resident-matrix limit. Only the tiled
    arm guarantees the explicit temporary-byte bound. These are unequal memory
    envelopes, not an equal-resource efficacy experiment. Precompilation cost
    and actual finite reuse count are reported, never amortized over future use.
    """
    if type(repeats) is not int or not 4 <= repeats <= 16 or repeats % 4:
        raise ValueError("four complete method-position rotations required")
    if torch.is_grad_enabled():
        raise ValueError("probe requires disabled autograd")
    total_cpu, total_wall = time.process_time_ns(), time.perf_counter_ns()
    _validate_request(bank, features, fids, cids, MAX_ELEMENTS)
    # No full dense allocation before its separate, explicitly unequal cap.
    active = torch.unique(cids, sorted=True)
    folded_bytes = len(active)*(bank.width*bank.classes+bank.width+1)*features.element_size()
    if folded_bytes > 64*1024*1024:
        raise ValueError("full-folded control exceeds separate 64 MiB envelope")
    _finite(*bank.state_dict().values())
    tile_plan(bank, features[:1], cids[:1], maximum_scratch_bytes)
    before = parameter_digest(bank)
    preparation_cpu, preparation_wall = time.process_time_ns(), time.perf_counter_ns()
    # Owned, bounded probe snapshot. Never cache views across mutation/epochs.
    fixed = deepcopy(bank).requires_grad_(False)
    batches = []
    for start in range(0, len(cids), 32):
        unique, inverse = torch.unique(fids[start:start+32], sorted=True, return_inverse=True)
        x, ids = features[unique].clone(), cids[start:start+32].clone()
        tile_plan(fixed, x, ids, maximum_scratch_bytes)
        batches.append((x, inverse, ids))
    preparation = {"cpu_ns": time.process_time_ns()-preparation_cpu,
                   "wall_ns": time.perf_counter_ns()-preparation_wall,
                   "copied_bank_tensor_bytes": sum(v.numel()*v.element_size() for v in fixed.state_dict().values())}
    inputs = hashlib.sha256(b"hepta.stem.bounded-probe.inputs.v1")
    for tensor in (features, fids, cids):
        raw = tensor.detach().contiguous().numpy().tobytes()
        inputs.update(len(raw).to_bytes(8, "big")); inputs.update(raw)
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    tensors = _fold(fixed, active)
    lookup = torch.full((len(fixed.cell_ids),), -1, dtype=torch.long)
    lookup[active] = torch.arange(len(active))
    folded = (*tensors, lookup)
    compilation = {"cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-wall,
                   "additional_tensor_bytes": sum(t.numel()*t.element_size() for t in tensors),
                   "compiled_active_cells": len(active), "registered_cells": len(fixed.cell_ids),
                   "index_lookup_bytes": lookup.numel()*lookup.element_size(),
                   "separate_resident_matrix_ceiling_bytes": 64*1024*1024}
    if compilation["additional_tensor_bytes"] != folded_bytes:
        raise ValueError("unaccounted folded matrix storage")
    warmup = {}
    for method in METHODS:
        cpu, wall = time.process_time_ns(), time.perf_counter_ns()
        _checked_comparison(fixed, *batches[0], method, folded, maximum_scratch_bytes)
        warmup[method] = {"cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-wall}
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    # Retain the existing bank implementation as the untimed equation oracle.
    reference = torch.cat([fixed(x[f], c) for x, f, c in batches])
    _finite(reference)
    reference_cost = {"cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-wall}
    trials = []
    for repeat in range(repeats):
        order = METHODS[repeat % 4:] + METHODS[:repeat % 4]
        for position, method in enumerate(order):
            cpu, wall = time.process_time_ns(), time.perf_counter_ns()
            results = [_checked_comparison(fixed, *batch, method, folded, maximum_scratch_bytes)
                       for batch in batches]
            output = torch.cat([pair[0] for pair in results])
            duration = {"cpu_ns": time.process_time_ns()-cpu, "wall_ns": time.perf_counter_ns()-wall}
            error = float((output-reference).abs().max())
            if error > MAX_ERROR or not torch.equal(output.argmax(1), reference.argmax(1)):
                raise ValueError("bounded execution differs from original Cell equation")
            item = {"repeat": repeat, "position": position, "method": method, **duration,
                    "request_rows": len(cids), "input_preflight_calls": len(batches),
                    "output_checked_rows": len(cids), "max_abs_logit_error": error, "argmax_reversals": 0}
            if method == "tiled_folded":
                work = [pair[1] for pair in results]
                item["tile_work"] = {
                    "compiled_cell_matrices": sum(w["compiled_cell_matrices"] for w in work),
                    "tile_count": sum(w["tile_count"] for w in work),
                    "maximum_live_compiled_cells": max(w["maximum_live_compiled_cells"] for w in work),
                    "explicit_scratch_upper_bytes": max(w["explicit_scratch_upper_bytes"] for w in work),
                    "folded_matrices_upper_bytes": max(w["folded_matrices_upper_bytes"] for w in work),
                    "retained_compiled_bytes_after_call": 0}
            trials.append(item)
    if parameter_digest(bank) != before or parameter_digest(fixed) != before:
        raise ValueError("fixed benchmark snapshot mutated")
    return {"schema": "hepta.stem.bounded-compute-probe.v1", "parameter_sha256": before,
            "input_bytes_sha256": inputs.hexdigest(), "request_rows": len(cids),
            "unique_inputs": len(features), "active_cells": len(torch.unique(cids)),
            "methods": list(METHODS), "repeats": repeats, "trials": trials,
            "median_wall_ns": {m: statistics.median(t["wall_ns"] for t in trials if t["method"] == m) for m in METHODS},
            "preparation": preparation, "full_folded_compilation": compilation,
            "full_folded_measured_invocations": 1 + repeats*len(batches),
            "warmup": warmup, "reference_cost": reference_cost,
            "explicit_tiled_scratch_ceiling_bytes": maximum_scratch_bytes,
            "scratch_excludes": ["bank/input tensors", "boolean/index temporaries", "Python/allocator", "library workspace", "RSS"],
            "total_cpu_ns": time.process_time_ns()-total_cpu,
            "total_wall_ns": time.perf_counter_ns()-total_wall,
            "autograd_enabled": False, "encoder_calls_this_run": 0,
            "equal_memory_envelopes": False, "quality_superiority_established": False,
            "production_authorized": False}
