"""Precommitted interpretation of matched LoCoMo k4/k8 Qwen quality and cost.

The 16 evaluation questions and 2 public source-family proxies cannot certify
independent generalization. Read an *externally* SHA-256-pinned completed scorer
report; never generate, train, retune, peek at private targets or choose k.
A completed scorer is not an autonomous deployment recommendation.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

BASE = "lexical_k4"
LARGER = "lexical_k8"
SCHEMA = "hepta.memorycell.locomo-frozen-reader-pair.v1.diagnostic.v1"
COST_SCHEMA = "hepta.memorycell.locomo-reader-matched-cost.v1"


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def bounded_number(value, *, lower, upper):
    return type(value) in (int, float) and math.isfinite(value) and lower <= value <= upper


def classify(report):
    """A gate for further research, *never* a policy or production switch."""
    require(isinstance(report, dict) and report.get("schema") == SCHEMA,
            "original completed matched frozen Reader score required")
    arms, paired = report["arms"], report["paired"]
    cost = report["actual_paired_prompt_and_generation_cost"]
    require(
        isinstance(arms, dict) and set(arms) == {BASE, LARGER}
        and report.get("production_accepted") is False
        and report.get("known_exposed_public_development_data") is True
        and report.get("same_frozen_reader_no_parameter_training") is True
        and report.get("independently_adjudicated_citation_precision") is None
        and paired["planned"] == 16
        and paired["family_proxies"] == 2
        and paired["independent_family_significance_established"] is False
        and cost.get("schema") == COST_SCHEMA
        and cost.get("original_planned_question_pairs") == 16
        and cost.get("logical_reader_attempts") == 32
        and cost.get("independent_source_family_significance") is False
        and cost.get("reader_task_gain_measured_by_this_module") is False
        and cost.get("missing_pair_costs_not_treated_as_zero") is True
        and cost.get("production_accepted") is False,
        "unregistered, promoted or inconsistent frozen Reader experiment",
    )
    for arm in (BASE, LARGER):
        a = arms[arm]
        require(
            type(a["planned"]) is int and a["planned"] == 16
            and all(type(a[k]) is int and a[k] >= 0
                    for k in ("succeeded", "failed", "diagnostic_scored",
                              "diagnostic_unscored", "emitted_citation_markers",
                              "answers_with_undelivered_marker",
                              "actual_input_tokens", "actual_generated_tokens",
                              "actual_source_bytes"))
            and a["succeeded"] + a["failed"] == 16
            and a["diagnostic_scored"] + a["diagnostic_unscored"]
            == a["succeeded"]
            and a["diagnostic_scored"] <= a["succeeded"]
            and a["independent_citation_entailment_precision"] is None
            and bounded_number(a["observed_inference_seconds"],lower=0,upper=1e9)
            and isinstance(a["all_planned_f1_bounds"], list)
            and len(a["all_planned_f1_bounds"]) == 2
            and all(bounded_number(x, lower=0, upper=1)
                    for x in a["all_planned_f1_bounds"]),
            "incomplete or fabricated arm-level Reader result",
        )
        # Each reported arm-F1 must reconstruct its own original 16-case
        # bounds, even when some Reader outputs fail or lack a reference.
        mean = a["diagnostic_f1"]
        scored = a["diagnostic_scored"]
        require(
            (mean is None if scored == 0
             else bounded_number(mean, lower=0, upper=1)),
            "invalid observed arm diagnostic F1 mean",
        )
        scored_sum = 0.0 if mean is None else scored * mean
        arm_bounds = (
            scored_sum / 16,
            (scored_sum + 16 - scored) / 16,
        )
        require(
            all(math.isclose(observed, computed, rel_tol=1e-8, abs_tol=1e-8)
                for observed, computed in zip(
                    a["all_planned_f1_bounds"], arm_bounds, strict=True
                )),
            "arm diagnostic score bounds differ from 16 planned attempts",
        )
        c = cost["per_arm"][arm]
        require(
            c["succeeded"] == a["succeeded"]
            and c["failed"] == a["failed"],
            "cost and answer success denominators differ",
        )
    q, c = paired, cost
    require(
        all(type(q[k]) is int and q[k] >= 0 for k in (
            "planned", "complete_scored", "wins", "losses", "ties",
            "missing_or_unscored",
        ))
        and q["complete_scored"] + q["missing_or_unscored"] == 16
        and q["wins"] + q["losses"] + q["ties"] == q["complete_scored"]
        and isinstance(q["all_planned_delta_bounds"], list)
        and len(q["all_planned_delta_bounds"]) == 2
        and all(bounded_number(x, lower=-1, upper=1)
                for x in q["all_planned_delta_bounds"])
        and q["all_planned_delta_bounds"][0] <= q["all_planned_delta_bounds"][1]
        and (q["observed_mean_f1_delta"] is None
             if not q["complete_scored"]
             else bounded_number(q["observed_mean_f1_delta"], lower=-1, upper=1))
        and type(c["completed_paired_questions"]) is int
        and 0 <= c["completed_paired_questions"] <= 16
        and q["complete_scored"] <= c["completed_paired_questions"]
        and (c["completed_paired_questions"]
             + c["k4_success_k8_failure"]
             + c["k8_success_k4_failure"]
             + c["both_reader_calls_failed"]) == 16
        and len(c["paired_cost_rows"]) == c["completed_paired_questions"]
        and isinstance(c["per_family_proxy_matched_only"], dict)
        and len(c["per_family_proxy_matched_only"]) == 2,
        "scored-answer versus live-paired-cost census drift",
    )
    require(
        max(0, arms[BASE]["diagnostic_scored"]
              + arms[LARGER]["diagnostic_scored"] - 16)
        <= q["complete_scored"]
        <= min(arms[BASE]["diagnostic_scored"],
               arms[LARGER]["diagnostic_scored"]),
        "paired answer-scored intersection contradicts per-arm original counts",
    )
    # Worst-case bounds MUST follow the originally planned denominator.
    # A forged optimistic lower bound could otherwise falsely "prove" k8.
    known_sum = (
        q["observed_mean_f1_delta"] * q["complete_scored"]
        if q["complete_scored"] else 0.0
    )
    missing = q["missing_or_unscored"]
    expected_interval = (
        (known_sum - missing) / 16,
        (known_sum + missing) / 16,
    )
    require(
        all(math.isclose(measured, actual, rel_tol=1e-8, abs_tol=1e-8)
            for measured, actual in zip(
                q["all_planned_delta_bounds"], expected_interval, strict=True
            )),
        "all-planned paired score bounds differ from original 16 denominator",
    )
    ids = set()
    family_counts = Counter()
    extra_tokens = extra_source_bytes = 0
    for row in c["paired_cost_rows"]:
        key = row["question_id"]
        require(
            isinstance(key, str) and key and key not in ids
            and row["family_proxy_digest"]
                in c["per_family_proxy_matched_only"]
            and row["both_real_model_calls_succeeded"] is True
            and type(row["extra_source_utf8_bytes"]) is int
            and row["extra_source_utf8_bytes"] >= 0
            and type(row["extra_prompt_tokens"]) is int
            and row["extra_prompt_tokens"] >= 0,
            "duplicate, fabricated or negative matched Reader prompt cost",
        )
        ids.add(key)
        family_counts[row["family_proxy_digest"]] += 1
        extra_source_bytes += row["extra_source_utf8_bytes"]
        extra_tokens += row["extra_prompt_tokens"]
    require(
        all(
            c["per_family_proxy_matched_only"][family][
                "complete_paired_question_count"
            ] == count
            for family, count in family_counts.items()
        )
        and sum(v["complete_paired_question_count"]
                for v in c["per_family_proxy_matched_only"].values())
        == c["completed_paired_questions"],
        "source-family matched-cost duplicates or missing rows",
    )
    for name, total in (
        ("mean_extra_prompt_tokens", extra_tokens),
        ("mean_extra_source_utf8_bytes", extra_source_bytes),
    ):
        mean = c["matched_only_cost"][name]
        expected = total / c["completed_paired_questions"] if ids else None
        require(
            (mean is None if expected is None else
             bounded_number(mean, lower=0, upper=1e9)
             and math.isclose(mean, expected, rel_tol=1e-9, abs_tol=1e-9)),
            "falsified marginal Reader input-cost mean",
        )
    if c["completed_paired_questions"] == 16:
        require(
            arms[LARGER]["actual_input_tokens"]
            - arms[BASE]["actual_input_tokens"] == extra_tokens
            and arms[LARGER]["actual_source_bytes"]
            - arms[BASE]["actual_source_bytes"] == extra_source_bytes,
            "complete original Reader prompt/source token accounting mismatch",
        )
    complete = (
        q["complete_scored"] == 16 and c["completed_paired_questions"] == 16
        and all(arms[arm]["failed"] == 0 for arm in (BASE, LARGER))
    )
    if complete:
        # With identical fully scored questions, paired mean MUST equal
        # the difference of the two unpaired means. Otherwise it is a
        # fabricated paired gain, even if both reported totals look plausible.
        require(
            math.isclose(
                q["observed_mean_f1_delta"],
                arms[LARGER]["diagnostic_f1"] - arms[BASE]["diagnostic_f1"],
                rel_tol=1e-8, abs_tol=1e-8,
            ),
            "completed paired Reader F1 disagrees with arm-level F1",
        )
    positive_all_planned = q["all_planned_delta_bounds"][0] > 0
    if not complete:
        status = "incomplete_pairs_no_quality_cost_verdict"
    elif not positive_all_planned:
        status = "no_positive_all_planned_QA_lower_bound"
    elif extra_tokens > 0:
        status = "exploratory_QA_gain_at_higher_reader_input_cost"
    else:
        status = "exploratory_QA_gain_without_extra_prompt_tokens"

    # This is intentionally a descriptive *development* gate. Two family
    # proxies are not statistically independent authenticated source families.
    return dict(
        schema="hepta.memorycell.locomo-reader-quality-cost-no-promotion.v1",
        registered_frozen_arms=[BASE, LARGER],
        matched_original_questions=16,
        family_proxies=2,
        live_reader_pairs=c["completed_paired_questions"],
        both_answer_scored=q["complete_scored"],
        missing_or_unscored_questions=q["missing_or_unscored"],
        paired_answer_f1_wins=q["wins"],
        paired_answer_f1_losses=q["losses"],
        paired_answer_f1_ties=q["ties"],
        all_planned_paired_f1_delta_bounds=q["all_planned_delta_bounds"],
        extra_source_utf8_bytes_matched_only=extra_source_bytes,
        extra_prompt_tokens_matched_only=extra_tokens,
        completed_original_control_comparison=complete,
        development_interpretation=status,
        policy_winner_selected=False,
        model_hyperparameters_modified=False,
        two_public_proxies_are_not_independent_family_significance=True,
        independent_reader_source_entailment_verified=False,
        semantic_citation_precision=None,
        source_only_bytes_not_full_serving_TCO=True,
        no_new_model_inference=True,
        scale_out_permitted=False,
        production_accepted=False,
    )


def strict_json(data):
    def unique(pairs):
        x = {}
        for k, v in pairs:
            require(k not in x, "duplicate cost-report JSON key")
            x[k] = v
        return x

    def nonfinite(value):
        raise ValueError("nonfinite JSON constant: " + value)

    return json.loads(data, object_pairs_hook=unique, parse_constant=nonfinite)


def audit_pinned_report(path, *, expected_sha256):
    require(
        isinstance(path, Path) and path.is_file() and not path.is_symlink()
        and re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is not None
        and 0 < path.stat().st_size <= 4 * 1024 * 1024,
        "external immutable report pin and bounded regular file required",
    )
    raw = path.read_bytes()
    require(
        hashlib.sha256(raw).hexdigest() == expected_sha256,
        "independent completed scorer report SHA-256 mismatch",
    )
    outcome = classify(strict_json(raw))
    outcome["actual_completed_report_sha256"] = expected_sha256
    return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("completed_score_report", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_pinned_report(
        args.completed_score_report, expected_sha256=args.expected_sha256
    )
    require(not args.output.exists() and not args.output.is_symlink(),
            "refuse to overwrite completed research audit")
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
