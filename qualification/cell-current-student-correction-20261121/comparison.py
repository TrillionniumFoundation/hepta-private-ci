"""Request preparation for comparable frozen and retrieval learner controls."""

import copy
import re

import corrections as contract


def comparison_contract(bundle, parent_mode):
    contract.verify_bundle(bundle)
    parent = bundle["parents"][parent_mode]
    records = bundle["records"][parent_mode]
    return {
        "parent_model_digest": parent["model_digest"],
        "training_information_digest": contract.digest(records),
        "frozen": {"optimizer_updates": 0, "retrieved_examples": 0},
        "retrieval": {"optimizer_updates": 0, "maximum_examples": 1,
                      "maximum_memory_tokens": 1024, "ranking": "lexical Jaccard; record-id tie break"},
        "final_only": {"optimizer_updates": 8, "failed_actions_supervised": False},
        "all_actions": {"distinct_comparison_eligible": False,
                        "reason": "only one verified positive assistant turn exists per record"},
        "cross_parent_result_comparison_is_information_matched": False,
        "direct_49_parameter_solver_is_same_hypothesis_class": False,
        "WSP_unqualified_program_search_is_same_compute_budget": False,
        "new_model_calls": 0, "native_adoption": False,
    }


def require_distinct_objectives(records):
    contract.require(any(row["verified_positive_intermediate_actions"] > 0 for row in records),
                     "all_actions and final_only are identical: no verified positive intermediate actions")


def prepare_request(variant, request, bundle, parent_mode, tokenizer, chat_protocol):
    """Prepare an inference request; this interface never calls a model or verifier."""
    contract.require(variant in ("frozen", "retrieval"), "trainable variants require their saved child manifest")
    contract.verify_bundle(bundle)
    result = copy.deepcopy(request)
    prompt = result["task"]["input"]
    messages = chat_protocol.inference_messages(prompt, result["task"].get("messages"))
    selected, memory_tokens = None, 0
    if variant == "retrieval":
        query = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]+", prompt.lower()))

        def rank(record):
            words = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]+", record["original_task"]["input"].lower()))
            score = len(query & words) / max(1, len(query | words))
            return (-score, record["record_id"])

        limit = bundle["parents"][parent_mode]["manifest"]["runtime"]["max_input_tokens"]
        for record in sorted(bundle["records"][parent_mode], key=rank):
            content = ("Retrieved authorized A training example; use only if relevant.\n"
                       + "Project: " + record["project_id"] + "\nVerified repair:\n" + record["final_answer"])
            count = len(tokenizer.encode(content, add_special_tokens=False))
            candidate = messages + [{"role": "user", "content": content}]
            rendered = chat_protocol.render_prompt(tokenizer, prompt, candidate)
            if count <= 1024 and len(tokenizer.encode(rendered, add_special_tokens=False)) <= limit:
                messages, selected, memory_tokens = candidate, record["record_id"], count
                break
    result["task"]["messages"] = messages
    receipt = {"variant": variant, "source_parent": bundle["parents"][parent_mode]["model_digest"],
               "original_request_digest": contract.digest(request), "prepared_request_digest": contract.digest(result),
               "retrieved_record_id": selected, "retrieved_memory_tokens": memory_tokens,
               "original_messages_preserved": True, "query_answers_used_for_ranking": False,
               "maximum_memory_tokens": 1024, "new_model_calls": 0}
    return result, receipt
