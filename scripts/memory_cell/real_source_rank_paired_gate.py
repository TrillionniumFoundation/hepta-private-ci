"""Original-answer-bound Reader-vs-no-code-rank contrast on the frozen Git v3.

Reads only externally SHA-pinned original JSONL journals and the original Git
blobs. Reuses the native independent scorer first; never runs a model or reads
an answer key in the inference path. Small, exposed source groups cannot
support statistical/semantic/production certification.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import re

from real_source_rank_null import rank_only_audit
from real_source_reader_probe import (
    CONDITIONS,
    FROZEN_PLAN_SHA256,
    MARKER,
    TIERS,
    canonical,
    digest,
    plan_from_archives,
    real_source,
    require,
    score_outputs,
    strict_json,
    write_once,
)

SCHEMA = "hepta.memory.real-git-reader-rank-paired-research.v1"
CONTRASTS = ("hybrid_k4", "removed_declaration")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def pinned_original_journal(path: Path, expected_sha256: str) -> list[dict]:
    """Read one original source-tier log only if externally byte-pinned."""
    require(
        isinstance(expected_sha256, str)
        and HEX64.fullmatch(expected_sha256) is not None,
        "external whole original-model journal SHA-256 required",
    )
    require(
        path.is_file()
        and not path.is_symlink()
        and 0 < path.stat().st_size <= 8_000_000,
        "bounded unlinked original-model journal required",
    )
    raw = path.read_bytes()
    require(
        digest(raw) == expected_sha256 and raw.endswith(b"\n"),
        "original model output bytes differ from external journal pin",
    )
    lines = raw.splitlines()
    require(len(lines) == 9 * len(CONDITIONS), "incomplete 36-call journal census")
    result = [strict_json(line) for line in lines]
    require(
        all(isinstance(row, dict) for row in result), "model receipt must be object"
    )
    return result


def _paired(rows: list[dict], left_key: str, right_key: str) -> dict:
    """Paired case/root summaries; no falsely independent bootstrap CI."""
    require(bool(rows), "nonempty paired original Reader cohort required")
    families = defaultdict(list)
    wins = losses = ties = 0
    for row in rows:
        a, b = row[left_key], row[right_key]
        require(type(a) is bool and type(b) is bool, "bounded paired bool results")
        wins += int(a and not b)
        losses += int(b and not a)
        ties += int(a == b)
        families[row["root"]].append(int(a) - int(b))
    effects = {k: sum(v) / len(v) for k, v in sorted(families.items())}
    require(wins + losses + ties == len(rows), "paired case census drift")
    return dict(
        cases=len(rows),
        reader_wins=wins,
        reader_losses=losses,
        ties=ties,
        reader_minus_control=(wins - losses) / len(rows),
        per_repository_root_effect=effects,
        repository_root_macro_effect=sum(effects.values()) / len(effects),
        independent_statistical_interval=None,
        independent_root_groups_certified=False,
    )


def compare_original_reader_to_rank(plan: dict, sources: tuple, journals: dict) -> dict:
    """Score all 72 original rows *before* computing any paired comparison."""
    require(
        plan.get("schema") == "hepta.memory.real-git-reader-function-probe.v3"
        and digest(canonical(plan) + b"\n") == FROZEN_PLAN_SHA256,
        "only exact externally frozen v3 study is comparable",
    )
    require(set(journals) == set(TIERS), "both original Reader tiers required")
    # Full provenance check recomputes Git source, delivered EvidenceBundle,
    # Reader identities, prompts, budgets and every original attempt.
    full_score = score_outputs(plan, sources, journals)
    rank = rank_only_audit(plan, sources)
    require(
        full_score["original_question_count"] == rank["authored_cases"] == 9
        and rank["fixed_rank_one_strict_correct"] == 7
        and full_score[
            "original_mechanical_support_marker_derivable_from_public_source"
        ]
        is True,
        "original 9-case no-code ranking cannot be established",
    )
    by_rank = {x["case_id"]: x for x in rank["cases"]}
    cases = {case["id"]: case for case in plan["cases"]}
    require(len(cases) == len(by_rank) == 9, "incomplete original source roots")
    summaries, rows_for_paired = {}, {}
    for tier in TIERS:
        raw = {(row["case_id"], row["condition"]): row for row in journals[tier]}
        require(len(raw) == 9 * len(CONDITIONS), "duplicate original model receipts")
        rows_for_paired[tier] = {}
        summaries[tier] = {}
        for condition in CONTRASTS:
            rows = []
            for case_id in sorted(cases):
                case = cases[case_id]
                original = raw[(case_id, condition)]
                rank_row = by_rank[case_id]
                retrieved = case["conditions"][condition]
                target_marker = case["conditions"]["mechanical_support"][0]["marker"]
                at = [
                    i
                    for i, evidence in enumerate(retrieved, 1)
                    if evidence["marker"] == target_marker
                ]
                require(
                    len(at) == 1
                    and at[0] == rank_row["actual_target_rank"]
                    and condition in CONTRASTS,
                    "no-code rank/Reader exposure differs from source corpus",
                )
                succeeded = original["status"] == "succeeded"
                answer = original["answer"] if succeeded else None
                matched = MARKER.fullmatch(answer) if isinstance(answer, str) else None
                correct = bool(matched and matched.group(1) == target_marker)
                citations = {
                    int(x) for x in re.findall(r"\[E([1-9][0-9]*)\]", answer or "")
                }
                target_cited = correct and citations == {at[0]}
                rows.append(
                    dict(
                        case_id=case_id,
                        root=case["root"],
                        condition=condition,
                        source_rank=at[0],
                        rank_only_correct=rank_row["strict_correct"],
                        reader_call_succeeded=succeeded,
                        reader_correct=correct,
                        reader_exact_target_citation=target_cited,
                        original_answer_sha256=(
                            digest(answer.encode()) if answer is not None else None
                        ),
                    )
                )
            paired = _paired(rows, "reader_correct", "rank_only_correct")
            paired["reader_strict_correct"] = sum(r["reader_correct"] for r in rows)
            paired["rank_only_strict_correct"] = sum(
                r["rank_only_correct"] for r in rows
            )
            paired["reader_original_target_cited"] = sum(
                r["reader_exact_target_citation"] for r in rows
            )
            paired["verified_model_attempts"] = sum(
                r["reader_call_succeeded"] for r in rows
            )
            paired["incremental_task_success_on_rank_two_cases"] = sum(
                r["reader_correct"] and not r["rank_only_correct"] for r in rows
            )
            require(
                paired["reader_strict_correct"]
                == full_score["reader_conditions"][tier][condition]["strict_correct"]
                and paired["reader_original_target_cited"]
                == full_score["reader_conditions"][tier][condition][
                    "original_correct_and_cited"
                ]
                and paired["verified_model_attempts"]
                == full_score["reader_conditions"][tier][condition][
                    "successful_model_calls"
                ],
                "independent paired result differs from original Git model scorer",
            )
            paired["case_outcomes"] = rows
            summaries[tier][condition] = paired
            rows_for_paired[tier][condition] = rows
        by_id_a = {row["case_id"]: row for row in rows_for_paired[tier]["hybrid_k4"]}
        lesion = rows_for_paired[tier]["removed_declaration"]
        causal_rows = [
            dict(
                root=r["root"],
                hybrid_correct=by_id_a[r["case_id"]]["reader_correct"],
                lesion_correct=r["reader_correct"],
            )
            for r in lesion
        ]
        summaries[tier]["hybrid_vs_full_symbol_lesion"] = _paired(
            causal_rows, "hybrid_correct", "lesion_correct"
        ) | dict(
            symbol_deleted_every_excerpt=True,
            label_rank_order_unchanged=True,
            human_verified_causal_necessity=False,
        )
    return dict(
        schema=SCHEMA,
        v3_plan_sha256=FROZEN_PLAN_SHA256,
        frozen_source_zip_sha256=rank["original_git_archive_zip_sha256"],
        reopened_original_source_zip_sha256=rank[
            "original_independent_reopen_zip_sha256"
        ],
        provenance_verified_by_independent_original_git_byte_reopen=True,
        independent_model_runner_authentication=False,
        planned_original_reader_attempts=(
            len(plan["cases"]) * len(CONDITIONS) * len(TIERS)
        ),
        successful_reader_model_calls_after_validation=full_score[
            "original_real_model_calls"
        ],
        source_name_group_proxies=len(rank["family_counts"]),
        rank_only_strict_correct=rank["fixed_rank_one_strict_correct"],
        comparisons=summaries,
        no_new_model_inference_in_this_comparator=True,
        future_source_cohort_qualified=False,
        human_semantic_evidence_review_performed=False,
        causal_necessity_or_general_code_repair_proven=False,
        parameter_learning_gain_established=False,
        complete_lifecycle_cost=None,
        independent_95_percent_interval=None,
        production_qualified=False,
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-zip", type=Path, required=True)
    p.add_argument("--reopen-zip", type=Path, required=True)
    for tier in TIERS:
        p.add_argument("--" + tier, type=Path, required=True)
        p.add_argument("--" + tier + "-sha256", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    plan = plan_from_archives(args.source_zip, args.reopen_zip)
    sources = real_source(args.source_zip, args.reopen_zip)
    original = {
        tier: pinned_original_journal(
            getattr(args, tier.replace("-", "_")),
            getattr(args, tier.replace("-", "_") + "_sha256"),
        )
        for tier in TIERS
    }
    result = compare_original_reader_to_rank(plan, sources, original)
    result["externally_pinned_original_journals"] = {
        tier: getattr(args, tier.replace("-", "_") + "_sha256") for tier in TIERS
    }
    write_once(args.output, canonical(result) + b"\n")
    print(
        "Original Reader-vs-rank comparison computed, "
        "independent human and production qualifications remain false"
    )


if __name__ == "__main__":
    main()
