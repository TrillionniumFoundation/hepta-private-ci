"""Freeze every B choice before opening C, preserving all raw execution results."""

from pathlib import Path
import time

from . import adoption, circuit_study_v2, circuit_task_readout_v2
from . import coding_sft, data, repo_execution, repo_interaction_v2, study_v2 as study
from . import study_v2_evidence as evidence, study_v2_support as support
from .composition_core import ARMS, digest as circuit_digest, require

cold = support.cold


def _evaluations(root, panel, rows, models, a_rows):
    return {
        name: evidence.checked_evaluation(
            root,
            name,
            panel,
            rows,
            models,
            prompts=study.retrieve(a_rows, rows) if name == "retrieval" else None,
        )
        for name in study.EVALUATED
    }


def _feature_rows(receipt):
    return [
        {**row, "feature_binding_digest": receipt["binding"]} for row in receipt["rows"]
    ]


def select(root):
    root = Path(root)
    frozen = study.guard(root)
    coding_sft.write_new(
        root / "SELECTION_STARTED.json", {"at_ns": time.time_ns(), "C_opened": False}
    )
    try:
        return _select(root, frozen)
    except Exception as failure:
        coding_sft.write_new(
            root / "SELECTION_FAILED.json",
            {"error": type(failure).__name__ + ": " + str(failure), "C_opened": False},
        )
        raise


def _select(root, frozen):
    ab = study.records(root)
    a, b = ([r for r in ab if r["split"] == split] for split in ("train", "selection"))
    models, training = evidence.material(root)
    b_reports = _evaluations(root, "B", b, models, a)
    a_reports = {
        name: evidence.checked_evaluation(root, name, "A", a, models)
        for name in study.ROUTED
    }
    feature_receipt = study.features(root, ab, root / "features/AB.json")
    features = _feature_rows(feature_receipt)
    a_ids = {r["task_id"] for r in a}
    af, bf = (
        [r for r in features if r["task_id"] in a_ids],
        [r for r in features if r["task_id"] not in a_ids],
    )
    identities = [data.digest(models[name]) for name in study.ROUTED]
    capacity = [training[name] for name in study.ROUTED]
    prepared = circuit_task_readout_v2.routing_targets(
        a,
        [a_reports[n] for n in study.ROUTED],
        identities,
        af,
        expected_panel_digest=data.digest(a),
    )
    a_labels = prepared["rows"]
    b_labels = evidence.heldout_targets(
        b, [b_reports[n] for n in study.ROUTED], identities, bf
    )
    coding_sft.write_new(root / "features/A_ROUTING_TARGETS.json", prepared)
    plan = {
        "schema": "hepta.repository-routing-plan.v2",
        "width": 64,
        "hidden": 8,
        "classes": 3,
        "cells": 4,
        "seed": 1729,
        "updates": 224,
        "rate": 0.03,
        "feature_binding_digest": feature_receipt["binding"],
        "label_rule": circuit_task_readout_v2.LABEL_RULE,
        "scope": "offline routing of three cached same-base first attempts",
    }
    result = circuit_study_v2.freeze_selection(
        a_labels, b_labels, plan, root / "circuit"
    )
    b_routes = {
        "arms": {arm: study.read(root / "circuit" / arm / "B.json") for arm in ARMS},
        "selected_arm": result["frozen"]["selected_arm"],
    }
    b_business = circuit_task_readout_v2.readout(
        b_routes,
        [b_reports[n] for n in study.ROUTED],
        identities,
        b,
        b_labels,
        expected_panel_digest=data.digest(b),
        capacity_evidence=capacity,
    )
    scores = {
        arm: evidence.source_macro(value["main"]["rows"], "success")
        for arm, value in b_business["arms"].items()
    }
    selected_arm = min(ARMS, key=lambda arm: (-scores[arm], ARMS.index(arm)))
    outer = {
        "selected_arm": selected_arm,
        "B_business_source_macro": scores,
        "rule": "B source-macro first-attempt business success; fixed arm order breaks ties",
        "tie_priority": list(ARMS),
        "inner_diagnostic_selection": result["frozen"]["selected_arm"],
        "B_business_digest": data.digest(b_business),
        "C_accessed": False,
    }
    coding_sft.write_new(root / "circuit/B_BUSINESS.json", b_business)
    coding_sft.write_new(root / "circuit/B_BUSINESS_SELECTION.json", outer)
    growth = support.freeze_growth(
        root,
        a_labels,
        b_labels,
        plan,
        b,
        [b_reports[n] for n in study.ROUTED],
        identities,
        capacity,
    )
    e6 = {}
    for name in ("final_answer", "trajectory"):
        item = training[name]
        evaluation = evidence.e6_evaluation(item["plan"], b_reports, name)
        choice = evidence.choose_e6(
            evaluation,
            item["training"]["parameter_change"],
            item["plan"]["minimum_gain"],
        )
        coding_sft.write_new(
            root / "E6_BINDINGS" / name / "B_EVALUATION.json", evaluation
        )
        e6[name] = {
            **choice,
            "plan_digest": data.digest(item["plan"]),
            "evaluation_digest": data.digest(evaluation),
            "candidate_model_digest": data.digest(models[name]),
            "selected_model_digest": data.digest(
                models[name if choice["decision"] == "ADOPTED" else "parent"]
            ),
        }
    adapter_recovery = support.cold_probes(root, b_reports, models)
    best_single = min(
        study.ROUTED[:2],
        key=lambda name: (
            -evidence.source_macro(b_reports[name]["rows"], "success"),
            study.ROUTED.index(name),
        ),
    )
    selection = {
        "schema": "hepta.repository-study.selection.v2",
        "status": "COMPLETE",
        "frozen_at_ns": time.time_ns(),
        "freeze_digest": data.digest(frozen),
        "models": {name: data.digest(model) for name, model in models.items()},
        "B": {
            name: {
                "source_macro_first": evidence.source_macro(report["rows"]),
                "source_macro_within_two": evidence.source_macro(
                    report["rows"], "success"
                ),
                "evaluation_digest": data.digest(report),
            }
            for name, report in b_reports.items()
        },
        "feature_binding_digest": feature_receipt["binding"],
        "circuit_freeze_digest": result["frozen_digest"],
        "circuit_business_selection": outer,
        "growth_digest": data.digest(growth),
        "E6": e6,
        "E3_best_single": best_single,
        "E3_selection_rule": "B source-macro within-two success then fixed specialist order",
        "cold_adapter_recovery": {
            name: data.digest(report) for name, report in adapter_recovery.items()
        },
        "C_answers_accessed": False,
        "shared_controller_custody": True,
        "independent_scientific_qualification": "BLOCKED",
    }
    study.guard(root)
    selection["bindings"] = evidence.binding_inventory(root)
    coding_sft.write_new(root / "B_SELECTION.json", selection)
    return {
        "status": "FROZEN",
        "selection_file_sha256": coding_sft.file_hash(root / "B_SELECTION.json"),
        "circuit_business_selected": selected_arm,
        "E6": e6,
    }


def confirm(root, expected_selection_sha):
    root = Path(root)
    require(
        isinstance(expected_selection_sha, str) and len(expected_selection_sha) == 64,
        "external B selection file SHA256 required",
    )
    require(
        coding_sft.file_hash(root / "B_SELECTION.json") == expected_selection_sha,
        "B selection changed after previous process",
    )
    frozen, selection = study.guard(root), study.read(root / "B_SELECTION.json")
    require(
        selection["status"] == "COMPLETE"
        and data.digest(frozen) == selection["freeze_digest"],
        "B freeze binding differs",
    )
    evidence.verify_bindings(root, selection["bindings"])
    coding_sft.write_new(
        root / "CONFIRMATION_STARTED.json",
        {"at_ns": time.time_ns(), "selection_file_sha256": expected_selection_sha},
    )
    try:
        return _confirm(root, selection, expected_selection_sha)
    except Exception as failure:
        coding_sft.write_new(
            root / "CONFIRMATION_FAILED.json",
            {
                "error": type(failure).__name__ + ": " + str(failure),
                "C_may_have_been_accessed": True,
            },
        )
        raise


def _confirm(root, selection, expected_selection_sha):
    custody = repo_execution.unlock_confirmation(
        root / "B_SELECTION.json", expected_selection_sha
    )
    ab, c = study.records(root), study.records(root, "confirmation")
    admission = data.validate_records(ab + c)
    require(
        study.panel(c)
        == [
            {k: row[k] for k in ("task_id", "source_id", "task_digest")}
            for row in study.read(root / "inputs/confirmation/META.json")[
                "task_metadata"
            ]
        ],
        "sealed C panel differs",
    )
    a, b = ([r for r in ab if r["split"] == split] for split in ("train", "selection"))
    models, training = evidence.material(root)
    require(
        {name: data.digest(model) for name, model in models.items()}
        == selection["models"],
        "selected models changed",
    )
    for name in study.EVALUATED:
        repo_interaction_v2.evaluate(
            models[name],
            root,
            c,
            root / "evaluation/C" / name,
            maximum=2,
            prompt_records=study.retrieve(a, c) if name == "retrieval" else None,
        )
    c_reports = _evaluations(root, "C", c, models, a)
    b_reports = _evaluations(root, "B", b, models, a)
    features = study.features(root, c, root / "features/C.json")
    require(
        features["binding"] == selection["feature_binding_digest"],
        "C encoder binding differs",
    )
    identities = [data.digest(models[name]) for name in study.ROUTED]
    capacity = [training[name] for name in study.ROUTED]
    c_labels = evidence.heldout_targets(
        c, [c_reports[n] for n in study.ROUTED], identities, _feature_rows(features)
    )
    circuit = circuit_study_v2.confirm_selection(
        c_labels, root / "circuit", selection["circuit_freeze_digest"]
    )
    business = circuit_task_readout_v2.readout(
        circuit,
        [c_reports[n] for n in study.ROUTED],
        identities,
        c,
        c_labels,
        expected_panel_digest=data.digest(c),
        capacity_evidence=capacity,
    )
    coding_sft.write_new(root / "circuit/C_BUSINESS.json", business)
    growth_frozen = study.read(root / "growth/FROZEN.json")
    require(
        data.digest(growth_frozen) == selection["growth_digest"], "E5 freeze changed"
    )
    growth = support.confirm_growth(
        root,
        growth_frozen,
        c_labels,
        c,
        [c_reports[n] for n in study.ROUTED],
        identities,
        capacity,
    )
    coding_sft.write_new(root / "growth/CONFIRMATION.json", growth)
    e6 = {}
    for name in ("final_answer", "trajectory"):
        item = training[name]
        evaluation = study.read(root / "E6_BINDINGS" / name / "B_EVALUATION.json")
        require(
            data.digest(evaluation) == selection["E6"][name]["evaluation_digest"],
            "frozen E6 evaluation changed",
        )
        request = {
            "plan": item["plan"],
            "parent": models["parent"],
            "candidate": models[name],
            "training": item["training"],
            "evaluation": evaluation,
            "c_tasks": [{**p, "record": r} for p, r in zip(study.panel(c), c)],
            "artifact_root": str(root.resolve()),
        }
        report = adoption.execute(request, root / "E6" / name)
        choice = selection["E6"][name]
        require(
            report["status"] == choice["decision"]
            and report["selected_model_digest"] == choice["selected_model_digest"],
            "E6 actual execution differs from pre-C decision or failed",
        )
        selected_name = name if choice["decision"] == "ADOPTED" else "parent"
        for actual, cached in zip(report["C"], c_reports[selected_name]["rows"]):
            require(
                adoption.comparable(actual["prediction"])
                == adoption.comparable(cached["steps"][0]["output"])
                and actual["outcome"]["success"] == cached["first_attempt_success"],
                "E6 first-shot execution differs from frozen profile",
            )
        e6[name] = report
    from .study_v2_reporting import report_experiments

    result = report_experiments(b_reports, c_reports, c, selection)
    selected_arm = selection["circuit_business_selection"]["selected_arm"]
    result.update(
        schema="hepta.repository-study.result.v2",
        status="COMPLETE_ENGINEERING",
        source_digest=data.digest(study.sources()),
        selection_file_sha256=expected_selection_sha,
        admission=admission,
        confirmation_custody=custody,
        E4={
            "diagnostic": circuit,
            "business": business,
            "outer_B_selection": selection["circuit_business_selection"],
            "selected_C_business": business["arms"][selected_arm]["main"],
            "matched_full_system_cost": False,
            "online_routed_execution_performed": False,
        },
        E5=growth,
        E6=e6,
        cold_adapter_recovery=selection["cold_adapter_recovery"],
        independent_scientific_qualification="BLOCKED",
        native_cell_adoption="BLOCKED",
        proof_of_useful_work="BLOCKED",
        foundation_model_emergence="UNTESTED",
        full_system_cost_known=False,
        production_eligible=False,
    )
    study.guard(root)
    evidence.verify_bindings(root, selection["bindings"])
    coding_sft.write_new(root / "RESULT.json", result)
    return {
        "status": result["status"],
        "result_sha256": coding_sft.file_hash(root / "RESULT.json"),
        "C_unique_tasks": len(c),
        "E6": {name: r["status"] for name, r in e6.items()},
        "independent_scientific_qualification": "BLOCKED",
    }
