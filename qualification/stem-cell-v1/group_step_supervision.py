"""Source-bound intermediate-operation teacher for TRAIN-only Group supervision.

This is a symbolic curriculum producer, not an inference-time oracle.
Only public evidence from a training GroupTask may contribute transitions.
No target label, future test sample, or privileged evaluator enters a step.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from group_tasks import GroupTask, supported_answer


@dataclass(frozen=True)
class OperationStep:
    operation: str
    evidence_index: int
    before: str
    after: str


def training_trace(task):
    if not isinstance(task, GroupTask) or task.split != "train":
        raise ValueError("intermediate labels are TRAIN-only")
    if task.family not in ("dependency", "constraint", "temporal"):
        raise ValueError("unregistered training family")
    if not task.source_group or len(task.evidence) > 64:
        raise ValueError("unbound or excessive source evidence")
    steps = []
    if task.family == "dependency":
        node = task.query[1]
        visited = set()
        links = {}
        labels = {}
        for idx, fact in enumerate(task.evidence):
            kind, name, value = fact
            if kind == "link":
                if name in links:
                    raise ValueError("conflicting dependency")
                links[name] = (idx, value)
            elif kind == "label":
                if name in labels:
                    raise ValueError("conflicting label")
                labels[name] = (idx, value)
            else:
                raise ValueError("unknown fact")
        while node in links:
            if node in visited:
                raise ValueError("cyclic dependencies")
            visited.add(node)
            idx, nxt = links[node]
            steps.append(OperationStep("follow_edge", idx, node, nxt))
            node = nxt
        if node not in labels:
            raise ValueError("insufficient terminal evidence")
        idx, label = labels[node]
        steps.append(OperationStep("read_terminal_label", idx, node, label))
        answer = label
    elif task.family == "constraint":
        current = set("ABCDEFGH")
        for idx, fact in enumerate(task.evidence):
            kind, _, values = fact
            if kind != "allow" or not values or not set(values) <= set("ABCDEFGH"):
                raise ValueError("malformed constraint")
            new = current & set(values)
            steps.append(OperationStep("intersect_constraints", idx, "".join(sorted(current)),
                                       "".join(sorted(new))))
            current = new
        if len(current) != 1:
            raise ValueError("insufficient constraint evidence")
        answer = next(iter(current))
    else:
        entity = task.query[1]
        latest = None
        for idx, (name, time, label) in enumerate(task.evidence):
            if name != entity:
                continue
            if type(time) is not int or type(label) is not str or len(label) != 1:
                raise ValueError("invalid event")
            if latest is None or time > latest[0]:
                before = "none" if latest is None else f"{latest[0]}:{latest[1]}"
                steps.append(OperationStep("update_latest_event", idx, before,
                                           f"{time}:{label}"))
                latest = (time, label)
            elif time == latest[0] and label != latest[1]:
                raise ValueError("ambiguous simultaneous events")
        if latest is None:
            raise ValueError("no relevant event")
        answer = latest[1]
    if not 1 <= len(steps) <= 64 or supported_answer(task) != ord(answer) - 65:
        raise ValueError("trace/reference mismatch")
    payload = {"source_group": task.source_group, "family": task.family,
               "task_id": task.task_id,
               "steps": [s.__dict__ for s in steps]}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {"schema": "hepta.group.train-operation-trace.v1",
            "operation_steps": payload["steps"],
            "source_group": task.source_group,
            "trace_sha256": hashlib.sha256(canonical).hexdigest(),
            "train_only": True, "authority": "DENY_ALL"}
