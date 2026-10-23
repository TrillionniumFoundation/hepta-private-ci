"""Source-only gradient sketches and dependency-preserving learned partitions."""

import hashlib
import time

import numpy as np
import torch

from grounded_protocol import completion_ids
from native import digest
from parametric_model import adapter_digest
from pretrained import frozen_digest
from source_completion_loss import completion_loss


def source_gradient_sketches(cell, facts, template, *, width=32):
    if type(width) is not int or not 8 <= width <= 128 or not 2 <= len(facts) <= 128:
        raise ValueError("bounded projection and source cohort required")
    cell._available()
    before = adapter_digest(cell.reader.model)
    started = time.perf_counter()
    named = [(n, p) for n, p in cell.reader.model.named_parameters() if "lora_" in n]
    maps = []
    for name, parameter in named:
        parameter.requires_grad_(True)
        seed = int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "little")
        coordinates = np.arange(parameter.numel(), dtype=np.uint64)
        mixed = coordinates * np.uint64(2654435761) + np.uint64(seed)
        maps.append(((mixed % width).astype(np.int64), ((mixed >> 9) % 2) * 2.0 - 1.0))
    rows, losses, tokens = [], [], 0
    try:
        for fact in facts:
            if fact["scope"] != cell.reader.scope:
                raise ValueError("gradient source scope mismatch")
            question = template.format(entity=fact["entity"], relation=fact["relation"])
            prompt = cell.prompt_ids(question)
            ids, labels = completion_ids(
                cell.reader.tokenizer, prompt, fact["value"], maximum=256
            )
            loss, charge = completion_loss(
                cell.reader.model, ids, labels, backend="full"
            )
            gradients = torch.autograd.grad(loss, [p for _, p in named])
            sketch = np.zeros(width, dtype=np.float64)
            for gradient, (buckets, signs) in zip(gradients, maps, strict=True):
                flat = gradient.detach().cpu().reshape(-1).numpy()
                sketch += np.bincount(buckets, weights=flat * signs, minlength=width)
            if not np.isfinite(sketch).all() or not torch.isfinite(loss):
                raise ValueError("nonfinite source-gradient projection")
            rows.append(sketch.tolist())
            losses.append(float(loss.detach()))
            tokens += charge["input_tokens"]
    finally:
        cell._freeze()
    if (
        adapter_digest(cell.reader.model) != before
        or frozen_digest(cell.reader.model) != cell.reader.base_digest
    ):
        raise ValueError("source probe changed weights")
    return {
        "schema": "hepta.parametric-memory.gradient-sketch.v1",
        "projection": "signed_coordinate_hash_sum_v1",
        "width": width,
        "sketches": rows,
        "completion_losses": losses,
        "source_facts_sha256": digest(facts),
        "source_digests": [f["source_digest"] for f in facts],
        "adapter_before_after_sha256": before,
        "optimizer_updates": 0,
        "model_forwards_and_backwards": len(facts),
        "input_tokens": tokens,
        "seconds": time.perf_counter() - started,
        "evaluation_targets_used": False,
    }


def _balanced_subset(scores, weights, target):
    # Exact dynamic programming balances examples while preserving whole source
    # dependency groups. Ties use stable group order, never family or gold labels.
    states = {0: (0.0, ())}
    for index, (score, weight) in enumerate(zip(scores, weights, strict=True)):
        previous = dict(states)
        for total, (utility, chosen) in previous.items():
            new = total + weight
            if new > target:
                continue
            candidate = utility + float(score) * weight, chosen + (index,)
            current = states.get(new)
            if current is None or candidate[0] > current[0]:
                states[new] = candidate
    if target not in states:
        raise ValueError("source dependency groups cannot satisfy registered balance")
    return set(states[target][1])


def balanced_partition(sketches, groups, *, seed, iterations=16):
    matrix = np.asarray(sketches, dtype=np.float64)
    if (
        matrix.ndim != 2
        or not 2 <= len(matrix) <= 128
        or len(matrix) % 2
        or matrix.shape[1] < 2
        or not np.isfinite(matrix).all()
        or len(groups) != len(matrix)
        or any(type(g) is not str or not g for g in groups)
        or type(seed) is not int
        or not 0 <= seed < 2**31
        or type(iterations) is not int
        or not 1 <= iterations <= 64
    ):
        raise ValueError("finite bounded sketches, dependency groups and seed required")
    names = sorted(set(groups))
    indices = [[i for i, group in enumerate(groups) if group == name] for name in names]
    weights = [len(part) for part in indices]
    vectors = np.asarray([matrix[part].mean(axis=0) for part in indices])
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    if len(names) < 2 or not np.any(vectors):
        raise ValueError("nonzero gradients from multiple dependency groups required")
    first = int(np.random.default_rng(seed).integers(len(names)))
    second = int(np.argmin(vectors @ vectors[first]))
    centers = vectors[[first, second]].copy()
    chosen, history = None, []
    for _ in range(iterations):
        difference = vectors @ centers[1] - vectors @ centers[0]
        next_chosen = _balanced_subset(difference, weights, len(matrix) // 2)
        assignment = [int(i in next_chosen) for i in range(len(names))]
        history.append(assignment)
        if next_chosen == chosen:
            break
        chosen = next_chosen
        for slot in (0, 1):
            mask = np.asarray(assignment) == slot
            center = np.average(
                vectors[mask], axis=0, weights=np.asarray(weights)[mask]
            )
            centers[slot] = center / max(float(np.linalg.norm(center)), 1e-12)
    slots = [assignment[names.index(group)] for group in groups]
    return {
        "schema": "hepta.parametric-memory.learned-partition.v1",
        "algorithm": "dependency_group_gradient_cosine_balanced_two_means_v1",
        "seed": seed,
        "slots": slots,
        "group_slots": dict(zip(names, assignment, strict=True)),
        "cluster_sizes": [slots.count(0), slots.count(1)],
        "iterations": len(history),
        "assignment_history": history,
        "sketches_sha256": digest(sketches),
        "groups_sha256": digest(groups),
        "memory_family_labels_used": False,
        "final_queries_used": False,
    }
