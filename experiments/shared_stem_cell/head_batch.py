"""Bounded CPU batching of the EXISTING offline Heads, not a new runtime owner.

Packing copies only Head tensors; no Encoder, optimizer, execution capability or
live selection is created. Callers own feature/Scope provenance. Numerical parity
is measured against a strong per-Cell grouped baseline; batching is never selected
automatically, even if this one workload is faster.
"""
from __future__ import annotations

from collections import defaultdict
import math
from pathlib import Path
import time

import torch

from experiments.shared_stem_cell.execution import (
    Head, InputError, integer, measured, parameters, tensor_digest,
)
from experiments.shared_stem_cell.head_artifacts import _shape_count, load_head
from experiments.shared_stem_cell.wire import canonical, sha

ATOL, RTOL = 1e-6, 1e-5  # fixed before measurement; never fit to task answers
MAX_BANK_BYTES = 256 * 1024**2
MAX_SCRATCH_BYTES = 64 * 1024**2
CHUNK = 32


class PackedHeads:
    """One homogeneous immutable-by-convention candidate bank, up to 4096 Cells.

    Originals are neither retained nor mutated. Private owned f32 tensors are
    inference-only. This ordinary Python object is NOT an isolation/security
    boundary against arbitrary in-process mutation, and conveys no authority.
    """
    def __init__(self, entries, *, maximum_parameter_bytes=MAX_BANK_BYTES):
        if type(entries) is not tuple or not 1 <= len(entries) <= 4096:
            raise InputError("bounded tuple of Cell/Head entries required")
        integer(maximum_parameter_bytes, 1, MAX_BANK_BYTES, "packed parameter budget")
        states, identities, self._rows = [], [], {}
        architecture = None
        for item in entries:
            if type(item) is not tuple or len(item) != 2:
                raise InputError("exact Cell/Head pair required")
            cell, model = item
            integer(cell, 0, 4095, "logical cell")
            if cell in self._rows or type(model) is not Head or model.training:
                raise InputError("distinct Cells and existing inference Heads required")
            shape = {"kind": model.kind, "width": model.base.in_features,
                     "classes": model.base.out_features,
                     "rank": model.down.out_features if hasattr(model, "down") else 1}
            count = _shape_count(shape)
            if architecture is not None and architecture != shape:
                raise InputError("homogeneous Head architecture required")
            architecture = shape
            if count * 4 * len(entries) > maximum_parameter_bytes:
                raise InputError("packed parameter budget exceeded before allocation")
            state = model.state_dict()
            if (sum(t.numel() for t in state.values()) != count
                    or any(t.device.type != "cpu" or t.dtype != torch.float32
                           or not bool(torch.isfinite(t).all()) for t in state.values())):
                raise InputError("finite complete CPU float32 Head state required")
            if states and (set(state) != set(states[0]) or
                           any(state[k].shape != states[0][k].shape for k in state)):
                raise InputError("Head tensor inventory differs")
            self._rows[cell] = len(states)
            states.append(state)
            identities.append([cell, parameters(model)["sha256"]])
        self.kind, self.width, self.classes, self.rank = (
            architecture[k] for k in ("kind", "width", "classes", "rank"))
        self.parameter_bytes = count * 4 * len(entries)
        self.identity = sha(canonical({"architecture": architecture, "cells": identities}))
        self._weights = {k: torch.stack([s[k] for s in states]).detach().contiguous()
                         for k in states[0] if not k.startswith("experts.")}
        if self.kind == "sparse_expert":
            for part in ("weight", "bias"):
                self._weights[f"experts.{part}"] = torch.stack([
                    torch.stack([s[f"experts.{j}.{part}"] for j in range(2)])
                    for s in states]).detach().contiguous()
        if identities != [[cell, parameters(model)["sha256"]] for cell, model in entries]:
            raise InputError("source Head changed during packing")
        self.backend_invocations = 0

    def preflight(self, x, cells, maximum_scratch_bytes):
        integer(maximum_scratch_bytes, 1, MAX_SCRATCH_BYTES, "numeric scratch budget")
        if (type(cells) is not tuple or not 1 <= len(cells) <= 16384
                or any(type(c) is not int or c not in self._rows for c in cells)
                or not isinstance(x, torch.Tensor) or x.device.type != "cpu"
                or x.dtype != torch.float32 or x.shape != (len(cells), self.width)):
            raise InputError("complete finite feature/Cell batch required")
        # Conservative bound for our owned gather, arithmetic, index and output
        # tensors, including a conservative full-input validation allowance.
        # Excludes borrowed x, packed resident tensors, Python, allocator
        # caching and internal BLAS workspace. It is NOT a process RSS bound.
        per_head = self.parameter_bytes // len(self._rows)
        scratch = (min(CHUNK, len(cells)) * (2 * per_head +
                   4 * (4 * self.width + 8 * self.classes + 4 * self.rank) + 64)
                   + len(cells) * (4 * self.classes + 32))
        scratch = max(scratch, 8 * x.numel() + len(cells) * 32)
        if scratch > maximum_scratch_bytes:
            raise InputError("numeric scratch budget exceeded before arithmetic")
        if not bool(torch.isfinite(x).all()):
            raise InputError("nonfinite feature batch")
        return scratch

    @torch.no_grad()
    def run(self, x, cells, *, maximum_scratch_bytes=MAX_SCRATCH_BYTES):
        bound = self.preflight(x, cells, maximum_scratch_bytes)
        output = torch.empty(len(cells), self.classes, dtype=torch.float32, device="cpu")
        matrix_calls = expert_rows = chunks = 0
        self.backend_invocations += 1
        # Pack each Cell's own request rows together before cross-Cell batching.
        # Exact-size buckets avoid both padded lanes and repeated per-row weights.
        positions, buckets = defaultdict(list), defaultdict(list)
        for position, cell in enumerate(cells):
            positions[cell].append(position)
        for cell, locations in positions.items():
            for start in range(0, len(locations), CHUNK):
                part = locations[start:start + CHUNK]
                buckets[len(part)].append((self._rows[cell], part))
        gathered_heads = 0
        for size, blocks in buckets.items():
            batch_cells = max(1, CHUNK // size)
            for start in range(0, len(blocks), batch_cells):
                group = blocks[start:start + batch_cells]
                rows = torch.tensor([g[0] for g in group], dtype=torch.long)
                locations = torch.tensor([g[1] for g in group], dtype=torch.long)
                values = x[locations]

                def linear(prefix, inputs):
                    nonlocal matrix_calls
                    w = self._weights[prefix + ".weight"].index_select(0, rows)
                    result = torch.bmm(inputs, w.transpose(1, 2))
                    matrix_calls += 1
                    if prefix + ".bias" in self._weights:
                        result = result + self._weights[prefix + ".bias"].index_select(0, rows).unsqueeze(1)
                    return result

                result = linear("base", values)
                if self.kind in {"gated", "low_rank"}:
                    residual = linear("up", torch.tanh(linear("down", values)))
                    if self.kind == "gated":
                        residual *= torch.sigmoid(linear("gate", values))
                    result += residual
                elif self.kind == "sparse_expert":
                    # Preserve the existing eval-time softmax/top-1/tie policy.
                    chosen = linear("router", values).softmax(-1).argmax(-1).flatten()
                    owners = rows.repeat_interleave(size)
                    w = self._weights["experts.weight"][owners, chosen]
                    b = self._weights["experts.bias"][owners, chosen]
                    local = torch.bmm(w, values.reshape(-1, self.width).unsqueeze(-1)).squeeze(-1) + b
                    result += local.reshape(len(group), size, self.classes)
                    matrix_calls += 1
                    expert_rows += len(group) * size
                output[locations] = result
                gathered_heads += len(group)
                chunks += 1
        if not bool(torch.isfinite(output).all()):
            raise InputError("nonfinite batched Head result")
        return output, {"active_rows": len(cells), "active_cells": len(set(cells)),
            "resident_cells": len(self._rows), "physical_chunks": chunks,
            "bmm_calls": matrix_calls, "expert_rows": expert_rows,
            "gathered_head_blocks": gathered_heads,
            "owned_numeric_scratch_bound_bytes": bound, "packed_parameter_bytes": self.parameter_bytes}


@torch.no_grad()
def compare_heads(entries, x, cells, *, repetitions=7):
    """Same exact features/weights; each scalar Head already groups its own rows.

    Validation, active routing, gathers, arithmetic and output assembly are ALL
    timed in each arm. Packing is separately charged, and raw timings/logits are
    returned. No labels or model-promotion decision enters this comparison.
    """
    integer(repetitions, 3, 101, "timing repetitions")
    with measured() as packing:
        bank = PackedHeads(entries)
    bank.preflight(x, cells, MAX_SCRATCH_BYTES)
    originals = {cell: parameters(model) for cell, model in entries}
    models = dict(entries)
    timings, outputs, details = {"per_cell_grouped": [], "packed": []}, {}, {}
    for repeat in range(repetitions):
        order = ("per_cell_grouped", "packed") if repeat % 2 == 0 else ("packed", "per_cell_grouped")
        for arm in order:
            begin = time.perf_counter_ns()
            if arm == "packed":
                value, detail = bank.run(x, cells)
            else:
                bank.preflight(x, cells, MAX_SCRATCH_BYTES)
                groups = defaultdict(list)
                for row, cell in enumerate(cells):
                    groups[cell].append(row)
                value = torch.empty(len(cells), bank.classes, dtype=torch.float32, device="cpu")
                for cell, ids in groups.items():
                    value[ids] = models[cell](x[ids])
                if not bool(torch.isfinite(value).all()):
                    raise InputError("nonfinite per-Cell Head result")
                detail = {"head_forward_calls": len(groups), "active_rows": len(cells)}
            elapsed = time.perf_counter_ns() - begin
            timings[arm].append(elapsed)
            if arm in outputs and not torch.equal(outputs[arm], value):
                raise InputError("same-arm repeated output drift")
            outputs[arm], details[arm] = value, detail
    if originals != {cell: parameters(model) for cell, model in entries}:
        raise InputError("original Head mutated during comparison")
    reference, candidate = outputs["per_cell_grouped"], outputs["packed"]
    flips = int((reference.argmax(-1) != candidate.argmax(-1)).sum())
    close = bool(torch.allclose(reference, candidate, atol=ATOL, rtol=RTOL))
    quantiles = {arm: {f"p{p}": sorted(samples)[math.ceil(len(samples) * p / 100) - 1]
                      for p in (50, 95, 99)} for arm, samples in timings.items()}
    saving = quantiles["per_cell_grouped"]["p50"] - quantiles["packed"]["p50"]
    return {"schema": "hepta.head-batch-comparison.v1", "bank_sha256": bank.identity,
        "feature_sha256": tensor_digest(x), "logical_cells": list(cells),
        "implementation_sha256": sha(Path(__file__).read_bytes()),
        "packing": packing, "counts": details, "samples_ns": timings, "quantiles_ns": quantiles,
        "logits": {k: v.tolist() for k, v in outputs.items()},
        "logit_sha256": {k: tensor_digest(v) for k, v in outputs.items()},
        "max_absolute_logit_difference": float((reference - candidate).abs().max()),
        "argmax_changes": flips, "atol": ATOL, "rtol": RTOL,
        "numerical_parity_passed": close and flips == 0,
        "pack_amortization_replays": math.ceil(packing["wall_ns"] / saving)
            if saving > 0 and close and flips == 0 else None,
        "includes_encoder_or_training": False, "production_accepted": False}


def compare_exported_heads(root, training, x, cases, *, repetitions=7):
    """Reopen the already exported per-Cell artifacts; never repeat training.

    Input comes from the existing producer, not an independently trusted caller.
    Binding checks reuse load_head; artifact paths are derived from exact Cell IDs,
    never from a caller-controlled relative_path. Official scores remain scalar.
    """
    selected = [i for i, c in enumerate(cases) if c.split in {"holdout", "retention"}]
    if not selected or len({c.scope for c in cases}) != 1:
        raise InputError("same-scope heldout Head comparison required")
    features, cells = x[selected], tuple(cases[i].cell for i in selected)
    reports = {}
    for kind, costs in training.items():
        if kind not in {"linear", "gated", "low_rank", "sparse_expert"}:
            raise InputError("closed trained Head kind")
        entries = []
        context = None
        with measured() as reopening:
            for cost in costs:
                cell = integer(cost["cell"], 0, 4095, "artifact logical cell")
                receipt = cost["offline_head_artifacts"]["learned"]
                binding = receipt["binding"]
                if binding["scope"] != cases[0].scope or binding["logical_cell"] != str(cell):
                    raise InputError("Head artifact Cell/Scope mismatch")
                common = {k: v for k, v in binding.items()
                          if k not in {"logical_cell", "training_lineage_sha256"}}
                if context is not None and common != context:
                    raise InputError("mixed Stem/feature/dataset/generation Head bank")
                context = common
                model = load_head(Path(root) / kind / f"cell-{cell}" / "learned",
                                  receipt["manifest_sha256"], binding)
                if model.kind != kind:
                    raise InputError("artifact kind mismatch")
                entries.append((cell, model))
        reports[kind] = {**compare_heads(tuple(entries), features, cells, repetitions=repetitions),
            "artifact_reopening": reopening, "binding_context": context,
            "case_ids": [cases[i].case_id for i in selected]}
    return reports
