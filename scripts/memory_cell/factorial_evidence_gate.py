#!/usr/bin/env python3
"""Fail-closed preregistered MemoryCell factorial evidence gate.

This analyzes *observed* externally produced responses, never fabricates inference.
It cannot certify source independence, semantic correctness, or production eligibility.
"""

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

CONDITIONS = ("none", "hybrid", "oracle", "ablated")
READERS = ("frozen", "reference")
ARMS = ("hybrid_rag", "event_graph", "learned_read", "knowledge", "knowledge_only")
TASKS = ("new_fact", "update", "cross_experience", "program")
COST_KEYS = (
    "extraction",
    "indexing",
    "training",
    "query",
    "maintenance",
    "revocation",
    "raw_storage",
)


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(path):
    p = Path(path)
    require(
        p.is_file() and not p.is_symlink() and p.stat().st_size <= 16_000_000,
        "bounded regular file required",
    )
    return json.loads(p.read_text(encoding="utf-8"))


def validate_plan(plan):
    require(plan.get("schema") == "hepta.memory-factorial.plan.v1", "plan schema")
    require(
        plan.get("conditions") == list(CONDITIONS),
        "four reader controls must be frozen",
    )
    require(plan.get("readers") == list(READERS), "reference reader required")
    require(plan.get("arms") == list(ARMS), "five memory arms required")
    require(plan.get("tasks") == list(TASKS), "four task families required")
    require(
        isinstance(plan.get("cutoff"), str) and plan["cutoff"],
        "pre-exposure cutoff required",
    )
    require(
        isinstance(plan.get("reader_budget"), dict) and plan["reader_budget"],
        "reader budget required",
    )
    cases = plan.get("cases")
    require(isinstance(cases, list) and cases, "nonempty frozen cases")
    seen = set()
    for case in cases:
        require(isinstance(case, dict), "case object required")
        for key in (
            "id",
            "root",
            "task",
            "answer_sha256",
            "oracle_source_sha256",
            "premise_sha256",
        ):
            require(
                isinstance(case.get(key), str) and bool(case[key]),
                "missing case binding " + key,
            )
        require(
            case["id"] not in seen and case["task"] in TASKS,
            "duplicate case or unknown task",
        )
        seen.add(case["id"])
        for key in ("answer_sha256", "oracle_source_sha256", "premise_sha256"):
            require(
                len(case[key]) == 64
                and all(c in "0123456789abcdef" for c in case[key]),
                "invalid SHA-256",
            )
    require(
        len({c["root"] for c in cases}) >= 2,
        "at least two stated source families required",
    )
    require(
        {c["task"] for c in cases} == set(TASKS),
        "every preregistered task family needs held-out cases",
    )
    require(
        plan.get("registered_before_exposure") is True,
        "must preregister before task exposure",
    )
    require(
        plan.get("tool_permissions_equal") is True,
        "baseline tool permissions must match",
    )
    return {c["id"]: c for c in cases}


def analyze(plan, rows):
    cases = validate_plan(plan)
    require(isinstance(rows, list), "rows must be a list")
    expected = {
        (cid, arm, condition, reader)
        for cid in cases
        for arm in ARMS
        for condition in CONDITIONS
        for reader in READERS
    }
    seen = set()
    by_key = {}
    for row in rows:
        require(isinstance(row, dict), "invalid observation")
        key = tuple(row.get(k) for k in ("id", "arm", "condition", "reader"))
        require(
            key in expected and key not in seen,
            "unexpected or duplicate experiment observation",
        )
        seen.add(key)
        require(
            row.get("plan_sha256") == sha(plan), "observation does not bind frozen plan"
        )
        require(row.get("root") == cases[row["id"]]["root"], "source-root drift")
        require(
            type(row.get("success")) is bool,
            "explicit independently scored success required",
        )
        require(
            type(row.get("verified")) is bool and row["verified"],
            "unverified adjudication",
        )
        require(
            isinstance(row.get("answer_digest"), str)
            and len(row["answer_digest"]) == 64
            and all(c in "0123456789abcdef" for c in row["answer_digest"]),
            "original answer hash missing",
        )
        require(
            isinstance(row.get("source_digest"), str)
            and len(row["source_digest"]) == 64
            and all(c in "0123456789abcdef" for c in row["source_digest"]),
            "delivered evidence hash missing",
        )
        require(
            isinstance(row.get("reader_revision"), str) and row["reader_revision"],
            "reader revision not recorded",
        )
        require(
            isinstance(row.get("prompt_digest"), str)
            and len(row["prompt_digest"]) == 64
            and all(c in "0123456789abcdef" for c in row["prompt_digest"]),
            "prompt hash missing",
        )
        require(
            type(row.get("tokens")) is int
            and 0 <= row["tokens"] <= plan["reader_budget"].get("total_tokens", -1),
            "incompatible reader token budget",
        )
        costs = row.get("cost")
        require(
            isinstance(costs, dict) and set(costs) == set(COST_KEYS),
            "full lifecycle cost required",
        )
        require(
            all(
                costs[k] is None
                or (type(costs[k]) in (float, int) and 0 <= costs[k] < 1e12)
                for k in COST_KEYS
            ),
            "invalid cost entry",
        )
        require(
            type(row.get("diagnostic_count")) is int and row["diagnostic_count"] >= 0,
            "diagnostic count required",
        )
        require(type(row.get("recovery_success")) is bool, "recovery success required")
        by_key[key] = row
    missing = expected - seen
    require(not missing, f"incomplete matrix: {len(missing)} observations missing")
    # A removed-premise condition cannot diagnose necessity when its delivered
    # evidence is byte-identical to the sufficient-evidence condition. This
    # guards mislabeled, no-op lesions, not the semantic quality of the lesion.
    # The two controls must also be distinguishable from the no-evidence arm.
    for cid in cases:
        for arm in ARMS:
            for reader in READERS:
                evidence = {
                    condition: by_key[(cid, arm, condition, reader)]["source_digest"]
                    for condition in CONDITIONS
                }
                if arm != "knowledge_only":
                    require(
                        evidence["oracle"] != evidence["ablated"]
                        and evidence["oracle"] != evidence["none"],
                        "oracle/ablation/no-evidence payload collision",
                    )
    # Across evidence conditions, lock the actual reader revision and prompt per arm
    # while allowing the evidence payload to change.
    for cid in cases:
        for arm in ARMS:
            for reader in READERS:
                matched = [by_key[(cid, arm, c, reader)] for c in CONDITIONS]
                require(
                    len({x["reader_revision"] for x in matched}) == 1,
                    "reader changed across conditions",
                )
                require(
                    len({x["prompt_digest"] for x in matched}) == 1,
                    "prompt changed across conditions",
                )
    # Whole-arm substitutions otherwise survive within-arm checks and produce
    # spurious parameter or capacity gains. These are consistency checks only,
    # not authentication of raw evidence, tools, review, or preregistration.
    for reader in READERS:
        require(
            len({r["reader_revision"] for r in rows if r["reader"] == reader}) == 1,
            "base reader changed between cases or memory arms",
        )
    require(
        by_key[(next(iter(cases)), "hybrid_rag", "none", "frozen")]["reader_revision"]
        != by_key[(next(iter(cases)), "hybrid_rag", "none", "reference")][
            "reader_revision"
        ],
        "frozen and reference reader must be distinct immutable revisions",
    )
    for cid in cases:
        for condition in CONDITIONS:
            matched = [by_key[(cid, a, condition, r)] for a in ARMS for r in READERS]
            require(
                len({r["prompt_digest"] for r in matched}) == 1,
                "common prompt template changed between memory arms or readers",
            )
            for arm in ARMS:
                require(
                    by_key[(cid, arm, condition, "frozen")]["source_digest"]
                    == by_key[(cid, arm, condition, "reference")]["source_digest"],
                    "reader capacity contrast changed delivered evidence",
                )
            for reader in READERS:
                require(
                    len(
                        {
                            by_key[(cid, arm, condition, reader)]["source_digest"]
                            for arm in ("event_graph", "learned_read", "knowledge")
                        }
                    )
                    == 1,
                    "parameter contrast changed delivered evidence",
                )
    out = {
        "schema": "hepta.memory-factorial.audit.v1",
        "plan_sha256": sha(plan),
        "observations": len(rows),
        "cases": len(cases),
        "source_families_claimed": len({c["root"] for c in cases.values()}),
        "independence_certified": False,
        "semantic_verifier_independent_certified": False,
        "production_qualified": False,
        "parametric_learning_qualified": False,
        "raw_evidence_authenticated": False,
        "tool_parity_authenticated": False,
        "arms": {},
    }
    for arm in ARMS:
        out["arms"][arm] = {}
        for reader in READERS:
            out["arms"][arm][reader] = {}
            for condition in CONDITIONS:
                subset = [by_key[(cid, arm, condition, reader)] for cid in cases]
                roots = defaultdict(list)
                for r in subset:
                    roots[r["root"]].append(r["success"])
                out["arms"][arm][reader][condition] = {
                    "success_rate": sum(r["success"] for r in subset) / len(subset),
                    "root_macro_success": sum(sum(v) / len(v) for v in roots.values())
                    / len(roots),
                    "diagnoses": sum(r["diagnostic_count"] for r in subset),
                    "recovery_rate": sum(r["recovery_success"] for r in subset)
                    / len(subset),
                    "total_cost": {
                        k: None
                        if any(r["cost"][k] is None for r in subset)
                        else sum(r["cost"][k] for r in subset)
                        for k in COST_KEYS
                    },
                    "missing_cost_measurements": {
                        k: sum(r["cost"][k] is None for r in subset) for k in COST_KEYS
                    },
                }
    baseline = out["arms"]["hybrid_rag"]["frozen"]["hybrid"]["success_rate"]
    organized = out["arms"]["event_graph"]["frozen"]["hybrid"]["success_rate"]
    learned = out["arms"]["learned_read"]["frozen"]["hybrid"]["success_rate"]
    knowledge = out["arms"]["knowledge"]["frozen"]["hybrid"]["success_rate"]
    oracle = out["arms"]["hybrid_rag"]["frozen"]["oracle"]["success_rate"]
    stronger = out["arms"]["hybrid_rag"]["reference"]["oracle"]["success_rate"]
    out["diagnosis"] = {
        "frozen_reader_oracle_ceiling": oracle,
        "reference_reader_oracle_ceiling": stronger,
        "nonparametric_delta": organized - baseline,
        "learned_read_delta_vs_organized": learned - organized,
        "knowledge_delta_vs_organized": knowledge - organized,
        "reader_capacity_gap": stronger - oracle,
        "learning_candidate_rejected": learned <= organized and knowledge <= organized,
        "oracle_reader_error_observed": oracle < 1,
        "candidate_rejected": {
            "learned_read": learned <= organized,
            "knowledge": knowledge <= organized,
        },
    }
    # Raw success labels are not an independent semantic or execution audit.
    # These pairwise diagnostics show what the registered observations imply
    # WITHOUT turning a positive contrast into a production admission.
    contrasts = {
        "frozen_oracle_vs_empty": paired_task_outcomes(
            by_key,
            cases,
            ("hybrid_rag", "frozen", "none"),
            ("hybrid_rag", "frozen", "oracle"),
        ),
        "frozen_oracle_vs_hybrid": paired_task_outcomes(
            by_key,
            cases,
            ("hybrid_rag", "frozen", "hybrid"),
            ("hybrid_rag", "frozen", "oracle"),
        ),
        "frozen_oracle_vs_ablation": paired_task_outcomes(
            by_key,
            cases,
            ("hybrid_rag", "frozen", "ablated"),
            ("hybrid_rag", "frozen", "oracle"),
        ),
        "reference_capacity_same_oracle": paired_task_outcomes(
            by_key,
            cases,
            ("hybrid_rag", "frozen", "oracle"),
            ("hybrid_rag", "reference", "oracle"),
        ),
        "organized_vs_hybrid": paired_task_outcomes(
            by_key,
            cases,
            ("hybrid_rag", "frozen", "hybrid"),
            ("event_graph", "frozen", "hybrid"),
        ),
        "learned_policy_vs_organized": paired_task_outcomes(
            by_key,
            cases,
            ("event_graph", "frozen", "hybrid"),
            ("learned_read", "frozen", "hybrid"),
        ),
        "learned_policy_vs_hybrid": paired_task_outcomes(
            by_key,
            cases,
            ("hybrid_rag", "frozen", "hybrid"),
            ("learned_read", "frozen", "hybrid"),
        ),
        "knowledge_vs_organized": paired_task_outcomes(
            by_key,
            cases,
            ("event_graph", "frozen", "hybrid"),
            ("knowledge", "frozen", "hybrid"),
        ),
        "knowledge_vs_hybrid": paired_task_outcomes(
            by_key,
            cases,
            ("hybrid_rag", "frozen", "hybrid"),
            ("knowledge", "frozen", "hybrid"),
        ),
        "knowledge_only_vs_empty": paired_task_outcomes(
            by_key,
            cases,
            ("hybrid_rag", "frozen", "none"),
            ("knowledge_only", "frozen", "none"),
        ),
    }
    out["paired_task_diagnostics"] = contrasts
    out["four_stage_disposition"] = four_stage_disposition(out, contrasts, rows)
    return out


def paired_task_outcomes(by_key, cases, control, candidate):
    """Report true paired outcomes rather than aggregate means alone.

    `root` is only an author-declared grouping. No confidence or external
    source-family independence can be inferred from these counts.
    """

    def blank():
        return dict(planned=0, wins=0, losses=0, both_success=0, both_fail=0)

    total = blank()
    by_kind, by_root = {}, {}
    diagnostics_delta = 0
    recovery_wins = recovery_losses = 0
    control_tokens = candidate_tokens = 0
    matched_evidence = 0
    for case in cases.values():
        cid, root, kind = case["id"], case["root"], case["task"]
        a = by_key[(cid, control[0], control[2], control[1])]
        b = by_key[(cid, candidate[0], candidate[2], candidate[1])]
        if b["source_digest"] == a["source_digest"]:
            matched_evidence += 1
        if b["success"] and not a["success"]:
            category = "wins"
        elif a["success"] and not b["success"]:
            category = "losses"
        elif a["success"]:
            category = "both_success"
        else:
            category = "both_fail"
        for bucket in (
            total,
            by_kind.setdefault(kind, blank()),
            by_root.setdefault(root, blank()),
        ):
            bucket["planned"] += 1
            bucket[category] += 1
        diagnostics_delta += b["diagnostic_count"] - a["diagnostic_count"]
        recovery_wins += b["recovery_success"] and not a["recovery_success"]
        recovery_losses += a["recovery_success"] and not b["recovery_success"]
        control_tokens += a["tokens"]
        candidate_tokens += b["tokens"]

    def effect(bucket):
        return dict(
            **bucket,
            net_task_success_delta=(bucket["wins"] - bucket["losses"])
            / bucket["planned"],
        )

    return dict(
        control=dict(zip(("arm", "reader", "condition"), control)),
        candidate=dict(zip(("arm", "reader", "condition"), candidate)),
        **effect(total),
        by_kind={key: effect(value) for key, value in sorted(by_kind.items())},
        by_root={key: effect(value) for key, value in sorted(by_root.items())},
        evidence_bytes_identity_matched_cases=matched_evidence,
        diagnostic_count_delta=diagnostics_delta,
        recovery_wins=int(recovery_wins),
        recovery_losses=int(recovery_losses),
        original_input_output_token_sum_delta=candidate_tokens - control_tokens,
        statistical_superiority_established=False,
        executable_receipts_independently_authenticated=False,
    )


def four_stage_disposition(report, pairs, rows):
    """Causal experiment order: capability -> organization -> learning -> lifetime."""
    a = report["arms"]["hybrid_rag"]["frozen"]
    oracle = a["oracle"]["success_rate"]
    hybrid = a["hybrid"]["success_rate"]
    reference = report["arms"]["hybrid_rag"]["reference"]["oracle"]["success_rate"]
    ablated = a["ablated"]["success_rate"]
    premise = pairs["frozen_oracle_vs_ablation"]
    if oracle < 1:
        reader_next = "audit_sufficiency_prompt_representation_and_reader_errors"
    elif premise["both_success"]:
        reader_next = "audit_removed_premise_independence_and_shortcut_paths"
    elif hybrid < oracle:
        reader_next = "investigate_retrieval_selection_distractors_and_packing"
    else:
        reader_next = "validate_on_independent_blinded_project_families"
    organized = pairs["organized_vs_hybrid"]
    learning = {}
    for name, prefix in (
        ("learned_read", "learned_policy"),
        ("knowledge", "knowledge"),
    ):
        vs_organized = pairs[prefix + "_vs_organized"]
        vs_hybrid = pairs[prefix + "_vs_hybrid"]
        learning[name] = dict(
            paired_vs_strong_rag=vs_hybrid["net_task_success_delta"],
            paired_vs_organized=vs_organized["net_task_success_delta"],
            rejected_on_observed_tasks=(
                vs_hybrid["net_task_success_delta"] <= 0
                or vs_organized["net_task_success_delta"] <= 0
            ),
            # Source-before-task training and independent future exposure are
            # not authenticated by a user's assertion in this JSON document.
            parameter_learning_admitted=False,
        )
    unknown_costs = sorted(
        key for key in COST_KEYS if any(row["cost"][key] is None for row in rows)
    )
    return dict(
        stage_1_reader=dict(
            frozen_oracle_success_rate=oracle,
            reference_oracle_success_rate=reference,
            ordinary_hybrid_success_rate=hybrid,
            ablated_success_rate=ablated,
            oracle_success_with_premise_removed=premise["both_success"],
            oracle_success_lost_after_ablation=premise["wins"],
            ablation_is_not_independent_necessity_proof=True,
            reference_only_gain_is_reader_capacity=True,
            claimed_full_evidence_human_certified=False,
            missing_premise_necessity_human_certified=False,
            next_priority=reader_next,
            reader_capability_independently_established=False,
        ),
        stage_2_nonparametric=dict(
            observed_organized_minus_hybrid=organized["net_task_success_delta"],
            paired_organization_wins=organized["wins"],
            paired_organization_losses=organized["losses"],
            no_task_gain_on_this_cohort=organized["wins"] == organized["losses"],
            matched_strong_rag_control_is_not_independently_qualified=True,
            independent_organization_superiority_established=False,
        ),
        stage_3_parametric=dict(
            candidates=learning,
            knowledge_only_vs_empty_task_delta=pairs["knowledge_only_vs_empty"][
                "net_task_success_delta"
            ],
            knowledge_only_original_body_absence_authenticated=False,
            prospective_training_freeze_authenticated=False,
            independent_heldout_gain_established=False,
        ),
        stage_4_lifetime=dict(
            missing_cost_fields=unknown_costs,
            per_observation_cost_totals_not_amortized_lifecycle=True,
            shared_write_cost_allocation_authenticated=False,
            retained_raw_source_storage_in_cost_model="raw_storage" in COST_KEYS,
            maintenance_revocation_recovery_observed_in_production=False,
            measured_query_reuse_break_even=None,
            independently_observed_future_windows=0,
            production_accepted=False,
        ),
        protocol_regressions_are_not_fresh_model_or_program_executions=True,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", required=True)
    p.add_argument("--observations", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = analyze(load(args.plan), load(args.observations))
    output = Path(args.output)
    if output.exists():
        raise ValueError("refuse to overwrite audit")
    output.write_bytes(canonical(result) + b"\n")


if __name__ == "__main__":
    main()
