"""Reconstruct truth and account for all issued predictions and terminal attempts."""

from collections import Counter, defaultdict

from actor import compose
from fixture import expected_answer, gate, metadata


def evaluate(stage, tasks, records):
    if [r["task_id"] for r in records] != [t["task_id"] for t in tasks]:
        raise ValueError("missing, reordered or duplicate terminal task")
    facts = {f["source"]: f for f in stage["facts"]}
    meta = metadata(stage["facts"])
    counts, families = Counter(), defaultdict(Counter)
    truth = []
    for task, record in zip(tasks, records):
        if record["value"] is not None and type(record["value"]) is not int:
            raise ValueError("terminal labels must be integers, not booleans")
        iterator = iter(record["steps"])

        class ReplayReader:
            def read(self, source):
                if source not in meta:
                    return None
                row = next(iterator)
                if (
                    row["source"] != source
                    or type(row["value"]) is not int
                    or not 0 <= row["value"] < 8
                ):
                    raise ValueError(
                        "raw prediction does not follow the actor's own path"
                    )
                if type(row["version"]) is not int or type(row["used"]) is not bool:
                    raise ValueError("invalid version/use record")
                return {"value": row["value"], "version": row["version"]}

        replayed = compose(ReplayReader(), meta, task, stage["tick"])
        if replayed != record or next(iterator, None) is not None:
            raise ValueError(
                "final result or gate does not derive from raw predictions"
            )
        expected = expected_answer(stage["facts"], task, stage["tick"])
        score = Counter(
            tasks=1,
            joint_correct=int(record["value"] == expected),
            answerable=int(expected is not None),
            answered=int(record["value"] is not None),
            answerable_correct=int(
                expected is not None and record["value"] == expected
            ),
            wrong_assertions=int(
                record["value"] is not None and record["value"] != expected
            ),
            invalid_terminal_assertions=int(
                record["value"] is not None and expected is None
            ),
            unknown_abstentions=int(record["abstain_reason"] == "unknown"),
            gate_abstentions=int(record["abstain_reason"] not in (None, "unknown")),
            raw_predictions=0,
            raw_errors=0,
            raw_valid_predictions=0,
            raw_valid_errors=0,
            used_sources=0,
            invalid_used_sources=0,
            revoked_used_sources=0,
        )
        for row in record["steps"]:
            source = row["source"]
            valid = (
                gate(
                    meta,
                    source,
                    row["version"],
                    stage["tick"],
                    task.get("required_versions", {}).get(source),
                )
                is None
            )
            wrong = row["value"] != facts[source]["value"]
            score.update(
                raw_predictions=1,
                raw_errors=int(wrong),
                raw_valid_predictions=int(valid),
                raw_valid_errors=int(valid and wrong),
                used_sources=int(row["used"]),
                invalid_used_sources=int(row["used"] and not valid),
                revoked_used_sources=int(row["used"] and not facts[source]["live"]),
            )
        counts.update(score)
        families[task["family"]].update(score)
        truth.append(
            {
                "task_id": task["task_id"],
                "expected": expected,
                "correct": record["value"] == expected,
            }
        )
    return {
        "counts": dict(counts),
        "families": {k: dict(v) for k, v in families.items()},
        "truth": truth,
    }
