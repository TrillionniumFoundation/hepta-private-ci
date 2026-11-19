"""Run a frozen raw-function fit or the fixed actual-current-policy A diagnostic."""

import argparse
import copy
import hashlib
import resource
import sys
import time
import traceback

import raw_context as ctx
import raw_sft as fit


def deployment(commit):
    value = ctx.read(ctx.WORK / "DEPLOYMENT.json")
    ctx.require(
        value["source_commit"] == commit and value["source_directory"] == str(ctx.HERE),
        "published candidate execution identity differs",
    )
    ctx.require(
        value["protocol_sha256"] == ctx.sha(ctx.HERE / "prepared/PROTOCOL.json"),
        "published protocol changed",
    )
    return ctx.admitted()


def policy_module(codec):
    path = ctx.read(ctx.COLLECTION / "DEPLOYMENT.json")["external_source_files"]
    policy = next(
        name for name in path if name.endswith("/execution-code/run_students.py")
    )
    sys.modules["native_sandbox"] = codec.native_module()
    loaded = ctx.load("raw_function_original_collection_policy", policy, path[policy])
    return loaded


def evaluate_A(mode, commit):
    freeze = deployment(commit)
    codec, _, tasks, inference = ctx.originals()
    weights = ctx.read(ctx.WORK / "WEIGHTS_FROZEN.json")
    ctx.require(
        weights["status"] == "MATCHED_AND_WEIGHTS_FROZEN"
        and weights["freeze_digest"] == ctx.digest(freeze),
        "both real candidate weights must be frozen before evaluation",
    )
    output = ctx.WORK / "evaluation-A" / mode
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    ctx.write(
        output / "STARTED.json",
        {
            "source_commit": commit,
            "mode": mode,
            "phase": "evaluation_A",
            "started_at_ns": str(time.time_ns()),
            "weights_frozen_sha256": ctx.sha(ctx.WORK / "WEIGHTS_FROZEN.json"),
            "planned_new_model_calls": 12,
            "new_training_updates": 0,
            "already_exposed_A": True,
        },
    )
    predictor, rows, pairs = None, [], []
    try:
        manifest_path = ctx.FIT_ROOT / "training" / mode / "manifest.json"
        ctx.require(
            ctx.sha(manifest_path) == weights["arms"][mode]["manifest_sha256"],
            "frozen manifest file changed",
        )
        manifest = ctx.read(manifest_path)
        torch, _ = fit.probe._libraries()
        device = torch.device(manifest["runtime"]["device"])
        torch.cuda.set_per_process_memory_fraction(0.70, device)
        torch.cuda.reset_peak_memory_stats(device)
        predictor = fit.Predictor(manifest, ctx.ARTIFACT, ctx.OLD_CODE, ctx.HERE)
        ctx.require(
            predictor.model_digest == weights["arms"][mode]["model_digest"],
            "actual cold-loaded model changed",
        )
        policy = policy_module(codec).CollectionPolicy(predictor, inference)
        ctx.write(
            output / "MODEL_LOADED.json",
            {
                "manifest_sha256": ctx.sha(manifest_path),
                "model_digest": predictor.model_digest,
                "actual_parameter_digest_verified_by_loader": manifest[
                    "parameter_after"
                ],
                "effective_policy_digest": policy.policy_digest,
                "generation_config_sha256": policy.generation_digest,
                "cold_load_wall_seconds": time.perf_counter() - started,
                "actual_attention_implementation": predictor.model.config._attn_implementation,
                "cuda_memory_fraction": 0.70,
                "all_parameters_frozen": all(
                    not p.requires_grad for p in predictor.model.parameters()
                ),
                "device": predictor.device_report,
            },
        )

        def call(task, request, folder, scope, attempt):
            deployment(commit)
            folder.mkdir(parents=True, exist_ok=False)
            ctx.write(folder / "ORIGINAL_TASK.json", task)
            ctx.write(folder / "REQUEST.json", request)
            produced = policy.predict(request, folder / "GENERATION_STARTED.json")
            ctx.write(folder / "OUTPUT.json", produced)
            receipt = codec.verify(
                task["project_id"], produced["answer"], folder / "verify"
            )
            ctx.write(folder / "VERIFICATION.json", receipt)
            feedback = {
                "content": codec.feedback(receipt),
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
                "request_sha256": ctx.sha(folder / "REQUEST.json"),
                "output_sha256": ctx.sha(folder / "OUTPUT.json"),
                "verification_sha256": ctx.sha(folder / "VERIFICATION.json"),
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
            messages = copy.deepcopy(task["task"]["messages"])
            outcomes = []
            for attempt in (0, 1):
                request = {
                    "record_id": task["record_id"],
                    "task": {
                        "input": task["task"]["input"],
                        "messages": copy.deepcopy(messages),
                    },
                }
                produced, receipt, feedback = call(
                    task,
                    request,
                    output / "current" / str(index) / str(attempt),
                    "current",
                    attempt,
                )
                outcomes.append(receipt["success"])
                messages += [
                    {"role": "assistant", "content": produced["answer"]},
                    {"role": "tool", "content": feedback["content"]},
                ]
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
        for index, task in enumerate(tasks):
            request = ctx.read(
                ctx.COLLECTION / "results/P" / str(index) / "REQUEST-1.json"
            )
            call(
                task,
                request,
                output / "common_P_prefix" / str(index),
                "common_P_prefix",
                1,
            )
        ctx.require(
            len(rows) == 12
            and len(list(output.rglob("GENERATION_STARTED.json"))) == 12,
            "actual A generation cap differs",
        )
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = {
            "status": "COMPLETE",
            "source_commit": commit,
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
                "wall_seconds": time.perf_counter() - started,
                "self_cpu_seconds": time.process_time() - cpu,
                "observed_children_cpu_seconds": after.ru_utime
                + after.ru_stime
                - usage.ru_utime
                - usage.ru_stime,
                "input_tokens": sum(row["input_tokens"] for row in rows),
                "output_tokens": sum(row["output_tokens"] for row in rows),
                "output_caps_hit": sum(row["hit_output_limit"] for row in rows),
                "cuda_peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
                "cuda_peak_reserved_bytes": torch.cuda.max_memory_reserved(device),
                "nested_windows_not_additive": True,
                "full_system_cost_known": False,
            },
            "decision": "A_ONLY_RETAIN_RESEARCH_NOUPDATE_PENDING_NEW_CONFIRMATION",
            "previous_NoUpdate_unchanged": True,
            "new_training_updates": 0,
            "future_panel_calls": 0,
            "authenticated_users": 0,
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
                "traceback": traceback.format_exc(),
                "completed_rows": len(rows),
                "actual_generation_entries": len(
                    list(output.rglob("GENERATION_STARTED.json"))
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
        "--phase", required=True, choices=("train", "audit_weights", "evaluation_A")
    )
    parser.add_argument("--mode", choices=fit.MODES)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    freeze = deployment(args.source_commit)
    if args.phase == "train":
        ctx.require(args.mode in fit.MODES, "training mode required")
        result = fit.train(
            ctx.read(ctx.HERE / "prepared/DATASET.json"),
            ctx.read(ctx.PARENT_PATH),
            ctx.ARTIFACT,
            ctx.OLD_CODE,
            ctx.HERE,
            freeze,
            args.mode,
            ctx.FIT_ROOT / "training" / args.mode,
        )
    elif args.phase == "audit_weights":
        result = fit.audit(ctx.FIT_ROOT, ctx.ARTIFACT, ctx.OLD_CODE, ctx.HERE, freeze)
    else:
        ctx.require(args.mode in fit.MODES, "evaluation mode required")
        result = evaluate_A(args.mode, args.source_commit)
    print(ctx.canonical(result).decode(), flush=True)
