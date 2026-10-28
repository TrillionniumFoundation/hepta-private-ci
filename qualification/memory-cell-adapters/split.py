"""Budget-comparable branching and behavior-based merge candidates."""

from dataclasses import replace
import time

import numpy as np

from tensor_cell import TensorCell, digest


def split_pair(parent, child_ids):
    if len(child_ids) != 2 or len(set(child_ids)) != 2:
        raise ValueError("a split requires two distinct child identities")
    return tuple(parent.fork(identity) for identity in child_ids)


def matched_high_rank(parent, cell_id):
    """Match two private rank-r adapters using one rank-2r adapter and one head."""
    return parent.expand_rank(2 * parent.config.rank, cell_id)


def fixed_experts(parent, child_ids):
    """Static partition comparator; the caller supplies its frozen assignments."""
    return split_pair(parent, child_ids)


def distill_merge(teachers, features, teacher_indices, *, source_ids, cell_id, rank,
                  steps=100, batch_size=32, lr=0.01, seed=0):
    """Return an unaccepted merge candidate trained on routed teacher behavior.

    Each row has exactly one selected teacher.  Conflicting cell parameters or
    outputs are never averaged; the caller must separately validate retention.
    """
    started, cpu_started = time.perf_counter(), time.process_time()
    if not teachers:
        raise ValueError("merge needs teachers")
    first = teachers[0]
    for teacher in teachers:
        if (teacher.base_encoder_sha != first.base_encoder_sha or
                teacher.config.input_dim != first.config.input_dim or
                teacher.config.outputs != first.config.outputs):
            raise ValueError("incompatible teacher contracts")
        if any(not np.array_equal(a.detach().numpy(), b.detach().numpy())
               for a, b in zip(teacher.head.parameters(), first.head.parameters(), strict=True)):
            raise ValueError("this merge profile requires the same frozen shared head")
    x = np.asarray(features, dtype=np.float32)
    selected = np.asarray(teacher_indices)
    if selected.shape != (len(x),) or not np.array_equal(selected, selected.astype(np.int64)):
        raise ValueError("one integer teacher assignment per row required")
    if np.any(selected < 0) or np.any(selected >= len(teachers)):
        raise ValueError("teacher assignment outside teacher set")
    targets = {s.name: np.zeros((len(x), s.size), dtype=np.float32) for s in first.config.outputs}
    for index, teacher in enumerate(teachers):
        rows = selected == index
        if rows.any():
            values = teacher.predict_proba(x[rows])
            for name in targets:
                targets[name][rows] = values[name]
    first.freeze_head()
    if rank >= first.config.rank:
        candidate = first.expand_rank(rank, cell_id)
    else:
        candidate = TensorCell(replace(first.config, cell_id=cell_id, rank=rank, seed=seed),
                               first.base_encoder_sha, head=first.head)
    candidate.source_ids = set().union(*(teacher.source_ids for teacher in teachers))
    candidate.parents = [{"cell_id": t.config.cell_id, "parameter_sha256": t.parameter_digest()}
                         for t in teachers]
    receipt = candidate.fit(x, targets, source_ids=source_ids, steps=steps, batch_size=batch_size,
                            lr=lr, seed=seed, train_head=False)
    receipt["objective"] = "routed teacher behavior distillation; no parameter averaging"
    receipt["teacher_parameter_sha256"] = [t.parameter_digest() for t in teachers]
    receipt["teacher_assignments_sha256"] = digest(selected.astype("<i8").tobytes())
    receipt["teacher_forward_rows"] = len(x)
    receipt["distillation_total_wall_seconds"] = time.perf_counter() - started
    receipt["distillation_total_cpu_seconds"] = time.process_time() - cpu_started
    receipt["distillation_total_includes_fit"] = True
    return candidate, receipt
