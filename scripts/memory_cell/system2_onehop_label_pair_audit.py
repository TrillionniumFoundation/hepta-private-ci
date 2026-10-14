"""Post-seal, no-model paired label-effect audit for the frozen one-hop Reader.

Never interprets token copying as a grounded answer or a source citation.
Question pairs and their planned denominators are preserved when calls fail.
Repeated arms of one synthetic question are NOT independent test subjects.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from math import comb
from pathlib import Path
import re

from system2_multihop_evidence import digest
from system2_multihop_trial import evidence
from system2_native_receipt import strict_json
from system2_onehop_label_ablation import (
    ALL_ARMS,
    MAX_NEW_TOKENS,
    PARENT_COMMIT,
    PARENT_RAW_SHA256,
    PARENT_SHA256,
    PRESENTATIONS,
    READER_IDENTITY,
    SOURCE_ARMS,
    TOKEN_LIMIT,
    cases,
    load_previous,
    score,
    selected,
)

METRICS = (
    "exact_answer_only",
    "correct_token_mentioned",
    "label_only_echo",
    "prescribed_refusal",
    "unsupported_token_output",
    "success",
)
PAIRS = SOURCE_ARMS[:3]
SCHEMA = "hepta.system2.onehop-label-postseal-paired-audit.v1"


def exact_two_sided_discordance_p(unlabeled_only, labeled_only):
    """Two-sided exact matched sign/McNemar conditional p, no iid-arm fiction."""
    if (
        type(unlabeled_only) is not int
        or type(labeled_only) is not int
        or unlabeled_only < 0
        or labeled_only < 0
    ):
        raise ValueError("nonnegative exact paired counts required")
    n = unlabeled_only + labeled_only
    if n == 0:
        return 1.0
    tail = sum(comb(n, k) for k in range(min(unlabeled_only, labeled_only) + 1))
    return min(1.0, 2 * tail / (2**n))


def compare_pairs(rows, *, registered):
    """No gold used to select an action: only score ALREADY SEALED outcomes."""
    qids = [c.question.identity for c in registered]
    if len(set(qids)) != len(qids) or len(qids) != 20:
        raise ValueError("complete fixed twenty-subject cohort required")
    expected = {(qid, arm, mode) for qid in qids for arm, mode in ALL_ARMS}
    actual = [(r["qid"], r["arm"], r["presentation"]) for r in rows]
    if len(actual) != 140 or len(set(actual)) != 140 or set(actual) != expected:
        raise ValueError("incomplete, repeated, or altered 140-position census")
    index = dict(zip(actual, rows, strict=True))
    if any(r["status"] not in ("succeeded", "failed") for r in rows):
        raise ValueError("unknown attempt status")
    cm = {case.question.identity: case for case in registered}
    detailed = []
    for arm in PAIRS:
        records = []
        for qid in qids:
            left = index[(qid, arm, "labeled")]
            right = index[(qid, arm, "unlabeled")]
            data = dict(
                qid=qid,
                arm=arm,
                labeled_status=left["status"],
                unlabeled_status=right["status"],
            )
            if left["status"] == right["status"] == "succeeded":
                sl, sr = (score_one_from_row(cm[qid], row) for row in (left, right))
                data.update(
                    labeled=sl,
                    unlabeled=sr,
                    labeled_input_tokens=left["reader"]["input_tokens"],
                    unlabeled_input_tokens=right["reader"]["input_tokens"],
                    labeled_generated_tokens=left["reader"]["generated_tokens"],
                    unlabeled_generated_tokens=right["reader"]["generated_tokens"],
                    input_token_gap=left["reader"]["input_tokens"]
                    - right["reader"]["input_tokens"],
                )
            else:
                data["missing_result_unknown"] = True
            records.append(data)
        known = [r for r in records if "labeled" in r]
        unknown = 20 - len(known)
        for metric in METRICS:
            both = sum(
                bool(r["labeled"][metric]) and bool(r["unlabeled"][metric])
                for r in known
            )
            left_only = sum(
                bool(r["labeled"][metric]) and not bool(r["unlabeled"][metric])
                for r in known
            )
            right_only = sum(
                not bool(r["labeled"][metric]) and bool(r["unlabeled"][metric])
                for r in known
            )
            neither = len(known) - both - left_only - right_only
            delta = right_only - left_only
            detailed.append(
                dict(
                    arm=arm,
                    metric=metric,
                    planned_pairs=20,
                    observed_pairs=len(known),
                    unknown_pairs=unknown,
                    both=both,
                    labeled_only=left_only,
                    unlabeled_only=right_only,
                    neither=neither,
                    observed_numerator_delta_unlabeled_minus_labeled=delta,
                    planned_denominator_delta_bounds=[
                        (delta - unknown) / 20,
                        (delta + unknown) / 20,
                    ],
                    exact_p_if_complete=(
                        exact_two_sided_discordance_p(right_only, left_only)
                        if unknown == 0
                        else None
                    ),
                    related_subjects_not_independent_model_calls=True,
                )
            )
    costs = []
    for arm in PAIRS:
        known = [r for r in rows if r["arm"] == arm and r["status"] == "succeeded"]
        # Costs from individual observations; the paired deltas are below.
        indexed = {(r["qid"], r["presentation"]): r for r in known}
        complete = [
            (indexed[(qid, "labeled")], indexed[(qid, "unlabeled")])
            for qid in qids
            if (qid, "labeled") in indexed and (qid, "unlabeled") in indexed
        ]
        gaps = [
            l["reader"]["input_tokens"] - u["reader"]["input_tokens"]
            for l, u in complete
        ]
        costs.append(
            dict(
                arm=arm,
                planned_pairs=20,
                paired_completed=len(complete),
                paired_unknown=20 - len(complete),
                label_minus_no_label_input_token_gap=gaps,
                exact_input_token_parity_pairs=sum(g == 0 for g in gaps),
                all_pairs_equal_compute_claimed=False,
                label_minus_no_label_generated_token_gap=[
                    l["reader"]["generated_tokens"] - u["reader"]["generated_tokens"]
                    for l, u in complete
                ],
            )
        )
    negative = [index[(qid, "no_evidence", "unlabeled")] for qid in qids]
    observed = [r for r in negative if r["status"] == "succeeded"]
    return dict(
        schema=SCHEMA,
        distinct_questions=20,
        planned_model_calls=140,
        source_pairs=len(PAIRS) * 20,
        paired_metrics=detailed,
        token_cost_contrasts=costs,
        zero_evidence_control=dict(
            planned=20,
            completed=len(observed),
            unknown=20 - len(observed),
            prescribed_refusals=sum(
                score_one_from_row(cm[r["qid"]], r)["prescribed_refusal"]
                for r in observed
            ),
        ),
        causal_label_effect_proven=False,
        different_input_token_lengths_may_confound=True,
        independent_natural_language_evidence=False,
        production_accepted=False,
    )


def score_one_from_row(case, row):
    from system2_onehop_label_ablation import outcome

    return outcome(case, row["arm"], row["presentation"], row["answer"])


def audit(source_dir, parent_zip, *, generating_commit):
    """Validate exact source/weights/answers/seal/scoring before any aggregation."""
    if not re.fullmatch("[0-9a-f]{40}", generating_commit or ""):
        raise ValueError("exact generating Git commit needed")
    root = Path(source_dir)
    parent = load_previous(parent_zip)
    plan = strict_json((root / "plan.json").read_bytes())
    cohort = cases()
    if (
        plan.get("schema") != "hepta.system2.onehop-answer-only-label-ablation.v1"
        or plan.get("source_commit") != generating_commit
        or plan.get("parent_commit") != PARENT_COMMIT
        or plan.get("parent_sha256") != PARENT_SHA256
        or plan.get("parent_raw_sha256") != PARENT_RAW_SHA256
        or plan.get("fixed_reader_identity") != READER_IDENTITY
        or plan.get("task_ids") != [c.question.identity for c in cohort]
        or plan.get("source_arms") != list(SOURCE_ARMS)
        or plan.get("conditions") != [list(a) for a in ALL_ARMS]
        or plan.get("planned") != 140
        or plan.get("same_prompt_system_in_two_label_variants") is not True
        or plan.get("no_weight_update") is not True
        or plan.get("production_accepted") is not False
    ):
        raise ValueError("source/condition/Reader plan drift")
    payload = root / "raw-answers.jsonl"
    if (
        payload.is_symlink()
        or not payload.is_file()
        or payload.stat().st_size > 16 * 1024 * 1024
    ):
        raise ValueError("raw answer file unavailable, linked or unbounded")
    raw = payload.read_bytes()
    seal = strict_json((root / "raw-seal.json").read_bytes())
    raw_sha = hashlib.sha256(raw).hexdigest()
    if seal != dict(sha256=raw_sha, rows=140, scoring_started=False):
        raise ValueError("raw answer archive seal mismatched")
    rows = [strict_json(line) for line in raw.splitlines()]
    starts = [
        strict_json(line) for line in (root / "starts.jsonl").read_bytes().splitlines()
    ]
    registered_cells = {
        (c.question.identity, arm, presentation)
        for c in cohort
        for arm, presentation in ALL_ARMS
    }
    start_keys = [
        (row.get("qid"), row.get("arm"), row.get("presentation")) for row in starts
    ]
    if (
        len(starts) != 140
        or len(set(start_keys)) != 140
        or set(start_keys) != registered_cells
        or any(r.get("status") != "started" for r in starts)
    ):
        raise ValueError("missing, extra or replayed original start journal")
    if len(rows) != 140:
        raise ValueError("raw 140 position census failed")
    profiles = {mode: set() for mode in PRESENTATIONS}
    for row in rows:
        if row["status"] != "succeeded":
            continue
        case = next((c for c in cohort if c.question.identity == row["qid"]), None)
        if case is None:
            raise ValueError("unregistered question ID")
        docs = selected(case, row["arm"])
        bundle, _, _ = evidence(case, docs, "answer-only:" + row["arm"])
        rec = row["reader"]
        if (
            row["selected"] != [d.identity for d in docs]
            or rec.get("reader_identity") != READER_IDENTITY
            or rec.get("query_digest") != digest(asdict(case.question))
            or rec.get("bundle_digest") != bundle.seal()
            or rec.get("delivered_evidence") != bundle.delivered()
            or rec.get("answer_postprocessed") is not False
            or rec.get("trainable_parameters") != 0
            or rec.get("token_limit") != TOKEN_LIMIT
            or not 0 < rec.get("input_tokens", 0) <= TOKEN_LIMIT
            or not 0 < rec.get("generated_tokens", 0) <= MAX_NEW_TOKENS
            or not re.fullmatch("[0-9a-f]{64}", rec.get("input_ids_digest", ""))
            or not re.fullmatch("[0-9a-f]{64}", rec.get("generated_ids_digest", ""))
        ):
            raise ValueError("Reader/evidence/source immutable identity mismatch")
        profiles[row["presentation"]].add(rec.get("reader_profile"))
    if (
        any(len(entries) > 1 for entries in profiles.values())
        or any(
            not all(re.fullmatch("[0-9a-f]{64}", value or "") for value in entries)
            for entries in profiles.values()
        )
        or (all(profiles.values()) and profiles["labeled"] == profiles["unlabeled"])
    ):
        raise ValueError("different frozen Reader profiles in the same presentation")
    recorded = strict_json((root / "scored.json").read_bytes())
    scores, groups = score(rows, cohort)
    if recorded != scores:
        raise ValueError("existing independent scoring record drift")
    summary = strict_json((root / "summary.json").read_bytes())
    if (
        summary.get("planned") != 140
        or summary.get("recorded") != 140
        or summary.get("groups") != groups
        or summary.get("raw_sha256") != raw_sha
        or summary.get("source_sha256") != PARENT_SHA256
        or summary.get("failed") != sum(r["status"] == "failed" for r in rows)
        or summary.get("production_accepted") is not False
    ):
        raise ValueError("old scoring summary inconsistency")
    if not isinstance(summary.get("candidate_disposition"), str):
        raise ValueError("missing recorded controller disposition")
    idx = {(x["arm"], x["presentation"]): x for x in groups}
    eligible = (
        summary["failed"] == 0
        and idx["target_decoy_two_first", "unlabeled"]["exact_answer_only"] >= 15
        and idx["decoy_one", "unlabeled"]["correct_refusals"] >= 18
        and idx["no_evidence", "unlabeled"]["correct_refusals"] >= 18
    )
    expected_disposition = (
        "independent_reader_confirmation_required"
        if eligible
        else "reader_answer_only_not_qualified"
    )
    if summary["candidate_disposition"] != expected_disposition:
        raise ValueError("posthoc promotion threshold drift")
    result = compare_pairs(rows, registered=cohort)
    result.update(
        source_commit=generating_commit,
        original_seal=raw_sha,
        verified_parent_files=parent["verified_files"],
        parent_sha256=PARENT_SHA256,
        candidate_disposition=summary["candidate_disposition"],
        contains_unknown_execution_failures=summary["failed"] > 0,
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parent_archive", type=Path)
    parser.add_argument("trial_directory", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    receipt = audit(
        args.trial_directory, args.parent_archive, generating_commit=args.source_commit
    )
    args.output_json.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                "planned": receipt["planned_model_calls"],
                "paired_source_conditions": receipt["source_pairs"],
                "failed_unknown": receipt["contains_unknown_execution_failures"],
                "disposition": receipt["candidate_disposition"],
            },
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
