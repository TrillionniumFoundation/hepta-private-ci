"""Reconstruct frozen final routing policies from actual generated answers."""

from population_audit_artifacts import _hash, _json, _read, _require, _same
from population_audit_generation import _assessment, _capability, _journal, _metrics
from population_audit_router import _route


def _final(directory, data, selection, report, router):
    root = directory / "final"
    _same(_json(root / "result.json"), report, "raw final report")
    plan, context = (
        _json(root / "route-plan.json"),
        _json(root / "route-plan-commit.json"),
    )
    probes = data["retention_final"] + data["transfer_final"] + data["ood_final"]
    versions, sources = selection["versions"], data["sources"]
    _require(
        context["route_plan_sha256"]
        == _hash(_read(root / "route-plan.json"))
        == report["route_plan_sha256"],
        "frozen route plan digest",
    )
    _require(
        context["selection_sha256"]
        == plan["selection_sha256"]
        == selection["selection_sha256"]
        and context["router_sha256"]
        == plan["router_sha256"]
        == selection["router_receipt"]["sha256"],
        "pre-final selection/router pins",
    )
    _same(plan["versions"], versions, "precommitted final versions")
    _require(
        plan["probe_gold_included"] is False and len(plan["rows"]) == 120,
        "answer-free full final route plan",
    )
    slots = {
        "split_learned_raw": [],
        "split_learned_guarded": [],
        "split_metadata_only": [],
    }
    for probe, row in zip(probes, plan["rows"], strict=True):
        _require("value" not in row, "final gold absent from route plan")
        for key in ("probe_id", "question", "family", "operation", "source_roots"):
            _same(row[key], probe[key], "route plan probe identity")
        chosen, probabilities = _route(probe["question"], router)
        _same(row["learned"]["slot"], chosen, "independent final learned route")
        _same(
            row["learned"]["probabilities"],
            probabilities,
            "independent final routing probabilities",
        )
        eligibility = [_capability(probe, v, sources) for v in versions["split"]]
        eligible = [i for i, v in enumerate(eligibility) if v["capability_allowed"]]
        _same(row["split_eligibility"], eligibility, "source-only capability decisions")
        _same(row["eligible_split_slots"], eligible, "eligible expert set")
        _same(
            row["single_eligibility"],
            _capability(probe, versions["single"][0], sources),
            "single source capability",
        )
        guard, metadata = (
            chosen if chosen in eligible else None,
            eligible[0] if eligible else None,
        )
        _same(row["learned_guarded_slot"], guard, "guard does not silently reroute")
        _same(row["metadata_slot"], metadata, "strong metadata-only baseline")
        for policy, value in zip(slots, (chosen, guard, metadata), strict=True):
            slots[policy].append(value)
    chosen = selection["choice"]["chosen_arm"]
    parent_probes = probes if chosen == "parent" else data["retention_final"][:16]
    journals = {
        "single": [
            _journal(root, "final-single", versions["single"][0], probes, context)
        ],
        "parent": [
            _journal(
                root, "final-parent", versions["parent"][0], parent_probes, context
            )
        ],
        "split": [
            _journal(root, f"final-split-{i}", v, probes, context)
            for i, v in enumerate(versions["split"])
        ],
    }
    policies = {}
    for arm, cohort in (("single", probes), ("parent", parent_probes)):
        rows = [
            _assessment(p, r, versions[arm][0], sources)
            for p, r in zip(cohort, journals[arm][0]["rows"], strict=True)
        ]
        policies[arm] = {"rows": rows, "metrics": _metrics(rows)}
    actual = []
    for i in (0, 1):
        rows = [
            _assessment(p, r, versions["split"][i], sources)
            for p, r in zip(probes, journals["split"][i]["rows"], strict=True)
        ]
        actual.append({"rows": rows, "metrics": _metrics(rows)})
    for policy, assignments in slots.items():
        rows = []
        for index, (probe, slot) in enumerate(zip(probes, assignments, strict=True)):
            generated, version = (
                (None, None)
                if slot is None
                else (journals["split"][slot]["rows"][index], versions["split"][slot])
            )
            rows.append(
                {**_assessment(probe, generated, version, sources), "slot": slot}
            )
        policies[policy] = {"rows": rows, "metrics": _metrics(rows)}
    for policy in ("oracle", "uniform_random"):
        rows = []
        for i, probe in enumerate(probes[:96]):
            correctness = [a["rows"][i]["supported_correct"] for a in actual]
            raw = [a["rows"][i]["raw_correct"] for a in actual]
            value = max(correctness) if policy == "oracle" else sum(correctness) / 2
            rows.append(
                {
                    "probe_id": probe["probe_id"],
                    "family": probe["family"],
                    "correct": value,
                    "supported_correct": value,
                    "raw_correct": max(raw) if policy == "oracle" else sum(raw) / 2,
                    "action_abstained": False,
                    "decoder_unknown": False,
                    "actual_supported_expert_correct": correctness,
                    "evaluation_only": True,
                }
            )
        policies[policy] = {"rows": rows, "metrics": _metrics(rows)}
    selected_policy = {
        "parent": "parent",
        "single": "single",
        "split": "split_learned_raw",
    }[chosen]
    policies["selected"] = policies[selected_policy]
    _same(
        _json(root / "policy-assessments.json"),
        {"policies": policies, "split_actual": actual},
        "all final scores reconstructed from raw answers",
    )
    _same(
        report["metrics"],
        {k: v["metrics"] for k, v in policies.items()},
        "reported final metrics",
    )
    _require(
        report["chosen_arm"] == chosen
        and report["selected_final_policy"] == selected_policy
        and report["chosen_before_final_read"] is True,
        "source-frozen final arm",
    )
    parent_correct = {
        r["probe_id"]: r["supported_correct"]
        for r in policies["parent"]["rows"]
        if r["family"] == "semantic"
    }
    for key, policy in (
        ("single", "single"),
        ("split", "split_learned_raw"),
        ("selected", "selected"),
    ):
        answers = {
            r["probe_id"]: r["supported_correct"] for r in policies[policy]["rows"]
        }
        _same(
            report["parent_correct_semantic_preserved"][key],
            all(not ok or answers[p] for p, ok in parent_correct.items()),
            "old final semantic preservation",
        )
    retention = policies["split_learned_raw"]["rows"][:64]
    routing = {
        "supported_retention_coverage": sum(
            not r["action_abstained"] and r["capability_allowed"] for r in retention
        )
        / 64,
        "raw_ood_reject_rate": sum(v is None for v in slots["split_learned_raw"][96:])
        / 24,
        "guarded_ood_abstention_rate": sum(
            v is None for v in slots["split_learned_guarded"][96:]
        )
        / 24,
        "learned_beats_metadata_only_known": policies["split_learned_raw"]["metrics"][
            "known"
        ]["accuracy"]
        > policies["split_metadata_only"]["metrics"]["known"]["accuracy"],
    }
    _same(
        report["routing"], routing, "raw learned rejection distinct from metadata guard"
    )
    flat = [j for values in journals.values() for j in values]
    for arm, values in journals.items():
        for j, retained in zip(values, report["journals"][arm], strict=True):
            _require(
                retained["journal_sha256"] == _hash(_read(j["journal_path"])),
                "raw final journal hash",
            )
    rows = [r for j in flat for r in j["rows"]]
    work = {
        "queries": len(rows),
        "total_queries": len(rows),
        "worker_processes": len(flat),
        "input_tokens": sum(r["input_tokens"] for r in rows),
        "generated_tokens": sum(r["generated_tokens"] for r in rows),
        "generation_seconds": sum(r["seconds"] for r in rows),
        "fresh_process_wall_seconds": sum(
            j["fresh_process_wall_seconds"] for j in flat
        ),
    }
    work["total_tokens"] = work["input_tokens"] + work["generated_tokens"]
    _same(report["work"], work, "all diagnostic expert reads charged")
    _require(
        report["live_guarded_dispatch_executed"] is False
        and report["oracle_used_for_selection_or_routing"] is False,
        "evaluation-only comparisons remain evaluation-only",
    )
    return policies
