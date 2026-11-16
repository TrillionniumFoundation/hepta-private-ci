"""Frozen repository-contract experiment stages; C stays sealed until B is saved."""

import argparse
import copy
import json
from pathlib import Path
import re
import time

from . import adapter_mix_v2, coding_sft, data, repo_execution, repo_interaction_v2

TRAINED = (
    "final_answer",
    "trajectory",
    "specialist_numeric",
    "specialist_structured",
    "e2_shadow",
    "e2_controlled",
)
EVALUATED = ("parent", "retrieval", *TRAINED, "integrated")
ROUTED = ("specialist_numeric", "specialist_structured", "final_answer")


def read(path):
    return json.loads(Path(path).read_text())


def sources():
    directory = Path(__file__).parent
    return {p.name: coding_sft.file_hash(p) for p in sorted(directory.glob("*.py"))}


def fixture_inventory():
    return {
        str(p.relative_to(repo_execution.FIXTURES)): coding_sft.file_hash(p)
        for p in sorted(repo_execution.FIXTURES.rglob("*"))
        if p.is_file()
    }


def guard(root):
    root = Path(root)
    frozen = read(root / "FREEZE.json")
    if (
        sources() != frozen["source_inventory"]
        or fixture_inventory() != frozen["fixture_inventory"]
    ):
        raise ValueError("frozen source or repository fixtures changed")
    for relative, expected in frozen["input_files"].items():
        if coding_sft.file_hash(root / relative) != expected:
            raise ValueError("frozen input changed: " + relative)
    return frozen


def records(root, panel="open"):
    return data.load_records(Path(root) / "inputs" / panel / "records.jsonl")


def manifest(root, name):
    return read(
        Path(root)
        / (
            "parent.json"
            if name in ("parent", "retrieval")
            else "models/" + name + "/manifest.json"
        )
    )


def panel(rows):
    return [
        {
            "task_id": r["task_id"],
            "source_id": r["source_id"],
            "task_digest": data.digest(r),
        }
        for r in rows
    ]


def make_plan(root, name, chosen, mode):
    root = Path(root)
    frozen, parent = guard(root), manifest(root, "parent")
    b = [r for r in records(root) if r["split"] == "selection"]
    c_meta = read(root / "inputs/confirmation/META.json")
    plan = {
        "schema": "hepta.e6.plan.v1",
        "operation_id": "repository-v2-" + name,
        "evidence_scope": "engineering",
        "frozen_at_ns": time.time_ns(),
        "training_owner": "repository-v2-trainer",
        "evaluation_owner": "repository-v2-evaluator",
        "parent_model_digest": data.digest(parent),
        "train_sources": sorted({r["source_id"] for r in chosen}),
        "training_records_digest": data.digest(chosen),
        "training_mode": mode,
        "source_digest": data.digest(frozen["source_inventory"]),
        "b_tasks": panel(b),
        "c_tasks": [
            {k: row[k] for k in ("task_id", "source_id", "task_digest")}
            for row in c_meta["task_metadata"]
        ],
        "baseline_models": {
            "parent": data.digest(parent),
            "retrieval": data.digest(parent),
        },
        "baseline_scope": "Frozen model and A-only retrieval; authored reference patches validate contracts and are unavailable as a task-independent policy.",
        "minimum_gain": 0.0,
        "cold_timeout_seconds": 300,
        "training": frozen["training"],
        "inference": parent["runtime"],
        "selection_outcome": "first attempt business success; group macro average by source",
        "independent_confirmation_qualified": False,
        "external_teacher_trajectories": False,
    }
    coding_sft.write_new(root / "plans" / (name + ".json"), plan)
    coding_sft.write_new(root / "plans" / (name + ".records.json"), chosen)
    return plan


def prepare(root, materials):
    root = Path(root)
    ab = records(root)
    c_meta = read(root / "inputs/confirmation/META.json")
    from .test_chat_protocol import check_native_tokenizer
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        materials, local_files_only=True, trust_remote_code=False
    )
    protocol = check_native_tokenizer(tokenizer)
    inputs = {
        str(p.relative_to(root)): coding_sft.file_hash(p)
        for p in (root / "inputs").rglob("*")
        if p.is_file()
    }
    frozen = {
        "schema": "hepta.repository-study.freeze.v2",
        "created_at_ns": time.time_ns(),
        "source_inventory": sources(),
        "fixture_inventory": fixture_inventory(),
        "input_files": inputs,
        "training": {
            "steps": 64,
            "sequence_tokens": 1536,
            "rank": 4,
            "learning_rate": 0.0003,
            "seed": 1729,
        },
        "protocol_preflight": protocol,
        "open_admission": data.validate_records(ab),
        "confirmation_metadata": c_meta,
        "c_answers_inspected_by_trainer": False,
        "shared_controller_custody": True,
        "independent_scientific_qualification": "BLOCKED",
        "e1_primary": "success within two observed-feedback attempts",
        "e1_secondary": "first-attempt function-contract success",
        "e2_maximum_attempts": 2,
        "e3_scope": "same-base specialists trained from authored references; external multi-teacher test unavailable",
        "routing_model_order": ROUTED,
        "routing_tie_priority": [0, 1, 2],
        "routing_all_failed_slot": 2,
        "source_growth_units": ["project_id", "source_id"],
        "requested_scales": [1, 4, 16, 64],
        "minimum_adoption_gain": 0.0,
        "production_eligible": False,
    }
    coding_sft.write_new(root / "FREEZE.json", frozen)
    coding_sft.prepare_base(
        materials,
        root,
        {
            "threads": 2,
            "max_input_tokens": 4096,
            "max_new_tokens": 256,
            "message_protocol": "native_chat_v2",
            "seed": 1729,
        },
    )
    a = [r for r in ab if r["split"] == "train"]
    for name in TRAINED[:4]:
        chosen = (
            [r for r in a if r.get("task_domain") == name.removeprefix("specialist_")]
            if name.startswith("specialist_")
            else a
        )
        if not chosen:
            raise ValueError("specialist domain has no authorized A records")
        make_plan(
            root, name, chosen, "trajectory" if name == "trajectory" else "final_answer"
        )
    return {
        "status": "FROZEN",
        "A": len(a),
        "B": len(ab) - len(a),
        "C": c_meta["records"],
        "source_digest": data.digest(sources()),
    }


def train(root, name):
    guard(root)
    plan = read(Path(root) / "plans" / (name + ".json"))
    chosen = read(Path(root) / "plans" / (name + ".records.json"))
    _, receipt = coding_sft.train(
        chosen,
        manifest(root, "parent"),
        root,
        plan,
        plan["training_mode"],
        Path(root) / "models" / name,
    )
    guard(root)
    return {
        "name": name,
        "status": receipt["status"],
        "model_digest": receipt["candidate_model_digest"],
        "cost": receipt["cost"],
    }


def collect(root):
    guard(root)
    a = [r for r in records(root) if r["split"] == "train"]
    cohorts, receipt = repo_interaction_v2.collect(
        a, manifest(root, "parent"), root, Path(root) / "E2_COLLECTION"
    )
    for name, chosen in cohorts.items():
        make_plan(root, "e2_" + name, chosen, "trajectory")
    return receipt


def retrieve(a, rows):
    """A fixed lexical retrieval rule with only A examples and their own answers."""
    words = lambda text: set(re.findall(r"\w+", text.lower()))
    result = []
    for record in rows:
        query = words(record["task"]["input"])
        chosen = min(
            a, key=lambda r: (-len(query & words(r["task"]["input"])), r["record_id"])
        )
        item = copy.deepcopy(record)
        prompt = (
            "Example task:\n"
            + chosen["task"]["input"]
            + "\nExample JSON edit:\n"
            + chosen["final_answer"]
            + "\nCurrent task:\n"
            + record["task"]["input"]
        )
        item["task"]["input"] = prompt
        item["task"]["messages"] = [
            {"role": "user", "content": prompt},
            *copy.deepcopy(record["task"].get("messages", [])[1:]),
        ]
        item["retrieval_record_id"] = chosen["record_id"]
        result.append(item)
    return result


def evaluate(root, name, panel_name="B"):
    guard(root)
    if panel_name not in ("A", "B"):
        raise ValueError("C requires the confirmation coordinator")
    ab = records(root)
    selected = [
        r for r in ab if r["split"] == ("train" if panel_name == "A" else "selection")
    ]
    prompts = (
        retrieve([r for r in ab if r["split"] == "train"], selected)
        if name == "retrieval"
        else None
    )
    result = repo_interaction_v2.evaluate(
        manifest(root, name),
        root,
        selected,
        Path(root) / "evaluation" / panel_name / name,
        maximum=1 if panel_name == "A" else 2,
        prompt_records=prompts,
    )
    return {
        "name": name,
        "panel": panel_name,
        "tasks": result["tasks"],
        "first": result["first_attempt_successes"],
        "within_two": result["successes"],
        "cost": result["cost"],
    }


def mix(root):
    guard(root)
    _, receipt = adapter_mix_v2.mix(
        [manifest(root, name) for name in ROUTED[:2]],
        root,
        Path(root) / "models/integrated",
    )
    return receipt


def features(root, selected, output):
    parent = manifest(root, "parent")
    binding = data.digest(
        {
            "model": data.digest(parent),
            "method": "input-only mean last hidden first64 L2",
        }
    )
    predictor = coding_sft.load_predictor(parent, root)
    start, cpu = time.perf_counter(), time.process_time()
    result = []
    try:
        for record in selected:
            result.append(
                {
                    "task_id": record["task_id"],
                    "source_id": record["source_id"],
                    "project_id": record["project_id"],
                    "lineage_id": record["lineage_id"],
                    "family_id": record["family_id"],
                    "observation_digest": data.digest(record["task"]["input"]),
                    "feature_binding_digest": binding,
                    "features": predictor.encode_features(record, dimensions=64),
                }
            )
    finally:
        predictor.close()
    receipt = {
        "rows": result,
        "base_model_digest": data.digest(parent),
        "binding": binding,
        "cost": {
            "wall_seconds": time.perf_counter() - start,
            "cpu_seconds": time.process_time() - cpu,
            "model_calls": len(result),
            "complete": False,
        },
    }
    coding_sft.write_new(output, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=(
            "prepare",
            "train",
            "collect",
            "evaluate-a",
            "evaluate-b",
            "mix",
            "select",
            "confirm",
            "cold",
        ),
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--materials")
    parser.add_argument("--name")
    args = parser.parse_args()
    root = Path(args.root)
    from .stage_resources_v2 import StageResources

    meter = StageResources(root, args.operation, args.name)
    status = "FAILED"
    try:
        if args.operation == "prepare":
            result = prepare(root, args.materials)
        elif args.operation == "train":
            result = train(root, args.name)
        elif args.operation == "collect":
            result = collect(root)
        elif args.operation.startswith("evaluate-"):
            result = evaluate(
                root, args.name, "A" if args.operation.endswith("-a") else "B"
            )
        elif args.operation == "mix":
            result = mix(root)
        else:
            from . import study_v2_confirm

            result = (
                getattr(study_v2_confirm, args.operation)(root, args.name)
                if args.operation in ("cold", "confirm")
                else getattr(study_v2_confirm, args.operation)(root)
            )
        status = "COMPLETE"
        print(json.dumps(result, sort_keys=True), flush=True)
    finally:
        meter.finish(status)


if __name__ == "__main__":
    main()
