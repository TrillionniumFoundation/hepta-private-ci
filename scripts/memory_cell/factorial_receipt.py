"""Read-only accounting of actual factorial answers, not semantic certification.

Separate answerable/unanswerable diagnostics from deliberate empty-context
controls. Original raw bytes and complete attempted census must remain intact.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re

ARMS = (
    "native_base",
    "token_base",
    "native_task",
    "token_task",
    "empty_base",
    "empty_task",
)
ABSTAIN = "I do not have enough evidence."


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("nonfinite JSON")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def conditional(rows):
    good = [r for r in rows if r["status"] == "succeeded"]
    scored = [r for r in good if r.get("f1") is not None]
    if any(type(r["f1"]) not in (int, float) or not 0 <= r["f1"] <= 1 for r in scored):
        raise ValueError("invalid diagnostic score")

    def mean(items):
        return sum(r["f1"] for r in items) / len(items) if items else None

    answerable = [r for r in scored if r.get("target_unanswerable") is False]
    null = [r for r in scored if r.get("target_unanswerable") is True]
    return dict(
        attempted=len(rows),
        succeeded=len(good),
        failed=len(rows) - len(good),
        scored=len(scored),
        diagnostic_f1=mean(scored),
        answerable_scored=len(answerable),
        answerable_f1=mean(answerable),
        unanswerable_scored=len(null),
        unanswerable_f1=mean(null),
        exact_protocol_abstentions=sum(r["answer"].strip() == ABSTAIN for r in good),
        emitted_citations=sum(
            len(re.findall(r"\[E[1-9][0-9]*\]", r["answer"])) for r in good
        ),
    )


def audit(root, expected_source):
    root = root.resolve()
    inventory = {}
    for line in (root / "SHA256SUMS").read_text().splitlines():
        hashed, name = line.split(maxsplit=1)
        file = root / name.strip()
        if (
            not re.fullmatch(r"[0-9a-f]{64}", hashed)
            or file.is_symlink()
            or not file.resolve().is_relative_to(root)
            or file.stat().st_size > 64 * 1024 * 1024
        ):
            raise ValueError("unsafe artifact inventory")
        key = file.relative_to(root).as_posix()
        if key in inventory:
            raise ValueError("duplicated artifact path")
        if hashlib.sha256(file.read_bytes()).hexdigest() != hashed:
            raise ValueError("artifact file hash mismatch")
        inventory[key] = hashed
    present = {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p != root / "SHA256SUMS"
    }
    if present != set(inventory):
        raise ValueError("artifact inventory does not cover all files")
    source = (root / "tested-commit.txt").read_text().strip()
    if source != expected_source:
        raise ValueError("different model source")
    experiment = root / "experiment"
    plan = decode((experiment / "preregistered.json").read_bytes())
    if plan["source_commit"] != source or tuple(plan["arms"]) != ARMS:
        raise ValueError("plan source/arms")
    expected = {
        (q, arm)
        for phase in ("squad_test", "locomo", "longmemeval")
        for q in plan["questions"][phase]
        for arm in ARMS
    }
    raw = [
        decode(line)
        for line in (experiment / "raw-answers.jsonl").read_bytes().splitlines()
    ]
    scored = decode((experiment / "scored-answers.json").read_bytes())
    for rows in (raw, scored):
        observed = {(r["question_id"], r["arm"]) for r in rows}
        if len(rows) != len(expected) or observed != expected:
            raise ValueError("missing/duplicate factorial records")
    original = {(r["question_id"], r["arm"]): r for r in raw}
    groups = {}
    for row in scored:
        first = original[(row["question_id"], row["arm"])]
        if any(row.get(k) != v for k, v in first.items()):
            raise ValueError("scoring altered original response or receipt")
        groups.setdefault(row["question_id"], {})[row["arm"]] = row
    result = dict(
        model_source=source,
        verified_manifest_files=len(inventory),
        raw_attempts=len(raw),
        cases=len(groups),
        conditional_metrics={},
        changed_top1={},
        changed_forced_answers={},
        production_accepted=False,
        independent_semantic_review=False,
        diagnostics_reaggregated_not_independently_judged=True,
    )
    comparisons = (
        ("native_base", "token_base"),
        ("native_task", "token_task"),
        ("native_base", "native_task"),
    )
    for phase in ("squad_test", "locomo", "longmemeval"):
        cases = [g for g in groups.values() if g["native_base"]["phase"] == phase]
        result["changed_top1"][phase] = sum(
            g["native_base"]["selected"] != g["token_base"]["selected"] for g in cases
        )
        for left, right in comparisons:
            result["changed_forced_answers"][f"{phase}/{left}->{right}"] = sum(
                g[left].get("answer") != g[right].get("answer") for g in cases
            )
        for arm in ARMS:
            result["conditional_metrics"][f"{phase}/{arm}"] = conditional(
                [g[arm] for g in cases]
            )
    training = decode((experiment / "training.json").read_bytes())
    result["training"] = {
        "token_steps": training["token"]["steps"],
        "token_parameters": training["token"]["parameters"],
        "token_delta": training["token"]["delta_squared_norm"],
        "reader_steps": training["reader"]["steps"],
        "reader_parameters": training["reader"]["trainable_parameters"],
        "reader_tokens": training["reader"]["tokens"],
        "reader_delta": training["reader"]["adapter_delta_squared_norm"],
        "position_labels": training["position_label_counts"],
    }
    if any(
        not math.isfinite(v)
        for k, v in result["training"].items()
        if k.endswith("delta")
    ):
        raise ValueError("invalid update receipt")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("source")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = audit(args.artifact, args.source)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    print(json.dumps(result, indent=2, allow_nan=False))
