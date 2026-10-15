"""Bind TRAIN-only symbolic intermediate evidence to physical Granite token rows.

Unlike an oracle readout, this emits only training-time attention masks.  At
inference Core sees the original public tokens and predicts its own attention.
No classifier target or held-out label is read.  Tokenization is repeated with
offset mapping under the same pinned tokenizer and counted by the campaign.
"""
from __future__ import annotations

import hashlib
import json

from group_step_supervision import training_trace


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()



def grouped_slots(operations, max_depth):
    """Compress ordered public operations into a bounded number of slots.

    No operation or terminal evidence is dropped. Multiple adjacent facts
    share one attention target when the trace is longer than the recurrent
    budget. This is a teacher compression, not a claim that a Core step can
    perform several logical operations at inference.
    """
    if (type(operations) is not int or not 1 <= operations <= 64
            or type(max_depth) is not int or not 1 <= max_depth <= 8):
        raise ValueError("bounded operation and recurrent-step counts required")
    if operations <= max_depth:
        return tuple(range(operations))
    return tuple(min(max_depth - 1, (index * max_depth) // operations)
                 for index in range(operations))


def _fact_spans(text, expected):
    if not isinstance(text, str) or not text:
        raise ValueError("bounded public text required")
    lines, cursor = [], 0
    for raw in text.splitlines(keepends=True):
        body = raw.rstrip("\r\n")
        lines.append((cursor, cursor + len(body)))
        cursor += len(raw)
    if len(lines) != expected + 1:
        raise ValueError("expected exactly one prompt and one line per public fact")
    return lines[1:]


def build_train_attention(tasks, snapshots, tokenizer, *, max_depth=4):
    """Return float32 [examples, depth, padded tokens] binary evidence masks.

    A 1 denotes a tokenizer position wholly inside the teacher-selected fact.
    This is not a token-index oracle at inference. Special/prompt/padded tokens
    never become supervision. Trace labels only derive from canonical TRAIN
    evidence, not the stored answer and not any selection/test case.
    """
    import torch
    if (type(max_depth) is not int or not 1 <= max_depth <= 8
            or not tasks or len(tasks) != len(snapshots)
            or not callable(tokenizer)):
        raise ValueError("bounded aligned training cohort and tokenizer required")
    widths = [len(s.mask) for s in snapshots]
    if any(n < 1 or n > 256 for n in widths):
        raise ValueError("invalid frozen token snapshot length")
    targets = torch.zeros((len(tasks), max_depth, max(widths)), dtype=torch.float32)
    trace_hashes, feature_hashes = [], []
    coalesced, supervised, total, supervised_slots, terminal_cases = 0, 0, 0, 0, 0
    slot_assignments = []
    unique_groups = set()
    for i, (task, snapshot) in enumerate(zip(tasks, snapshots)):
        teacher = training_trace(task)
        if task.source_group in unique_groups:
            raise ValueError("duplicate TRAIN source group")
        unique_groups.add(task.source_group)
        if (snapshot.identity.source_digest != hashlib.sha256(task.text.encode()).hexdigest()
                or snapshot.identity.modality != "text"
                or len(snapshot.tokens) != len(snapshot.mask)
                or not all(isinstance(v, bool) for v in snapshot.mask)):
            raise ValueError("feature/text/modality identity mismatch")
        encoded = tokenizer(task.text, return_tensors="pt",
                            return_offsets_mapping=True, truncation=False)
        if not all(k in encoded for k in ("input_ids", "attention_mask", "offset_mapping")):
            raise ValueError("offset-aware tokenizer required; no guessed alignment")
        ids, mask, offsets = (encoded[k] for k in
                              ("input_ids", "attention_mask", "offset_mapping"))
        n = widths[i]
        if (ids.ndim != 2 or ids.shape != (1, n) or
                mask.shape != (1, n) or offsets.shape != (1, n, 2)
                or mask[0].tolist() != [int(v) for v in snapshot.mask]):
            raise ValueError("tokenizer/snapshot row mismatch")
        spans = _fact_spans(task.text, len(task.evidence))
        offsets = offsets[0].tolist()
        for j, (start, end) in enumerate(offsets):
            if (type(start) is not int or type(end) is not int
                    or not 0 <= start <= end <= len(task.text)):
                raise ValueError("invalid tokenizer offsets")
            if start == end or not snapshot.mask[j]:
                continue
            if sum(a <= start and end <= b for a, b in spans) > 1:
                raise ValueError("overlapping fact/token alignment")
        steps = teacher["operation_steps"]
        total += len(steps)
        slots = grouped_slots(len(steps), max_depth)
        coalesced += max(0, len(steps) - max_depth)
        supervised_slots += len(set(slots))
        for operation_index, step in enumerate(steps):
            depth = slots[operation_index]
            idx = step["evidence_index"]
            a, b = spans[idx]
            positions = [j for j, (start, end) in enumerate(offsets)
                         if start < end and snapshot.mask[j] and a <= start and end <= b]
            if not positions:
                raise ValueError("teacher fact lost during tokenization or truncation")
            targets[i, depth, positions] = 1.0
            supervised += 1
        if not targets[i, slots[-1]].any():
            raise ValueError("terminal public evidence was not retained")
        terminal_cases += 1
        slot_assignments.append((task.source_group, list(slots),
                                 [step["evidence_index"] for step in steps]))
        trace_hashes.append(teacher["trace_sha256"])
        feature_hashes.append(snapshot.digest)
    if not supervised:
        raise ValueError("zero aligned intermediate steps")
    return targets, {
        "schema": "hepta.group.train-attention-binding.v2",
        "authority": "DENY_ALL", "train_only": True,
        "source_groups_sha256": digest(sorted(unique_groups)),
        "trace_hashes_sha256": digest(trace_hashes),
        "feature_hashes_sha256": digest(feature_hashes),
        "teacher_tensor_sha256": hashlib.sha256(targets.numpy().tobytes()).hexdigest(),
        "tokenizer_identity_attested_independently": False,
        "supervised_steps": supervised, "truncated_teacher_steps": 0,
        "coalesced_teacher_steps": coalesced,
        "supervised_slots": supervised_slots,
        "terminal_evidence_supervised_cases": terminal_cases,
        "slot_assignment_sha256": digest(slot_assignments),
        "total_teacher_steps": total, "tokenizer_calls": len(tasks),
        "teacher_does_not_run_at_inference": True,
    }
