"""Reaudit post-answer LoCoMo source-ID coverage versus selected source bytes.

This consumes ONLY a previously sealed, nine-arm aggregate and NEVER runs
retrieval, opens original answer texts, learns a ranker, or picks a new arm.
Actual Reader token budgets, latency, citation entailment and dollars are
not derivable from source UTF-8 bytes. This is a two-family diagnostic.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re


ARMS = tuple(
    f"{name}_k{k}" for name in ("lexical", "recent", "fusion") for k in (2, 4, 8)
)
SOURCE_COMMIT = "fcc24ad653700ad5f47f09350cf7815242dc5de8"
PUBLISHED_REPORT_GIT_BLOB = "6b7592e000bf5e0569b47dc2bcce1ec5b5004717"
ORIGINAL_DECISIONS_SHA256 = (
    "0c80477394abadce7cfd192404ac2531c571e14a9dabdefb371633c1ae3aec89"
)
REPLAY_JOURNAL_SHA256 = (
    "d3c09d944f5bfc855056d109fa0cc379a9a2dc11a3e628556af0448f8be82197"
)
SCHEMA = "hepta.memorycell.locomo-nine-arm-independent-evaluation.v1"


def _require(allowed, why):
    if not allowed:
        raise ValueError(why)


def verified_original_report_bytes(data):
    """Pin the exact original committed report bytes before interpreting scores."""
    _require(
        isinstance(data, bytes) and 0 < len(data) <= 512000,
        "bounded original report bytes required",
    )
    git_blob = hashlib.sha1(
        f"blob {len(data)}".encode("ascii") + bytes((0,)) + data
    ).hexdigest()
    _require(
        git_blob == PUBLISHED_REPORT_GIT_BLOB,
        "historical source-only result Git blob pin drift",
    )
    return hashlib.sha256(data).hexdigest()


def _phase(rows, *, name, eligible, unknown, outside):
    _require(set(rows) == set(ARMS), "not nine registered source-only arms")
    reviewed = {}
    for arm in ARMS:
        row = rows[arm]
        _require(
            row.get("planned") == 16
            and row.get("eligible") == eligible
            and row.get("unknown_or_unanswerable") == unknown
            and row.get("annotated_support_outside_original_pool") == outside
            and type(row.get("full_annotated_support_covered")) is int
            and 0 <= row["full_annotated_support_covered"] <= eligible
            and type(row.get("selected_source_bytes")) is int
            and row["selected_source_bytes"] > 0
            and isinstance(row.get("per_family"), dict)
            and len(row["per_family"]) == 2,
            "mismatched original source-only source/cost census",
        )
        families = row["per_family"]
        _require(
            all(
                re.fullmatch(r"[0-9a-f]{64}", k)
                and type(v.get("covered")) is int
                and type(v.get("eligible")) is int
                and 0 <= v["covered"] <= v["eligible"]
                for k, v in families.items()
            )
            and sum(v["covered"] for v in families.values())
            == row["full_annotated_support_covered"]
            and sum(v["eligible"] for v in families.values()) == eligible,
            "family proxy labels not bound to original coverage totals",
        )
        covered = row["full_annotated_support_covered"]
        lo, hi = row["missing_outcome_lower"], row["missing_outcome_upper"]
        _require(
            type(lo) in (float, int)
            and type(hi) in (float, int)
            and math.isfinite(lo)
            and math.isfinite(hi)
            and math.isclose(lo, covered / 16, abs_tol=1e-12)
            and math.isclose(hi, (covered + unknown) / 16, abs_tol=1e-12),
            "all-planned missing-outcome bounds changed",
        )
        reviewed[arm] = dict(
            originally_planned_questions=16,
            native_support_eligible=eligible,
            native_support_unknown_or_unanswerable=unknown,
            annotated_full_source_support_covered=covered,
            selected_source_bytes=row["selected_source_bytes"],
            all_planned_support_coverage_bounds=[lo, hi],
            native_source_families=2,
        )
    return reviewed


def audit_frontier(report):
    _require(
        isinstance(report, dict)
        and report.get("schema") == SCHEMA
        and report.get("source_commit") == SOURCE_COMMIT
        and report.get("original_published_task_count") == 80
        and report.get("evaluation_questions") == 16
        and report.get("selection_families") == 2
        and report.get("tested_families") == 2
        and report.get("selected_arm") == "lexical_k8"
        and report.get("models_generated") == 0
        and report.get("original_pinned_six_arm_decisions_sha256")
        == ORIGINAL_DECISIONS_SHA256
        and report.get("journal_sha256") == REPLAY_JOURNAL_SHA256
        and report.get("original_six_arm_replay_agrees") is True
        and report.get("independent_source_family_authentication") is False
        and report.get("published_data_pretraining_contamination_unknown") is True
        and report.get("citation_entailment_precision") is None
        and report.get("production_accepted") is False
        and all(
            isinstance(report.get(k), str) and re.fullmatch(r"[0-9a-f]{64}", report[k])
            for k in (
                "frozen_policy_sha256",
                "journal_sha256",
                "original_pinned_six_arm_decisions_sha256",
            )
        ),
        "unqualified or incorrect sealed nine-arm original source report",
    )
    selected = _phase(
        report["selection"],
        name="selection",
        eligible=10,
        unknown=6,
        outside=1,
    )
    evals = _phase(
        report["evaluation"],
        name="evaluation",
        eligible=13,
        unknown=3,
        outside=0,
    )
    # A descriptive post-hoc budget frontier is NOT a new selected arm.
    frontier = []
    dominated_by = {}
    for arm in ARMS:
        x = evals[arm]
        dominators = sorted(
            other
            for other in ARMS
            if other != arm
            and evals[other]["selected_source_bytes"] <= x["selected_source_bytes"]
            and evals[other]["annotated_full_source_support_covered"]
            >= x["annotated_full_source_support_covered"]
            and (
                evals[other]["selected_source_bytes"] < x["selected_source_bytes"]
                or evals[other]["annotated_full_source_support_covered"]
                > x["annotated_full_source_support_covered"]
            )
        )
        dominated_by[arm] = dominators
        if not dominators:
            frontier.append(arm)
    k4, k8 = evals["lexical_k4"], evals["lexical_k8"]
    delta_coverage = (
        k8["annotated_full_source_support_covered"]
        - k4["annotated_full_source_support_covered"]
    )
    delta_bytes = k8["selected_source_bytes"] - k4["selected_source_bytes"]
    _require(
        delta_coverage >= 0
        and delta_bytes > 0
        and selected["lexical_k8"]["annotated_full_source_support_covered"]
        >= selected["lexical_k4"]["annotated_full_source_support_covered"],
        "precommitted BM25 source-size controls inconsistent",
    )
    return dict(
        schema="hepta.memorycell.locomo-posthoc-source-budget-frontier.v1",
        original_report_sha256=hashlib.sha256(
            json.dumps(
                report,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest(),
        selected_policy_from_original_selection_cut=report["selected_arm"],
        selection=selected,
        evaluation=evals,
        posthoc_evaluation_pareto_frontier=frontier,
        dominated_by=dominated_by,
        preexisting_fixed_budget_comparison=dict(
            lower_budget_arm="lexical_k4",
            selection_frozen_arm="lexical_k8",
            net_annotated_support_coverage_difference=delta_coverage,
            extra_delivered_utf8_source_bytes=delta_bytes,
            both_policies_preexisted_in_original_fixed_grid=True,
            posthoc_selection_of_new_policy_prohibited=True,
        ),
        native_support_not_verified_context_sufficiency=True,
        delivered_source_bytes_are_not_reader_input_tokens=True,
        no_new_source_reader_calls=True,
        independent_source_family_effect_not_established=True,
        independent_citation_entailment_precision=None,
        end_to_end_reader_p95_dollars_energy_not_measured=True,
        production_accepted=False,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.source.is_symlink() or not args.source.is_file():
        raise ValueError("original result must be regular pinned local file")
    data = args.source.read_bytes()
    original_byte_sha256 = verified_original_report_bytes(data)

    def unique(pairs):
        o = {}
        for k, v in pairs:
            if k in o:
                raise ValueError("duplicate original JSON key")
            o[k] = v
        return o

    report = json.loads(
        data,
        object_pairs_hook=unique,
        parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)),
    )
    output = audit_frontier(report)
    output["original_source_exact_bytes_sha256"] = original_byte_sha256
    output["original_source_git_blob_sha1"] = PUBLISHED_REPORT_GIT_BLOB
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "schema": output["schema"],
                "frontier": output["posthoc_evaluation_pareto_frontier"],
                "frozen_source_size_control": output[
                    "preexisting_fixed_budget_comparison"
                ],
                "production_accepted": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
