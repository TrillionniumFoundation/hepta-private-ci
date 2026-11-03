#!/usr/bin/env python3
"""Actual-original-Git, source-only declaration parser null for v3/v4 Reader.

This null reads exactly the source snippets the frozen Reader is given, never
original source files, target paths, reviewer labels, model weights or oracle
selections during prediction. It is a deliberately narrow *syntax* baseline,
not a general programming, memory, or semantic verifier.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re

from real_source_reader_probe import (
    DECL,
    EVALUATION,
    FROZEN_PLAN_SHA256,
    canonical,
    digest,
    plan_from_archives,
    real_source,
    require,
    write_once,
)
from real_source_rank_null import rank_only_audit
from real_git_order_v4 import ORDER_PLAN_SHA256, build_order_plan

PROFILE = "hepta.memory.real-git-declaration-content-null.v1"
VERSIONED_ARMS = (
    ("v3", "none"),
    ("v3", "hybrid_k4"),
    ("v3", "mechanical_support"),
    ("v3", "removed_declaration"),
    ("v4", "lexical_order"),
    ("v4", "reverse_order"),
)
QUESTION_SYMBOL = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")
SOURCE_MARKER = re.compile(r"F\d{2}\Z")


def read_snippets_only(question: str, delivered: list[dict]) -> dict:
    """Parse literal declarations in received evidence; abstain if ambiguous.

    No target or original archive is accepted as an input. Function names are
    read from the public query, and evidence markers come from supplied snippets.
    """
    matches = QUESTION_SYMBOL.findall(question)
    require(len(matches) == 1 and matches[0], "one public queried symbol required")
    symbol = matches[0]
    require(isinstance(delivered, list) and len(delivered) <= 4,
            "bounded delivered source list required")
    matching = []
    seen_markers = set()
    for index, entry in enumerate(delivered, 1):
        require(isinstance(entry, dict) and isinstance(entry.get("text"), str)
                and isinstance(entry.get("marker"), str)
                and SOURCE_MARKER.fullmatch(entry["marker"])
                and entry["marker"] not in seen_markers,
                "source marker or original text missing/duplicated")
        seen_markers.add(entry["marker"])
        source = entry["text"]
        require(len(source.encode("utf-8")) <= 4096,
                "delivered code window exceeded research budget")
        # Check real definition syntax, not mere function mentions in calls,
        # comments, filenames, lexical search relevance, or source rank.
        if any(match is not None and match.group(1) == symbol
               for line in source.splitlines()
               for match in [DECL.match(line)]):
            matching.append((index, entry["marker"]))
    # If multiple sources claim the same declaration, do NOT choose by rank.
    if len(matching) != 1:
        return dict(answer=None, cited_source_index=None,
                    evidence_match_count=len(matching), abstained=True)
    index, marker = matching[0]
    return dict(answer=f"{marker} [E{index}]", cited_source_index=index,
                evidence_match_count=1, abstained=False)


def audit(v3: dict, original_sources: tuple) -> dict:
    """Only after producing source-only predictions, check original Git truth."""
    files, blobs = original_sources
    from real_source_reader_probe import build_plan
    require(canonical(v3) == canonical(build_plan(files, blobs))
            and digest(canonical(v3) + b"\n") == FROZEN_PLAN_SHA256,
            "original v3 source byte/plan drift")
    v4 = build_order_plan(v3)
    require(digest(canonical(v4) + b"\n") == ORDER_PLAN_SHA256,
            "original v4 plan identity drift")
    rank = rank_only_audit(v3, original_sources)
    nulls = {case["case_id"]: case for case in rank["cases"]}
    require(len(nulls) == len(v3["cases"]) == 9, "original nine-case census")
    v3_by_id = {row["id"]: row for row in v3["cases"]}
    v4_by_id = {row["id"]: row for row in v4["cases"]}
    require(set(v3_by_id) == set(v4_by_id) == set(nulls),
            "source and task identity changed between v3 and v4")
    results = []
    for version, arm in VERSIONED_ARMS:
        for id_ in sorted(nulls):
            case = (v3_by_id if version == "v3" else v4_by_id)[id_]
            entries = case["conditions"][arm]
            prediction = read_snippets_only(case["question"], entries)
            # The expected marker is reconstructed in the original Git verifier;
            # it is NEVER an input to read_snippets_only().
            oracle_rank = nulls[id_]["actual_target_rank"]
            target_marker = v3_by_id[id_]["conditions"]["hybrid_k4"][oracle_rank - 1]["marker"]
            evidence_positions = [i for i, entry in enumerate(entries, 1)
                                  if entry["marker"] == target_marker]
            expected_position = evidence_positions[0] if len(evidence_positions) == 1 else None
            expected_answer = (f"{target_marker} [E{expected_position}]"
                               if expected_position is not None else None)
            correct = prediction["answer"] == expected_answer and expected_answer is not None
            results.append(dict(
                case_id=id_, family=case["root"], version=version, condition=arm,
                strict_correct=correct, exact_delivered_citation=correct,
                declaration_count=prediction["evidence_match_count"],
                abstained=prediction["abstained"],
                original_answer_sha256=(digest(prediction["answer"].encode())
                                        if prediction["answer"] is not None else None),
                rank_only_first_correct=nulls[id_]["strict_correct"]
                if (version, arm) in (("v3", "hybrid_k4"), ("v4", "lexical_order"))
                else None,
            ))
    require(len(results) == 54, "full v3/v4 source-only outcome census required")
    # The reversed no-code rank null is independently rederived from the
    # immutable v4 delivery order and Git-reopened original declaration target.
    reversed_rank_only = sum(
        v4_by_id[id_]["conditions"]["reverse_order"][0]["marker"]
        == v3_by_id[id_]["conditions"]["hybrid_k4"][nulls[id_]["actual_target_rank"] - 1]["marker"]
        for id_ in sorted(nulls)
    )
    require(reversed_rank_only == 1, "reversed rank-only source baseline drift")
    by_arm = {}
    for version, arm in VERSIONED_ARMS:
        observed = [r for r in results if r["version"] == version and r["condition"] == arm]
        roots = defaultdict(list)
        for r in observed:
            roots[r["family"]].append(r)
        require(set(roots) == set(EVALUATION), "original source-family census changed")
        by_arm[f"{version}:{arm}"] = dict(
            tasks=len(observed), correct=sum(r["strict_correct"] for r in observed),
            abstained=sum(r["abstained"] for r in observed),
            exact_citations=sum(r["exact_delivered_citation"] for r in observed),
            by_repository={family:dict(tasks=len(group),
                                       correct=sum(r["strict_correct"] for r in group))
                           for family, group in sorted(roots.items())},
        )
    require(by_arm["v3:none"]["correct"] == 0
            and by_arm["v3:hybrid_k4"]["correct"] == 9
            and by_arm["v3:mechanical_support"]["correct"] == 9
            and by_arm["v3:removed_declaration"]["correct"] == 0
            and by_arm["v4:lexical_order"]["correct"] == 9
            and by_arm["v4:reverse_order"]["correct"] == 9,
            "source-only declaration baseline changed")
    return dict(
        schema=PROFILE, v3_source_plan_sha256=FROZEN_PLAN_SHA256,
        v4_order_plan_sha256=ORDER_PLAN_SHA256,
        original_git_source_sha256=v3["source_zip_sha256"],
        original_independent_reopen_sha256=v3["independent_reopen_zip_sha256"],
        original_repository_family_proxies=len(EVALUATION),
        source_original_questions=9, source_only_predicted_attempts=len(results),
        actual_model_generations=0, model_weights_loaded=False,
        source_order_invariant_on_this_cohort=True,
        syntax_matches_are_not_semantic_entailment=True,
        independent_human_review_performed=False,
        prospective_source_family_benefit_established=False,
        parameter_memory_benefit_established=False,
        learned_head_or_encoder_tested=False,
        complete_lifecycle_tco=None, production_qualified=False,
        rank_only_first_original_correct=rank["fixed_rank_one_strict_correct"],
        rank_only_first_reversed_correct=reversed_rank_only,
        arms=by_arm, cases=results,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-zip", required=True, type=Path)
    parser.add_argument("--reopen-zip", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    v3 = plan_from_archives(args.source_zip, args.reopen_zip)
    report = audit(v3, real_source(args.source_zip, args.reopen_zip))
    write_once(args.output, canonical(report) + b"\n")
    print(json.dumps(dict(tasks=9, actual_model_generations=0,
                          declaration_v3=report["arms"]["v3:hybrid_k4"]["correct"],
                          declaration_v4=report["arms"]["v4:reverse_order"]["correct"],
                          production_qualified=False), sort_keys=True))


if __name__ == "__main__":
    main()
