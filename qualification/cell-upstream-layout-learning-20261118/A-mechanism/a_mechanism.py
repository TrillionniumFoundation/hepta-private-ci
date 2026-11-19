"""Read-only A failure and tokenizer/mask diagnosis; no model or verifier calls."""

import collections
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(
    "/home/qian-qi/work/hepta-upstream-layout-learning-20261118-2e9b-checkpoint2"
)
SOURCE = ROOT / "source/qualification/cell-upstream-layout-learning-20261118"
OUT = ROOT / "a-mechanism-1"
sys.path.insert(0, str(SOURCE))
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
ctx = importlib.import_module("layout_context")
layout = importlib.import_module("layout_sft")
chat = layout.chat_protocol


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(name, value):
    with (OUT / name).open("xb") as stream:
        stream.write(ctx.data.canonical(value) + b"\n")


def main():
    os.nice(19)
    started = time.perf_counter()
    OUT.mkdir(exist_ok=False)
    inputs = {}

    def record(path):
        path = Path(path)
        inputs[str(path)] = {"bytes": path.stat().st_size, "sha256": sha(path)}
        return read(path)

    protocol = record(SOURCE / "prepared/PROTOCOL.json")
    if (
        sha(SOURCE / "prepared/PROTOCOL.json")
        != "c71f8348977e955b1d5b6b98e8780ff13188b88b141fad683efb6f08bb03814f"
    ):
        raise ValueError("original protocol differs")
    for name, expected in protocol["candidate_files"].items():
        if sha(SOURCE / name) != expected:
            raise ValueError("original candidate changed")
    records = record(SOURCE / "prepared/DATASET.json")
    from transformers import AutoTokenizer
    import torch

    torch.set_num_threads(1)
    tokenizer = AutoTokenizer.from_pretrained(
        str(
            ctx.ARTIFACT
            / protocol["inference_policy"]["immutable_ancestral_runtime"][
                "base_directory"
            ]
        ),
        local_files_only=True,
        trust_remote_code=False,
    )
    expected_template = protocol["inference_policy"]["immutable_ancestral_runtime"][
        "chat_template_sha256"
    ]
    actual_template = hashlib.sha256(tokenizer.chat_template.encode()).hexdigest()
    if actual_template != expected_template:
        raise ValueError("actual tokenizer template differs")
    encoding_audit = []
    regenerated = {}
    for mode in ("document_evidence", "native_feedback"):
        saved = record(ROOT / "retained" / mode / "ENCODED_GROUPS.json")
        regenerated[mode] = layout.encode_groups(tokenizer, records, 3584, mode)
        if saved != regenerated[mode]:
            raise ValueError(
                "actual saved encoding differs from frozen source/tokenizer"
            )
        if ctx.data.digest(saved) != protocol["encoded_groups_digest"][mode]:
            raise ValueError("frozen encoded group digest differs")
        for index, (example, parts) in enumerate(zip(records, saved)):
            ids = parts[0]["input_ids"]
            if any(part["input_ids"] != ids for part in parts):
                raise ValueError("chunks do not retain one identical full context")
            prefix = parts[0]["prefix_tokens"]
            positions = [
                i
                for part in parts
                for i, label in enumerate(part["labels"])
                if label != -100
            ]
            expected_positions = list(range(prefix, len(ids)))
            actual_labels = [
                label for part in parts for label in part["labels"] if label != -100
            ]
            if positions != expected_positions or actual_labels != ids[prefix:]:
                raise ValueError(
                    "targets not exactly partitioned once after masked prefix"
                )
            if any(
                label != -100 for part in parts for label in part["labels"][:prefix]
            ):
                raise ValueError("failed action or feedback received positive labels")
            target_text = tokenizer.decode(
                ids[prefix:],
                skip_special_tokens=False,
                clean_up_tokenization_spaces=False,
            )
            if target_text != example["final_answer"] + tokenizer.eos_token + "\n":
                raise ValueError(
                    "actual target differs from maintainer answer plus native terminator"
                )
            native_prefix = layout.evidence_messages(example, "native_feedback")
            native_render = chat.render_prompt(
                tokenizer, example["task"]["input"], native_prefix
            )
            native_prefix_ids = tokenizer.encode(
                native_render, add_special_tokens=False
            )
            encoding_audit.append(
                {
                    "mode": mode,
                    "record_index": index,
                    "record_id": example["record_id"],
                    "project_id": example["project_id"],
                    "observed_actor": example["observed_actor"],
                    "full_tokens": len(ids),
                    "prefix_tokens": prefix,
                    "target_tokens": len(ids) - prefix,
                    "chunks": len(parts),
                    "every_target_position_exactly_once": True,
                    "observed_action_and_feedback_fully_masked": True,
                    "actual_target": target_text,
                    "target_ends_with": repr(target_text[-40:]),
                    "target_eos_ids": [
                        token for token in ids[prefix:] if token in (151645, 151643)
                    ],
                    "native_prefix_matches_saved_prefix": native_prefix_ids
                    == ids[:prefix],
                    "document_prefix_difference_is_declared_layout": mode
                    == "document_evidence",
                    "original_positive_native_receipt_sha256": example[
                        "reference_receipt_sha256"
                    ],
                }
            )
    calls = []
    for mode in ("document_evidence", "native_feedback"):
        result = record(ROOT / "evaluation/A" / mode / "RESULT.json")
        for summary in result["rows"]:
            folder = (
                ROOT
                / "evaluation/A"
                / mode
                / summary["kind"]
                / str(summary["task_index"])
            )
            attempt = str(summary["attempt"])
            request = record(folder / ("REQUEST-" + attempt + ".json"))
            output = record(folder / ("OUTPUT-" + attempt + ".json"))
            receipt = record(folder / ("VERIFICATION-" + attempt + ".json"))
            feedback = record(folder / ("FEEDBACK-" + attempt + ".json"))
            generation = record(folder / ("GENERATION_STARTED-" + attempt + ".json"))
            messages = chat.inference_messages(
                request["task"]["input"], request["task"]["messages"]
            )
            rendered = chat.render_prompt(tokenizer, request["task"]["input"], messages)
            inferred_ids = tokenizer.encode(rendered, add_special_tokens=False)
            if (
                ctx.data.digest(messages) != output["messages_sha256"]
                or hashlib.sha256(rendered.encode()).hexdigest()
                != output["rendered_input_sha256"]
                or hashlib.sha256(request["task"]["input"].encode()).hexdigest()
                != output["input_sha256"]
                or len(inferred_ids) != output["input_tokens"]
                or generation["input_tokens"] != len(inferred_ids)
                or generation["messages_sha256"] != output["messages_sha256"]
                or generation["effective_policy_digest"]
                != output["effective_policy_digest"]
                or output["generation_config_sha256"]
                != protocol["inference_policy"]["generation_config_sha256"]
                or output["input_truncated"]
            ):
                raise ValueError(
                    "actual generation input/template/policy binding differs"
                )
            if (
                hashlib.sha256(output["answer"].encode()).hexdigest()
                != receipt["answer_sha256"]
            ):
                raise ValueError("actual raw answer/verification binding differs")
            if feedback["verification_digest"] != ctx.data.digest(receipt):
                raise ValueError("feedback does not bind actual receipt")
            candidate_records = [
                r for r in records if r["project_id"] == summary["project_id"]
            ]
            example = next(r for r in candidate_records if r["observed_actor"] == "P")
            expected = example["final_answer"]
            schema = {}
            try:
                parsed = json.loads(output["answer"])
                schema["json_parse_success"] = True
                schema["outer_type"] = type(parsed).__name__
                if isinstance(parsed, dict):
                    schema["outer_keys"] = sorted(parsed)
                    edits = parsed.get("edits")
                    schema["edits_type"] = type(edits).__name__
                    if isinstance(edits, list):
                        schema["edit_count"] = len(edits)
                        schema["edit_key_sets"] = [
                            sorted(e) if isinstance(e, dict) else type(e).__name__
                            for e in edits
                        ]
            except (ValueError, TypeError) as error:
                schema = {"json_parse_success": False, "parse_error": str(error)}
            ids = output["output_token_ids"]
            repeated = collections.Counter(
                tuple(ids[i : i + 16]) for i in range(max(0, len(ids) - 15))
            )
            top = repeated.most_common(1)
            same_prefix = None
            if summary["kind"] == "common_P_prefix":
                index = records.index(example)
                part = regenerated[mode][index][0]
                same_prefix = inferred_ids == part["input_ids"][: part["prefix_tokens"]]
            calls.append(
                {
                    "mode": mode,
                    "kind": summary["kind"],
                    "task_index": summary["task_index"],
                    "project_id": summary["project_id"],
                    "attempt": summary["attempt"],
                    "original_success": receipt["success"],
                    "original_stage": receipt["stage"],
                    "actual_native_child": receipt["actual_native_child"],
                    "original_error_type": receipt.get("error_type"),
                    "original_reason": receipt.get("reason"),
                    "input_tokens": output["input_tokens"],
                    "output_tokens": output["output_tokens"],
                    "input_truncated": output["input_truncated"],
                    "hit_output_limit": output["hit_output_limit"],
                    "eos_seen": output["eos_seen"],
                    "finish_reason": output["finish_reason"],
                    "raw_answer_bytes": len(output["answer"].encode()),
                    "answer_prefix_240": output["answer"][:240],
                    "answer_suffix_240": output["answer"][-240:],
                    "exact_reference_target": output["answer"] == expected,
                    "reference_target_prefix_240": expected[:240],
                    "answer_equals_P_first": output["answer"]
                    == example["observed_answer"],
                    "answer_equals_C_first": any(
                        output["answer"] == r["observed_answer"]
                        for r in candidate_records
                        if r["observed_actor"] == "C"
                    ),
                    "schema": schema,
                    "most_repeated_16_token_sequence_count": top[0][1] if top else 0,
                    "most_repeated_16_token_sequence_text": tokenizer.decode(
                        list(top[0][0]), skip_special_tokens=False
                    )
                    if top
                    else "",
                    "common_request_matches_exact_training_prefix_for_this_layout": same_prefix,
                    "original_files": {
                        name: {
                            "path": str(folder / (name + "-" + attempt + ".json")),
                            "sha256": sha(folder / (name + "-" + attempt + ".json")),
                        }
                        for name in ("REQUEST", "OUTPUT", "VERIFICATION", "FEEDBACK")
                    },
                }
            )
    if len(calls) != 24 or any(call["actual_native_child"] for call in calls):
        raise ValueError("unexpected original A result scope")
    if torch.cuda.is_initialized():
        raise ValueError("CPU tokenizer diagnosis unexpectedly initialized CUDA")
    native_common = [
        c
        for c in calls
        if c["mode"] == "native_feedback" and c["kind"] == "common_P_prefix"
    ]
    summary = {
        "schema": "hepta.layout-exposed-A-tokenizer-failure-audit.v1",
        "created_at_ns": time.time_ns(),
        "source_commit": "78099aa6af4c70c00f26cb11888e20aa59510014",
        "calls_audited": len(calls),
        "model_calls": 0,
        "new_verifier_calls": 0,
        "new_native_children": 0,
        "B3_tasks_or_outputs_read": False,
        "CUDA_initialized": False,
        "actual_chat_template_sha256": actual_template,
        "both_actual_encoded_groups_exactly_regenerated": True,
        "all_actual_inference_prompts_messages_tokens_and_generation_digests_match": True,
        "all_supervised_targets_equal_original_maintainer_answer_plus_native_terminator": True,
        "observations_fully_masked_and_targets_partitioned_exactly_once": True,
        "native_common_prefix_exactly_equals_saved_training_prefix": all(
            c["common_request_matches_exact_training_prefix_for_this_layout"]
            for c in native_common
        ),
        "error_type_counts": dict(
            collections.Counter(str(c["original_error_type"]) for c in calls)
        ),
        "original_reason_counts": dict(
            collections.Counter(str(c["original_reason"]) for c in calls)
        ),
        "cap_hits": sum(c["hit_output_limit"] for c in calls),
        "parse_successes": sum(c["schema"]["json_parse_success"] for c in calls),
        "unchanged_raw_success_count": sum(c["original_success"] for c in calls),
        "observed_generation_repetition_counts": [
            {
                "mode": c["mode"],
                "kind": c["kind"],
                "task": c["task_index"],
                "attempt": c["attempt"],
                "maximum_16gram_occurrences": c[
                    "most_repeated_16_token_sequence_count"
                ],
            }
            for c in calls
        ],
        "wall_seconds": time.perf_counter() - started,
        "no_scoring_or_candidate_changes": True,
        "limits": "No forward/logit test is added. This proves byte/token/masking admission and describes observed outputs, not why learned probabilities or free generation failed.",
    }
    write("ENCODING_AUDIT.json", encoding_audit)
    write("CALLS.json", calls)
    write("INPUT_INDEX.json", inputs)
    write("READOUT.json", summary)
    print(
        json.dumps(
            {
                "summary": summary,
                "files": {
                    name: {
                        "path": str(OUT / name),
                        "sha256": sha(OUT / name),
                        "bytes": (OUT / name).stat().st_size,
                    }
                    for name in (
                        "ENCODING_AUDIT.json",
                        "CALLS.json",
                        "INPUT_INDEX.json",
                        "READOUT.json",
                    )
                },
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
