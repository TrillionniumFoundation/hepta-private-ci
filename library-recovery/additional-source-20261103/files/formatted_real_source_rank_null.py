"""Answer-blind *rank-only* null for the frozen real-Git Reader study.

At inference this baseline reads NO source code, no function declaration and no
human gold. It simply outputs the first retrieved file marker and [E1]. An
independent read-only scorer determines the actual target file using original
SHA-pinned Git source bytes AFTER construction of the rank-only answer.

This is NOT a language-model execution or any MemoryCell learning result.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from real_source_reader_probe import (
    EVALUATION,
    FROZEN_PLAN_SHA256,
    RETIRED_V1_PLAN_SHA256,
    RETIRED_V2_PLAN_SHA256,
    SCHEMA,
    SOURCE_SHA,
    REOPEN_SHA,
    build_plan,
    canonical,
    declarations,
    digest,
    plan_from_archives,
    real_source,
    require,
    write_once,
)

PROFILE = "hepta.memory.real-git-reader-rank-only-null.v1"


def rank_only_audit(plan: dict, sources: tuple) -> dict:
    """Rebuild exact plan/source identity and compute no-code-Reader nulls.

    The source-bearing answer key is reconstructed independently of source
    ranking and of the plan's mechanically supplied one-file 'oracle'.
    """
    files, blobs = sources
    require(
        isinstance(plan, dict) and plan.get("schema") == SCHEMA,
        "frozen v3 plan required",
    )
    require(
        canonical(build_plan(files, blobs)) == canonical(plan),
        "source identity or frozen query/selection changed",
    )
    require(
        plan.get("replaced_v1_plan_sha256") == RETIRED_V1_PLAN_SHA256
        and plan.get("replaced_v2_plan_sha256") == RETIRED_V2_PLAN_SHA256,
        "prior causal lesion versions must remain retired",
    )
    cases = plan["cases"]
    require(
        len(cases) == 9 and len({c["id"] for c in cases}) == 9,
        "exact nine-case source census required",
    )
    results = []
    for case in cases:
        family = case["root"]
        symbol = case["symbol"]
        require(
            family in EVALUATION and isinstance(symbol, str) and symbol,
            "unregistered task family",
        )
        ranked = case["conditions"]["hybrid_k4"]
        lesioned = case["conditions"]["removed_declaration"]
        require(
            2 <= len(ranked) <= 4
            and len(ranked) == len(lesioned)
            and [r["marker"] for r in ranked] == [r["marker"] for r in lesioned]
            and len({r["marker"] for r in ranked}) == len(ranked)
            and all(symbol not in r["text"] for r in lesioned),
            "rank-only negative control not an identical, fully-lesioned file ranking",
        )
        candidate_paths = []
        for entry in files:
            if entry["repo"] != family or entry["partition"] != "evaluation":
                continue
            if not entry["path"].endswith((".py", ".rs")):
                continue
            try:
                source = blobs[(family, entry["path"])].decode("utf-8")
            except UnicodeDecodeError:
                continue
            if symbol in [name for name, _ in declarations(source)]:
                candidate_paths.append(entry["path"])
        require(
            len(candidate_paths) == 1,
            "original immutable Git declarations are missing or ambiguous",
        )
        correct_path = candidate_paths[0]
        matched = [
            i for i, item in enumerate(ranked, 1) if item["path"] == correct_path
        ]
        require(len(matched) == 1, "ranked source lacks exactly one actual target")
        actual = ranked[matched[0] - 1]["marker"]
        guess = ranked[0]["marker"]
        # The rank-only baseline cannot see the source bytes of any record.
        # Its arbitrary-but-valid citation is always the first delivered [E1].
        answer = f"{guess} [E1]"
        correct = guess == actual
        results.append(
            dict(
                case_id=case["id"],
                repository_proxy=family,
                literal_question_symbol_sha256=digest(symbol.encode()),
                source_rank_count=len(ranked),
                actual_target_rank=matched[0],
                raw_rank_only_answer=answer,
                strict_correct=correct,
                marker_citation_is_original_and_complete=correct,
                no_code_read_during_inference=True,
                is_model_generated=False,
            )
        )
    counts = Counter(x["repository_proxy"] for x in results)
    require(
        dict(counts) == {root: 3 for root in EVALUATION},
        "evaluation repository-family proxy census drift",
    )
    by_root = defaultdict(list)
    for result in results:
        by_root[result["repository_proxy"]].append(result)
    success = sum(x["strict_correct"] for x in results)
    return dict(
        schema=PROFILE,
        frozen_plan_bytes_sha256=FROZEN_PLAN_SHA256,
        original_git_archive_zip_sha256=SOURCE_SHA,
        original_independent_reopen_zip_sha256=REOPEN_SHA,
        v1_retired_sha256=RETIRED_V1_PLAN_SHA256,
        v2_retired_sha256=RETIRED_V2_PLAN_SHA256,
        observed_real_model_calls=0,
        authored_cases=len(results),
        repository_name_independence_proxies=len(counts),
        fixed_rank_one_strict_correct=success,
        fixed_rank_one_strict_accuracy=success / len(results),
        fixed_rank_one_full_target_citation=success,
        family_counts={
            k: dict(
                tasks=len(v), rank_one_correct=sum(row["strict_correct"] for row in v)
            )
            for k, v in sorted(by_root.items())
        },
        rank_one_is_question_specific_lexical_search_not_random_selection=True,
        rank_alone_is_a_shortcut_for_this_mechanical_task=True,
        label_access_during_null_prediction=False,
        independent_human_sufficient_evidence_certified=False,
        new_held_out_source_family_qualification=False,
        parameter_memory_gain_established=False,
        semantic_citation_entailment_certified=False,
        amortized_lifecycle_tco=None,
        production_qualified=False,
        cases=results,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-zip", type=Path, required=True)
    p.add_argument("--reopen-zip", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    # Reopen exact immutable source bytes and ensure v3 plan matches externally
    # committed SHA before any answer selection or independent scoring.
    plan = plan_from_archives(args.source_zip, args.reopen_zip)
    audit = rank_only_audit(plan, real_source(args.source_zip, args.reopen_zip))
    write_once(args.output, canonical(audit) + b"\n")
    print(
        json.dumps(
            {
                "rank_one_correct": audit["fixed_rank_one_strict_correct"],
                "cases": audit["authored_cases"],
                "model_calls": 0,
                "production_qualified": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
