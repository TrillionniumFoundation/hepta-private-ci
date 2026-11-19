"""Evaluate the predeclared parent and two frozen adapters on four new tasks.

This entry never trains or selects a model. The original native gate, complete
request policy and already frozen raw-function models remain authoritative.
"""

import argparse
import copy
import hashlib
import importlib
import json
from pathlib import Path
import resource
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
WORK = Path("/home/qian-qi/work/hepta-upstream-raw-function-learning-20261119-2e9b")
TRAIN_SOURCE = (
    WORK / "source/qualification/cell-upstream-raw-function-learning-20261119"
)
TRAIN_COMMIT = "2b85ea867e2749d4dc3bbb75ac16c9b5f9344f82"
WEIGHTS_SHA = "237ae92fc94d6ae411671c671190314049ded5cdc0d5dae254d57c9d8bb67be6"
NATIVE_SHA = "a36a3880753aea81019cdecb35554af859839c7b7d7941f7a5e0e07c08bbafaa"
MODES = ("P", "document_evidence", "native_feedback")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def load_training():
    declared = read(HERE / "DEPLOYMENT.json")
    require(declared["training_source_commit"] == TRAIN_COMMIT, "wrong training source")
    for name, expected in declared["training_source_files"].items():
        require(sha(TRAIN_SOURCE / name) == expected, "frozen training source changed")
    sys.path.insert(0, str(TRAIN_SOURCE))
    ctx = importlib.import_module("raw_context")
    run = importlib.import_module("run_raw")
    require(
        Path(ctx.__file__).resolve() == TRAIN_SOURCE / "raw_context.py",
        "wrong context import",
    )
    require(
        Path(run.__file__).resolve() == TRAIN_SOURCE / "run_raw.py",
        "wrong policy import",
    )
    run.deployment(TRAIN_COMMIT)
    return ctx, run


def admission(commit):
    declared = read(HERE / "DEPLOYMENT.json")
    require(
        declared["source_commit"] == commit
        and declared["source_directory"] == str(HERE),
        "future deployment identity differs",
    )
    for name, expected in declared["candidate_files"].items():
        require(
            sha(HERE / name) == expected, "future executable source changed: " + name
        )
    panel = Path(declared["panel_directory"])
    for name, expected in declared["panel_files"].items():
        require(sha(panel / name) == expected, "published panel changed: " + name)
    protocol = read(panel / "PROTOCOL.json")
    require(
        protocol["qualification_status"]
        == "FOUR_ORIGINAL_PAIRS_CONTEXTS_LICENSES_AND_DEDUP_FROZEN",
        "future material qualification is incomplete",
    )
    require(
        protocol["global_new_generation_cap"] == 56
        and protocol["future_new_generation_cap"] == 32,
        "original generation budget changed",
    )
    require(
        protocol["primary_arm"] == "native_feedback"
        and protocol["new_training_updates"] == 0,
        "primary candidate changed",
    )
    require(
        sha(WORK / "WEIGHTS_FROZEN.json") == WEIGHTS_SHA,
        "frozen real weights record changed",
    )
    weights = read(WORK / "WEIGHTS_FROZEN.json")
    require(weights["status"] == "MATCHED_AND_WEIGHTS_FROZEN", "weights not frozen")
    require(
        int(declared["published_at_ns"]) > int(weights["created_at_ns"]),
        "panel publication predates frozen weights",
    )
    require(sha(HERE / "future_native.py") == NATIVE_SHA, "native executable changed")
    native = importlib.import_module("future_native")
    require(
        Path(native.__file__).resolve() == HERE / "future_native.py",
        "wrong native module",
    )
    tasks = read(panel / "TASKS.json")
    require(
        len(tasks) == 4 and len({t["project_id"] for t in tasks}) == 4,
        "four distinct frozen projects required",
    )
    require(
        [task["project_id"] for task in tasks]
        == protocol["selected_projects_in_declared_order"],
        "published task order differs",
    )
    for task in tasks:
        require(
            not task["training_allowed"] and task["evaluation_allowed"],
            "future task authorization changed",
        )
        require(
            task["task"]["messages"]
            == [{"role": "user", "content": task["task"]["input"]}],
            "common first request changed",
        )
        spec = native.bound(task["task_spec_path"], task["task_spec_sha256"])
        require(
            spec["project_id"] == task["project_id"]
            and spec["before_sha256"] == task["original_source_sha256"],
            "native task binding differs",
        )
    ctx, run = load_training()
    return ctx, run, native, tasks, weights, declared


def first_request(task):
    return {"record_id": task["record_id"], "task": copy.deepcopy(task["task"])}


def next_request(task, produced, feedback):
    request = first_request(task)
    request["task"]["messages"] += [
        {"role": "assistant", "content": produced["answer"]},
        {"role": "tool", "content": feedback["content"]},
    ]
    return request


def common_prefix(ctx, task, index):
    root = WORK / "evaluation-future" / "P"
    frozen = read(root / "COMMON_P_PREFIX.json")
    row = frozen["prefixes"][index]
    require(
        row["project_id"] == task["project_id"], "parent prefix belongs to another task"
    )
    require(
        sha(root / "RESULT.json") == frozen["parent_result_sha256"],
        "parent result changed after prefix freeze",
    )
    for name, expected in row["files"].items():
        require(
            sha(root / name) == expected,
            "original actual parent prefix changed: " + name,
        )
    first = root / "current" / str(index) / "0"
    request = read(root / "current" / str(index) / "1" / "REQUEST.json")
    produced, feedback = read(first / "OUTPUT.json"), read(first / "FEEDBACK.json")
    receipt = read(first / "VERIFICATION.json")
    require(
        feedback["verification_digest"] == ctx.digest(receipt),
        "parent actual feedback binding changed",
    )
    require(
        read(first / "REQUEST.json") == first_request(task),
        "parent first request differs",
    )
    require(
        request == next_request(task, produced, feedback),
        "common prefix is not the actual parent response and feedback",
    )
    return request, sha(root / "COMMON_P_PREFIX.json")


def freeze_parent_prefixes(ctx, output, tasks):
    prefixes = []
    for index, task in enumerate(tasks):
        names = [
            "current/" + str(index) + "/0/" + name
            for name in (
                "REQUEST.json",
                "OUTPUT.json",
                "VERIFICATION.json",
                "FEEDBACK.json",
            )
        ] + ["current/" + str(index) + "/1/REQUEST.json"]
        prefixes.append(
            {
                "project_id": task["project_id"],
                "files": {name: sha(output / name) for name in names},
            }
        )
    ctx.write(
        output / "COMMON_P_PREFIX.json",
        {
            "schema": "hepta.future-actual-parent-prefix-freeze.v1",
            "parent_result_sha256": sha(output / "RESULT.json"),
            "created_at_ns": str(time.time_ns()),
            "prefixes": prefixes,
            "new_model_calls": 0,
            "no_teacher_or_reference_answer_substitution": True,
        },
    )


def evaluate(mode, commit):
    ctx, run, native, tasks, weights, declared = admission(commit)
    require(mode in MODES, "unknown model arm")
    output = WORK / "evaluation-future" / mode
    output.mkdir(parents=True, exist_ok=False)
    begun, cpu = time.perf_counter(), time.process_time()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    planned = 8 if mode == "P" else 12
    parent_prefix_sha = None
    if mode != "P":
        for index, task in enumerate(tasks):
            _, observed = common_prefix(ctx, task, index)
            require(
                parent_prefix_sha in (None, observed), "parent prefix snapshot changed"
            )
            parent_prefix_sha = observed
    ctx.write(
        output / "STARTED.json",
        {
            "source_commit": commit,
            "training_source_commit": TRAIN_COMMIT,
            "mode": mode,
            "started_at_ns": str(time.time_ns()),
            "panel_files": declared["panel_files"],
            "panel_published_at_ns": declared["published_at_ns"],
            "weights_frozen_sha256": WEIGHTS_SHA,
            "planned_new_model_calls": planned,
            "parent_prefix_frozen_sha256": parent_prefix_sha,
            "new_training_updates": 0,
        },
    )
    predictor, rows, pairs = None, [], []
    try:
        manifest_path = (
            ctx.PARENT_PATH
            if mode == "P"
            else ctx.FIT_ROOT / "training" / mode / "manifest.json"
        )
        expected_manifest = (
            ctx.PARENT_SHA if mode == "P" else weights["arms"][mode]["manifest_sha256"]
        )
        require(
            sha(manifest_path) == expected_manifest, "actual frozen manifest changed"
        )
        manifest = read(manifest_path)
        torch, _ = run.fit.probe._libraries()
        device = torch.device(manifest["runtime"]["device"])
        torch.cuda.set_per_process_memory_fraction(0.70, device)
        torch.cuda.reset_peak_memory_stats(device)
        predictor = (
            run.fit.matched.Predictor(manifest, ctx.ARTIFACT, ctx.OLD_CODE)
            if mode == "P"
            else run.fit.Predictor(manifest, ctx.ARTIFACT, ctx.OLD_CODE, ctx.HERE)
        )
        expected_model = (
            run.fit.PARENT if mode == "P" else weights["arms"][mode]["model_digest"]
        )
        require(predictor.model_digest == expected_model, "actual loaded model differs")
        codec, _, _, inference = ctx.originals()
        policy = run.policy_module(codec).CollectionPolicy(predictor, inference)
        require(
            predictor.model.config._attn_implementation == "eager"
            and all(not p.requires_grad for p in predictor.model.parameters()),
            "frozen inference engine differs",
        )
        ctx.write(
            output / "MODEL_LOADED.json",
            {
                "manifest_path": str(manifest_path),
                "manifest_sha256": expected_manifest,
                "model_digest": predictor.model_digest,
                "actual_parameter_digest_verified_by_loader": manifest[
                    "parameter_after"
                ],
                "effective_policy_digest": policy.policy_digest,
                "generation_config_sha256": policy.generation_digest,
                "cold_load_wall_seconds": time.perf_counter() - begun,
                "actual_attention_implementation": predictor.model.config._attn_implementation,
                "cuda_memory_fraction": 0.70,
                "all_parameters_frozen": True,
                "device": predictor.device_report,
            },
        )

        def call(task, request, folder, scope, attempt):
            admission(commit)
            require(
                int(time.time_ns()) > int(declared["published_at_ns"]),
                "call predates panel publication",
            )
            require(
                len(list(output.rglob("GENERATION_STARTED.json"))) < planned,
                "new-call budget exhausted",
            )
            folder.mkdir(parents=True, exist_ok=False)
            ctx.write(folder / "ORIGINAL_TASK.json", task)
            ctx.write(folder / "REQUEST.json", request)
            produced = policy.predict(request, folder / "GENERATION_STARTED.json")
            ctx.write(folder / "OUTPUT.json", produced)
            receipt = native.verify(
                task["task_spec_path"],
                task["task_spec_sha256"],
                produced["answer"],
                folder / "verify",
                task["expected_cases"],
            )
            ctx.write(folder / "VERIFICATION.json", receipt)
            feedback = {
                "content": native.feedback(receipt),
                "verification_digest": ctx.digest(receipt),
            }
            ctx.write(folder / "FEEDBACK.json", feedback)
            row = {
                "mode": mode,
                "project_id": task["project_id"],
                "scope": scope,
                "attempt": attempt,
                "success": receipt["success"],
                "stage": receipt["stage"],
                "actual_native_child": receipt["actual_native_child"],
                "request_sha256": sha(folder / "REQUEST.json"),
                "output_sha256": sha(folder / "OUTPUT.json"),
                "verification_sha256": sha(folder / "VERIFICATION.json"),
                "raw_answer_sha256": hashlib.sha256(
                    produced["answer"].encode()
                ).hexdigest(),
                "input_tokens": produced["input_tokens"],
                "output_tokens": produced["output_tokens"],
                "hit_output_limit": produced["hit_output_limit"],
                "generation_wall_seconds": produced["wall_seconds"],
                "codec_and_native_wall_seconds": receipt["wall_seconds"],
            }
            rows.append(row)
            print(ctx.canonical(row).decode(), flush=True)
            return produced, receipt, feedback

        for index, task in enumerate(tasks):
            request = first_request(task)
            outcomes = []
            for attempt in (0, 1):
                produced, receipt, feedback = call(
                    task,
                    request,
                    output / "current" / str(index) / str(attempt),
                    "current",
                    attempt,
                )
                outcomes.append(receipt["success"])
                request = next_request(task, produced, feedback)
            pairs.append(
                {
                    "project_id": task["project_id"],
                    "first": outcomes[0],
                    "final": outcomes[1],
                    "selected": any(outcomes),
                    "recovery": not outcomes[0] and outcomes[1],
                    "recovery_opportunity": not outcomes[0],
                    "regression": outcomes[0] and not outcomes[1],
                    "preservation_opportunity": outcomes[0],
                }
            )
        if mode != "P":
            for index, task in enumerate(tasks):
                request, observed = common_prefix(ctx, task, index)
                require(
                    observed == parent_prefix_sha,
                    "parent prefix snapshot changed before call",
                )
                call(
                    task,
                    request,
                    output / "common_P_prefix" / str(index),
                    "common_P_prefix",
                    1,
                )
        require(
            len(rows) == planned == len(list(output.rglob("GENERATION_STARTED.json"))),
            "actual future generation count differs",
        )
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = {
            "status": "COMPLETE",
            "source_commit": commit,
            "training_source_commit": TRAIN_COMMIT,
            "mode": mode,
            "actual_model_calls": len(rows),
            "actual_native_children": sum(row["actual_native_child"] for row in rows),
            "pairs": pairs,
            "rows": rows,
            "summary": {
                key: sum(pair[key] for pair in pairs)
                for key in (
                    "first",
                    "final",
                    "selected",
                    "recovery",
                    "recovery_opportunity",
                    "regression",
                    "preservation_opportunity",
                )
            },
            "common_P_prefix_successes": sum(
                row["success"] for row in rows if row["scope"] == "common_P_prefix"
            ),
            "cost": {
                "wall_seconds": time.perf_counter() - begun,
                "self_cpu_seconds": time.process_time() - cpu,
                "observed_children_cpu_seconds": after.ru_utime
                + after.ru_stime
                - usage.ru_utime
                - usage.ru_stime,
                "children_cpu_scope": "Reaped outer children only; namespace-descendant completeness is not established. Do not add to inner CPU or whole-host measurements.",
                "input_tokens": sum(row["input_tokens"] for row in rows),
                "output_tokens": sum(row["output_tokens"] for row in rows),
                "output_caps_hit": sum(row["hit_output_limit"] for row in rows),
                "cuda_peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
                "cuda_peak_reserved_bytes": torch.cuda.max_memory_reserved(device),
                "nested_windows_not_additive": True,
                "full_system_cost_known": False,
            },
            "decision": "RETAIN_RESEARCH_NOUPDATE_PENDING_COMPLETE_PREDECLARED_PAIRED_READOUT",
            "previous_NoUpdate_unchanged": True,
            "new_training_updates": 0,
            "authenticated_users": 0,
            "authenticated_independent_controller": False,
            "pretraining_contamination_eliminated": False,
            "native_adoption": False,
        }
        ctx.write(output / "RESULT.json", result)
        if mode == "P":
            freeze_parent_prefixes(ctx, output, tasks)
        return result
    except BaseException as error:
        ctx.write(
            output / "FAILED.json",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "traceback": traceback.format_exc(),
                "completed_rows": len(rows),
                "actual_generation_entries": len(
                    list(output.rglob("GENERATION_STARTED.json"))
                ),
                "wall_seconds": time.perf_counter() - begun,
                "automatic_retry": False,
            },
        )
        raise
    finally:
        if predictor is not None:
            predictor.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    result = evaluate(args.mode, args.source_commit)
    print(
        json.dumps(
            {
                "status": result["status"],
                "mode": args.mode,
                "actual_model_calls": result["actual_model_calls"],
            }
        ),
        flush=True,
    )
