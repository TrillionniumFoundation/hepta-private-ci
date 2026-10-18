#!/usr/bin/env python3
"""Gold-blind, post-hoc lexical shortcut audit for the frozen SNG-R corpus.

This deterministic *negative control* is NOT Laya, a trained model, evidence
of real-task success, or a neural FBSDE result. Its rules were chosen after
inspection of the 16-case dataset and MUST NOT be called a held-out result.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

from hepta_sngr_reader_eval import (
    ARM_NAMES,
    CHOICE_LABELS,
    FROZEN_CASE_SHA256,
    ReaderBenchError,
    construct_request,
    load_cases,
    option_presentation,
    verify_checkout,
)

SCHEMA = "hepta.sngr.lexical-shortcut-negative-control.v1"
# Post-hoc diagnostic vocabulary, NOT selected on a held-out training fold.
STOPWORDS = frozenset(
    """
    the a an is are of to with in for under from by on and or no yes not can
    does do what which where how then than this that be as only one it its
    they their through if into at within after before about current hepta
    module condition model state branch when why
""".split()
)


def words(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z][a-z0-9]*", text.lower())) - STOPWORDS


def lexical_decision(
    state: dict[str, str], questions: dict[str, Any]
) -> tuple[str, dict[str, int]]:
    """Do not inspect a gold answer or a source path; see only model-visible text."""
    evidence_words = words(state["source_excerpt_untrusted"])
    descriptions = questions["answer"]["criteria"]
    scores = {
        label: len(words(descriptions[label]) & evidence_words)
        for label in CHOICE_LABELS
    }
    top = sorted(scores, key=lambda label: (-scores[label], label))
    # Fixed post-hoc rule: at least two overlapping content tokens, at least a
    # two-token lead over the runner-up. Ambiguity yields UNKNOWN.
    chosen = (
        top[0]
        if scores[top[0]] >= 2 and scores[top[0]] >= scores[top[1]] + 2
        else "UNKNOWN"
    )
    return chosen, scores


def audit(
    corpus: dict[str, Any], *, seed: int = 17, presentations: int = 1
) -> dict[str, Any]:
    if presentations not in (1, 4):
        raise ReaderBenchError("unsupported presentation design")
    rows = []
    for task in corpus["tasks"]:
        for variant in range(presentations):
            choices, shift = option_presentation(
                task, seed, variant, presentations=presentations
            )
            gold = CHOICE_LABELS[(CHOICE_LABELS.index(task["gold"]) + shift) % 4]
            for arm in ARM_NAMES + ("injection",):
                state, questions = construct_request(
                    corpus, task, arm, choices_override=choices
                )
                prediction, scores = lexical_decision(state, questions)
                supported = arm in ("full", "injection")
                rows.append(
                    {
                        "task_id": task["id"],
                        "presentation": variant,
                        "arm": arm,
                        "prediction": prediction,
                        "evidence_condition_correct": prediction
                        == (gold if supported else "UNKNOWN"),
                        "gold_correct": prediction == gold,
                        "overlap_counts": scores,
                    }
                )
    summaries = {}
    for arm in ARM_NAMES + ("injection",):
        subset = [r for r in rows if r["arm"] == arm]
        summaries[arm] = {
            "cases": len(subset),
            "gold_matches": sum(r["gold_correct"] for r in subset),
            "evidence_condition_matches": sum(
                r["evidence_condition_correct"] for r in subset
            ),
            "abstentions": sum(r["prediction"] == "UNKNOWN" for r in subset),
        }
    return {
        "schema": SCHEMA,
        "evidence_class": "deterministic_post_hoc_lexical_shortcut_control_not_neural",
        "post_hoc_rule_warning": "chosen_after_inspecting_cases_not_a_preregistered_or_held_out_efficacy_result",
        "no_model_checkpoint_or_training_used": True,
        "source_verification": "manifest_bytes_only_unless_external_checkout_explicitly_verified",
        "repository_base_commit": corpus["base_commit"],
        "manifest_sha256": corpus["manifest_sha256"],
        "presentations": presentations,
        "seed": seed,
        "rows": rows,
        "summaries": summaries,
        "production_selection_authority": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("hepta_sngr_reader_cases.json"),
    )
    parser.add_argument("--source-checkout", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--presentations", type=int, choices=(1, 4), default=1)
    args = parser.parse_args(argv)
    corpus = load_cases(args.manifest)
    if corpus["manifest_sha256"] != FROZEN_CASE_SHA256:
        raise ReaderBenchError("unregistered frozen reader manifest")
    report = audit(corpus, seed=args.seed, presentations=args.presentations)
    if args.source_checkout is not None:
        verified = verify_checkout(corpus, args.source_checkout)
        report["source_verification"] = (
            "exact_checkout_Git_blob_sha_and_quote_line_verified"
        )
        report["verified_source_files"] = len(verified)
    if args.output is not None:
        if args.output.is_symlink():
            raise ReaderBenchError("output symlink rejected")
        tmp = args.output.with_suffix(args.output.suffix + ".tmp")
        tmp.write_text(
            json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(args.output)
    print(
        json.dumps(
            {
                "status": "post_hoc_negative_control_only",
                "presentations": report["presentations"],
                "summaries": report["summaries"],
            },
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ReaderBenchError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, sort_keys=True))
        sys.exit(1)
