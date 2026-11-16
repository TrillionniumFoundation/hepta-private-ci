"""Frozen CPU development campaign; curated data cannot gain independent status."""

import argparse
import copy
import json
import math
import os
from pathlib import Path
import re
import time

from . import coding_sft, data
from .data_builder import oracle_answer


def json_value_domain(answer):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(value)

    try:
        value = json.loads(answer, object_pairs_hook=pairs, parse_constant=invalid)
        if (
            isinstance(value, dict)
            and value
            and all(
                type(v) in (int, float, bool)
                and (type(v) is not float or math.isfinite(v))
                for v in value.values()
            )
        ):
            return int(any(type(v) is bool for v in value.values()))
    except (ValueError, TypeError):
        pass
    return 2


def panel(records):
    return [
        {
            "task_id": r["task_id"],
            "source_id": r["source_id"],
            "task_digest": data.digest(r),
        }
        for r in records
    ]


def guard(root, dataset):
    """Keep all later stages bound to the dataset and executable source freeze."""
    records = data.load_records(dataset)
    frozen = json.loads((Path(root) / "CAMPAIGN.json").read_text())
    actual = {
        p.name: coding_sft.file_hash(p)
        for p in sorted(Path(__file__).parent.glob("*.py"))
    }
    if (
        data.digest(records) != frozen["dataset_digest"]
        or data.digest(actual) != frozen["source_digest"]
    ):
        raise ValueError("campaign dataset or executable source changed after freeze")
    return records


def frozen_plan(records, selected, parent, root, name, source_digest, steps):
    b = [r for r in records if r["split"] == "selection"]
    c = [r for r in records if r["split"] == "confirmation"]
    oracle = data.digest(
        {
            "kind": "deterministic_reference",
            "implementation": coding_sft.file_hash(
                Path(__file__).with_name("data_builder.py")
            ),
        }
    )
    parent_digest = data.digest(parent)
    plan = {
        "schema": "hepta.e6.plan.v1",
        "operation_id": name,
        "evidence_scope": "engineering",
        "frozen_at_ns": time.time_ns(),
        "training_owner": "isolated-trainer-process",
        "evaluation_owner": "separate-evaluator-process",
        "parent_model_digest": parent_digest,
        "train_sources": sorted({r["source_id"] for r in selected}),
        "b_tasks": panel(b),
        "c_tasks": panel(c),
        "baseline_models": {"parent": parent_digest, "reference": oracle},
        "minimum_gain": 0.0,
        "cold_timeout_seconds": 120,
        "dataset_digest": data.digest(records),
        "source_digest": source_digest,
        "training_records_digest": data.digest(selected),
        "training_mode": "trajectory" if name == "trajectory" else "final_answer",
        "training": {
            "steps": steps,
            "sequence_tokens": 256,
            "rank": 4,
            "learning_rate": 0.0003,
            "seed": 1729,
        },
        "inference": parent["runtime"],
        "independent_confirmation_qualified": False,
        "external_teacher_trajectories": False,
        "trajectory_protocol_context_confounds_controlled": False,
    }
    coding_sft.write_new(Path(root) / "plans" / (name + ".json"), plan)
    return plan


def score(predictor, records, arm, plan):
    rows, outputs = [], []
    for record in records:
        if arm == "reference":
            start = time.perf_counter()
            output = {
                "answer": oracle_answer(record),
                "input_tokens": 0,
                "output_tokens": 0,
                "elapsed_seconds": time.perf_counter() - start,
                "loaded_model_digest": plan["baseline_models"]["reference"],
                "kind": "deterministic_reference_not_language_model",
            }
        else:
            output = predictor.predict(record)
        verified = data.verify_answer(record, output["answer"])
        outputs.append(
            {
                "task_id": record["task_id"],
                "arm": arm,
                "output": output,
                "verification": verified,
            }
        )
        rows.append(
            {
                "arm": arm,
                "task_id": record["task_id"],
                "source_id": record["source_id"],
                "task_digest": data.digest(record),
                "loaded_model_digest": output["loaded_model_digest"],
                "success": verified["success"],
                "output_digest": data.digest(output),
            }
        )
    return rows, outputs


def evaluate(root, name, dataset):
    root = Path(root)
    records = guard(root, dataset)
    plan = json.loads((root / "plans" / (name + ".json")).read_text())
    if data.digest(records) != plan["dataset_digest"]:
        raise ValueError("evaluation dataset changed since freeze")
    parent = json.loads((root / "parent.json").read_text())
    candidate = json.loads((root / "models" / name / "manifest.json").read_text())
    b = [r for r in records if r["split"] == "selection"]
    start = time.time_ns()
    rows, outputs = [], []
    for arm, manifest in (
        ("parent", parent),
        ("candidate", candidate),
        ("reference", None),
    ):
        predictor = coding_sft.load_predictor(manifest, root) if manifest else None
        try:
            observed, raw = score(predictor, b, arm, plan)
            rows.extend(observed)
            outputs.extend(raw)
        finally:
            if predictor:
                predictor.close()
    receipt = {
        "status": "COMPLETE",
        "owner": plan["evaluation_owner"],
        "pid": os.getpid(),
        "started_at_ns": start,
        "completed_at_ns": time.time_ns(),
        "plan_digest": data.digest(plan),
        "rows": rows,
        "independent_control_authenticated": False,
        "raw_outputs": outputs,
    }
    coding_sft.write_new(root / "models" / name / "B.json", receipt)
    return {
        "operation": name,
        "B": {
            arm: sum(r["success"] for r in rows if r["arm"] == arm)
            for arm in ("parent", "candidate", "reference")
        },
        "tasks": len(b),
    }


def retrieve(records, record):
    words = lambda value: set(re.findall(r"\w+", value.lower()))
    query = words(record["task"]["input"])
    chosen = min(
        records,
        key=lambda row: (-len(words(row["task"]["input"]) & query), row["record_id"]),
    )
    result = copy.deepcopy(record)
    result["task"]["input"] = (
        "Example:\n"
        + chosen["task"]["input"]
        + "\n"
        + chosen["final_answer"]
        + "\nNew task:\n"
        + record["task"]["input"]
    )
    return result, chosen["record_id"]


def after_training(root, dataset):
    root = Path(root)
    records = guard(root, dataset)
    parent = json.loads((root / "parent.json").read_text())
    a = [r for r in records if r["split"] == "train"]
    probes = [r for r in records if r["split"] == "selection"]
    predictor = coding_sft.load_predictor(parent, root)
    retrieval, features = [], []
    binding = data.digest(
        {
            "parent": data.digest(parent),
            "encoding": "input-only-last-hidden-mean-first64-L2-v1",
        }
    )
    for record in records:
        row = copy.deepcopy(record)
        encode_started, encode_cpu = time.perf_counter(), time.process_time()
        values = predictor.encode_features(record, dimensions=64)
        encode_cost = {
            "wall_seconds": time.perf_counter() - encode_started,
            "cpu_seconds": time.process_time() - encode_cpu,
            "scope": "input tokenization and frozen hidden state; excludes model load",
        }
        available = int(time.time())
        row.update(
            target=json_value_domain(record["final_answer"]),
            n_classes=3,
            target_name="required_result_value_domain",
        )
        row["features"] = {
            "values": values,
            "binding": binding,
            "available_at": available,
            "preaction_at": available,
        }
        row["upstream_cost"] = {
            "feature_encoding": {
                "shared_identity": record["record_id"],
                "measured_once": encode_cost,
            },
            "complete": False,
        }
        features.append(row)
    for record in probes:
        augmented, retrieved = retrieve(a, record)
        output = predictor.predict(augmented)
        verification = data.verify_answer(record, output["answer"])
        retrieval.append(
            {
                "task_id": record["task_id"],
                "retrieved_record": retrieved,
                "output": output,
                "verification": verification,
            }
        )
    predictor.close()
    coding_sft.write_new(root / "RETRIEVAL.json", retrieval)
    registry, teacher_rows = {}, []
    for name in ("numeric_specialist", "boolean_specialist"):
        manifest = json.loads((root / "models" / name / "manifest.json").read_text())
        training = json.loads((root / "models" / name / "training.json").read_text())
        predictor = coding_sft.load_predictor(manifest, root)
        receipt = {
            "teacher_id": name,
            "kind": "same_base_domain_specialist",
            "model_digest": data.digest(manifest),
            "base_model_digest": data.digest(parent),
            "training_receipt_sha256": coding_sft.file_hash(
                root / "models" / name / "training.json"
            ),
            "training_source_ids": training["training_source_ids"],
            "outputs": {},
            "external_teacher": False,
        }
        prepared = []
        for row in [r for r in features if r["split"] == "train"]:
            output = predictor.predict(row)
            receipt["outputs"][row["task_id"]] = {
                "output": output["answer"],
                "teacher_target": json_value_domain(output["answer"]),
                "raw": output,
            }
            copied = copy.deepcopy(row)
            copied.update(
                record_id=row["record_id"] + "/" + name,
                teacher_id=name,
                model_digest=receipt["model_digest"],
                actual_output=output["answer"],
                teacher_target=json_value_domain(output["answer"]),
            )
            copied["upstream_cost"] = {
                "feature_encoding_ref": row["record_id"],
                "teacher_inference": {
                    key: output[key]
                    for key in ("input_tokens", "output_tokens", "elapsed_seconds")
                },
                "teacher_training_ref": str(root / "models" / name / "training.json"),
                "complete": False,
            }
            prepared.append(copied)
        predictor.close()
        path = root / "teachers" / (name + ".json")
        coding_sft.write_new(path, receipt)
        registry[name] = {
            "receipt_path": str(path),
            "receipt_sha256": coding_sft.file_hash(path),
            "model_digest": receipt["model_digest"],
        }
        for row in prepared:
            row["teacher_output_receipt_sha256"] = registry[name]["receipt_sha256"]
        teacher_rows.extend(prepared)
    coding_sft.write_new(root / "FEATURES.json", features + teacher_rows)
    coding_sft.write_new(root / "TEACHER_REGISTRY.json", registry)
    coding_sft.write_new(
        root / "FEATURE_BINDING.json",
        {
            "digest": binding,
            "model": data.digest(parent),
            "target": "required_result_value_domain",
            "scope": "curated maintenance type-routing diagnostic",
        },
    )
    return {
        "features": len(features),
        "teachers": len(registry),
        "retrieval_tasks": len(retrieval),
        "feature_binding": binding,
    }


def confirm(root, dataset):
    """Read C only after both E1 decisions and composition selections are durable."""
    root = Path(root)
    for name in ("final_answer", "trajectory"):
        if not (root / "E6" / name / "DECISION.json").is_file():
            raise ValueError("C readout requires frozen E1 decisions")
    if not (root / "composition/FROZEN_SELECTIONS.json").is_file():
        raise ValueError("C readout requires frozen composition choices")
    records = guard(root, dataset)
    a = [r for r in records if r["split"] == "train"]
    c = [r for r in records if r["split"] == "confirmation"]
    result = []
    for arm in ("parent", "retrieval", "final_answer", "trajectory"):
        path = (
            root / "parent.json"
            if arm in ("parent", "retrieval")
            else root / "models" / arm / "manifest.json"
        )
        predictor = coding_sft.load_predictor(json.loads(path.read_text()), root)
        for record in c:
            actual = retrieve(a, record)[0] if arm == "retrieval" else record
            output = predictor.predict(actual)
            result.append(
                {
                    "task_id": record["task_id"],
                    "arm": arm,
                    "output": output,
                    "verification": data.verify_answer(record, output["answer"]),
                }
            )
        predictor.close()
    coding_sft.write_new(root / "E1_C_READOUT.json", result)
    return {
        arm: sum(r["verification"]["success"] for r in result if r["arm"] == arm)
        for arm in ("parent", "retrieval", "final_answer", "trajectory")
    }


def prepare(root, materials, dataset, source_digest, steps):
    records = data.load_records(dataset)
    observed = {
        p.name: coding_sft.file_hash(p)
        for p in sorted(Path(__file__).parent.glob("*.py"))
    }
    if data.digest(observed) != source_digest:
        raise ValueError("prepare requires the actual executable source digest")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    parent = coding_sft.prepare_base(
        materials,
        root,
        {"threads": 2, "max_input_tokens": 512, "max_new_tokens": 48, "device": "cpu"},
    )
    a = [r for r in records if r["split"] == "train"]
    for name in (
        "final_answer",
        "trajectory",
        "numeric_specialist",
        "boolean_specialist",
    ):
        selected = (
            a
            if name in ("final_answer", "trajectory")
            else [
                r
                for r in a
                if json_value_domain(r["final_answer"])
                == int(name == "boolean_specialist")
            ]
        )
        frozen_plan(records, selected, parent, root, name, source_digest, steps)
        coding_sft.write_new(root / "plans" / (name + ".records.json"), selected)
    composition = {
        "schema": "hepta.composition-plan.v1",
        "evidence_scope": "engineering",
        "max_train_mac": 1000000,
        "max_examples": 224,
        "passes": 32,
        "learning_rate": 0.05,
        "cells": 4,
        "active": 2,
        "classes": 3,
        "seeds": [1729],
        "source_digest": source_digest,
        "feature_recipe": "input-only-last-hidden-mean-first64-L2-v1",
        "target_name": "required_result_value_domain",
        "frozen_at_ns": time.time_ns(),
    }
    coding_sft.write_new(root / "COMPOSITION_PLAN.json", composition)
    coding_sft.write_new(
        root / "CAMPAIGN.json",
        {
            "schema": "hepta.six-experiments.campaign.v1",
            "dataset_digest": data.digest(records),
            "source_digest": source_digest,
            "observed_at_ns": time.time_ns(),
            "admission": data.validate_records(records),
            "independent_experiment_qualification": False,
        },
    )
    return {"parent": data.digest(parent), "plans": 4, "root": str(root)}


def e6(root, dataset, name):
    from .adoption import execute

    root = Path(root)
    records = guard(root, dataset)
    plan = json.loads((root / "plans" / (name + ".json")).read_text())
    c = [r for r in records if r["split"] == "confirmation"]
    request = {
        "plan": plan,
        "artifact_root": str(root),
        "c_tasks": [{**entry, "record": record} for entry, record in zip(panel(c), c)],
    }
    for key, path in (
        ("parent", root / "parent.json"),
        ("candidate", root / "models" / name / "manifest.json"),
        ("training", root / "models" / name / "training.json"),
        ("evaluation", root / "models" / name / "B.json"),
    ):
        request[key] = json.loads(path.read_text())
    coding_sft.write_new(root / "E6" / (name + "-request.json"), request)
    result = execute(request, root / "E6" / name)
    return {
        "operation": name,
        "status": result["status"],
        "model_decision": result.get("model_decision"),
        "independent_e6_status": result.get("independent_e6_status"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=("prepare", "train", "evaluate", "after", "e6", "compose", "confirm"),
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument(
        "--name",
        choices=(
            "final_answer",
            "trajectory",
            "numeric_specialist",
            "boolean_specialist",
        ),
    )
    parser.add_argument("--materials")
    parser.add_argument("--source-digest")
    parser.add_argument("--steps", type=int, default=32)
    args = parser.parse_args()
    root = Path(args.root)
    if args.operation == "prepare":
        result = prepare(
            root, args.materials, args.dataset, args.source_digest, args.steps
        )
    elif args.operation == "train":
        plan = json.loads((root / "plans" / (args.name + ".json")).read_text())
        records = json.loads(
            (root / "plans" / (args.name + ".records.json")).read_text()
        )
        parent = json.loads((root / "parent.json").read_text())
        model, receipt = coding_sft.train(
            records, parent, root, plan, plan["training_mode"], args.name
        )
        result = {
            "operation": args.name,
            "status": receipt["status"],
            "model_digest": data.digest(model),
            "parameter_change": receipt["parameter_change"],
            "cost": receipt["cost"],
        }
    elif args.operation == "evaluate":
        result = evaluate(root, args.name, args.dataset)
    elif args.operation == "after":
        result = after_training(root, args.dataset)
    elif args.operation == "e6":
        result = e6(root, args.dataset, args.name)
    elif args.operation == "confirm":
        result = confirm(root, args.dataset)
    else:
        from .composition import run

        guard(root, args.dataset)
        binding = json.loads((root / "FEATURE_BINDING.json").read_text())["digest"]
        result = run(
            json.loads((root / "FEATURES.json").read_text()),
            json.loads((root / "COMPOSITION_PLAN.json").read_text()),
            root / "composition",
            binding,
            json.loads((root / "TEACHER_REGISTRY.json").read_text()),
        )
        result = {
            "status": result["status"],
            "E3": result["E3"],
            "E4": result["E4"],
            "E5": result["E5"],
        }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
