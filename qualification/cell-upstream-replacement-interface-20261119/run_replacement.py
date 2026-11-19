"""Run the frozen common A replacement interface on one unchanged model."""

import argparse
import copy
import importlib
import json
from pathlib import Path
import resource
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
codec = importlib.import_module("replacement_codec")

LAYOUT_SOURCE = Path(
    "/home/qian-qi/work/hepta-upstream-layout-learning-20261118-2e9b-checkpoint2/"
    "source/qualification/cell-upstream-layout-learning-20261118"
)
OLD_CODE = Path("/home/qian-qi/work/hepta-e1-matched-info-20261118-2e9b/source")
COLLECTION = Path("/home/qian-qi/work/hepta-upstream-current-policy-20261118-2e9b")
ARTIFACT = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")


def admitted(root, commit):
    deployment = json.loads((root / "DEPLOYMENT.json").read_bytes())
    if deployment["source_commit"] != commit:
        raise ValueError("published execution source identity differs")
    for name, digest in deployment["candidate_files"].items():
        if codec.sha((HERE / name).read_bytes()) != digest:
            raise ValueError("published candidate file changed: " + name)
    for path, digest in deployment["external_source_files"].items():
        if codec.sha(Path(path).read_bytes()) != digest:
            raise ValueError("original loaded source changed: " + path)
    protocol_raw = (root / "prepared/PROTOCOL.json").read_bytes()
    if codec.sha(protocol_raw) != deployment["protocol_sha256"]:
        raise ValueError("published CPU-qualified protocol changed")
    protocol = json.loads(protocol_raw)
    qualification_raw = Path(deployment["cpu_qualification_result_path"]).read_bytes()
    if codec.sha(qualification_raw) != protocol["cpu_controls_result_sha256"]:
        raise ValueError("actual CPU qualification receipt changed")
    qualification = json.loads(qualification_raw)
    if (
        qualification["status"] != "QUALIFIED_CPU_ONLY"
        or qualification["actual_native_children"] != 8
        or qualification["negative_control_count"] != 70
        or qualification["new_model_calls"] != 0
    ):
        raise ValueError("actual CPU qualification is incomplete")
    for name, key in (
        ("TASKS.json", "task_records_sha256"),
        ("BINDINGS.json", "source_bindings_sha256"),
    ):
        if codec.sha((root / "prepared" / name).read_bytes()) != protocol[key]:
            raise ValueError("frozen task or source binding changed: " + name)
    if codec.sha(Path(codec.__file__).read_bytes()) != protocol["codec_sha256"]:
        raise ValueError("CPU-qualified codec changed")
    tasks = json.loads((root / "prepared/TASKS.json").read_bytes())
    bindings = json.loads((root / "prepared/BINDINGS.json").read_bytes())
    if len(tasks) != len(bindings) or len(tasks) != 4:
        raise ValueError("exact four-task A panel required")
    for task, binding in zip(tasks, bindings):
        _, current = codec.source_binding(task["project_id"])
        if (
            current != binding
            or codec.sha(codec.canonical(binding)) != task["source_binding_sha256"]
        ):
            raise ValueError("original BEFORE binding changed")
    if (
        protocol["planned_total_model_calls"] != 24
        or protocol["planned_calls_per_mode"] != 8
        or protocol["planned_training_updates"] != 0
        or protocol["primary_model_predeclared"] != "native_feedback"
        or protocol["B3_model_calls"] != 0
    ):
        raise ValueError("frozen diagnostic scope differs")
    return deployment, protocol, tasks


def environment():
    sys.path.insert(0, str(OLD_CODE / "scripts"))
    sys.path.insert(0, str(LAYOUT_SOURCE))
    context = importlib.import_module("layout_context")
    if (
        Path(context.__file__).resolve()
        != (LAYOUT_SOURCE / "layout_context.py").resolve()
    ):
        raise ValueError("wrong original context module loaded")
    context.originals()
    layout = importlib.import_module("layout_sft")
    if Path(layout.__file__).resolve() != (LAYOUT_SOURCE / "layout_sft.py").resolve():
        raise ValueError("wrong original model loader loaded")
    policy_module = context.load(
        "replacement_original_collection_policy",
        COLLECTION / "execution-code/run_students.py",
        context.POLICY_SHA,
    )
    return context, layout, policy_module


def run(root, mode, commit):
    deployment, protocol, tasks = admitted(root, commit)
    if mode not in protocol["planned_modes"]:
        raise ValueError("mode is outside the fixed three-model experiment")
    output = root / "results" / mode
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    codec.write(
        output / "STARTED.json",
        {
            "mode": mode,
            "source_commit": commit,
            "deployment_sha256": codec.sha((root / "DEPLOYMENT.json").read_bytes()),
            "protocol_sha256": deployment["protocol_sha256"],
            "started_at_ns": str(time.time_ns()),
            "planned_model_calls": 8,
            "new_training_updates": 0,
            "B3_material_read": False,
        },
    )
    predictor, rows, pairs, attempted = None, [], [], 0
    try:
        context, layout, policy_module = environment()
        identity = protocol["models"][mode]
        manifest_raw = Path(identity["path"]).read_bytes()
        if codec.sha(manifest_raw) != identity["file_sha256"]:
            raise ValueError("frozen model manifest changed")
        manifest = json.loads(manifest_raw)
        if codec.sha(codec.canonical(manifest)) != identity["manifest_digest"]:
            raise ValueError("frozen model digest differs")
        torch, _ = layout.probe._libraries()
        device = torch.device(manifest["runtime"]["device"])
        torch.cuda.set_per_process_memory_fraction(0.70, device)
        torch.cuda.reset_peak_memory_stats(device)
        predictor = (
            layout.matched.Predictor(manifest, ARTIFACT, OLD_CODE)
            if mode == "P"
            else layout.Predictor(manifest, ARTIFACT, OLD_CODE, LAYOUT_SOURCE)
        )
        if predictor.model_digest != identity["manifest_digest"]:
            raise ValueError("actual admitted loader returned a different model")
        if any(parameter.requires_grad for parameter in predictor.model.parameters()):
            raise ValueError("inference-only candidate unexpectedly enables gradients")
        policy = policy_module.CollectionPolicy(predictor, protocol)
        codec.write(
            output / "MODEL_LOADED.json",
            {
                "mode": mode,
                "model_manifest_digest": predictor.model_digest,
                "manifest_file_sha256": identity["file_sha256"],
                "actual_parameter_digest_verified_by_original_loader": manifest[
                    "parameter_after"
                ],
                "cold_load_wall_seconds": time.perf_counter() - started,
                "effective_policy_digest": policy.policy_digest,
                "generation_config_sha256": policy.generation_digest,
                "ancestral_generation_config_sha256": predictor.generation_digest,
                "actual_native_context": policy.native_context,
                "actual_attention_implementation": predictor.model.config._attn_implementation,
                "device": predictor.device_report,
                "cuda_memory_fraction": 0.70,
                "all_parameters_frozen": True,
                "training_updates": 0,
            },
        )
        for index, task in enumerate(tasks):
            folder = output / str(index)
            folder.mkdir()
            codec.write(folder / "ORIGINAL_TASK.json", task)
            messages = copy.deepcopy(task["task"]["messages"])
            outcomes = []
            for attempt in range(2):
                admitted(root, commit)
                request = {
                    "record_id": task["record_id"],
                    "task": {
                        "input": task["task"]["input"],
                        "messages": copy.deepcopy(messages),
                    },
                }
                codec.write(folder / ("REQUEST-" + str(attempt) + ".json"), request)
                attempted += 1
                produced = policy.predict(
                    request, folder / ("GENERATION_STARTED-" + str(attempt) + ".json")
                )
                codec.write(folder / ("OUTPUT-" + str(attempt) + ".json"), produced)
                if attempt == 0 and (
                    produced["input_tokens"] != task["input_tokens"]
                    or produced["rendered_input_sha256"]
                    != task["rendered_input_sha256"]
                ):
                    raise ValueError(
                        "actual first input differs from the frozen CPU tokenizer preflight"
                    )
                receipt = codec.verify(
                    task["project_id"],
                    produced["answer"],
                    folder / ("verify-" + str(attempt)),
                )
                codec.write(
                    folder / ("VERIFICATION-" + str(attempt) + ".json"), receipt
                )
                feedback = codec.feedback(receipt)
                codec.write(
                    folder / ("FEEDBACK-" + str(attempt) + ".json"),
                    {
                        "content": feedback,
                        "verification_digest": codec.sha(codec.canonical(receipt)),
                    },
                )
                row = {
                    "mode": mode,
                    "task_index": index,
                    "project_id": task["project_id"],
                    "record_id": task["record_id"],
                    "attempt": attempt,
                    "success": receipt["success"],
                    "stage": receipt["stage"],
                    "actual_native_child": receipt["actual_native_child"],
                    "raw_answer_sha256": receipt["raw_answer_sha256"],
                    "converted_action_sha256": receipt["converted_action_sha256"],
                    "request_file_sha256": codec.sha(
                        (folder / ("REQUEST-" + str(attempt) + ".json")).read_bytes()
                    ),
                    "output_file_sha256": codec.sha(
                        (folder / ("OUTPUT-" + str(attempt) + ".json")).read_bytes()
                    ),
                    "verification_file_sha256": codec.sha(
                        (
                            folder / ("VERIFICATION-" + str(attempt) + ".json")
                        ).read_bytes()
                    ),
                    "input_tokens": produced["input_tokens"],
                    "output_tokens": produced["output_tokens"],
                    "generation_wall_seconds": produced["wall_seconds"],
                    "codec_and_verifier_wall_seconds": receipt["wall_seconds"],
                    "input_truncated": produced["input_truncated"],
                    "hit_output_limit": produced["hit_output_limit"],
                }
                rows.append(row)
                outcomes.append(receipt["success"])
                messages += [
                    {"role": "assistant", "content": produced["answer"]},
                    {"role": "tool", "content": feedback},
                ]
                print(
                    json.dumps(
                        {
                            key: row[key]
                            for key in (
                                "mode",
                                "task_index",
                                "attempt",
                                "success",
                                "stage",
                                "actual_native_child",
                                "output_tokens",
                            )
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
            pair = {
                "project_id": task["project_id"],
                "first": outcomes[0],
                "final": outcomes[1],
                "any_success": any(outcomes),
                "recovery": not outcomes[0] and outcomes[1],
                "recovery_opportunity": not outcomes[0],
                "regression": outcomes[0] and not outcomes[1],
                "preservation_opportunity": outcomes[0],
            }
            pairs.append(pair)
            codec.write(folder / "PAIR.json", pair)
        generation_count = len(list(output.glob("*/GENERATION_STARTED-*.json")))
        if not len(rows) == attempted == generation_count == 8:
            raise ValueError("bounded complete call count differs")
        torch.cuda.synchronize(device)
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = {
            "status": "COMPLETE",
            "source_commit": commit,
            "protocol_sha256": deployment["protocol_sha256"],
            "mode": mode,
            "rows": rows,
            "pairs": pairs,
            "actual_model_calls": generation_count,
            "actual_native_children": sum(row["actual_native_child"] for row in rows),
            "summary": {
                key: sum(pair[key] for pair in pairs)
                for key in (
                    "first",
                    "final",
                    "any_success",
                    "recovery",
                    "recovery_opportunity",
                    "regression",
                    "preservation_opportunity",
                )
            },
            "cost": {
                "wall_seconds": time.perf_counter() - started,
                "self_cpu_seconds": time.process_time() - cpu,
                "observed_completed_children_cpu_seconds": after.ru_utime
                + after.ru_stime
                - usage.ru_utime
                - usage.ru_stime,
                "input_tokens": sum(row["input_tokens"] for row in rows),
                "output_tokens": sum(row["output_tokens"] for row in rows),
                "output_caps_hit": sum(row["hit_output_limit"] for row in rows),
                "generation_wall_seconds": sum(
                    row["generation_wall_seconds"] for row in rows
                ),
                "codec_and_native_wall_seconds": sum(
                    row["codec_and_verifier_wall_seconds"] for row in rows
                ),
                "cuda_peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
                "cuda_peak_reserved_bytes": torch.cuda.max_memory_reserved(device),
                "nested_windows_are_not_additive": True,
                "full_system_cost_known": False,
            },
            "new_training_updates": 0,
            "B3_model_calls": 0,
            "old_research_NoUpdate_unchanged": True,
            "independent_confirmation_qualified": False,
            "native_adoption": False,
            "authenticated_users": 0,
        }
        codec.write(output / "RESULT.json", result)
        return result
    except BaseException as error:
        codec.write(
            output / "FAILED.json",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "traceback": traceback.format_exc(),
                "attempted_requests": attempted,
                "completed_rows": len(rows),
                "actual_generation_entries": len(
                    list(output.glob("*/GENERATION_STARTED-*.json"))
                ),
                "persisted_model_outputs": len(list(output.glob("*/OUTPUT-*.json"))),
                "wall_seconds": time.perf_counter() - started,
                "unknown_requests_not_replayed": True,
                "new_training_updates": 0,
            },
        )
        raise
    finally:
        if predictor is not None:
            predictor.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument(
        "--mode", choices=("P", "document_evidence", "native_feedback"), required=True
    )
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    result = run(args.root, args.mode, args.source_commit)
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in ("rows", "pairs")
            },
            sort_keys=True,
        ),
        flush=True,
    )
