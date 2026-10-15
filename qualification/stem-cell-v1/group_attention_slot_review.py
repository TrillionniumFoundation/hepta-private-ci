"""Independent public-evidence replay of TRAIN operation-to-slot supervision.

No Torch, Encoder, Group Task object, or training labels are imported.
This audits the human-readable training provenance and bounded slot map only;
a feature SHA does not independently prove physical tokenizer/model execution.
"""
from __future__ import annotations
import hashlib
import json
import re

from group_campaign_review import _parse


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _public_ops(case):
    """Reconstruct minimal ordered evidence operations from raw public text."""
    _answer, query, source = _parse(case)
    if source != case["source_group"]:
        raise ValueError("training public source not independently reproducible")
    lines = case["text"].splitlines()[1:]
    family = case["family"]
    if family == "dependency":
        links, labels = {}, {}
        for i, text in enumerate(lines):
            link = re.fullmatch(r"(n\d+) links to (n\d+)\.", text)
            label = re.fullmatch(r"(n\d+) has class ([A-H])\.", text)
            if link:
                if link[1] in links:
                    raise ValueError("conflicting dependency links")
                links[link[1]] = (i, link[2])
            elif label:
                if label[1] in labels:
                    raise ValueError("conflicting terminal label")
                labels[label[1]] = i
            else:
                raise ValueError("unregistered dependency line")
        current, seen, steps = query[1], set(), []
        while current in links:
            if current in seen:
                raise ValueError("cycle in independent public evidence")
            seen.add(current)
            position, current = links[current]
            steps.append(("follow_edge", position))
        if current not in labels:
            raise ValueError("terminal public label missing")
        steps.append(("read_terminal_label", labels[current]))
    elif family == "constraint":
        for text in lines:
            if re.fullmatch(r"Constraint \d+ allows [A-H](?: [A-H])*\.", text) is None:
                raise ValueError("unregistered constraint fact")
        steps = [("intersect_constraints", i) for i in range(len(lines))]
    elif family == "temporal":
        last_time, steps = None, []
        for i, text in enumerate(lines):
            event = re.fullmatch(r"At time (\d+), (sensor\d+) has class ([A-H])\.", text)
            if event is None:
                raise ValueError("unregistered temporal event")
            if event[2] != query[1]:
                continue
            event_time = int(event[1])
            if last_time is None or event_time > last_time:
                steps.append(("update_latest_event", i))
                last_time = event_time
        if not steps:
            raise ValueError("no relevant public temporal event")
    else:
        raise ValueError("training teacher family not registered")
    if not 1 <= len(steps) <= 64:
        raise ValueError("bounded public operation sequence required")
    return steps


def _slots(length, depth):
    if not 1 <= length <= 64 or not 1 <= depth <= 8:
        raise ValueError("bounded stage geometry required")
    if length <= depth:
        return list(range(length))
    return [min(depth-1, (i*depth)//length) for i in range(length)]


def review_train_slots(public_cases, receipt, max_depth):
    """Recompute all supervised operations; reject missing terminal evidence."""
    if (type(public_cases) is not list or not public_cases
            or len(public_cases) > 4096
            or type(max_depth) is not int or not 1 <= max_depth <= 8):
        raise ValueError("bounded public train manifest required")
    if (type(receipt) is not dict
            or receipt.get("schema") != "hepta.group.train-attention-binding.v2"
            or receipt.get("authority") != "DENY_ALL"
            or receipt.get("train_only") is not True):
        raise ValueError("TRAIN-only bounded receipt required")
    rows = receipt.get("slot_assignments")
    if type(rows) is not list or len(rows) != len(public_cases):
        raise ValueError("all public TRAIN source/slot records required")
    if receipt.get("slot_assignment_sha256") != digest(rows):
        raise ValueError("teacher slot archive digest mismatch")
    total = grouped = slots = 0
    for case, row in zip(public_cases, rows):
        expected = _public_ops(case)
        n = len(expected)
        wanted = {
            "case_id": case["case_id"], "source_group": case["source_group"],
            "family": case["family"],
            "operations": [name for name, _ in expected],
            "evidence_indices": [idx for _, idx in expected],
            "slots": _slots(n, max_depth),
        }
        if type(row) is not dict or row != wanted:
            raise ValueError("source fact/operation/terminal slot differs from public evidence")
        total += n
        grouped += max(0, n-max_depth)
        slots += min(n,max_depth)
    if (type(receipt.get("total_teacher_steps")) is not int
            or receipt["total_teacher_steps"] != total
            or receipt.get("supervised_steps") != total
            or receipt.get("truncated_teacher_steps") != 0
            or receipt.get("coalesced_teacher_steps") != grouped
            or receipt.get("supervised_slots") != slots
            or receipt.get("terminal_evidence_supervised_cases") != len(public_cases)):
        raise ValueError("self-reported teacher coverage differs from independently replayed evidence")
    return {
        "schema": "hepta.group.train-attention-independent-slots.v1",
        "authority": "DENY_ALL",
        "entire_public_operation_sequence_recomputed": True,
        "terminal_evidence_preserved": True,
        "independent_physical_tokenizer_attestation": False,
        "cases": len(public_cases), "operations": total,
        "coalesced_operations": grouped,
        "slot_assignment_sha256": digest(rows),
    }
