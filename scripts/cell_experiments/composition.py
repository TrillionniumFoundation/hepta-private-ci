"""E3--E5 research on supplied observations; never invent tasks or adopt weights."""

import argparse
import copy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from hepta_cells.semantic import LocalHead, LocalObjective

# Keep the original import surface available to campaign and downstream callers.
from .composition_core import (
    ARMS,
    COST_SCOPE,
    SparseCircuit,
    canonical,
    digest,
    evaluate,
    fit,
    require,
    schedule,
    sha,
    unique_tasks,
)


SPLITS = {
    "A": "A",
    "B": "B",
    "C": "C",
    "train": "A",
    "selection": "B",
    "confirmation": "C",
}
SIZES = (1, 4, 16, 64)


def timestamp(value):
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.tzinfo is not None, "timestamp requires timezone")
        value = parsed.timestamp()
    require(
        type(value) in (int, float) and math.isfinite(value),
        "finite timestamp required",
    )
    return float(value)


def write_new(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def normalize(records, binding, classes, *, require_temporal=True):
    """Validate supplied rows, temporal order and task/content isolation."""
    require(sha(binding), "frozen feature binding required")
    require(
        type(classes) is int and 2 <= classes <= 128, "bounded class manifest required"
    )
    require(
        type(records) is list and 1 <= len(records) <= 16384, "bounded records required"
    )
    rows, identities, groups, contents = [], set(), {}, {}
    for original in records:
        row = copy.deepcopy(original)
        row["split"] = SPLITS.get(row.get("split"))
        require(row["split"] is not None, "unknown split")
        row["lineage_id"] = row.get("lineage_id", row.get("task_id"))
        for key in ("task_id", "source_id", "project_id", "family_id", "lineage_id"):
            require(
                isinstance(row.get(key), str) and 0 < len(row[key]) <= 256,
                "missing bounded " + key,
            )
        feature = row.get("features")
        observed = timestamp(row.get("timestamp", row.get("observed_at")))
        available = timestamp(row.get("available_at", observed))
        require(available >= observed, "outcome available before observation")
        if isinstance(feature, dict):
            require(feature.get("binding") == binding, "feature binding differs")
            preaction = timestamp(feature.get("preaction_at", observed))
            require(
                timestamp(feature.get("available_at")) <= preaction,
                "post-action feature information",
            )
            feature = feature.get("values")
        else:
            require(
                row.get("feature_binding_digest") == binding, "feature binding differs"
            )
        require(
            type(feature) is list and 1 <= len(feature) <= 1024,
            "bounded frozen feature vector required",
        )
        require(
            all(type(v) in (int, float) and math.isfinite(v) for v in feature),
            "nonfinite or nonnumeric features",
        )
        require(
            type(row.get("target")) is int and 0 <= row["target"] < classes,
            "target must be a manifest class",
        )
        require(row.get("n_classes", classes) == classes, "row class manifest differs")
        outcome = row.get("verified_outcome", {})
        require(
            type(outcome.get("success")) is bool and sha(outcome.get("receipt_sha256")),
            "observed verifier outcome and receipt required",
        )
        observation = row.get("observation_digest")
        if not sha(observation):
            task_input = row.get("task", {}).get("input")
            require(task_input is not None, "original observation identity required")
            observation = digest(task_input)
        content_group = contents.setdefault(
            observation, (row["source_id"], row["split"])
        )
        require(
            content_group == (row["source_id"], row["split"]),
            "same observation relabeled as a new source or split",
        )
        for key in ("task_id", "lineage_id", "source_id", "family_id"):
            require(
                groups.setdefault((key, row[key]), row["split"]) == row["split"],
                "task/lineage/source/family crosses split",
            )
        identity = (observation, row.get("teacher_id"), row.get("model_digest"))
        require(identity not in identities, "duplicate observation/teacher")
        identities.add(identity)
        row.update(
            features=[float(v) for v in feature],
            timestamp=observed,
            available_at=available,
            observation_digest=observation,
        )
        rows.append(row)
    require(len({len(r["features"]) for r in rows}) == 1, "feature dimensions differ")
    panels = {s: [r for r in rows if r["split"] == s] for s in "ABC"}
    require(all(panels.values()), "A training, B selection and C evaluation required")
    for before, after in (("A", "B"), ("B", "C")):
        if require_temporal:
            require(
                max(r["available_at"] for r in panels[before])
                < min(r["timestamp"] for r in panels[after]),
                "nonchronological panels",
            )
    return rows


def teacher_registry(rows, registry, classes):
    """Bind producer receipts; hashes do not authenticate an external provider."""
    admitted = {}
    for teacher, entry in sorted((registry or {}).items()):
        path = Path(entry["receipt_path"])
        require(
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_size <= 8 * 1024 * 1024,
            "bounded teacher receipt required",
        )
        raw = path.read_bytes()
        require(
            hashlib.sha256(raw).hexdigest() == entry.get("receipt_sha256"),
            "teacher receipt bytes differ",
        )
        receipt = json.loads(raw)
        require(
            receipt.get("teacher_id") == teacher
            and sha(receipt.get("model_digest"))
            and receipt["model_digest"] == entry.get("model_digest"),
            "teacher identity/model binding differs",
        )
        require(
            receipt.get("kind") in ("external_model", "same_base_domain_specialist"),
            "teacher must name an actual model, not a seed",
        )
        if receipt["kind"] == "same_base_domain_specialist":
            require(
                sha(receipt.get("training_receipt_sha256"))
                and sha(receipt.get("base_model_digest"))
                and bool(receipt.get("training_source_ids")),
                "unbound specialist training",
            )
        matching = [r for r in rows if r.get("teacher_id") == teacher]
        require(matching, "unused teacher registry entry")
        for row in matching:
            require(
                row.get("model_digest") == receipt["model_digest"],
                "row teacher differs",
            )
            expected = receipt.get("outputs", {}).get(row["task_id"], {})
            output = row.get("actual_output", row.get("final_answer"))
            label = row.get("teacher_target")
            require(
                type(label) is int
                and 0 <= label < classes
                and isinstance(output, str)
                and len(output.encode("utf-8")) <= 65536
                and expected.get("output") == output
                and expected.get("teacher_target") == label,
                "unbound teacher output",
            )
        admitted[teacher] = receipt
    require(
        len({r["model_digest"] for r in admitted.values()}) >= 2,
        "two distinct evidenced teacher models required",
    )
    return admitted


def _plan(plan):
    require(
        isinstance(plan, dict) and plan.get("schema") == "hepta.composition-plan.v1",
        "unknown plan",
    )
    require(
        plan.get("evidence_scope", "independent") in ("independent", "engineering"),
        "unknown evidence scope",
    )
    require(
        isinstance(plan.get("target_name"), str)
        and 0 < len(plan["target_name"]) <= 256,
        "named classification target required",
    )
    for key, ceiling in (
        ("max_train_mac", 10**12),
        ("max_examples", 100000),
        ("passes", 100),
    ):
        require(
            type(plan.get(key)) is int and 1 <= plan[key] <= ceiling, "invalid " + key
        )
    require(
        type(plan.get("learning_rate")) in (int, float)
        and 0 < plan["learning_rate"] <= 1,
        "invalid learning rate",
    )
    require(
        type(plan.get("cells")) is int
        and 2 <= plan["cells"] <= 16
        and type(plan.get("active")) is int
        and 2 <= plan["active"] <= plan["cells"],
        "learned router needs at least two active Cells",
    )
    require(
        type(plan.get("classes")) is int
        and 2 <= plan["classes"] <= 128
        and plan["cells"] * (plan["classes"] + 1) <= 256,
        "ablation matrix exceeds bound",
    )
    seeds = plan.get("seeds")
    require(
        type(seeds) is list
        and 1 <= len(seeds) <= 8
        and len(set(seeds)) == len(seeds)
        and all(type(s) is int and 0 <= s < 2**32 for s in seeds),
        "bounded distinct seeds required",
    )


def run(records, plan, output_dir, feature_binding_digest, teacher_evidence=None):
    """Freeze inputs, train E3--E5, choose using B, then evaluate frozen choices on C."""
    _plan(plan)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=False)
    write_new(root / "PLAN.json", plan)
    write_new(root / "INPUTS.json", records)
    report = dict(
        schema="hepta.composition-results.v1",
        plan_digest=digest(plan),
        input_digest=digest(records),
        feature_binding_digest=feature_binding_digest,
        status="started",
        attempts=[],
        selections=[],
        E3={},
        E4={},
        E5=[],
        independent_confirmation_qualified=False,
        ordinary_daemon_adoptions=0,
        full_cost_known=False,
        real_users_verified=0,
        graph_necessity_qualified=False,
        independent_experiment_status="BLOCKED",
        production_eligible=False,
        evidence_scope=plan.get("evidence_scope", "independent"),
        evidence_gaps=[],
    )
    try:
        rows = normalize(
            records, feature_binding_digest, plan["classes"], require_temporal=False
        )
        require(
            all(
                r.get("target_name", plan["target_name"]) == plan["target_name"]
                for r in rows
            ),
            "row target semantics differ from plan",
        )
        panels = {s: [r for r in rows if r["split"] == s] for s in "ABC"}
        width = len(rows[0]["features"])
        unique = {s: unique_tasks(panels[s]) for s in "ABC"}
        report["upstream_costs"] = [
            {
                "task_id": r["task_id"],
                "source_id": r["source_id"],
                "cost": r.get("upstream_cost"),
            }
            for r in rows
        ]
        report["group_isolation"] = {
            key: all(
                not ({r[key] for r in panels[a]} & {r[key] for r in panels[b]})
                for a, b in (("A", "B"), ("A", "C"), ("B", "C"))
            )
            for key in ("source_id", "project_id", "family_id", "lineage_id")
        }
        report["time_ordered"] = all(
            max(r["available_at"] for r in panels[a])
            < min(r["timestamp"] for r in panels[b])
            for a, b in (("A", "B"), ("B", "C"))
        )
        gaps = report["evidence_gaps"]
        if not report["time_ordered"]:
            gaps.append("A/B/C observation times overlap or are not ordered")
        if not report["group_isolation"]["project_id"]:
            gaps.append("project identity crosses panels")
        if any(
            r.get("origin_kind") == "curated_development"
            or r.get("exposure") != "unexposed"
            for r in panels["C"]
        ):
            gaps.append(
                "C is development, previously exposed, or lacks exposure evidence"
            )
        if any(
            not (
                sha(r.get("custody", {}).get("receipt_sha256"))
                and type(r.get("custody", {}).get("frozen_at")) in (int, float)
                and r["custody"]["frozen_at"] < r["timestamp"]
                and r["custody"].get("exposed_to_training") is False
            )
            for r in panels["C"]
        ):
            gaps.append("independent C custody declarations incomplete")
        require(
            report["evidence_scope"] == "engineering" or not gaps,
            "independent admission blocked: " + "; ".join(gaps),
        )
        gaps.extend(
            [
                "provider origin and external custody are not authenticated by this process",
                "matched total cost and independent superiority are not established",
            ]
        )
        budget = {k: plan[k] for k in ("max_examples", "max_train_mac")}
        pending, models = {}, {}

        def attempt(
            experiment,
            label,
            arm,
            data,
            limit,
            seed,
            *,
            target_key="target",
            specialists=None,
        ):
            identity = f"{experiment}-{label}-s{seed}"
            folder = root / identity
            folder.mkdir()
            start = dict(
                attempt_id=identity,
                experiment=experiment,
                arm=arm,
                label=label,
                seed=seed,
                train_digest=digest(data),
                budget=limit,
                plan_digest=report["plan_digest"],
                status="started",
            )
            write_new(folder / "STARTED.json", start)
            model = SparseCircuit(
                width, plan["classes"], plan["cells"], plan["active"], arm, seed
            )
            preparation, remaining, training = [], dict(limit), None
            try:
                if specialists:
                    count = len(specialists)
                    model = SparseCircuit(
                        width,
                        plan["classes"],
                        count,
                        min(plan["active"], count),
                        arm,
                        seed,
                    )
                    part = {k: v // (2 * count) for k, v in limit.items()}
                    for i, examples in enumerate(specialists):
                        initial = SparseCircuit(
                            width, plan["classes"], 1, 1, "single", (seed + i) % 2**32
                        )
                        expert, receipt = fit(
                            initial,
                            examples,
                            part,
                            plan["learning_rate"],
                            plan["passes"],
                            target_key="teacher_target",
                        )
                        preparation.append(receipt)
                        require(
                            receipt["status"] == "completed_candidate_only",
                            "specialist training incomplete",
                        )
                        model.heads[i] = expert.heads[0]
                        remaining["max_train_mac"] -= receipt["linear_mac"]
                        remaining["max_examples"] -= receipt["updates"]
                model, training = fit(
                    model,
                    data,
                    remaining,
                    plan["learning_rate"],
                    plan["passes"],
                    target_key=target_key,
                    freeze_heads=bool(specialists),
                )
                result = dict(
                    start,
                    status=training["status"],
                    training=training,
                    preparation=preparation,
                )
                result["total_training"] = {
                    key: sum(p.get(key, 0) for p in preparation + [training])
                    for key in (
                        "linear_mac",
                        "linear_flops",
                        "messages",
                        "message_bytes",
                        "active_parameter_uses",
                        "updates",
                        "attempted_updates",
                        "wall_ns",
                        "process_cpu_ns",
                    )
                }
                result["total_training"]["full_cost_known"] = False
                write_new(folder / "PARAMETERS.json", model.record())
                if training["status"] == "completed_candidate_only":
                    result["B"] = evaluate(model, unique["B"])
                    pending.setdefault((experiment, label), []).append(identity)
                    models[identity] = model
            except Exception as error:
                result = dict(
                    start,
                    status="FAILED",
                    preparation=preparation,
                    error=f"{type(error).__name__}: {error}",
                )
                if training is not None:
                    result["training"] = training
            write_new(folder / "RESULT.json", result)
            report["attempts"].append(result)

        for seed in plan["seeds"]:
            for arm in ARMS:
                attempt("E4", arm, arm, unique["A"], budget, seed)
        report["E4"] = dict(
            status="executed_research_candidates",
            scope="one-hop sparse logit circuit",
            native_circuit_integrated=False,
            budget_caps_matched=True,
            actual_costs_matched=False,
            necessity_claim=False,
        )
        try:
            registry = teacher_registry(rows, teacher_evidence, plan["classes"])
            training = [r for r in panels["A"] if r.get("teacher_id") in registry]
            teachers = sorted({r["teacher_id"] for r in training})
            require(
                2 <= len(teachers) <= 16,
                "two to sixteen teachers must have A observations",
            )
            choices = {
                "single_" + digest(t)[:12]: [
                    r for r in training if r["teacher_id"] == t
                ]
                for t in teachers
            }
            choices["pooled"] = training
            routed = []
            for family in sorted({r["family_id"] for r in training}):
                candidates = [r for r in training if r["family_id"] == family]
                teacher = min(
                    {r["teacher_id"] for r in candidates},
                    key=lambda t: (
                        -np.mean(
                            [
                                r["teacher_target"] == r["target"]
                                for r in candidates
                                if r["teacher_id"] == t
                            ]
                        ),
                        t,
                    ),
                )
                routed.extend(r for r in candidates if r["teacher_id"] == teacher)
            choices["domain_routed"] = routed
            for seed in plan["seeds"]:
                for label, data in choices.items():
                    attempt(
                        "E3",
                        label,
                        "single",
                        data,
                        budget,
                        seed,
                        target_key="teacher_target",
                    )
                specialist_data = [
                    [r for r in training if r["teacher_id"] == t] for t in teachers
                ]
                attempt(
                    "E3",
                    "student_specialists",
                    "learned_sparse",
                    unique["A"],
                    budget,
                    seed,
                    specialists=specialist_data,
                )
            report["E3"] = dict(
                status="executed_hard_label_imitation",
                teachers=teachers,
                registry_pins=teacher_evidence,
                on_policy_distillation=False,
                specialist_scope="student LocalHeads on one frozen representation",
                identity_scope="hash-bound producer receipts; origin authentication external",
            )
        except (ValueError, KeyError, OSError) as error:
            report["E3"] = dict(status="BLOCKED", reason=str(error))
        sources = sorted({r["source_id"] for r in unique["A"]})
        for mode in ("fixed_total", "fixed_per_source"):
            for size in SIZES:
                group = dict(
                    mode=mode,
                    requested_sources=size,
                    available_sources=len(sources),
                    real_users_verified=0,
                )
                if len(sources) < size:
                    group.update(
                        status="BLOCKED",
                        reason="insufficient distinct observed sources",
                    )
                else:
                    selected = sources[:size]
                    data = [r for r in unique["A"] if r["source_id"] in selected]
                    limit = {
                        k: v * (size if mode == "fixed_per_source" else 1)
                        for k, v in budget.items()
                    }
                    if mode == "fixed_per_source":
                        limit.update(
                            per_source_max_examples=budget["max_examples"],
                            per_source_max_train_mac=budget["max_train_mac"],
                        )
                    for seed in plan["seeds"]:
                        attempt("E5", f"{mode}-{size}", "single", data, limit, seed)
                    group.update(
                        status="executed_local_source_replay",
                        sources=selected,
                        budget=limit,
                        distributed_concurrency=False,
                    )
                report["E5"].append(group)
        # All B selection ends before the first C evaluation; C never chooses a candidate.
        for key, identifiers in sorted(pending.items()):
            options = [a for a in report["attempts"] if a["attempt_id"] in identifiers]
            chosen = min(options, key=lambda a: (a["B"]["loss"], a["attempt_id"]))
            report["selections"].append(
                dict(
                    selection_round=len(report["selections"]) + 1,
                    experiment=key[0],
                    label=key[1],
                    candidate_ids=identifiers,
                    chosen_attempt_id=chosen["attempt_id"],
                    chosen_digest=models[chosen["attempt_id"]].digest,
                    rule="minimum B cross entropy, then lexicographic attempt ID",
                    B_panel_digest=digest(unique["B"]),
                )
            )
        write_new(root / "FROZEN_SELECTIONS.json", report["selections"])
        ablation_evaluations = 0
        for choice in report["selections"]:
            model = models[choice["chosen_attempt_id"]]
            evaluation = dict(selection=choice, C=evaluate(model, unique["C"]))
            if choice["experiment"] == "E4" and model.cells > 1:
                evaluation["ablation"] = dict(
                    cells=[
                        dict(cell=i, result=evaluate(model, unique["C"], drop_cell=i))
                        for i in range(model.cells)
                    ],
                    edges=[
                        dict(
                            edge=[i, j],
                            result=evaluate(model, unique["C"], drop_edge=(i, j)),
                        )
                        for i in range(model.cells)
                        for j in range(model.classes)
                    ],
                    semantics="learned Cell removal reroutes; fixed drops/renormalizes; edge zeros one Cell/class logit; no retraining",
                    matched_active_resources=False,
                    necessity_claim=False,
                )
                ablation_evaluations += model.cells * (model.classes + 1)
            write_new(
                root / choice["chosen_attempt_id"] / "C_EVALUATION.json", evaluation
            )
        report.update(
            status="completed_research_only"
            if report["selections"]
            else "BLOCKED_NO_EVALUATED_CANDIDATE",
            C_evaluations=len(report["selections"]),
            attempted_candidates=len(report["attempts"]),
            C_ablation_evaluations=ablation_evaluations,
            C_total_evaluations=len(report["selections"]) + ablation_evaluations,
            B_evaluations=sum("B" in a for a in report["attempts"]),
        )
    except Exception as error:
        report.update(status="BLOCKED", error=f"{type(error).__name__}: {error}")
    write_new(root / "RESULTS.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records")
    parser.add_argument("plan")
    parser.add_argument("output")
    parser.add_argument("--feature-binding", required=True)
    parser.add_argument("--teacher-registry")
    args = parser.parse_args()
    result = run(
        json.loads(Path(args.records).read_bytes()),
        json.loads(Path(args.plan).read_bytes()),
        args.output,
        args.feature_binding,
        None
        if args.teacher_registry is None
        else json.loads(Path(args.teacher_registry).read_bytes()),
    )
    print(
        json.dumps(
            {key: result[key] for key in ("status", "plan_digest", "input_digest")}
        )
    )
    return 0 if result["status"] == "completed_research_only" else 2


if __name__ == "__main__":
    raise SystemExit(main())
