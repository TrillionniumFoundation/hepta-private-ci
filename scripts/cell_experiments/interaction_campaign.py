"""Frozen E2 collection/training/B-selection/C-readout orchestration."""

import argparse
import json
from pathlib import Path
import time

from . import campaign, coding_sft, data, interaction

NAMES = ("e2_demonstration", "e2_shadow", "e2_controlled")
TRAINING = {
    "steps": 32,
    "sequence_tokens": 512,
    "rank": 4,
    "learning_rate": 0.0003,
    "seed": 1729,
}
MAX_STEPS = 2


def _read(path):
    return json.loads(Path(path).read_bytes())


def _sources():
    return data.digest(
        {
            p.name: coding_sft.file_hash(p)
            for p in sorted(Path(__file__).parent.glob("*.py"))
        }
    )


def _checked(root, dataset):
    records = campaign.guard(
        root, dataset
    )  # Missing guard is an error, never a fallback.
    frozen = _read(root / "CAMPAIGN.json")
    if (
        data.digest(records) != frozen["dataset_digest"]
        or _sources() != frozen["source_digest"]
    ):
        raise ValueError("E2 campaign dataset or executable source changed")
    return records, frozen


def _plan(root, records, frozen):
    plan = _read(root / "E2" / "E2_PLAN.json")
    parent = _read(root / "parent.json")
    if (
        plan["dataset_digest"] != data.digest(records)
        or plan["source_digest"] != frozen["source_digest"]
        or plan["parent_model_digest"] != data.digest(parent)
        or plan["training"] != TRAINING
        or plan["training_mode"] != "trajectory"
        or plan["max_steps"] != MAX_STEPS
        or plan["b_tasks"]
        != campaign.panel([r for r in records if r["split"] == "selection"])
        or plan["c_tasks"]
        != campaign.panel([r for r in records if r["split"] == "confirmation"])
    ):
        raise ValueError("E2 frozen plan binding changed")
    return plan, parent


def _training_plan(root, name, plan):
    result = _read(root / "plans" / (name + ".json"))
    rows = _read(root / "plans" / (name + ".records.json"))
    if (
        result["e2_plan_digest"] != data.digest(plan)
        or result["source_digest"] != plan["source_digest"]
        or result["dataset_digest"] != plan["dataset_digest"]
        or result["training"] != TRAINING
        or result["training_mode"] != "trajectory"
        or result["training_records_digest"] != data.digest(rows)
        or result["parent_model_digest"] != plan["parent_model_digest"]
        or result["train_sources"] != sorted({r["source_id"] for r in rows})
    ):
        raise ValueError("E2 corpus or training plan changed")
    return result, rows


def _collect(root, records, frozen):
    parent = _read(root / "parent.json")
    a = [r for r in records if r["split"] == "train"]
    plan = {
        "schema": "hepta.e2.frozen-plan.v1",
        "frozen_at_ns": time.time_ns(),
        "dataset_digest": data.digest(records),
        "source_digest": frozen["source_digest"],
        "parent_model_digest": data.digest(parent),
        "training": TRAINING,
        "training_mode": "trajectory",
        "max_steps": MAX_STEPS,
        "inference": parent["runtime"],
        "a_records_digest": data.digest(a),
        "original_tasks": len({r["task_id"] for r in a}),
        "original_sources": sorted({r["source_id"] for r in a}),
        "original_families": sorted({r["family_id"] for r in a}),
        "b_tasks": campaign.panel([r for r in records if r["split"] == "selection"]),
        "c_tasks": campaign.panel([r for r in records if r["split"] == "confirmation"]),
        "selection_rule": "highest B successes, lexicographic arm name breaks ties",
        "trajectory_protocol_context_confounds_controlled": False,
        "trajectory_repeats_correction_as_final_answer": True,
        "evaluation_protocol": "one JSON artifact per generation; full trajectory serialization may differ",
        "external_teacher_trajectories": False,
        "independent_e2": "BLOCKED",
        "production_eligible": False,
    }
    coding_sft.write_new(root / "E2" / "E2_PLAN.json", plan)
    collected = interaction.collect(
        a, parent, root, root / "E2" / "collection", max_steps=MAX_STEPS
    )
    if collected["status"] != "COMPLETE_DEVELOPMENT_COLLECTION":
        raise ValueError("E2 collection incomplete")
    original = {data.record_digest(r): r for r in a}
    for name in NAMES:
        rows = data.load_records(
            root / "E2" / "collection" / (name.removeprefix("e2_") + ".jsonl")
        )
        for row in rows:
            source = original[row["interaction"]["parent_record_digest"]]
            if any(
                row[key] != source[key]
                for key in (
                    "task_id",
                    "source_id",
                    "family_id",
                    "lineage_id",
                    "project_id",
                )
            ):
                raise ValueError("derived corpus changed original task/source identity")
        training = {
            "schema": "hepta.e2.training-plan.v1",
            "operation_id": name,
            "frozen_at_ns": time.time_ns(),
            "training_owner": "isolated-e2-trainer-process",
            "evaluation_owner": "separate-e2-evaluator-process",
            "e2_plan_digest": data.digest(plan),
            "dataset_digest": plan["dataset_digest"],
            "source_digest": plan["source_digest"],
            "parent_model_digest": data.digest(parent),
            "training_records_digest": data.digest(rows),
            "training_mode": "trajectory",
            "training": TRAINING,
            "inference": parent["runtime"],
            "train_sources": sorted({r["source_id"] for r in rows}),
            "collection_result_sha256": coding_sft.file_hash(
                root / "E2" / "collection" / "RESULT.json"
            ),
            "independent_e2": "BLOCKED",
            "production_eligible": False,
        }
        coding_sft.write_new(root / "plans" / (name + ".records.json"), rows)
        coding_sft.write_new(root / "plans" / (name + ".json"), training)
    return {
        "status": "E2_COLLECTION_AND_TRAINING_PLANS_FROZEN",
        "collection": collected,
    }


def _candidate(root, name, plan):
    training_plan, _ = _training_plan(root, name, plan)
    manifest = _read(root / "models" / name / "manifest.json")
    model_digest = coding_sft.verify_model(manifest, root)
    trained = _read(root / "models" / name / "training.json")
    if (
        trained["status"] != "COMPLETE"
        or trained["candidate_model_digest"] != model_digest
        or trained["parent_model_digest"] != plan["parent_model_digest"]
        or trained["plan_digest"] != data.digest(training_plan)
        or trained["steps"] != TRAINING["steps"]
        or trained["mode"] != "trajectory"
        or trained["records_digest"] != training_plan["training_records_digest"]
    ):
        raise ValueError("E2 training receipt/model binding changed")
    return manifest, model_digest


def _snapshot(root, plan):
    result = {}
    expected_tasks = [(r["task_id"], r["task_digest"]) for r in plan["b_tasks"]]
    for name in NAMES:
        _, model_digest = _candidate(root, name, plan)
        model_path = root / "models" / name / "manifest.json"
        training_path = root / "models" / name / "training.json"
        directory = root / "E2" / "B" / name
        b = _read(directory / "RESULT.json")
        if (
            b["status"] != "COMPLETE_DEVELOPMENT_EVALUATION"
            or b["model_digest"] != model_digest
            or b["denominator"] != len(expected_tasks)
            or b["max_model_calls_per_task"] != plan["max_steps"]
            or [(r["task_id"], r["record_digest"]) for r in b["tasks"]]
            != expected_tasks
            or any(type(r["success"]) is not bool for r in b["tasks"])
            or b["successes"] != sum(r["success"] for r in b["tasks"])
        ):
            raise ValueError(
                "E2 B receipt is incomplete or bound to different tasks/model"
            )
        evidence = {
            str(p.relative_to(directory)): coding_sft.file_hash(p)
            for p in sorted(directory.rglob("*.json"))
        }
        result[name] = {
            "model_digest": model_digest,
            "manifest_sha256": coding_sft.file_hash(model_path),
            "training_receipt_sha256": coding_sft.file_hash(training_path),
            "b_result_sha256": coding_sft.file_hash(directory / "RESULT.json"),
            "b_evidence_digest": data.digest(evidence),
            "b_successes": b["successes"],
        }
    return result


def run(operation, root, dataset, name=None):
    root = Path(root)
    records, frozen = _checked(root, dataset)
    if operation == "collect":
        return _collect(root, records, frozen)
    if operation in ("train", "evaluate") and name not in NAMES:
        raise ValueError("an explicit E2 arm name is required")
    plan, parent = _plan(root, records, frozen)
    if operation == "train":
        training_plan, corpus = _training_plan(root, name, plan)
        model, receipt = coding_sft.train(
            corpus, parent, root, training_plan, "trajectory", name
        )
        return {"name": name, "model_digest": data.digest(model), "training": receipt}
    if operation == "evaluate":
        manifest, _ = _candidate(root, name, plan)
        return interaction.evaluate(
            manifest,
            root,
            [r for r in records if r["split"] == "selection"],
            root / "E2" / "B" / name,
            max_steps=plan["max_steps"],
        )
    if operation not in ("select", "confirm"):
        raise ValueError("unknown E2 operation")
    observed = _snapshot(root, plan)
    selected = min(NAMES, key=lambda arm: (-observed[arm]["b_successes"], arm))
    path = root / "E2" / "FROZEN_SELECTION.json"
    if operation == "select":
        if (root / "E2" / "C").exists():
            raise ValueError("cannot select after E2 C execution began")
        choice = {
            "schema": "hepta.e2.frozen-selection.v1",
            "frozen_at_ns": time.time_ns(),
            "e2_plan_digest": data.digest(plan),
            "dataset_digest": plan["dataset_digest"],
            "source_digest": plan["source_digest"],
            "models_and_b_receipts": observed,
            "selected_arm": selected,
            "rule": plan["selection_rule"],
            "independent_e2": "BLOCKED",
            "production_eligible": False,
        }
        coding_sft.write_new(path, choice)
        return choice
    choice = _read(path)
    if (
        choice["e2_plan_digest"] != data.digest(plan)
        or choice["dataset_digest"] != plan["dataset_digest"]
        or choice["source_digest"] != plan["source_digest"]
        or choice["selected_arm"] != selected
        or choice["models_and_b_receipts"] != observed
    ):
        raise ValueError("frozen E2 choice/model/B evidence changed before C")
    c = [r for r in records if r["split"] == "confirmation"]
    results = {}
    for arm in NAMES:
        if _snapshot(root, plan) != observed:
            raise ValueError("E2 model/B evidence changed during C readout")
        outcome = interaction.evaluate(
            _read(root / "models" / arm / "manifest.json"),
            root,
            c,
            root / "E2" / "C" / arm,
            max_steps=plan["max_steps"],
        )
        results[arm] = {"selected_before_C": arm == selected, "result": outcome}
    result = {
        "schema": "hepta.e2.c-readout.v1",
        "selection_sha256": coding_sft.file_hash(path),
        "results": results,
        "independent_e2": "BLOCKED",
        "production_eligible": False,
    }
    coding_sft.write_new(root / "E2" / "C_READOUT.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--operation",
        required=True,
        choices=("collect", "train", "evaluate", "select", "confirm"),
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--name", choices=NAMES)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.operation, args.root, args.dataset, args.name), ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
