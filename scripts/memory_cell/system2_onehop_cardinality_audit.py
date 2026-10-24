"""Read-only sealed paired audit for the fixed one-hop Reader cardinality trial.

No model calls, no trained parameters, no prompt or evidence changes.
Historic 80-answer model receipts and 140 new attempts remain distinct.
"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re

from native import digest as native_digest
from system2_multihop_trial import ABSTAIN, CITATION_RE, TOKEN_RE, evidence
from system2_native_receipt import strict_json
from system2_onehop_reader import select as legacy_select
from system2_onehop_cardinality import (
    ARMS,
    LABEL_ONLY,
    PARENT_RAW_SHA256,
    PARENT_SHA256,
    POSITIVE,
    READER_IDENTITY,
    READER_PROFILE,
    REPEATED,
    TOTAL_TASKS,
    cases,
    choose_onehop,
    load_parent,
    score_one,
)

METRICS = (
    "target_token_mentioned",
    "correct_single_token",
    "grounded_answer_success",
    "label_only_answer",
    "strict_abstention",
    "unsupported_token_copy",
)
PAIR_CONTRASTS = (
    ("same_two_facts_swap", "target_decoy_two_first", "target_decoy_two_last"),
    (
        "three_facts_target_order",
        "historic_fact_plus_distractors",
        "target_decoys_three_last",
    ),
    ("same_two_count_decoy_type", "target_decoy_two_first", "target_context_two"),
    ("same_three_count_decoy_type", "target_decoys_three_last", "target_context_three"),
    ("unsupported_source_count", "decoy_one", "decoy_two"),
)
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def entries(path):
    """Parse strict JSONL; no silent blank rows, duplicate keys or non-finite data."""
    raw = Path(path).read_bytes()
    if not raw or not raw.endswith(b"\n"):
        raise ValueError("missing or partial raw-answer ledger")
    return [strict_json(part) for part in raw.splitlines()]


def independent_verdict(case, arm, row):
    """Recompute acceptance from original provided sources, not old score fields."""
    docs = (
        choose_onehop(case, arm)
        if arm in ARMS
        else legacy_select(case.question, case.documents, arm)
    )
    if row.get("selected") != [d.identity for d in docs]:
        raise ValueError("source identity/order changed")
    answer = row["answer"]
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("missing successful answer")
    bound = {f"E{i + 1}": d.identity for i, d in enumerate(docs)}
    tokens = TOKEN_RE.findall(answer.upper())
    citations = [c.upper() for c in CITATION_RE.findall(answer)]
    bounded = bool(citations) and all(c in bound for c in citations)
    justified = bounded and case.required_id in {bound[c] for c in citations}
    sufficient = arm in POSITIVE or arm in ("single_fact", "fact_plus_distractors")
    return dict(
        target_token_mentioned=case.answer in answer.upper(),
        correct_single_token=len(tokens) == 1 and tokens[0] == case.answer,
        grounded_answer_success=sufficient
        and len(tokens) == 1
        and tokens[0] == case.answer
        and justified,
        label_only_answer=bool(LABEL_ONLY.fullmatch(answer)),
        strict_abstention=answer.strip().strip('"').casefold() == ABSTAIN.casefold(),
        unsupported_token_copy=not sufficient and bool(tokens),
    )


def verify_registered_pair_design(case):
    """The two pure order contrasts must contain the EXACT same source IDs."""
    pairs = (
        (
            choose_onehop(case, "target_decoy_two_first"),
            choose_onehop(case, "target_decoy_two_last"),
        ),
        (
            legacy_select(case.question, case.documents, "fact_plus_distractors"),
            choose_onehop(case, "target_decoys_three_last"),
        ),
    )
    for original, changed in pairs:
        if sorted(d.identity for d in original) != sorted(d.identity for d in changed):
            raise ValueError("same-source positional contrast changed membership")
    for a, b in (
        ("target_decoy_two_first", "target_context_two"),
        ("target_decoys_three_last", "target_context_three"),
    ):
        left, right = choose_onehop(case, a), choose_onehop(case, b)
        if (
            len(left) != len(right)
            or case.required_id not in {d.identity for d in left}
            or case.required_id not in {d.identity for d in right}
        ):
            raise ValueError("same-cardinality distractor contrast drift")


def interval(rows, metric):
    known = sum(row[metric] for row in rows if row is not None)
    missing = sum(row is None for row in rows)
    return {
        "known": known,
        "lower": known,
        "upper": known + missing,
        "planned": len(rows),
        "unknown": missing,
    }


def compare(name, before, after, by_arm, fixed):
    """Pair by original question ID; never pretend repeated arms are new tasks."""
    left, right = [], []
    for case in fixed:
        qid = case.question.identity
        left.append(by_arm[(qid, before)])
        right.append(by_arm[(qid, after)])
    counters = {}
    for metric in METRICS:
        both = [
            (a[metric], b[metric])
            for a, b in zip(left, right)
            if a is not None and b is not None
        ]
        counters[metric] = dict(
            paired=len(both),
            gain=sum(not a and b for a, b in both),
            loss=sum(a and not b for a, b in both),
            both_positive=sum(a and b for a, b in both),
            both_negative=sum(not a and not b for a, b in both),
            unpaired=len(fixed) - len(both),
        )
    return dict(
        name=name,
        before=before,
        after=after,
        question_pairs=len(fixed),
        metrics=counters,
        independent_question_families_claimed=False,
        causality_not_established=True,
    )


def audit(parent_zip, trial_dir, output, *, source_commit, count=TOTAL_TASKS):
    """Revalidate all sources and scores, then publish paired cost+outcome bounds."""
    if not isinstance(source_commit, str) or not re.fullmatch(
        r"[0-9a-f]{40}", source_commit
    ):
        raise ValueError("exact generating source commit required")
    if type(count) is not int or not 1 <= count <= TOTAL_TASKS:
        raise ValueError("bounded cohort required")
    trial_dir, output = Path(trial_dir), Path(output)
    parent = load_parent(parent_zip)  # full externally pinned ZIP and 80 responses
    fixed = cases()[:count]
    plan = strict_json((trial_dir / "plan.json").read_bytes())
    if (
        plan.get("schema") != "hepta.system2.onehop-cardinality.v1"
        or plan.get("source_commit") != source_commit
        or plan.get("parent_sha256") != PARENT_SHA256
        or plan.get("parent_raw_sha256") != PARENT_RAW_SHA256
        or plan.get("parent_manifest_files") != parent["manifest_entries"]
        or plan.get("reader_identity") != READER_IDENTITY
        or plan.get("reader_profile") != READER_PROFILE
        or plan.get("registered_question_ids") != [c.question.identity for c in fixed]
        or plan.get("old_control_arms") != list(REPEATED)
        or plan.get("new_arms") != list(ARMS)
        or plan.get("expected_new_calls") != count * len(ARMS)
        or plan.get("max_new_tokens") != 64
        or plan.get("input_budget_tokens") != 1024
        or plan.get("production_accepted") is not False
    ):
        raise ValueError("registered original trial changed")

    raw_path = trial_dir / "raw-answers.jsonl"
    raw = raw_path.read_bytes()
    seal = strict_json((trial_dir / "raw-seal.json").read_bytes())
    if seal != dict(
        sha256=hashlib.sha256(raw).hexdigest(),
        rows=count * len(ARMS),
        scoring_started=False,
    ):
        raise ValueError("raw response seal/denominator drift")
    rows = entries(raw_path)
    started = entries(trial_dir / "starts.jsonl")
    score_rows = strict_json((trial_dir / "scored.json").read_bytes())
    saved = strict_json((trial_dir / "summary.json").read_bytes())
    expected = {(c.question.identity, arm) for c in fixed for arm in ARMS}
    actual = [(r["qid"], r["arm"]) for r in rows]
    if (
        len(actual) != len(expected)
        or len(set(actual)) != len(actual)
        or set(actual) != expected
        or len(started) != len(actual)
    ):
        raise ValueError("incomplete or duplicate new Reader census")
    for begin, row in zip(started, rows):
        if (
            begin.get("qid") != row["qid"]
            or begin.get("arm") != row["arm"]
            or begin.get("status") != "started"
            or row.get("status") not in ("succeeded", "failed")
        ):
            raise ValueError("mispaired start/result journal")
    original_scored = {(r["qid"], r["arm"]): r for r in score_rows}
    if len(score_rows) != len(expected) or set(original_scored) != expected:
        raise ValueError("incomplete original scored Reader table")
    if (
        saved.get("source_commit") != source_commit
        or saved.get("production_accepted") is not False
        or saved.get("no_new_model_training") is not True
        or saved.get("independent_human_review") is not False
        or saved.get("census")
        != dict(
            planned=len(expected),
            recorded=len(rows),
            succeeded=sum(r["status"] == "succeeded" for r in rows),
            failed=sum(r["status"] == "failed" for r in rows),
        )
    ):
        raise ValueError("historical scoring/census changed")

    for case in fixed:
        verify_registered_pair_design(case)
    cmap = {c.question.identity: c for c in fixed}
    by_arm = {}
    costs = {}
    for row in rows:
        qid, arm = row["qid"], row["arm"]
        case = cmap[qid]
        scored = original_scored[(qid, arm)]
        if row["status"] == "failed":
            if (
                scored
                != dict(qid=qid, arm=arm, status="failed", grounded_answer_success=None)
                or row.get("incomplete_cost_unknown") is not True
            ):
                raise ValueError("failed call silently scored or assigned free work")
            by_arm[(qid, arm)] = None
            continue
        chosen = choose_onehop(case, arm)
        bundle, _, _ = evidence(case, chosen, arm)
        rec = row["reader"]
        if (
            row["selected"] != [d.identity for d in chosen]
            or row["bundle_digest"] != bundle.seal()
            or rec.get("bundle_digest") != bundle.seal()
            or rec.get("reader_identity") != READER_IDENTITY
            or rec.get("reader_profile") != READER_PROFILE
            or rec.get("query_digest") != native_digest(asdict(case.question))
            or rec.get("delivered_evidence") != bundle.delivered()
            or rec.get("token_limit") != 1024
            or rec.get("answer_postprocessed") is not False
            or rec.get("trainable_parameters") != 0
            or not 1 <= rec.get("input_tokens", 0) <= 1024
            or not 1 <= rec.get("generated_tokens", 0) <= 64
            or not isinstance(rec.get("input_ids_digest"), str)
            or HEX64.fullmatch(rec["input_ids_digest"]) is None
            or not isinstance(rec.get("generated_ids_digest"), str)
            or HEX64.fullmatch(rec["generated_ids_digest"]) is None
            or not isinstance(row.get("elapsed_seconds"), (float, int))
            or row["elapsed_seconds"] < 0
        ):
            raise ValueError("unbound/fabricated Reader model/evidence receipt")
        # Recompute independently from the actual source documents and raw string.
        verdict = independent_verdict(case, arm, row)
        recomputed = score_one(case, arm, row["selected"], row["answer"])
        for key, value in recomputed.items():
            if scored.get(key) != value:
                raise ValueError("original scoring field mutated: " + key)
        for key, value in verdict.items():
            if recomputed.get(key) != value:
                raise ValueError(
                    "independent answer/refusal scoring disagreement: " + key
                )
        if scored.get("status") != "succeeded":
            raise ValueError("success marked failed in original table")
        by_arm[(qid, arm)] = verdict
        costs[(qid, arm)] = dict(
            input_tokens=rec["input_tokens"],
            generated_tokens=rec["generated_tokens"],
            elapsed_seconds=row["elapsed_seconds"],
            bound_input_digest=rec["input_ids_digest"],
            answered_with_original_bytes=(
                rec["delivered_evidence"] == bundle.delivered()
            ),
        )

    # Old model outputs are never regenerated, edited or counted as new calls.
    for case in fixed:
        for arm in REPEATED:
            old = parent["rows"][(case.question.identity, arm)]
            verdict = independent_verdict(
                case, arm, dict(selected=old["selected"], answer=old["answer"])
            )
            # Original old scorer may expose fewer fields; new audit is read-only.
            by_arm[(case.question.identity, "historic_" + arm)] = verdict

    # Fail closed if the original summary changed, including its legacy rows.
    expected_groups = {}
    for arm in ARMS:
        part = [by_arm[(c.question.identity, arm)] for c in fixed]
        valid = [v for v in part if v is not None]
        expected_groups[arm] = dict(
            arm=arm,
            planned=count,
            completed=len(valid),
            sufficient=sum(arm in POSITIVE for _ in valid),
            target_token_mentions=sum(v["target_token_mentioned"] for v in valid),
            correct_single_token=sum(v["correct_single_token"] for v in valid),
            grounded_answers=sum(v["grounded_answer_success"] for v in valid),
            strict_abstentions=sum(v["strict_abstention"] for v in valid),
            label_only_answers=sum(v["label_only_answer"] for v in valid),
            unsupported_token_copy=sum(v["unsupported_token_copy"] for v in valid),
            failures=count - len(valid),
            unknown_failed_work=True,
        )
    for arm in REPEATED:
        old = [parent["rows"][(c.question.identity, arm)] for c in fixed]
        expected_groups["historic_" + arm] = dict(
            arm="historic_" + arm,
            planned=count,
            completed=count,
            target_token_mentions=sum(
                cmap[r["qid"]].answer in r["answer"].upper() for r in old
            ),
            label_only_answers=sum(
                bool(LABEL_ONLY.fullmatch(r["answer"])) for r in old
            ),
            strict_abstentions=sum(
                r["answer"].strip().strip('"').casefold() == ABSTAIN.casefold()
                for r in old
            ),
            reader_calls_replayed=0,
            authenticated_parent=True,
        )
    groups = saved["groups"]
    if (
        len(groups) != len(ARMS) + len(REPEATED)
        or {item["arm"] for item in groups} != set(expected_groups)
        or any(item != expected_groups[item["arm"]] for item in groups)
    ):
        raise ValueError("historical summary fields changed")

    contrasts = [compare(name, a, b, by_arm, fixed) for name, a, b in PAIR_CONTRASTS]
    arms = []
    for arm in ARMS:
        part = [by_arm[(c.question.identity, arm)] for c in fixed]
        observed_cost = [
            costs[(c.question.identity, arm)]
            for c, v in zip(fixed, part)
            if v is not None
        ]
        arms.append(
            dict(
                arm=arm,
                planned=count,
                observed=len(observed_cost),
                outcome_bounds={k: interval(part, k) for k in METRICS},
                input_tokens_observed=sum(r["input_tokens"] for r in observed_cost),
                generated_tokens_observed=sum(
                    r["generated_tokens"] for r in observed_cost
                ),
                elapsed_seconds_observed=sum(
                    r["elapsed_seconds"] for r in observed_cost
                ),
                unknown_failed_cpu_and_tokens=count - len(observed_cost),
            )
        )
    output.mkdir(parents=True, exist_ok=False)
    report = dict(
        schema="hepta.system2.onehop.paired-archive-audit.v1",
        source_commit=source_commit,
        reference_zip_sha256=PARENT_SHA256,
        reference_raw_sha256=PARENT_RAW_SHA256,
        original_reader_call_replay_count=0,
        archived_original_calls=80,
        new_planned=count * len(ARMS),
        new_recorded=len(rows),
        new_failures=sum(r["status"] == "failed" for r in rows),
        sealed_new_raw_sha256=seal["sha256"],
        arms=arms,
        paired_contrasts=contrasts,
        repeated_fixed_synthetic_questions=True,
        correct_token_not_equivalent_to_grounded_answer=True,
        measured_token_cost_not_equal_flops=True,
        unknown_failed_cost_not_zero=True,
        semantic_human_review=False,
        independent_reader_generalization=False,
        production_accepted=False,
    )
    (output / "audit-summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    if hashlib.sha256(raw_path.read_bytes()).hexdigest() != seal["sha256"]:
        raise ValueError("source predictions mutated by analysis")
    return report


def main():
    import argparse
    import os

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("original_parent_zip", type=Path)
    ap.add_argument("sealed_trial_dir", type=Path)
    ap.add_argument("output_dir", type=Path)
    opts = ap.parse_args()
    summary = audit(
        opts.original_parent_zip,
        opts.sealed_trial_dir,
        opts.output_dir,
        source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
    )
    print(
        json.dumps(
            {
                "new_recorded": summary["new_recorded"],
                "new_failures": summary["new_failures"],
                "paired_contrasts": [x["name"] for x in summary["paired_contrasts"]],
            },
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
