"""Pinned fresh readers and explicitly costed, evaluation-only routing comparisons."""

import hashlib
import json
from pathlib import Path
import time

from learned_router import load_router
from parametric_owner import Frontier, ParametricOwner
from population_fixtures import canonical_bytes
from population_worker import fresh_read
from population_scoring import (
    GROUPS,
    assess_probe,
    probe_eligibility,
    score_single,
    source_capabilities,
    summarize_rows,
)


def read_final(model, data, training, selection, output, write_json):
    """Freeze routes first; score all actual outputs after every worker completes."""
    selection_path = Path(selection["selection_path"])
    selection_bytes = selection_path.read_bytes()
    selection_hash = hashlib.sha256(selection_bytes).hexdigest()
    if (
        selection_hash != selection["selection_sha256"]
        or json.loads(selection_bytes)
        != {
            k: v
            for k, v in selection.items()
            if k not in ("selection_path", "selection_sha256")
        }
        or selection["versions"] != training["versions"]
    ):
        raise ValueError("final reader requires the unchanged precommitted selection")
    versions = selection["versions"]
    chosen = selection["choice"]["chosen_arm"]
    if (
        chosen not in ("parent", "single", "split")
        or selection["final_scores_used"] is not False
    ):
        raise ValueError("invalid source-only chosen arm")
    capabilities = source_capabilities(data["sources"])
    if (
        hashlib.sha256(canonical_bytes(data["sources"])).hexdigest()
        != selection["sources_sha256"]
    ):
        raise ValueError("source metadata changed after selection")
    cohorts = [data["retention_final"], data["transfer_final"], data["ood_final"]]
    if [len(v) for v in cohorts] != [64, 32, 24]:
        raise ValueError("registered untouched final cohorts required")
    probes = [p for cohort in cohorts for p in cohort]
    router = load_router(
        selection["router_path"], expected_sha256=selection["router_receipt"]["sha256"]
    )
    plan = []
    for probe in probes:
        decision = router.predict({"question": probe["question"]})
        eligibilities = [
            probe_eligibility(probe, v, capabilities) for v in versions["split"]
        ]
        eligible = [
            i for i, value in enumerate(eligibilities) if value["capability_allowed"]
        ]
        plan.append(
            {
                **{
                    key: probe[key]
                    for key in (
                        "probe_id",
                        "question",
                        "family",
                        "operation",
                        "source_roots",
                    )
                },
                "learned": decision,
                "split_eligibility": eligibilities,
                "eligible_split_slots": eligible,
                "single_eligibility": probe_eligibility(
                    probe, versions["single"][0], capabilities
                ),
                "learned_guarded_slot": decision["slot"]
                if decision["slot"] in eligible
                else None,
                "metadata_slot": eligible[0] if eligible else None,
            }
        )
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    plan_path = output / "route-plan.json"
    write_json(
        plan_path,
        {
            "schema": "hepta.population.frozen-route-plan.v1",
            "rows": plan,
            "selection_sha256": selection_hash,
            "router_sha256": selection["router_receipt"]["sha256"],
            "versions": versions,
            "probe_gold_included": False,
            "metadata_guard_uses_supplied_structured_operations": True,
        },
    )
    context = {
        "selection_sha256": selection_hash,
        "router_sha256": selection["router_receipt"]["sha256"],
        "route_plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "route_plan_committed_unix_ns": time.time_ns(),
    }
    write_json(output / "route-plan-commit.json", context)
    owner, frontier = (
        ParametricOwner(output / "owners.sqlite3"),
        Frontier(data["scope"], 1, ()),
    )
    questions = [p["question"] for p in probes]
    journals = {
        "single": [
            fresh_read(
                model,
                versions["single"][0],
                questions,
                output,
                "final-single",
                owner,
                frontier,
                write_json,
                context=context,
            )
        ]
    }
    journals["split"] = [
        fresh_read(
            model,
            version,
            questions,
            output,
            f"final-split-{i}",
            owner,
            frontier,
            write_json,
            context=context,
        )
        for i, version in enumerate(versions["split"])
    ]
    parent_probes = (
        probes
        if chosen == "parent"
        else [p for p in probes if p["family"] == "semantic"]
    )
    journals["parent"] = [
        fresh_read(
            model,
            versions["parent"][0],
            [p["question"] for p in parent_probes],
            output,
            "final-parent",
            owner,
            frontier,
            write_json,
            context=context,
        )
    ]
    # Gold is consumed only after every fresh worker and owner postcheck returns.
    policies = {
        "single": score_single(
            probes, journals["single"][0], versions["single"][0], capabilities
        ),
        "parent": score_single(
            parent_probes, journals["parent"][0], versions["parent"][0], capabilities
        ),
    }
    split_scored = [
        score_single(probes, journal, version, capabilities)
        for journal, version in zip(journals["split"], versions["split"], strict=True)
    ]
    for policy, field in (
        ("split_learned_raw", "learned"),
        ("split_learned_guarded", "learned_guarded_slot"),
        ("split_metadata_only", "metadata_slot"),
    ):
        rows = []
        for index, (probe, route) in enumerate(zip(probes, plan, strict=True)):
            slot = route[field]["slot"] if field == "learned" else route[field]
            generated = (
                journals["split"][slot]["rows"][index] if slot is not None else None
            )
            version = versions["split"][slot] if slot is not None else None
            rows.append(
                {**assess_probe(probe, generated, version, capabilities), "slot": slot}
            )
        policies[policy] = {"rows": rows, "metrics": summarize_rows(rows)}
    for policy in ("oracle", "uniform_random"):
        rows = []
        for index, probe in enumerate(probes):
            if probe["family"] == "unknown":
                continue
            actual = [scored["rows"][index] for scored in split_scored]
            correct = [row["supported_correct"] for row in actual]
            raw = [row["raw_correct"] for row in actual]
            value = max(correct) if policy == "oracle" else sum(correct) / 2
            rows.append(
                {
                    "probe_id": probe["probe_id"],
                    "family": probe["family"],
                    "correct": value,
                    "supported_correct": value,
                    "raw_correct": max(raw) if policy == "oracle" else sum(raw) / 2,
                    "action_abstained": False,
                    "decoder_unknown": False,
                    "actual_supported_expert_correct": correct,
                    "evaluation_only": True,
                }
            )
        policies[policy] = {"rows": rows, "metrics": summarize_rows(rows)}
    selected_policy = {
        "parent": "parent",
        "single": "single",
        "split": "split_learned_raw",
    }[chosen]
    policies["selected"] = policies[selected_policy]
    metrics = {name: scored["metrics"] for name, scored in policies.items()}
    parent_old = {
        row["probe_id"]: row["supported_correct"]
        for row in policies["parent"]["rows"]
        if row["family"] == "semantic"
    }
    preservation = {}
    for name, policy in (
        ("single", "single"),
        ("split", "split_learned_raw"),
        ("selected", "selected"),
    ):
        candidate = {
            row["probe_id"]: row["supported_correct"]
            for row in policies[policy]["rows"]
        }
        preservation[name] = all(
            not correct or candidate[key] for key, correct in parent_old.items()
        )
    raw_routes = policies["split_learned_raw"]["rows"]
    retention_routes = [r for r in raw_routes if r["family"] in GROUPS["retention"]]
    unknown_routes = [r for r in plan if r["family"] == "unknown"]
    work_rows = [
        r
        for entries in journals.values()
        for journal in entries
        for r in journal["rows"]
    ]
    work = {
        "queries": len(work_rows),
        "total_queries": len(work_rows),
        "input_tokens": sum(r["input_tokens"] for r in work_rows),
        "generated_tokens": sum(r["generated_tokens"] for r in work_rows),
        "generation_seconds": sum(r["seconds"] for r in work_rows),
        "fresh_process_wall_seconds": sum(
            j["fresh_process_wall_seconds"]
            for entries in journals.values()
            for j in entries
        ),
        "worker_processes": sum(len(entries) for entries in journals.values()),
    }
    work["total_tokens"] = work["input_tokens"] + work["generated_tokens"]
    unchanged = (
        hashlib.sha256(selection_path.read_bytes()).hexdigest() == selection_hash
    )
    if (
        not unchanged
        or hashlib.sha256(plan_path.read_bytes()).hexdigest()
        != context["route_plan_sha256"]
        or hashlib.sha256(Path(selection["router_path"]).read_bytes()).hexdigest()
        != context["router_sha256"]
    ):
        raise ValueError(
            "frozen selection, router, or route plan changed during final reads"
        )
    assessments_path = output / "policy-assessments.json"
    write_json(assessments_path, {"policies": policies, "split_actual": split_scored})
    retained = {
        arm: [
            {
                "journal_path": j["journal_path"],
                "journal_sha256": hashlib.sha256(
                    Path(j["journal_path"]).read_bytes()
                ).hexdigest(),
                "active_version": j["active_version"],
                "queries": len(j["rows"]),
            }
            for j in entries
        ]
        for arm, entries in journals.items()
    }
    report = {
        "schema": "hepta.population.final-read-result.v1",
        "metrics": metrics,
        "chosen_arm": chosen,
        "selected_final_policy": selected_policy,
        "versions": versions,
        "parent_semantic_recall": metrics["parent"]["semantic"]["accuracy"],
        "parent_correct_semantic_preserved": preservation,
        "routing": {
            "supported_retention_coverage": sum(
                not r["action_abstained"] and r["capability_allowed"]
                for r in retention_routes
            )
            / len(retention_routes),
            "raw_ood_reject_rate": sum(
                r["learned"]["slot"] is None for r in unknown_routes
            )
            / len(unknown_routes),
            "guarded_ood_abstention_rate": sum(
                r["learned_guarded_slot"] is None for r in unknown_routes
            )
            / len(unknown_routes),
            "learned_beats_metadata_only_known": metrics["split_learned_raw"]["known"][
                "accuracy"
            ]
            > metrics["split_metadata_only"]["known"]["accuracy"],
        },
        "work": work,
        "owner_database_bytes": (output / "owners.sqlite3").stat().st_size,
        "all_owner_admitted": all(
            j["owner_admitted_before_and_after"]
            for entries in journals.values()
            for j in entries
        ),
        "selection_unchanged": unchanged,
        "chosen_before_final_read": True,
        "route_plan_path": str(plan_path),
        "assessment_path": str(assessments_path),
        **context,
        "assessment_sha256": hashlib.sha256(assessments_path.read_bytes()).hexdigest(),
        "journals": retained,
        "capability_metadata_bytes": len(canonical_bytes(capabilities)),
        "all_expert_outputs_computed_for_evaluation": True,
        "live_guarded_dispatch_executed": False,
        "oracle_used_for_selection_or_routing": False,
        "raw_ood_and_metadata_abstention_are_separate": True,
        "source_authority": "pinned_local_research_sources",
        "production_accepted": False,
    }
    write_json(output / "result.json", report)
    return report
