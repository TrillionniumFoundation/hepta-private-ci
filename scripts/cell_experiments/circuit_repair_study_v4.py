"""Native-turn and A-only retrieval controls for the existing Circuit runner."""

import copy
import re
import time

from . import data, repo_execution
from .online_v4.circuit_contract import Graph


def retrieve(record, memory):
    """Rank public input terms only; ties use immutable training record identities."""
    query = set(re.findall(r"[a-z_][a-z_0-9]*", record["task"]["input"].lower()))
    ranked = []
    for row in memory:
        terms = set(re.findall(r"[a-z_][a-z_0-9]*", row["task"]["input"].lower()))
        # The ratio is represented as an integer score to avoid float ordering.
        score = len(query & terms) * 1_000_000 // max(1, len(query | terms))
        ranked.append((-score, data.digest(row), row))
    negative_score, identity, selected = min(ranked, key=lambda item: item[:2])
    observation = {
        "schema": "hepta.training-reference.v1",
        "instruction": "This is a different previously verified training task. Solve the current task; do not copy its expected values.",
        "task": selected["task"]["input"],
        "answer": selected["final_answer"],
    }
    content = data.canonical(observation).decode()
    if len(content.encode()) > 4096:
        raise ValueError("retrieval exceeds frozen 4096-byte limit; no truncation")
    result = copy.deepcopy(record)
    messages = result["task"].setdefault(
        "messages", [{"role": "user", "content": result["task"]["input"]}]
    )
    messages.append({"role": "tool", "content": content})
    return result, {
        "query_record_digest": data.digest(record),
        "memory_record_digest": identity,
        "message_sha256": data.digest(messages[-1]),
        "augmented_record_digest": data.digest(result),
        "lexical_score_millionths": -negative_score,
    }


def prepare(records, root):
    """Build fixed controls and verify only training references, before model calls."""
    tick, cpu = time.perf_counter(), time.process_time()
    rows = data.load_records(
        root
        / "qualification/cell-experiments-v3-20261116/development-old-open.records.jsonl"
    )
    memory = [row for row in rows if row["split"] == "train"]
    if len(memory) != 6 or any(
        not row["authorization"]["training_allowed"] for row in memory
    ):
        raise ValueError("the six original authorized training records are required")
    if len({data.digest(row) for row in memory}) != len(memory):
        raise ValueError("duplicate training reference")
    repo_execution.load_catalog("open")
    receipts = [data.verify_answer(row, row["final_answer"]) for row in memory]
    if not all(receipt["success"] for receipt in receipts):
        raise ValueError("training references no longer pass their original verifier")
    selected, augmented = [], {}
    for panel, record in records:
        value, receipt = retrieve(record, memory)
        augmented[(panel, record["record_id"])] = value
        selected.append(receipt)
    arms = [
        ("bundled_FF", Graph("bundled_FF", ("F", "F")), {}),
        ("bundled_TF", Graph("bundled_TF", ("T", "F")), {}),
    ]
    for name, path in (
        ("native_FF", ("F", "F")),
        ("native_TT", ("T", "T")),
        ("native_CC", ("C", "C")),
        ("native_TF", ("T", "F")),
        ("native_CF", ("C", "F")),
    ):
        arms.append((name, Graph(name, path), {"message_style": "native_turn_v1"}))
    for edge in ("answer", "feedback"):
        name = "native_TF_no_" + edge
        arms.append(
            (
                name,
                Graph(name, ("T", "F")),
                {"message_style": "native_turn_v1", "drop_edge": edge},
            )
        )
    for cell in ("F", "T"):
        name = "native_" + cell + "F_retrieval"
        arms.append(
            (name, Graph(name, (cell, "F")), {"message_style": "native_turn_v1"})
        )
    return (
        arms,
        augmented,
        {
            "schema": "hepta.circuit-repair-retrieval-study.v1",
            "hypothesis": "Matching the trained assistant/action then tool/feedback roles improves second-call execution; same-reference retrieval may explain apparent multi-Cell gains.",
            "retrieval_rule": "one maximum integer Jaccard input-term overlap; tie by full training record digest",
            "reference_source": "only six pre-existing A training records; no evaluation targets or trajectories",
            "memory_record_digests": [data.digest(row) for row in memory],
            "reference_verifications": receipts,
            "reference_verifier_calls": len(receipts),
            "selections": selected,
            "wall_seconds": time.perf_counter() - tick,
            "parent_cpu_seconds": time.process_time() - cpu,
            "retrieval_policy_selected_before_any_arm_result": True,
            "exposed_diagnostic_panel": True,
            "training_updates": 0,
            "independent_users_added": 0,
            "no_equal_actual_cost_claim": True,
        },
    )
