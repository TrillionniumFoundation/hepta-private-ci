"""Execute one immutable training or current-policy stage; never retry an unknown call."""

import argparse
import copy
import importlib
from pathlib import Path
import resource
import time

import layout_context as ctx

layout = importlib.import_module("layout_sft")


def admitted():
    freeze = ctx.read(ctx.HERE / "prepared/PROTOCOL.json")
    for name, expected in freeze["candidate_files"].items():
        layout.require(
            ctx.sha(ctx.HERE / name) == expected, "frozen candidate changed: " + name
        )
    for name, expected in freeze["original_input_files"].items():
        layout.require(
            ctx.sha(name) == expected, "frozen original evidence changed: " + name
        )
    layout.require(
        len(freeze["A_parent_reuse_files"]) == 32
        and all(
            freeze["original_input_files"].get(name) == expected
            for name, expected in freeze["A_parent_reuse_files"].items()
        ),
        "all reused A parent calls must be precommitted",
    )
    records = ctx.read(ctx.HERE / "prepared/DATASET.json")
    layout.require(
        ctx.data.digest(records) == freeze["train_records_digest"],
        "frozen records differ",
    )
    native, parent, tasks, inference = ctx.originals()
    return freeze, records, native, parent, tasks, inference


def panel_material(panel, freeze, binding_path):
    native, _, tasks, _ = ctx.originals()
    if panel == "A":
        return (
            native,
            tasks,
            {
                "panel": "A",
                "tasks_sha256": ctx.TASKS_SHA,
                "source": str(ctx.COLLECTION),
                "previously_exposed": True,
            },
        )
    layout.require(
        panel == "B3" and binding_path is not None, "released B3 binding required"
    )
    binding = ctx.read(binding_path)
    frozen = ctx.FIT_ROOT / "WEIGHTS_FROZEN.json"
    layout.require(
        ctx.sha(frozen) == binding["weights_frozen_sha256"], "B3 release weights differ"
    )
    weight_record = ctx.read(frozen)
    layout.require(
        weight_record["status"] == "MATCHED_AND_WEIGHTS_FROZEN"
        and int(binding["released_at_ns"]) > weight_record["created_at_ns"],
        "B3 must be released after both real fits",
    )
    for key in ("tasks", "protocol", "loader"):
        layout.require(
            ctx.sha(binding[key + "_path"]) == freeze["B3_commitment"][key + "_sha256"],
            "B3 precommitment differs: " + key,
        )
    layout.require(
        ctx.sha(binding["release_path"]) == binding["release_sha256"],
        "original coordinator release changed",
    )
    module = ctx.load(
        "layout_b3_native",
        Path(binding["loader_path"]),
        freeze["B3_commitment"]["loader_sha256"],
    )
    tasks = ctx.read(binding["tasks_path"])
    layout.require(len(tasks) == 4, "four sealed B3 tasks required")
    layout.require(
        not set(task["project_id"] for task in tasks) & set(ctx.PROJECTS),
        "new B3 projects must be distinct from A",
    )
    return (
        module,
        tasks,
        {
            "panel": "B3",
            "binding": binding,
            "binding_sha256": ctx.sha(binding_path),
            "tasks_sha256": ctx.sha(binding["tasks_path"]),
            "authenticated_external_custody": False,
            "base_pretraining_contamination_excluded": False,
        },
    )


def evaluate(panel, mode, commit, binding_path):
    freeze, _, _, parent, _, inference = admitted()
    verifier, tasks, provenance = panel_material(panel, freeze, binding_path)
    layout.require(
        mode in ("P", *layout.MODES) and not (panel == "A" and mode == "P"),
        "A original P calls are reused, not rerun",
    )
    policy_module = ctx.load(
        "layout_original_collection_policy",
        ctx.COLLECTION / "execution-code/run_students.py",
        ctx.POLICY_SHA,
    )
    output = ctx.WORK / "evaluation" / panel / mode
    output.mkdir(parents=True, exist_ok=False)
    ctx.write(
        output / "STARTED.json",
        {
            "source_commit": commit,
            "panel": panel,
            "mode": mode,
            "at_ns": time.time_ns(),
            "protocol_sha256": ctx.sha(ctx.HERE / "prepared/PROTOCOL.json"),
            "provenance": provenance,
            "planned_new_calls": 8 if mode == "P" else 12,
        },
    )
    started, cpu = time.perf_counter(), time.process_time()
    predictor, rows, attempted = None, [], 0
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        manifest = (
            parent
            if mode == "P"
            else ctx.read(ctx.FIT_ROOT / "training" / mode / "manifest.json")
        )
        if mode != "P":
            frozen = ctx.read(ctx.FIT_ROOT / "WEIGHTS_FROZEN.json")
            layout.require(
                frozen["arms"][mode]["model_digest"] == ctx.data.digest(manifest),
                "post-freeze model changed",
            )
        predictor = (
            layout.matched.Predictor(manifest, ctx.ARTIFACT, ctx.OLD_CODE)
            if mode == "P"
            else layout.Predictor(manifest, ctx.ARTIFACT, ctx.OLD_CODE, ctx.HERE)
        )
        policy = policy_module.CollectionPolicy(predictor, inference)
        ctx.write(
            output / "MODEL_LOADED.json",
            {
                "model_digest": predictor.model_digest,
                "parameter_after": manifest["parameter_after"],
                "cold_load_wall_seconds": time.perf_counter() - started,
                "effective_policy_digest": policy.policy_digest,
                "generation_config_sha256": policy.generation_digest,
                "device": predictor.device_report,
            },
        )
        passes = ("current",) if mode == "P" else ("current", "common_P_prefix")
        for kind in passes:
            for index, task in enumerate(tasks):
                folder = output / kind / str(index)
                folder.mkdir(parents=True, exist_ok=False)
                ctx.write(folder / "ORIGINAL_TASK.json", task)
                messages = copy.deepcopy(task["task"]["messages"])
                source_prefix = None
                if kind == "common_P_prefix":
                    baseline = (
                        ctx.COLLECTION / "results/P"
                        if panel == "A"
                        else ctx.WORK / "evaluation/B3/P/current"
                    )
                    original = baseline / str(index)
                    first = ctx.read(original / "OUTPUT-0.json")
                    feedback = ctx.read(original / "FEEDBACK-0.json")
                    receipt = ctx.read(original / "VERIFICATION-0.json")
                    layout.require(
                        first["loaded_model_manifest_digest"] == layout.PARENT
                        and feedback["verification_digest"] == ctx.data.digest(receipt)
                        and feedback["content"] == verifier.feedback(receipt),
                        "actual common P prefix differs",
                    )
                    messages += [
                        {"role": "assistant", "content": first["answer"]},
                        {"role": "tool", "content": feedback["content"]},
                    ]
                    layout.require(
                        ctx.read(original / "REQUEST-1.json")["task"]
                        == {"input": task["task"]["input"], "messages": messages},
                        "new common-prefix request must equal original P second request",
                    )
                    source_prefix = {
                        "path": str(original),
                        "first_output_sha256": ctx.sha(original / "OUTPUT-0.json"),
                        "first_feedback_sha256": ctx.sha(original / "FEEDBACK-0.json"),
                        "original_second_request_sha256": ctx.sha(
                            original / "REQUEST-1.json"
                        ),
                        "reused_parent_second_output_sha256": ctx.sha(
                            original / "OUTPUT-1.json"
                        ),
                        "parent_first_success": receipt["success"],
                        "parent_second_success": ctx.read(
                            original / "VERIFICATION-1.json"
                        )["success"],
                    }
                    ctx.write(folder / "PREFIX_PROVENANCE.json", source_prefix)
                outcomes = []
                for attempt in range(2 if kind == "current" else 1):
                    request = {
                        "record_id": task["record_id"],
                        "task": {
                            "input": task["task"]["input"],
                            "messages": copy.deepcopy(messages),
                        },
                    }
                    ctx.write(folder / ("REQUEST-" + str(attempt) + ".json"), request)
                    attempted += 1
                    result = policy.predict(
                        request,
                        folder / ("GENERATION_STARTED-" + str(attempt) + ".json"),
                    )
                    ctx.write(folder / ("OUTPUT-" + str(attempt) + ".json"), result)
                    receipt = verifier.verify(
                        task["project_id"],
                        result["answer"],
                        folder / ("verify-" + str(attempt)),
                    )
                    ctx.write(
                        folder / ("VERIFICATION-" + str(attempt) + ".json"), receipt
                    )
                    feedback = verifier.feedback(receipt)
                    ctx.write(
                        folder / ("FEEDBACK-" + str(attempt) + ".json"),
                        {
                            "content": feedback,
                            "verification_digest": ctx.data.digest(receipt),
                        },
                    )
                    row = {
                        "panel": panel,
                        "mode": mode,
                        "kind": kind,
                        "task_index": index,
                        "record_id": task["record_id"],
                        "project_id": task["project_id"],
                        "attempt": attempt,
                        "success": receipt["success"],
                        "stage": receipt.get("stage"),
                        "actual_native_child": receipt["actual_native_child"],
                        "request_sha256": ctx.sha(
                            folder / ("REQUEST-" + str(attempt) + ".json")
                        ),
                        "output_sha256": ctx.sha(
                            folder / ("OUTPUT-" + str(attempt) + ".json")
                        ),
                        "verification_sha256": ctx.sha(
                            folder / ("VERIFICATION-" + str(attempt) + ".json")
                        ),
                        "input_tokens": result["input_tokens"],
                        "output_tokens": result["output_tokens"],
                        "generation_wall_seconds": result["wall_seconds"],
                        "verification_wall_seconds": receipt.get(
                            "verification_wall_seconds", receipt["wall_seconds"]
                        ),
                        "input_truncated": result["input_truncated"],
                        "hit_output_limit": result["hit_output_limit"],
                        "prefix_provenance": source_prefix,
                    }
                    rows.append(row)
                    outcomes.append(receipt["success"])
                    messages += [
                        {"role": "assistant", "content": result["answer"]},
                        {"role": "tool", "content": feedback},
                    ]
                    print(
                        ctx.data.canonical(
                            {
                                key: row[key]
                                for key in (
                                    "panel",
                                    "mode",
                                    "kind",
                                    "task_index",
                                    "attempt",
                                    "success",
                                    "stage",
                                    "output_tokens",
                                )
                            }
                        ).decode(),
                        flush=True,
                    )
                ctx.write(folder / "OUTCOMES.json", outcomes)
        require_count = 8 if mode == "P" else 12
        generation_count = len(list(output.glob("*/*/GENERATION_STARTED-*.json")))
        layout.require(
            len(rows) == attempted == generation_count == require_count,
            "complete bounded call count",
        )
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = {
            "status": "COMPLETE",
            "panel": panel,
            "mode": mode,
            "rows": rows,
            "actual_model_calls": generation_count,
            "new_training_updates": 0,
            "cost": {
                "wall_seconds": time.perf_counter() - started,
                "self_cpu_seconds": time.process_time() - cpu,
                "observed_completed_children_cpu_seconds": after.ru_utime
                + after.ru_stime
                - usage.ru_utime
                - usage.ru_stime,
                "child_cpu_scope_complete": False,
                "input_tokens": sum(row["input_tokens"] for row in rows),
                "output_tokens": sum(row["output_tokens"] for row in rows),
                "generation_wall_seconds": sum(
                    row["generation_wall_seconds"] for row in rows
                ),
                "verification_wall_seconds": sum(
                    row["verification_wall_seconds"] for row in rows
                ),
                "full_system_cost_known": False,
                "nested_windows_are_not_additive": True,
            },
            "old_NoUpdate_unchanged": True,
            "native_adoption": False,
        }
        ctx.write(output / "RESULT.json", result)
        return result
    except BaseException as error:
        ctx.write(
            output / "FAILED.json",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "attempted_requests": attempted,
                "completed_calls": len(rows),
                "actual_started_generations": len(
                    list(output.glob("*/*/GENERATION_STARTED-*.json"))
                ),
                "wall_seconds": time.perf_counter() - started,
                "automatic_retry": False,
            },
        )
        raise
    finally:
        if predictor is not None:
            predictor.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", choices=("calibrate", "train", "audit", "evaluate"), required=True
    )
    parser.add_argument("--mode", choices=("P", *layout.MODES))
    parser.add_argument("--panel", choices=("A", "B3"))
    parser.add_argument("--b3-binding", type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    freeze, records, native, parent, tasks, inference = admitted()
    if args.stage == "calibrate":
        result = layout.calibrate(
            records,
            parent,
            ctx.ARTIFACT,
            ctx.OLD_CODE,
            freeze,
            ctx.FIT_ROOT / "calibration",
        )
    elif args.stage == "train":
        result = layout.train(
            records,
            parent,
            ctx.ARTIFACT,
            ctx.OLD_CODE,
            ctx.HERE,
            freeze,
            args.mode,
            ctx.FIT_ROOT / "training" / args.mode,
        )
    elif args.stage == "audit":
        result = layout.audit(
            ctx.FIT_ROOT, ctx.ARTIFACT, ctx.OLD_CODE, ctx.HERE, freeze
        )
    else:
        result = evaluate(args.panel, args.mode, args.source_commit, args.b3_binding)
    print(ctx.data.canonical(result).decode(), flush=True)
