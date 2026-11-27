"""Project a full pinned historical citation audit into its published summary.

The detailed read-only audit remains the evidence source. The compact summary
is not an independent judgement, a model result, or permission to deploy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from historical_event_citation_chain import SCHEMA, strict_json

MODEL_FIELDS = frozenset(
    {
        "archive_sha256",
        "attempted",
        "generating_commit",
        "scored_answers_sha256",
        "by_arm",
        "cases",
    }
)
FAILURE_FIELDS = (
    "question_id",
    "kind",
    "arm",
    "cited_source_ids",
    "missing_program_declared_support",
    "publicly_declared_event_path_connected",
)


def compact_report(full):
    """Retain only exactly replayable aggregate metrics and missing-chain cases."""
    if not isinstance(full, dict) or full.get("schema") != SCHEMA:
        raise ValueError("wrong full historical citation audit schema")
    if set(full) != {
        "schema",
        "pinned_plan_sha256",
        "generating_commit",
        "real_model_generations",
        "model_semantic_entailment_certified",
        "program_declared_support_is_human_certified",
        "formal_event_path_is_production_semantic_precision",
        "independent_source_families",
        "production_accepted",
        "models",
    }:
        raise ValueError("unrecognized full receipt fields")
    if (
        full["production_accepted"] is not False
        or full["model_semantic_entailment_certified"] is not False
        or full["program_declared_support_is_human_certified"] is not False
        or full["formal_event_path_is_production_semantic_precision"] is not False
        or full["independent_source_families"] != 0
        or not isinstance(full["models"], dict)
        or set(full["models"]) != {"qwen-3b", "smol-1.7b"}
    ):
        raise ValueError("unsupported or promoted historical qualifications")
    result = {k: v for k, v in full.items() if k != "models"}
    result["models"] = {}
    for name, model in full["models"].items():
        if not isinstance(model, dict) or set(model) != MODEL_FIELDS:
            raise ValueError("incomplete pinned reader receipt")
        cases = model["cases"]
        if (
            not isinstance(cases, list)
            or len(cases) != model["attempted"]
            or len(cases) != 48
        ):
            raise ValueError("incomplete real-answer census")
        if model["generating_commit"] != full["generating_commit"]:
            raise ValueError("mixed generating commits")
        if len({(r["question_id"], r["arm"]) for r in cases}) != 48:
            raise ValueError("duplicated real-answer slot")
        by_arm = model["by_arm"]
        for arm, counts in by_arm.items():
            arm_rows = [r for r in cases if r["arm"] == arm]
            if (
                len(arm_rows) != counts["attempted"]
                or sum(r["strict_task_success"] is True for r in arm_rows)
                != counts["strict_task_success"]
                or sum(
                    r["strict_task_success"] is True
                    and r["program_declared_support_cited"] is True
                    for r in arm_rows
                )
                != counts["correct_with_full_program_declared_citations"]
            ):
                raise ValueError(
                    "aggregated citation counts detached from original rows"
                )
        failures = [
            {k: r[k] for k in FAILURE_FIELDS}
            for r in cases
            if r["strict_task_success"] is True
            and r["program_declared_support_cited"] is not True
        ]
        result["models"][name] = {k: model[k] for k in MODEL_FIELDS if k != "cases"}
        result["models"][name]["failed_complete_program_citation_rows"] = failures
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("full_report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.full_report.is_symlink() or not args.full_report.is_file():
        raise ValueError("regular full report required")
    raw = args.full_report.read_bytes()
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("bounded complete report required")
    summary = compact_report(strict_json(raw))
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(
            summary,
            stream,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        stream.write("\n")
    print(args.output)


if __name__ == "__main__":
    main()
