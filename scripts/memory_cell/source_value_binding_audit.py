"""Blind-preserving audit of exact source-value recovery from frozen outputs.

This is a historical research diagnostic: source-derived training values are not
independently verified facts, generated identifiers are never repaired, and
recorded completion probabilities cannot stand in for task success.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

_PROBE = "hepta.source-recall.probe-plan.v1"
_REPORT = "hepta.source-recall.diagnostic.v1"
_READY = "hepta.source-knowledge.snapshot.v1"
_IDENTIFIER = re.compile(r"(?:site|mode|person|component)_[0-9a-f]{8}\Z")
_CITATION = re.compile(r"\[E[1-9][0-9]*\]")
_REFUSAL = "I do not have enough evidence."
_MAX_BYTES = 4 * 1024 * 1024


def _strict_pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError("duplicate JSON field")
        value[key] = item
    return value


def _reject_constant(_):
    raise ValueError("nonfinite JSON values are not admitted")


def load(path):
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("symlink inputs are forbidden")
    with path.open("rb") as stream:
        raw = stream.read(_MAX_BYTES + 1)
    if not raw or len(raw) > _MAX_BYTES:
        raise ValueError("bounded nonempty input required")
    return raw


def parse(raw):
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_strict_pairs,
        parse_constant=_reject_constant,
    )


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def audit(ready, plan, original, published):
    """Recompute exact output categories; never generate or score new answers."""
    if ready.get("schema") != _READY or plan.get("schema") != _PROBE:
        raise ValueError("wrong snapshot or question plan schema")
    if published.get("schema") != _REPORT:
        raise ValueError("wrong original output audit schema")
    if (
        plan["writer_source"] != ready["writer_source"]
        or published["writer_source"] != ready["writer_source"]
        or published["generating_commit"] != plan["probe_source"]
        or plan["reader_identity"] != ready["base_identity"]
        or plan["reader_profile"] != ready["reader_profile"]
        or plan["snapshot_sha256"] != published["snapshot_sha256"]
        or plan["question_mode"] != "training"
        or plan["in_sample_training_recall"] is not True
        or plan["training_exposure_verified"] is not True
        or published["training_exposure_verified"] is not True
        or plan["training_schedule_sha256"] != ready["training"]["schedule_sha256"]
        or published["training_schedule_sha256"] != plan["training_schedule_sha256"]
        or ready["task_payload_consumed"] is not False
        or ready["production_accepted"] is not False
    ):
        raise ValueError("source-only generation and exposure identities disagree")
    supervision = ready["training"]["source_supervision"]
    if not isinstance(supervision, list) or not 1 <= len(supervision) <= 2048:
        raise ValueError("missing bounded source-only training census")
    expected_by_q = {}
    known_by_value = defaultdict(set)
    for item in supervision:
        q = item["query"]
        qid = q["identity"]
        target = item["target"]
        if (
            qid in expected_by_q
            or not isinstance(target, str)
            or not target
            or not isinstance(q["scope"], str)
            or not q["scope"]
        ):
            raise ValueError("ambiguous source-only supervision")
        expected_by_q[qid] = (q, target)
        known_by_value[target].add(q["scope"])
    questions = plan["source_questions"]
    if not isinstance(questions, list) or not 1 <= len(questions) <= 2048:
        raise ValueError("missing frozen source-question census")
    expected = {}
    for q in questions:
        qid = q["identity"]
        if qid not in expected_by_q or qid in expected:
            raise ValueError(
                "question missing or duplicated in original source training"
            )
        if q != expected_by_q[qid][0]:
            raise ValueError(
                "frozen question differs from original source-only training"
            )
        expected[qid] = expected_by_q[qid][1]
    schedule = ready["training"]["write_schedule"]
    planned = schedule["visits_per_example"]
    if (
        not isinstance(planned, list)
        or len(planned) != len(supervision)
        or any(type(n) is not int or n < 0 for n in planned)
    ):
        raise ValueError("original optimizer visits missing")
    by_q_visits = {
        row["query"]["identity"]: planned[i] for i, row in enumerate(supervision)
    }
    question_ids = [q["identity"] for q in questions]
    if (
        plan["source_training_question_ids"] != question_ids
        or plan["source_example_optimizer_visits"]
        != [by_q_visits[qid] for qid in question_ids]
        or any(by_q_visits[qid] <= 0 for qid in question_ids)
    ):
        raise ValueError(
            "claimed trained-source exposure differs from actual write schedule"
        )
    if not isinstance(original, list) or len(original) != 2 * len(expected):
        raise ValueError("complete base/adapter answer census required")
    by_key = {}
    for record in original:
        key = (record["question_id"], record["arm"])
        if (
            key in by_key
            or key[0] not in expected
            or key[1] not in ("base", "memory")
            or record["scope"] != expected_by_q[key[0]][0]["scope"]
            or record["source_training_question_id"] != key[0]
            or record["result_is_in_sample_training_recall"] is not True
            or record["source_example_optimizer_visits"] != by_q_visits[key[0]]
            or record["delivered_evidence"] != []
            or record["status"] not in ("succeeded", "failed")
        ):
            raise ValueError("original zero-evidence answer or training binding drift")
        by_key[key] = record
    if set(by_key) != {(qid, arm) for qid in expected for arm in ("base", "memory")}:
        raise ValueError("missing paired original model answer")
    if published["model_calls"] != len(original):
        raise ValueError("original model execution count disagrees")
    by_arm = {}
    for arm in ("base", "memory"):
        counts = Counter()
        cases = []
        for q in questions:
            qid = q["identity"]
            row = by_key[(qid, arm)]
            target = expected[qid]
            if row["status"] == "failed":
                category = "execution_failed"
            else:
                answer = row["answer"]
                if not isinstance(answer, str) or not answer:
                    raise ValueError("successful model returned no original answer")
                if answer == target:
                    category = "exact_source_target"
                elif _CITATION.search(answer):
                    category = "unbacked_citation_in_empty_context"
                elif answer == _REFUSAL:
                    category = "explicit_refusal"
                elif answer in known_by_value:
                    category = (
                        "wrong_value_from_same_scope"
                        if q["scope"] in known_by_value[answer]
                        else "cross_scope_source_value"
                    )
                elif _IDENTIFIER.fullmatch(answer):
                    category = "fabricated_identifier_not_in_any_source_target"
                else:
                    category = "other_unverified_output"
            counts[category] += 1
            cases.append(dict(question_id=qid, category=category))
        if counts["exact_source_target"] != published["arms"][arm]["exact_targets"]:
            raise ValueError("historical task correctness count disagrees")
        if counts["execution_failed"] != published["arms"][arm]["failed"]:
            raise ValueError("historical error count disagrees")
        by_arm[arm] = dict(counts=dict(sorted(counts.items())), cases=cases)
    return dict(
        schema="hepta.source-value-binding.diagnostic.v1",
        generating_source=published["generating_commit"],
        training_source=ready["writer_source"],
        question_mode="in_sample_source_training_questions",
        question_count=len(expected),
        original_model_answers=len(original),
        unique_source_target_values=len(known_by_value),
        source_only_training_targets=len(supervision),
        exact_source_targets_are_not_independent_fact_certification=True,
        target_nll_improvement_is_not_correct_generation=True,
        no_new_model_calls=True,
        source_family_independence_not_established=True,
        semantic_citation_precision=None,
        production_accepted=False,
        arms=by_arm,
    )


def inspect(root, output, *, auditor_commit):
    if not re.fullmatch(r"[0-9a-f]{40}", auditor_commit):
        raise ValueError("exact independent auditor source identity required")
    if output.exists():
        raise ValueError("must not overwrite a prior effect report")
    inputs = {
        "ready": root / "snapshot/READY.json",
        "plan": root / "source-recall/plan.json",
        "original": root / "source-recall/raw-answers.jsonl",
        "published": root / "source-recall/report.json",
    }
    original = {}
    for key, path in inputs.items():
        raw = load(path)
        original[key] = (
            raw,
            [parse(x) for x in raw.splitlines()] if key == "original" else parse(raw),
        )
    ready_raw, ready = original["ready"]
    plan_raw, plan = original["plan"]
    rows_raw, rows = original["original"]
    report_raw, report = original["published"]
    if (
        sha(ready_raw) != plan["snapshot_sha256"]
        or sha(plan_raw) != report["plan_sha256"]
        or sha(rows_raw) != report["raw_sha256"]
    ):
        raise ValueError("original source, plan and raw-answer SHA256 pins disagree")
    result = audit(ready, plan, rows, report)
    result.update(
        auditor_commit=auditor_commit,
        original_source_sha256=sha(ready_raw),
        original_plan_sha256=sha(plan_raw),
        original_answers_sha256=sha(rows_raw),
        original_report_sha256=sha(report_raw),
    )
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return result


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("root", type=Path)
    cli.add_argument("output", type=Path)
    cli.add_argument("--auditor-commit", required=True)
    a = cli.parse_args()
    inspect(a.root, a.output, auditor_commit=a.auditor_commit)
