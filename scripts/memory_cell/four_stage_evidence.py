"""Four-stage MemoryCell evidence audit: actual historical negatives + prospective guard.

No training, new neural inference, original-question re-scoring, authority issuance,
or production admission. Historical inputs are exact Git blob pinned; this is a
read-only consistency audit of published receipts, NOT a replay of raw tensors.
"""

import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re

SCHEMA = "hepta.memory.four-stage-evidence.v1"
ROOT = Path(__file__).resolve().parents[2]
PINNED = {
    "strong": (
        "scripts/memory_cell/data/observed-strong-rag-disposition-38224780900.json",
        "0c54b19413772d10f0c467a79fbf9e036fb25a12",
    ),
    "readers": (
        "scripts/memory_cell/data/historical-frozen-reader-multimetric-pareto-20261011.json",
        "56a6ef8d60df905f9285fda6b2ef26cb45c2f242",
    ),
    "organized": (
        "scripts/memory_cell/data/matched-structured-rag-negative-20261016.json",
        "d3bf5a458554842b07f7303bfabe0d489213df4a",
    ),
    "learned": (
        "scripts/memory_cell/data/stem-two-run-negative-gate-20261011.json",
        "f86b66bfc580ca1bbea46ed10e70352b70fc1441",
    ),
}
EMPTY_SHA = hashlib.sha256(b"").hexdigest()
SHA = re.compile(r"[0-9a-f]{64}\Z")
ARMS = (
    "base:none",
    "base:retrieved",
    "base:sufficient",
    "base:lesion",
    "reference:none",
    "reference:retrieved",
    "reference:sufficient",
    "reference:lesion",
    "base:organized",
    "base:learned_policy",
    "base:knowledge",
    "base:knowledge_only",
)
TASK_KINDS = frozenset({"new_fact", "updated_fact", "composition", "program"})
COST_FIELDS = (
    "extraction",
    "index",
    "train",
    "source_storage",
    "artifact_storage",
    "query_per_use",
    "maintenance_fixed",
    "maintenance_per_use",
    "revocation",
    "recovery",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def strict_json(data):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            require(key not in out, "duplicate JSON key")
            out[key] = value
        return out

    def constant(value):
        raise ValueError("nonfinite JSON: " + value)

    return json.loads(data, object_pairs_hook=unique, parse_constant=constant)


def pinned_receipt(root, key):
    name, digest = PINNED[key]
    path = root / name
    require(path.is_file() and not path.is_symlink(), "regular pinned receipt required")
    data = path.read_bytes()
    require(len(data) < 2_000_000, "receipt size limit")
    actual = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    require(actual == digest, "pinned Git blob mismatch: " + key)
    return strict_json(data)


def historical(root=ROOT):
    """Re-audit original published summaries, preserving all unknown claims."""
    strong = pinned_receipt(root, "strong")
    readers = pinned_receipt(root, "readers")
    organized = pinned_receipt(root, "organized")
    learned = pinned_receipt(root, "learned")

    require(strong["research_source_run_id"] == 38224780900, "original run drift")
    require(
        strong["generating_commit"] == "6304b451268c73f3d1a605985226b102df841bbf"
        and strong["actual_calibration_calls"] == 40
        and strong["actual_evaluation_calls"] == 72
        and strong["planned_real_model_calls"] == 112
        and strong["all_actual_generations_and_replay_complete"] is True,
        "full original neural-generation census absent",
    )
    require(
        strong["human_certified_citation_semantics"] is False
        and strong["independent_future_source_families"] == 0
        and strong["parametric_memory_training_qualified"] is False
        and strong["production_accepted"] is False,
        "historical qualification boundary drift",
    )
    s = strong["by_arm"]
    require(
        len(s) == 9 and all(x["planned"] == 8 for x in s.values()),
        "nine-arm census drift",
    )
    for name in (
        "empty",
        "hybrid_k4",
        "selected_k",
        "single_hop",
        "entity_time",
        "organized",
    ):
        require(name in s, "strong baseline arm missing: " + name)
    require(
        (
            s["empty"]["correct"],
            s["hybrid_k4"]["correct"],
            s["selected_k"]["correct"],
            s["single_hop"]["correct"],
            s["entity_time"]["correct"],
            s["organized"]["correct"],
        )
        == (0, 3, 5, 4, 8, 8),
        "original model task-success receipts changed",
    )
    require(
        s["entity_time"]["correct_with_complete_declared_citations"] == 4
        and s["organized"]["correct_with_complete_declared_citations"] == 4
        and strong["paired_effects"]["organized_vs_complete_path"]
        == {"wins": 0, "losses": 0, "ties": 8, "difference_eighths": 0}
        and strong["organized_saved_input_tokens_vs_complete_path"]
        == s["entity_time"]["prompt_tokens"] - s["organized"]["prompt_tokens"]
        == 573,
        "source organization cannot gain fabricated successes/citations",
    )
    require(
        readers["schema"] == "hepta.memory-frozen-reader.multimetric-pareto.v1"
        and readers["human_semantic_adjudication"] is False
        and readers["independent_source_families"] == 0
        and readers["production_accepted"] is False,
        "reference Reader independence misrepresented",
    )
    pairs = readers["model_pairs"]
    require(set(pairs) == {"qwen-3b", "smol-1.7b"}, "reference model census changed")
    outcome = {}
    for model, expected in (
        ("qwen-3b", (0, 3, 8, 8, 8, 4)),
        ("smol-1.7b", (0, 1, 2, 3, 3, 2)),
    ):
        rows = {r["arm"]: r for r in pairs[model]["arms"]}
        require(
            len(rows) == 6 and all(r["attempts"] == 8 for r in rows.values()),
            "reference evidence-arm census changed",
        )
        ordered = (
            "empty",
            "hybrid",
            "entity_time",
            "organized",
            "program_support",
            "without_prerequisite",
        )
        require(
            tuple(rows[a]["strict_correct"] for a in ordered) == expected,
            "reference original success tally drift",
        )
        outcome[model] = {
            "strict_success": {a: rows[a]["strict_correct"] for a in ordered},
            "source_only_organized_tokens": rows["organized"]["input_tokens"],
            "citation_chain_organized": rows["organized"]["correct_with_full_chain"],
        }
    require(
        organized["source_artifact"]["zip_sha256"]
        == "861e84719f26f48d1d1156bb39273ce706ae83cde47bafcd7f400c037edd871d"
        and organized["audit"]["observed_rows"] == 48
        and organized["limitations"]["decoder_is_deterministic_symbolic_not_llm"]
        is True
        and organized["limitations"]["all_questions_previously_exposed"] is True,
        "symbolic source-local experiment mislabelled",
    )
    contrast = organized["paired_contrasts"]["organized_vs_hybrid"]
    require(
        contrast["strict_wins"]
        == contrast["strict_losses"]
        == contrast["citation_wins"]
        == contrast["citation_losses"]
        == 0
        and organized["per_arm"]["hybrid"]["strict_success"]
        == organized["per_arm"]["organized"]["strict_success"]
        == 8
        and organized["limitations"]["total_lifecycle_cost"] is None,
        "symbolic same-reader negative or unknown cost changed",
    )
    require(
        learned["schema"] == "hepta.memory-cell.stem-native-two-run-negative-gate.v1"
        and len(learned["runs"]) == 2
        and all(
            r["status"] == "success" and r["logical_policy_attempts"] == 576
            for r in learned["runs"]
        )
        and learned["heldout_development_source_selection_wins_per_arm"] == 0
        and learned["heldout_development_answer_changes_per_arm"] == 0
        and learned["independently_authenticated_prospective_source_families"] == 0
        and learned["parametric_memory_advantage_established"] is False
        and learned["production_accepted"] is False,
        "frozen learned-head negative mutated",
    )
    return {
        "schema": SCHEMA,
        "admission": "DENY_ALL",
        "historical_summary_only": True,
        "new_model_inferences": 0,
        "new_learner_updates": 0,
        "original_receipt_git_blob_ids": {k: sha for k, (_, sha) in PINNED.items()},
        "phase1_reader": {
            "evidence_regimes": [
                "empty",
                "hybrid",
                "program_support",
                "without_prerequisite",
            ],
            "real_original_reader_conditions": outcome,
            "program_support_is_authored_oracle": True,
            "missing_premise_can_still_yield_correct_answer": True,
            "independent_human_sufficiency": None,
            "stronger_reader_is_capacity_control_not_memory_gain": True,
            "reader_sufficiency_qualified": False,
        },
        "phase2_organization": {
            "qwen_fixed_hybrid_k4_correct": s["hybrid_k4"]["correct"],
            "qwen_complete_path_correct": s["entity_time"]["correct"],
            "qwen_organized_correct": s["organized"]["correct"],
            "organized_additional_success_vs_complete_path": 0,
            "organized_additional_complete_citations_vs_complete_path": 0,
            "organized_saved_input_tokens_vs_complete_path": 573,
            "symbolic_same_reader_additional_success_vs_hybrid": 0,
            "same_reader_independent_population_gain": False,
        },
        "phase3_parameters": {
            "tested_learned_read_heads": learned["learned_arms"],
            "heldout_development_task_answer_changes_per_head": 0,
            "novel_source_family_advantage": False,
            "knowledge_weight_compression_qualified": False,
            "source_disjoint_program_success_proven": False,
        },
        "phase4_lifetime": {
            "independent_future_families": 0,
            "independent_semantic_citation_precision": None,
            "cross_host_production_recovery": None,
            "complete_lifecycle_cost": None,
            "production_accepted": False,
        },
        "cannot_conclude": [
            "new prospective Reader competence",
            "independent sufficiency",
            "parameter memory superiority",
            "general executable program success",
            "semantic citation entailment",
            "total cost break-even",
            "production acceptance",
        ],
    }


def _cost(value):
    if value is not None:
        require(
            type(value) in (int, float) and math.isfinite(value) and 0 <= value < 1e15,
            "invalid finite cost",
        )
    return value


def total_cost(components, queries):
    """USD per fixed retention horizon; storage and revocation cannot disappear."""
    require(type(queries) is int and 1 <= queries <= 1_000_000, "invalid query horizon")
    require(
        isinstance(components, dict) and set(components) == set(COST_FIELDS),
        "full cost component schema required",
    )
    for value in components.values():
        _cost(value)
    missing = [key for key in COST_FIELDS if components[key] is None]
    fixed = sum(
        components[k] or 0
        for k in COST_FIELDS
        if k not in ("query_per_use", "maintenance_per_use")
    )
    repeated = sum(components[k] or 0 for k in ("query_per_use", "maintenance_per_use"))
    return {
        "queries": queries,
        "unit": "USD at one fixed retention horizon",
        "known_terms_subtotal": fixed + queries * repeated,
        "missing": missing,
        "complete_total": fixed + queries * repeated if not missing else None,
        "production_cost_qualified": False,
    }


def break_even(baseline, candidate):
    """First N >= 1 with C_candidate <= C_baseline; None for unknown/no crossing."""
    require(set(baseline) == set(candidate) == set(COST_FIELDS), "cost schema mismatch")
    for item in (baseline, candidate):
        total_cost(item, 1)
    if any(value is None for x in (baseline, candidate) for value in x.values()):
        return None
    a = total_cost(baseline, 1)["complete_total"]
    b = total_cost(candidate, 1)["complete_total"]
    if b <= a:
        return 1
    slope_base = baseline["query_per_use"] + baseline["maintenance_per_use"]
    slope_new = candidate["query_per_use"] + candidate["maintenance_per_use"]
    if slope_new >= slope_base:
        return None
    return 1 + math.ceil((b - a) / (slope_base - slope_new))


def _utc(value):
    require(isinstance(value, str), "UTC timestamp required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise ValueError("invalid UTC timestamp") from err
    require(
        parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0,
        "real UTC timestamp required",
    )
    return parsed


def prospective_guard(plan, rows):
    """Check recorded paired attempts; scored flags remain externally UNAUTHENTICATED.

    This cannot establish the authenticity of the generation journal, labels,
    independent reviewers, or program verifier. A positive toy fixture never
    becomes admissible production evidence.
    """
    require(
        plan.get("schema") == "hepta.memory.four-stage-prospective-plan.v1",
        "preregistered plan required",
    )
    cases = plan.get("cases")
    require(isinstance(cases, list) and len(cases) > 0, "nonempty cohort required")
    require(plan.get("arms") == list(ARMS), "exact paired arm roster required")
    require(plan.get("contains_gold_answers") is False, "gold not allowed in plan")
    require(plan.get("answer_space_oracle") is False, "candidate oracle forbidden")
    profile = plan.get("frozen_execution")
    required = {
        "base_reader_sha256",
        "reference_reader_sha256",
        "prompt_template_sha256",
        "tools_sha256",
        "input_budget",
        "output_budget",
    }
    require(
        isinstance(profile, dict) and set(profile) == required,
        "frozen execution manifest required",
    )
    for field in (
        "base_reader_sha256",
        "reference_reader_sha256",
        "prompt_template_sha256",
        "tools_sha256",
    ):
        require(
            isinstance(profile[field], str) and SHA.fullmatch(profile[field]),
            "frozen execution identity missing",
        )
    require(
        profile["base_reader_sha256"] != profile["reference_reader_sha256"],
        "distinct reference reader required",
    )
    for field in ("input_budget", "output_budget"):
        require(
            type(profile[field]) is int and 0 < profile[field] <= 100_000,
            "frozen bounded token ceilings required",
        )
    require(
        isinstance(rows, list) and len(rows) == len(cases) * len(ARMS),
        "all planned real answers retained, including failures",
    )
    task_map = {}
    for c in cases:
        require(isinstance(c, dict), "case structure required")
        require(
            set(
                (
                    "id",
                    "family",
                    "kind",
                    "snapshot_frozen_at",
                    "revealed_at",
                    "candidate_pool_sha256",
                    "policy_snapshot_sha256",
                    "knowledge_snapshot_sha256",
                )
            ).issubset(c),
            "case identity missing",
        )
        require(
            c["id"] not in task_map
            and isinstance(c["family"], str)
            and c["family"]
            and c["kind"] in TASK_KINDS,
            "duplicate case or invalid task family/kind",
        )
        require(
            _utc(c["snapshot_frozen_at"]) < _utc(c["revealed_at"]),
            "learning snapshot must freeze before unseen task",
        )
        require(
            isinstance(c["candidate_pool_sha256"], str)
            and SHA.fullmatch(c["candidate_pool_sha256"]),
            "candidate source pin required",
        )
        for field in ("policy_snapshot_sha256", "knowledge_snapshot_sha256"):
            require(
                isinstance(c[field], str) and SHA.fullmatch(c[field]),
                "frozen parameter snapshot identity required",
            )
        task_map[c["id"]] = c
    require(
        {c["kind"] for c in cases} == TASK_KINDS,
        "all four new/update/composition/program strata required",
    )
    row_map = {}
    for row in rows:
        require(isinstance(row, dict), "row structure required")
        key = (row.get("task_id"), row.get("arm"))
        require(
            key not in row_map and key[0] in task_map and key[1] in ARMS,
            "duplicate/unplanned attempt",
        )
        require(row.get("status") in ("succeeded", "failed"), "known attempt status")
        for field in (
            "reader_sha256",
            "prompt_template_sha256",
            "tools_sha256",
            "candidate_pool_sha256",
            "evidence_sha256",
            "specialization_sha256",
        ):
            require(
                isinstance(row.get(field), str) and SHA.fullmatch(row[field]),
                "unbound inference identity: " + field,
            )
        for field in (
            "prompt_template_sha256",
            "tools_sha256",
            "input_budget",
            "output_budget",
        ):
            require(row[field] == profile[field], "frozen execution config drift")
        tier = (
            "reference_reader_sha256"
            if key[1].startswith("reference:")
            else "base_reader_sha256"
        )
        require(row["reader_sha256"] == profile[tier], "frozen reader identity drift")
        require(
            row["candidate_pool_sha256"] == task_map[key[0]]["candidate_pool_sha256"],
            "candidate pool changed after freeze",
        )
        for field in ("input_budget", "output_budget", "input_tokens", "output_tokens"):
            require(
                type(row.get(field)) is int and 0 <= row[field] <= 100_000,
                "invalid model budget/actual usage",
            )
        require(
            0 < row["input_budget"]
            and 0 < row["output_budget"]
            and row["input_tokens"] <= row["input_budget"]
            and row["output_tokens"] <= row["output_budget"],
            "token budget exceeded",
        )
        require(
            type(row.get("strict_task_success")) is bool
            and type(row.get("complete_citation_chain")) is bool,
            "full-denominator typed task/citation outcome required",
        )
        require(
            not row["complete_citation_chain"] or row["strict_task_success"],
            "citation-qualified correctness requires success",
        )
        require(
            row["status"] != "failed" or not row["strict_task_success"],
            "failed model call cannot be counted as success",
        )
        if task_map[key[0]]["kind"] == "program" and row["strict_task_success"]:
            require(
                row.get("program_exit_code") == 0
                and isinstance(row.get("program_test_sha256"), str)
                and SHA.fullmatch(row["program_test_sha256"]),
                "actual program verifier required",
            )
        row_map[key] = row
    require(len(row_map) == len(rows), "incomplete paired result matrix")
    paired = {}
    by_arm = {
        a: {"planned": len(cases), "correct": 0, "cited": 0, "failed": 0} for a in ARMS
    }
    for c in cases:
        cid = c["id"]
        group = {a: row_map[(cid, a)] for a in ARMS}
        original = group["base:retrieved"]
        for arm, row in group.items():
            require(
                row["prompt_template_sha256"] == original["prompt_template_sha256"]
                and row["tools_sha256"] == original["tools_sha256"]
                and (row["input_budget"], row["output_budget"])
                == (original["input_budget"], original["output_budget"]),
                "prompt, tools or budget mismatch",
            )
            require(
                row["reader_sha256"]
                == (
                    group["reference:none"]["reader_sha256"]
                    if arm.startswith("reference:")
                    else original["reader_sha256"]
                ),
                "reader identity drift",
            )
            b = by_arm[arm]
            b["correct"] += row["strict_task_success"]
            b["cited"] += row["complete_citation_chain"]
            b["failed"] += row["status"] == "failed"
        require(
            group["base:none"]["evidence_sha256"] == EMPTY_SHA
            and group["reference:none"]["evidence_sha256"] == EMPTY_SHA
            and group["base:knowledge_only"]["evidence_sha256"] == EMPTY_SHA,
            "no-evidence or module-only access to raw context",
        )
        require(
            group["base:organized"]["evidence_sha256"]
            == group["base:knowledge"]["evidence_sha256"],
            "knowledge gain must hold organized evidence constant",
        )
        require(
            group["base:organized"]["evidence_sha256"]
            == group["base:learned_policy"]["evidence_sha256"],
            "read-policy gain must hold organized evidence constant",
        )
        require(
            group["reference:none"]["reader_sha256"] != original["reader_sha256"],
            "reference reader must be independently identified",
        )
        for regime in ("none", "retrieved", "sufficient", "lesion"):
            require(
                group["base:" + regime]["evidence_sha256"]
                == group["reference:" + regime]["evidence_sha256"],
                "reference evidence parity required",
            )
        for arm, row in group.items():
            specialization = (
                c["policy_snapshot_sha256"]
                if arm == "base:learned_policy"
                else c["knowledge_snapshot_sha256"]
                if arm in ("base:knowledge", "base:knowledge_only")
                else EMPTY_SHA
            )
            require(
                row["specialization_sha256"] == specialization,
                "frozen pre-reveal policy/knowledge snapshot mismatch",
            )
    for arm, baseline in (
        ("base:organized", "base:retrieved"),
        ("base:learned_policy", "base:organized"),
        ("base:knowledge", "base:organized"),
        ("base:knowledge_only", "base:organized"),
        ("base:knowledge_only", "base:none"),
    ):
        wins = sum(
            row_map[(c["id"], arm)]["strict_task_success"]
            and not row_map[(c["id"], baseline)]["strict_task_success"]
            for c in cases
        )
        losses = sum(
            row_map[(c["id"], baseline)]["strict_task_success"]
            and not row_map[(c["id"], arm)]["strict_task_success"]
            for c in cases
        )
        paired[arm + "__vs__" + baseline] = {
            "wins": wins,
            "losses": losses,
            "net_on_planned": (wins - losses) / len(cases),
        }
    return {
        "schema": "hepta.memory.four-stage-prospective-audit.v1",
        "recorded_tasks": len(cases),
        "recorded_families_not_independently_authenticated": len(
            {c["family"] for c in cases}
        ),
        "by_arm": by_arm,
        "paired_descriptive": paired,
        "journal_authenticity_certified": False,
        "human_sufficiency_certified": False,
        "strict_execution_success_independently_certified": False,
        "training_admitted": False,
        "production_accepted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = historical(args.root)
    require(
        not args.output.exists() and not args.output.is_symlink(),
        "immutable new audit destination required",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(report, f, sort_keys=True, indent=2, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    print(
        json.dumps(
            {
                "admission": report["admission"],
                "new_model_inferences": 0,
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
