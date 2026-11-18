"""Collect two actual current-policy attempts per authorized upstream task."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import resource
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import native_sandbox as native

PREVIOUS = Path("/home/qian-qi/work/hepta-e2-current-credit-20261118-2e9b")
OLD_CODE = Path("/home/qian-qi/work/hepta-e1-matched-info-20261118-2e9b/source")
CANDIDATE = PREVIOUS / "source/qualification/cell-current-policy-credit-20261118"
ARTIFACT = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
sys.path.insert(0, str(OLD_CODE / "scripts"))
sys.path.insert(0, str(CANDIDATE))
import current_credit as credit
from cell_experiments import chat_protocol, data


def manifest_path(mode):
    return (
        PREVIOUS / "retained/PARENT_MODEL.json"
        if mode == "P"
        else PREVIOUS / "retained/training/verified_credit/manifest.json"
    )


class CollectionPolicy:
    """Use the unchanged admitted weights with an explicitly separate runtime policy."""

    def __init__(self, predictor, protocol):
        self.predictor, self.protocol = predictor, protocol
        from transformers import GenerationConfig

        self.generation = GenerationConfig.from_dict(protocol["generation_config"])
        self.generation_digest = data.digest(self.generation.to_dict())
        if self.generation_digest != protocol["generation_config_sha256"]:
            raise ValueError("new common generation policy differs")
        if (
            predictor.generation_digest
            != protocol["ancestral_generation_config_sha256"]
        ):
            raise ValueError("original admitted model policy changed")
        self.native_context = int(predictor.model.config.max_position_embeddings)
        if self.native_context != protocol["native_max_position_embeddings"]:
            raise ValueError(
                "actual model context differs from local configuration preflight"
            )
        if (
            self.native_context
            < protocol["maximum_input_tokens"] + protocol["maximum_new_tokens"]
        ):
            raise ValueError(
                "native context cannot hold the complete uniform input/output window"
            )
        self.policy_digest = data.digest(
            {
                "weight_manifest_digest": predictor.model_digest,
                "generation_config_sha256": self.generation_digest,
                "max_input_tokens": protocol["maximum_input_tokens"],
                "max_new_tokens": protocol["maximum_new_tokens"],
                "native_max_position_embeddings": self.native_context,
            }
        )

    def predict(self, record, generation_receipt):
        predictor, protocol = self.predictor, self.protocol
        if data.digest(predictor.manifest) != predictor.model_digest:
            raise ValueError("admitted original manifest changed")
        if data.digest(self.generation.to_dict()) != self.generation_digest:
            raise ValueError("frozen common generation policy changed")
        started_at, started = time.time_ns(), time.perf_counter()
        prompt = record["task"]["input"]
        messages = chat_protocol.inference_messages(prompt, record["task"]["messages"])
        rendered = chat_protocol.render_prompt(predictor.tokenizer, prompt, messages)
        if len(rendered.encode()) > 131072:
            raise ValueError("complete rendered context exceeds byte limit")
        encoded = predictor.tokenizer(
            rendered,
            return_tensors="pt",
            add_special_tokens=False,
            truncation=False,
            padding=False,
        )
        count = int(encoded["input_ids"].shape[1])
        if not (
            0 < count <= protocol["maximum_input_tokens"]
            and count + protocol["maximum_new_tokens"] <= self.native_context
        ):
            raise ValueError(
                "complete current-policy context plus output reserve exceeds native window; no generation or truncation"
            )
        encoded = {key: value.to(predictor.device) for key, value in encoded.items()}
        native.write(
            generation_receipt,
            {
                "started_at_ns": time.time_ns(),
                "input_tokens": count,
                "output_token_cap": protocol["maximum_new_tokens"],
                "messages_sha256": data.digest(messages),
                "effective_policy_digest": self.policy_digest,
                "unknown_requests_not_replayed": True,
            },
        )
        with predictor.torch.inference_mode():
            outputs = predictor.model.generate(
                **encoded, generation_config=self.generation
            )
        ids = outputs[0, count:].tolist()
        answer = predictor.tokenizer.decode(
            ids, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )
        eos = self.generation.eos_token_id
        eos = eos if isinstance(eos, list) else [eos]
        stopped = any(value in eos for value in ids)
        capped = len(ids) >= protocol["maximum_new_tokens"] and not stopped
        return {
            "answer": answer,
            "output_token_ids": ids,
            "loaded_model_manifest_digest": predictor.model_digest,
            "effective_policy_digest": self.policy_digest,
            "generation_config_sha256": self.generation_digest,
            "ancestral_generation_config_sha256": predictor.generation_digest,
            "original_manifest_unchanged": True,
            "input_sha256": native.sha(prompt.encode()),
            "messages_sha256": data.digest(messages),
            "rendered_input_sha256": native.sha(rendered.encode()),
            "input_tokens": count,
            "output_tokens": len(ids),
            "maximum_new_tokens": protocol["maximum_new_tokens"],
            "native_max_position_embeddings": self.native_context,
            "input_truncated": False,
            "eos_seen": stopped,
            "hit_output_limit": capped,
            "finish_reason": "eos_token"
            if stopped
            else "max_new_tokens"
            if capped
            else "other",
            "started_at_ns": started_at,
            "completed_at_ns": time.time_ns(),
            "wall_seconds": time.perf_counter() - started,
            "device": predictor.device_report,
            "time_scope": "render/tokenize/generate/decode; excludes cold load and native verifier",
            "backend_versions": predictor.manifest["backend_versions"],
            "new_training_updates": 0,
        }


def run(root, mode, commit):
    protocol = native.read(root / "prepared/PROTOCOL.json")
    tasks = native.read(root / "prepared/TASKS.json")
    if (
        native.sha((root / "prepared/TASKS.json").read_bytes())
        != protocol["task_records_sha256"]
    ):
        raise ValueError("fixed A task panel changed")
    if (
        native.sha(Path(native.__file__).read_bytes())
        != protocol["native_verifier_sha256"]
    ):
        raise ValueError("native verifier differs from actual before/after preflight")
    path = manifest_path(mode)
    if native.sha(path.read_bytes()) != protocol["manifest_sha256"][mode]:
        raise ValueError("frozen original weight manifest changed")
    directory = root / "results" / mode
    directory.mkdir(parents=True, exist_ok=False)
    native.write(
        directory / "STARTED.json",
        {
            "mode": mode,
            "source_commit": commit,
            "protocol_sha256": native.sha(
                (root / "prepared/PROTOCOL.json").read_bytes()
            ),
            "started_at_ns": time.time_ns(),
            "planned_model_calls": 8,
            "new_training_updates": 0,
        },
    )
    started, cpu, usage = (
        time.perf_counter(),
        time.process_time(),
        resource.getrusage(resource.RUSAGE_CHILDREN),
    )
    predictor, rows, attempted = None, [], 0
    try:
        manifest = native.read(path)
        predictor = (
            credit.matched.Predictor(manifest, ARTIFACT, OLD_CODE)
            if mode == "P"
            else credit.Predictor(manifest, ARTIFACT, OLD_CODE, CANDIDATE)
        )
        if predictor.model_digest != protocol["model_digests"][mode]:
            raise ValueError("cold-loaded original model identity changed")
        policy = CollectionPolicy(predictor, protocol)
        native.write(
            directory / "MODEL_LOADED.json",
            {
                "loaded_model_manifest_digest": predictor.model_digest,
                "parameter_after": manifest["parameter_after"],
                "effective_policy_digest": policy.policy_digest,
                "generation_config_sha256": policy.generation_digest,
                "ancestral_generation_config_sha256": predictor.generation_digest,
                "cold_load_wall_seconds": time.perf_counter() - started,
                "device": predictor.device_report,
                "native_max_position_embeddings": policy.native_context,
            },
        )
        for index, task in enumerate(tasks):
            folder = directory / str(index)
            folder.mkdir()
            native.write(folder / "ORIGINAL_TASK.json", task)
            messages = copy.deepcopy(task["task"]["messages"])
            outcomes = []
            for attempt in range(2):
                request = {
                    "record_id": task["record_id"],
                    "task": {
                        "input": task["task"]["input"],
                        "messages": copy.deepcopy(messages),
                    },
                }
                native.write(folder / ("REQUEST-" + str(attempt) + ".json"), request)
                attempted += 1
                output = policy.predict(
                    request, folder / ("GENERATION_STARTED-" + str(attempt) + ".json")
                )
                native.write(folder / ("OUTPUT-" + str(attempt) + ".json"), output)
                if attempt == 0 and (
                    output["rendered_input_sha256"] != task["rendered_input_sha256"]
                    or output["input_tokens"] != task["input_tokens"]
                ):
                    raise ValueError(
                        "actual first model-visible input differs from frozen tokenizer preflight"
                    )
                receipt = native.verify(
                    task["project_id"],
                    output["answer"],
                    folder / ("verify-" + str(attempt)),
                )
                native.write(
                    folder / ("VERIFICATION-" + str(attempt) + ".json"), receipt
                )
                observation = native.feedback(receipt)
                native.write(
                    folder / ("FEEDBACK-" + str(attempt) + ".json"),
                    {
                        "content": observation,
                        "verification_digest": native.sha(native.canonical(receipt)),
                    },
                )
                outcomes.append(receipt["success"])
                row = {
                    "task_id": task["task_id"],
                    "source_id": task["source_id"],
                    "project_id": task["project_id"],
                    "attempt": attempt,
                    "success": receipt["success"],
                    "stage": receipt["stage"],
                    "request_sha256": native.sha(native.canonical(request)),
                    "output_sha256": native.sha(native.canonical(output)),
                    "verification_sha256": native.sha(native.canonical(receipt)),
                    "input_tokens": output["input_tokens"],
                    "output_tokens": output["output_tokens"],
                    "generation_wall_seconds": output["wall_seconds"],
                    "verifier_wall_seconds": receipt.get(
                        "verification_wall_seconds", receipt["wall_seconds"]
                    ),
                    "actual_native_child": receipt["actual_native_child"],
                    "hit_output_limit": output["hit_output_limit"],
                }
                rows.append(row)
                messages += [
                    {"role": "assistant", "content": output["answer"]},
                    {"role": "tool", "content": observation},
                ]
                print(
                    json.dumps(
                        {
                            "mode": mode,
                            "task_index": index,
                            "attempt": attempt,
                            "success": row["success"],
                            "stage": row["stage"],
                            "output_tokens": row["output_tokens"],
                        }
                    ),
                    flush=True,
                )
            native.write(
                folder / "PAIR.json",
                {
                    "first": outcomes[0],
                    "final": outcomes[1],
                    "any_success": any(outcomes),
                    "recovery": not outcomes[0] and outcomes[1],
                    "regression": outcomes[0] and not outcomes[1],
                },
            )
        predictor.close()
        predictor = None
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = {
            "status": "COMPLETE",
            "mode": mode,
            "source_commit": commit,
            "rows": rows,
            "actual_model_calls": len(rows),
            "attempted_prediction_entries": attempted,
            "actual_verifier_calls": len(rows),
            "actual_native_children": sum(row["actual_native_child"] for row in rows),
            "input_tokens": sum(row["input_tokens"] for row in rows),
            "output_tokens": sum(row["output_tokens"] for row in rows),
            "output_caps_hit": sum(row["hit_output_limit"] for row in rows),
            "wall_seconds": time.perf_counter() - started,
            "self_cpu_seconds": time.process_time() - cpu,
            "completed_children_cpu_seconds": after.ru_utime
            + after.ru_stime
            - usage.ru_utime
            - usage.ru_stime,
            "full_system_cost_known": False,
            "nested_windows_are_not_additive": True,
            "new_training_updates": 0,
            "research_NoUpdate_retained": True,
            "independent_confirmation_qualified": False,
            "authenticated_users": 0,
            "native_adoption": False,
        }
        native.write(directory / "RESULT.json", result)
        return result
    except BaseException as error:
        native.write(
            directory / "FAILED.json",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "completed_rows": len(rows),
                "attempted_prediction_entries": attempted,
                "persisted_model_outputs": len(list(directory.glob("*/OUTPUT-*.json"))),
                "actual_generation_entries": len(
                    list(directory.glob("*/GENERATION_STARTED-*.json"))
                ),
                "unknown_requests_not_replayed": True,
                "wall_seconds": time.perf_counter() - started,
            },
        )
        raise
    finally:
        if predictor is not None:
            predictor.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--mode", choices=("P", "C"), required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    result = run(args.root, args.mode, args.source_commit)
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "rows"},
            sort_keys=True,
        )
    )
