"""Train data-proposed children and matched rank/static alternatives."""

import json
from pathlib import Path
import time

import numpy as np

from cells import Cell, RoutedPair, SEMANTIC_OUTPUTS, fit, objective
from corpus import targets, source_id
from export_native import canonical, sha


def train_structure(parent, x, rows, protocol, seed, output, encoder_sha):
    output = Path(output)
    output.mkdir()
    values = np.asarray([row["value"] for row in rows], dtype=np.int64)
    corrected = [i for i in range(len(rows)) if i % 7 == 0]
    values[corrected] = (values[corrected] + np.asarray([5, 3, 7])) % 16
    y = targets(values.tolist(), "semantic")
    started = time.perf_counter()
    _, derivatives = objective(parent.forward(x), y, SEMANTIC_OUTPUTS)
    gradients = np.asarray([parent.gradients(x[i:i + 1], derivatives[i:i + 1])["B"].reshape(-1) for i in range(len(x))])
    first = int(np.argmax(np.linalg.norm(gradients, axis=1)))
    second = int(np.argmax(np.linalg.norm(gradients - gradients[first], axis=1)))
    centers = gradients[[first, second]].copy()
    valid = first != second
    assignments = np.zeros(len(x), dtype=np.int64)
    iterations = 0
    for iterations in range(20):
        assignments = np.argmin(np.sum((gradients[:, None, :] - centers[None, :, :]) ** 2, axis=2), axis=1)
        if not all(np.any(assignments == i) for i in (0, 1)):
            valid = False
            break
        centers = np.asarray([gradients[assignments == i].mean(0) for i in (0, 1)])
    proposal_seconds = time.perf_counter() - started
    # A degenerate proposal is retained as failed, never replaced by a good-looking split.
    np.savez_compressed(output / "proposal.npz", gradients=gradients, centers=centers, assignments=assignments)
    schedule = np.random.default_rng(seed + 80000).integers(len(x), size=(protocol["budget"]["structure_steps"], 32), dtype=np.int64)
    np.save(output / "schedule.npy", schedule, allow_pickle=False)
    ids = [source_id("semantic", i, 1) if i in corrected else row["source_id"] for i, row in enumerate(rows)]
    arms = {"rank8": parent.fork(rank=8, seed=seed + 100)}
    if valid:
        arms["dynamic_children"] = RoutedPair([parent.fork(seed=seed + 101), parent.fork(seed=seed + 102)], assignments)
    arms["fixed_experts"] = RoutedPair([parent.fork(seed=seed + 103), parent.fork(seed=seed + 104)], np.arange(len(x)) % 2)
    result = {"proposal_valid": valid, "assignments": assignments.tolist(), "proposal_wall_seconds": proposal_seconds,
              "iterations": iterations + 1, "corrected_indices": corrected, "values": values.tolist(),
              "historical_parent_parameter_sha256": parent.identity(), "arms": {},
              "required_full_lifecycle_cost_scopes_measured": False, "split_admitted": False,
              "admission_reason": "complete native owner/installation/lifecycle comparison is not measured in this research process"}
    for name, model in arms.items():
        receipt = fit(model, x, y, SEMANTIC_OUTPUTS, schedule, lr=protocol["optimizer"]["learning_rate"], source_ids=ids, label="structure-" + name)
        children = model.cells if isinstance(model, RoutedPair) else [model]
        checkpoints = [child.save(output / f"{name}-{i}", encoder_sha256=encoder_sha, outputs=SEMANTIC_OUTPUTS,
                                  extra={"private_adapter_shared_frozen_head": True, "parent": parent.identity()}) for i, child in enumerate(children)]
        result["arms"][name] = {"fit": receipt, "checkpoints": checkpoints,
                                "assignments": model.assignments.tolist() if isinstance(model, RoutedPair) else None,
                                "logical_unique_parameter_count": 12 * 384 + 12 + 2 * 384 * 8,
                                "physical_checkpoint_bytes": sum(item["stored_bytes"] for item in checkpoints)}
    if valid:
        dynamic = arms["dynamic_children"]
        dynamic.rows = np.arange(len(x))
        logits = dynamic.forward(x)
        teacher = 1 / (1 + np.exp(-np.clip(logits, -60, 60)))
        merged = parent.fork(seed=seed + 105)
        merge_schedule = np.random.default_rng(seed + 81000).integers(len(x), size=(protocol["budget"]["merge_steps"], 32), dtype=np.int64)
        np.save(output / "merge-schedule.npy", merge_schedule, allow_pickle=False)
        np.save(output / "merge-teacher.npy", teacher, allow_pickle=False)
        receipt = fit(merged, x, teacher, SEMANTIC_OUTPUTS, merge_schedule, lr=0.01, source_ids=ids, label="merge-distillation")
        saved = merged.save(output / "merged", encoder_sha256=encoder_sha, outputs=SEMANTIC_OUTPUTS,
                            extra={"teacher_parameters": [cell.identity() for cell in dynamic.cells]})
        result["merge"] = {"fit": receipt, "checkpoint": saved, "admitted": False,
                           "reason": "cost completeness gate remains closed"}
        # This is an actual memory release/reload operation, measured by the fresh evaluator.
        result["sleep_wake_contract"] = "fresh evaluator reads saved child after releasing its in-memory arrays"
    (output / "STRUCTURE.json").write_bytes(canonical(result))
    return result
