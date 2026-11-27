"""Stdlib-only independent replay of TRAIN-only terminal-eligibility receipts.

Recreates both the byte-exact Bool tensor and Python's frozen minibatch/depth
sampler. This checks logical/source consistency, not model execution, future
labels, or independent hardware/optimizer attestation.
"""
from __future__ import annotations

import hashlib
import random


def replay_terminal_guard(protocol, teacher, receipt):
    if (type(protocol) is not dict or protocol.get("terminal_guard") is not True
            or type(teacher) is not dict or type(receipt) is not dict):
        raise ValueError("guarded TRAIN protocol and receipts required")
    cases = protocol["public_cases"]["train"]
    records = teacher["slot_assignments"]
    depth, steps, seed = protocol["max_depth"], protocol["steps"], protocol["seed"]
    if (not isinstance(cases, list) or not cases or len(cases) > 4096
            or not isinstance(records, list) or len(records) != len(cases)
            or type(depth) is not int or not 1 <= depth <= 64
            or type(steps) is not int or not 1 <= steps <= 10000
            or type(seed) is not int or seed < 0):
        raise ValueError("invalid source-scoped TRAIN prefix schedule")
    last_slots = []
    for case, record in zip(cases, records):
        slots = record.get("slots") if type(record) is dict else None
        if (type(case) is not dict or type(slots) is not list
                or not 1 <= len(slots) <= 64
                or record.get("case_id") != case.get("case_id")
                or record.get("source_group") != case.get("source_group")
                or any(type(slot) is not int or not 0 <= slot < depth
                       for slot in slots)
                or slots != sorted(slots)):
            raise ValueError("original source-group and operation-order slot binding required")
        last_slots.append(max(slots))
    tensor_bytes = bytes(int(level >= last)
                         for last in last_slots for level in range(depth))
    tensor_digest = hashlib.sha256(tensor_bytes).hexdigest()
    if (receipt.get("terminal_eligibility_sha256") != tensor_digest
            or receipt.get("terminal_eligibility_bytes") != len(tensor_bytes)):
        raise ValueError("terminal-eligibility tensor bytes mismatch public TRAIN operations")
    batch_size = min(32, len(cases))
    if receipt.get("batch_size") != batch_size:
        raise ValueError("unregistered terminal-guard training batch size")
    rng, sampled = random.Random(seed), hashlib.sha256()
    eligible, suppressed = 0, 0
    for _ in range(steps):
        indices = rng.sample(range(len(cases)), batch_size)
        sampled_depth = rng.randint(1, depth)
        sampled.update(repr((indices, sampled_depth)).encode())
        for case_index in indices:
            for level in range(sampled_depth):
                if level >= last_slots[case_index]:
                    eligible += 1
                else:
                    suppressed += 1
    if (receipt.get("sample_and_depth_sha256") != sampled.hexdigest()
            or receipt.get("terminal_eligible_step_examples") != eligible
            or receipt.get("terminal_suppressed_step_examples") != suppressed
            or receipt.get("completed_steps") != steps):
        raise ValueError("TRAIN terminal-label withholding count or frozen sampler mismatch")
    return dict(status="source_consistent_not_execution_attested", eligible=eligible,
                suppressed=suppressed, eligibility_sha256=tensor_digest,
                sample_and_depth_sha256=sampled.hexdigest())
