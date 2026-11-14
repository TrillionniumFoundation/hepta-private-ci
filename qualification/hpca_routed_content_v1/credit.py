"""Delayed analytic SGD for two private first-token answer-logit heads.

The body and original LM output matrix remain frozen. No independent evaluator
or production owner is supplied by this development mechanism.
"""

from hashlib import sha256
import json
import re
import numpy as np

ARMS = ("routed", "shuffled", "no_eligibility", "scalar")


def digest_array(value):
    a = np.ascontiguousarray(value, dtype="<f8")
    return sha256(str(a.shape).encode() + a.tobytes()).hexdigest()


def feature(hidden):
    hidden = np.asarray(hidden, dtype=np.float64)
    if hidden.ndim != 1 or not np.isfinite(hidden).all() or np.linalg.norm(hidden) == 0:
        raise ValueError("invalid frozen model feature")
    return np.append(hidden / np.linalg.norm(hidden), 1.0) / np.sqrt(2.0)


def expectation(base, delta):
    """Exact full-vocabulary YES-minus-NO probability after the two logit edits."""
    logits = np.array([base[0] + delta, base[1] - delta, base[2]], dtype=np.float64)
    probability = np.exp(logits - logits.max())
    probability /= probability.sum()
    return float(probability[0] - probability[1])


def route_vector(vector, arm):
    vector = np.asarray(vector, dtype=np.float64)
    if arm not in ARMS or vector.shape != (2,) or not np.isin(vector, (-1, 1)).all():
        raise ValueError("unregistered feedback or arm")
    if arm == "shuffled":
        return vector[::-1].copy()
    if arm == "scalar":
        return np.repeat(vector.mean(), 2)
    return vector.copy()


def update(weights, packet, feedback, arm, plan, now):
    """One shared budget slot; no-eligibility computes but discards the trace."""
    if (
        now < packet["available"]
        or feedback["action_id"] != packet["action_id"]
        or now - packet["sequence"] != plan["delay_steps"]
    ):
        raise ValueError("feedback did not match its recorded causal action")
    e = np.asarray(packet["features"], dtype=np.float64)
    if e.shape != weights.shape or not np.isfinite(e).all():
        raise ValueError("invalid eligibility")
    teacher = route_vector(feedback["vector"], arm)
    coefficient = teacher - np.asarray(packet["expectations"])
    trace = np.zeros_like(e) if arm == "no_eligibility" else e
    delta = (
        plan["learning_rate"]
        * plan["decay"] ** plan["delay_steps"]
        * coefficient[:, None]
        * trace
    )
    candidate = weights + delta
    for row in candidate:
        norm = np.linalg.norm(row)
        if norm > plan["head_norm_limit"]:
            row *= plan["head_norm_limit"] / norm
    if not np.isfinite(candidate).all():
        raise ValueError("nonfinite candidate")
    return candidate, {
        "teacher_input": list(feedback["vector"]),
        "teacher_routed": teacher.tolist(),
        "coefficient": coefficient.tolist(),
        "eligibility_sha256": digest_array(e),
        "delta_norm": float(np.linalg.norm(candidate - weights)),
    }


def train(features, base, labels, seed, arm, plan):
    features, base, labels = map(np.asarray, (features, base, labels))
    if (
        features.shape[:2] != (32, 2)
        or base.shape != (32, 2, 3)
        or labels.shape != (32, 2)
    ):
        raise ValueError("incomplete paired training roster")
    rng = np.random.default_rng(seed)
    order = [int(i) for _ in range(plan["epochs"]) for i in rng.permutation(32)]
    weights = np.zeros((2, features.shape[-1]), dtype=np.float64)
    pending, receipts, sequence = {}, [], 0
    for index in range(len(order) + plan["delay_steps"]):
        sequence = index
        if index < len(order):
            pair = order[index]
            packet = {
                "action_id": f"{seed}:{index}:{pair}",
                "sequence": sequence,
                "available": sequence + plan["delay_steps"],
                "features": features[pair].copy(),
                "expectations": [
                    expectation(base[pair, g], weights[g] @ features[pair, g])
                    for g in range(2)
                ],
            }
            pending[packet["available"]] = (
                packet,
                {"action_id": packet["action_id"], "vector": labels[pair].tolist()},
            )
        if sequence in pending:
            packet, feedback = pending.pop(sequence)
            before = digest_array(weights)
            weights, measured = update(weights, packet, feedback, arm, plan, sequence)
            receipts.append(
                {
                    "sequence": sequence,
                    "action_id": packet["action_id"],
                    "action_sequence": packet["sequence"],
                    "before_sha256": before,
                    "after_sha256": digest_array(weights),
                    **measured,
                }
            )
    if pending or len(receipts) != plan["epochs"] * 32:
        raise ValueError("incomplete feedback drain")
    feedback_digest = sha256(
        json.dumps(
            [(r["action_id"], r["teacher_input"]) for r in receipts],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return weights, receipts, feedback_digest


def parse_answer(text):
    match = re.fullmatch(r"\s*(yes|no)[.!]?\s*", text, flags=re.IGNORECASE)
    return match.group(1).lower() if match else None


def score(rows, labels):
    if not rows or len({r["id"] for r in rows}) != len(rows):
        raise ValueError("empty or duplicated scored roster")
    valid = correct = 0
    for row in rows:
        parsed = parse_answer(row["text"]) if row["status"] == "completed" else None
        valid += parsed is not None
        correct += parsed == labels[row["id"]]
    return {
        "n": len(rows),
        "valid": valid,
        "correct": correct,
        "accuracy_including_invalid": correct / len(rows),
    }


def generation_counts(rows):
    if any(row.get("status") not in ("completed", "failed") for row in rows):
        raise ValueError("unknown generation status")
    completed = sum(row["status"] == "completed" for row in rows)
    return {
        "generation_attempts": len(rows),
        "completed_generations": completed,
        "failed_generations": len(rows) - completed,
        "actual_generations": completed,
    }
