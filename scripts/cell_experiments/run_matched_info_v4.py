"""Freeze, fit and evaluate the four-arm matched-information E1 candidate."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import resource
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cell_experiments import (
    causal_probe_v3 as probe,
    data,
    matched_info_sft_v4 as matched,
    repo_execution,
)
from cell_experiments.coding_sft import file_hash, write_new
from cell_experiments.protocol_v3 import (
    ACTION_CONTRACT,
    feedback,
    prepare_record,
    require_prepared,
    verify_reference,
)
from cell_experiments.upstream_panel_v4 import load_panel

INPUTS_SHA256 = "691945696e7dad9ee0f3023617edf5ca0f787850c16f2623c08d14bc6cfbeaf3"
PARENT_DIGEST = "f63def6407c72c0b6e19647f5879582ab8ed35e4f6207352be931a9f417b0ff6"
MODES = ("frozen", "retrieval", "final_only", "all_actions")


def retrieval_copy(record, training):
    """Select by input overlap from the complete A-only reference index."""
    words = lambda text: set(re.findall(r"[a-z][a-z0-9_]+", text.lower()))
    query = words(record["task"]["input"])
    ranked = sorted(
        training,
        key=lambda row: (
            -len(query & words(row["task"]["input"]))
            / max(1, len(query | words(row["task"]["input"]))),
            row["task_id"],
        ),
    )
    selected = ranked[0]
    context = {
        "kind": "retrieved_verified_A_example",
        "task_id": selected["task_id"],
        "source_id": selected["source_id"],
        "input": selected["task"]["input"],
        "trajectory": selected["trajectory"],
        "final_answer": selected["final_answer"],
    }
    shown = copy.deepcopy(record)
    for key in ("action_protocol_v3", "protocol_reference_receipt", "verified_outcome"):
        shown.pop(key, None)
    prompt = shown["task"]["input"].removesuffix("\n" + ACTION_CONTRACT)
    shown["task"].update(
        input=prompt,
        messages=[
            {"role": "user", "content": prompt},
            {"role": "tool", "content": data.canonical(context).decode()},
        ],
    )
    return verify_reference(prepare_record(shown)), {
        "task_id": record["task_id"],
        "source_task_id": selected["task_id"],
        "source_record_digest": data.digest(selected),
        "context_digest": data.digest(context),
        "selector": "input-only lowercase-token Jaccard, task_id tie break",
        "retrieval_sources": "all six authorized A records",
        "top_k": 1,
    }


def freeze_candidate(artifact, root, output, commit):
    source = artifact / "research-sft-02/INPUTS.json"
    matched.require(
        file_hash(source) == INPUTS_SHA256, "retained original input context differs"
    )
    context = data._parse(source.read_bytes())
    training, parent = context["records"][:6], context["parent"]
    matched.require(data.digest(parent) == PARENT_DIGEST, "original parent differs")
    matched.require(
        all(
            row["split"] == "train" and row["authorization"]["training_allowed"]
            for row in training
        ),
        "authorized A-only corpus required",
    )
    repo_execution.load_catalog("open")
    upstream = load_panel()
    for row in upstream:
        matched.require(
            all(
                row["project_id"] != old["project_id"]
                and row["source"]["sha256"] != old["source"]["sha256"]
                for old in training
            ),
            "upstream source overlaps A",
        )
    panels = {"A_retention": training, "B_upstream": upstream}
    shown, bindings = {}, []
    for panel, records in panels.items():
        shown[panel] = []
        for record in records:
            prepared, binding = retrieval_copy(record, training)
            shown[panel].append(prepared)
            bindings.append({"panel": panel, **binding})
    output.mkdir(parents=True, exist_ok=False)
    payloads = {
        "TRAIN_RECORDS.json": training,
        "BASE_MODEL.json": parent,
        "PANELS.json": panels,
        "RETRIEVAL_PANELS.json": shown,
        "RETRIEVAL_BINDINGS.json": bindings,
    }
    for name, value in payloads.items():
        write_new(output / name, value)
    freeze = {
        "schema": "hepta.matched-information-e1-freeze.v1",
        "code_commit": commit,
        "created_at_ns": time.time_ns(),
        "base_model_digest": data.digest(parent),
        "train_records_digest": data.digest(training),
        "source_inventory": matched.source_inventory(root),
        "payloads": {name: file_hash(output / name) for name in payloads},
        "training_settings": matched.SETTINGS,
        "modes": MODES,
        "maximum_calls_per_task": 2,
        "maximum_new_tokens_per_call": 384,
        "input_context_limit": 4096,
        "planned_evaluation_calls": 96,
        "comparison": "same full transcript turn tuples, native serialization, common fresh LoRA initialization, optimizer schedule, padded positions and head positions; only loss weights differ",
        "retrieval": "full A-only trajectory information available to deterministic top-1 index; input tokens charged",
        "selection": "no selection from B; both candidates evaluated regardless of outcome",
        "training_data_sources": "original six authored A references, not independent teacher behavior",
        "upstream_tasks": 6,
        "upstream_projects": 3,
        "upstream_maintainer_groups": 2,
        "pretraining_overlap_known": False,
        "independent_users": 0,
        "external_teachers": 0,
        "independent_evaluator": False,
        "full_system_cost_known": False,
        "scientific_confirmation_qualified": False,
        "native_adoption": False,
    }
    write_new(output / "FREEZE.json", freeze)
    return freeze


def read_frozen(output, root):
    freeze = data._parse((output / "FREEZE.json").read_bytes())
    matched.require(
        freeze["source_inventory"] == matched.source_inventory(root),
        "source changed after prospective freeze",
    )
    matched.require(
        freeze["training_settings"] == matched.SETTINGS, "training settings changed"
    )
    for name, expected in freeze["payloads"].items():
        matched.require(
            file_hash(output / name) == expected, "frozen payload changed: " + name
        )
    return freeze


def audit_training(output, root, artifact, freeze):
    """Refuse comparison unless both fits consumed identical inputs and work shapes."""
    arms = {}
    for mode in ("final_only", "all_actions"):
        directory = output / "training" / mode
        manifest = data._parse((directory / "manifest.json").read_bytes())
        training = data._parse((directory / "TRAINING.json").read_bytes())
        steps = [
            data._parse(line)
            for line in (directory / "STEPS.jsonl").read_bytes().splitlines()
        ]
        identity = matched.verify_manifest(manifest, artifact, root)
        matched.require(
            training["status"] == "COMPLETE"
            and training["model_digest"] == identity
            and training["steps"] == len(steps) == matched.SETTINGS["steps"],
            "completed matched training originals required",
        )
        matched.require(
            manifest["freeze_digest"] == data.digest(freeze),
            "fit does not belong to this candidate freeze",
        )
        arms[mode] = {
            "model_digest": identity,
            "parameter_before": manifest["parameter_before"],
            "encoded_groups_digest": data.digest(
                data._parse((directory / "ENCODED_GROUPS.json").read_bytes())
            ),
            "step_shapes": [
                {
                    key: row[key]
                    for key in (
                        "step",
                        "task_id",
                        "group",
                        "input_group_digest",
                        "model_forwards",
                        "model_backwards",
                        "head_positions",
                        "input_tokens",
                        "padded_positions",
                    )
                }
                for row in steps
            ],
            "training_sha256": file_hash(directory / "TRAINING.json"),
            "manifest_sha256": file_hash(directory / "manifest.json"),
        }
        matched.require(
            arms[mode]["encoded_groups_digest"]
            == manifest["encoded_groups_digest"]
            == training["encoded_groups_digest"],
            "encoded training inputs differ from manifests",
        )
    comparable = ("parameter_before", "encoded_groups_digest", "step_shapes")
    matched.require(
        all(arms["final_only"][key] == arms["all_actions"][key] for key in comparable),
        "matched information, initialization or compute shapes differ",
    )
    result = {
        "status": "MATCHED",
        "freeze_digest": data.digest(freeze),
        "arms": arms,
        "physical_wall_energy_equality_claim": False,
        "scientific_gain_claim": False,
    }
    write_new(output / "TRAINING_COMPARISON.json", result)
    return result


def evaluate(artifact, root, output, freeze, mode):
    directory = output / "evaluation" / mode
    directory.mkdir(parents=True, exist_ok=False)
    write_new(
        directory / "STARTED.json",
        {
            "mode": mode,
            "freeze_digest": data.digest(freeze),
            "started_at_ns": time.time_ns(),
        },
    )
    panels = data._parse((output / "PANELS.json").read_bytes())
    shown = data._parse(
        (
            output / ("RETRIEVAL_PANELS.json" if mode == "retrieval" else "PANELS.json")
        ).read_bytes()
    )
    parent = data._parse((output / "BASE_MODEL.json").read_bytes())
    repo_execution.load_catalog("open")
    load_panel()
    before, cpu, children = (
        time.perf_counter(),
        time.process_time(),
        resource.getrusage(resource.RUSAGE_CHILDREN),
    )
    predictor = None
    rows = []
    try:
        if mode in ("frozen", "retrieval"):
            predictor = probe.Predictor(parent, artifact)
        else:
            manifest = data._parse(
                (output / "training" / mode / "manifest.json").read_bytes()
            )
            predictor = matched.Predictor(manifest, artifact, root)
        loaded = time.perf_counter()
        write_new(
            directory / "MODEL_LOADED.json",
            {
                "model_digest": predictor.model_digest,
                "generation_digest": predictor.generation_digest,
                "load_wall_seconds": loaded - before,
                "device": predictor.device_report,
            },
        )
        for panel, records in panels.items():
            for index, (original, visible) in enumerate(zip(records, shown[panel])):
                messages = require_prepared(visible)
                taskdir = directory / panel / str(index)
                taskdir.mkdir(parents=True, exist_ok=False)
                write_new(taskdir / "ORIGINAL_RECORD.json", original)
                write_new(taskdir / "VISIBLE_RECORD.json", visible)
                steps = []
                for attempt in range(2):
                    request = {
                        "record_id": visible["record_id"],
                        "task": {
                            "input": visible["task"]["input"],
                            "messages": copy.deepcopy(messages),
                        },
                    }
                    write_new(taskdir / f"REQUEST-{attempt}.json", request)
                    prediction = predictor.predict(request)
                    write_new(taskdir / f"OUTPUT-{attempt}.json", prediction)
                    matched.require(
                        prediction["loaded_model_digest"] == predictor.model_digest
                        and prediction["messages_sha256"] == data.digest(messages),
                        "observed model or history differs",
                    )
                    verification = data.verify_answer(visible, prediction["answer"])
                    write_new(taskdir / f"VERIFICATION-{attempt}.json", verification)
                    steps.append(
                        {
                            "attempt": attempt,
                            "request_digest": data.digest(request),
                            "output_digest": data.digest(prediction),
                            "verification": verification,
                            "model_call_cost": {
                                key: prediction[key]
                                for key in (
                                    "input_tokens",
                                    "output_tokens",
                                    "wall_seconds",
                                    "hit_output_limit",
                                )
                            },
                        }
                    )
                    messages.extend(
                        [
                            {"role": "assistant", "content": prediction["answer"]},
                            {"role": "tool", "content": feedback(verification)},
                        ]
                    )
                first, last = [step["verification"]["success"] for step in steps]
                result = {
                    "task_id": original["task_id"],
                    "panel": panel,
                    "first": first,
                    "last": last,
                    "selected": first or last,
                    "recovered": not first and last,
                    "regressed": first and not last,
                    "steps": steps,
                }
                write_new(taskdir / "RESULT.json", result)
                rows.append(result)
        predictor.close()
        predictor = None
        cost = {
            "wall_seconds": time.perf_counter() - before,
            "self_cpu_seconds": time.process_time() - cpu,
            "completed_children_cpu_seconds": resource.getrusage(
                resource.RUSAGE_CHILDREN
            ).ru_utime
            + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime
            - children.ru_utime
            - children.ru_stime,
            "model_calls": sum(len(row["steps"]) for row in rows),
            "verifier_calls": sum(len(row["steps"]) for row in rows),
            "input_tokens": sum(
                step["model_call_cost"]["input_tokens"]
                for row in rows
                for step in row["steps"]
            ),
            "output_tokens": sum(
                step["model_call_cost"]["output_tokens"]
                for row in rows
                for step in row["steps"]
            ),
            "energy_joules": None,
            "full_system_cost_known": False,
            "scope": "load, all attempts, business verifier children and close; do not sum nested windows",
        }
        result = {
            "status": "COMPLETE",
            "mode": mode,
            "freeze_digest": data.digest(freeze),
            "rows": rows,
            "by_panel": {
                panel: {
                    "tasks": len(records),
                    **{
                        key: sum(row[key] for row in rows if row["panel"] == panel)
                        for key in (
                            "first",
                            "last",
                            "selected",
                            "recovered",
                            "regressed",
                        )
                    },
                }
                for panel, records in panels.items()
            },
            "cost": cost,
            "training_from_B": False,
            "selection_from_B": False,
            "scientific_confirmation_qualified": False,
            "native_adoption": False,
        }
        write_new(directory / "RESULT.json", result)
        return result
    except BaseException as error:
        write_new(
            directory / "FAILED.json",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "completed_rows": len(rows),
                "wall_seconds": time.perf_counter() - before,
                "self_cpu_seconds": time.process_time() - cpu,
                "automatic_retry": False,
            },
        )
        raise
    finally:
        if predictor is not None:
            predictor.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage",
        choices=(
            "freeze",
            "train-final_only",
            "train-all_actions",
            "audit-training",
            *MODES,
        ),
    )
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-commit")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    artifact, output = args.artifact_root.resolve(strict=True), args.output.resolve()
    output.relative_to(artifact)
    if args.stage == "freeze":
        matched.require(
            bool(re.fullmatch(r"[0-9a-f]{40}", args.code_commit or "")),
            "published source commit required",
        )
        result = freeze_candidate(artifact, root, output, args.code_commit)
    else:
        freeze = read_frozen(output, root)
        if args.stage == "audit-training":
            result = audit_training(output, root, artifact, freeze)
        elif args.stage.startswith("train-"):
            mode = args.stage.removeprefix("train-")
            result = matched.train(
                data._parse((output / "TRAIN_RECORDS.json").read_bytes()),
                data._parse((output / "BASE_MODEL.json").read_bytes()),
                artifact,
                root,
                freeze,
                mode,
                output / "training" / mode,
            )
        else:
            comparison = data._parse((output / "TRAINING_COMPARISON.json").read_bytes())
            matched.require(
                comparison["status"] == "MATCHED"
                and comparison["freeze_digest"] == data.digest(freeze),
                "both matched fits must complete before evaluation",
            )
            result = evaluate(artifact, root, output, freeze, args.stage)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
