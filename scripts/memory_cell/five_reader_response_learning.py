"""Response-only LoRA learning for the fixed Reader, never a serving default.

Inputs are explicitly TRAIN supervision. This module does not create semantic
sufficiency judgments or authorize a candidate. Public-benchmark supervision
and externally reviewed supervision must not be conflated. The frozen Reader,
prompt, tokenizer, and selection gates remain owned by their existing modules.
"""
from __future__ import annotations

from copy import deepcopy
import random
from pathlib import Path
import time

import torch
from peft import LoraConfig, PeftModel, get_peft_model, get_peft_model_state_dict

import five_causal_experiments as c
from five_causal_native import SYSTEM, public_text, count_forwards
from experiments.shared_stem_cell.execution import tensor_digest, measured

PROFILE = "hepta.five-reader.response-only-lora.v1"
FORWARD_COUNTER = "causal-decoder-backbone-forward-pre-hook-v1"
REFUSAL = "I do not have enough evidence."
TRAINING = {"rank": 4, "alpha": 8, "dropout": 0.0, "targets": ["q_proj", "v_proj"],
            "epochs": 2, "learning_rate": 0.0002, "seed": 20261013,
            "maximum_input_tokens": 768, "maximum_response_tokens": 64}


def require(ok, reason):
    c.require(ok, reason)


def state_digest(state):
    return c.digest({k: tensor_digest(v) for k, v in sorted(state.items())})


def training_forward_owner(model):
    """PEFT's tuner calls the causal LM's .forward directly during training.

    That bypasses pre-hooks on the outer causal LM. Its decoder backbone is
    still dispatched through Module.__call__, including the pinned Llama path.
    Count that actual dispatch, not optimizer steps or LoRA sublayer calls.
    """
    require(callable(getattr(model, "get_base_model", None)), "PEFT base accessor required")
    causal = model.get_base_model()
    decoder = getattr(causal, "base_model", None)
    require(isinstance(causal, torch.nn.Module) and isinstance(decoder, torch.nn.Module)
            and decoder is not causal, "distinct causal decoder counter owner required")
    return decoder


def validate_examples(examples, forbidden_families=()):
    require(isinstance(examples, list) and 2 <= len(examples) <= 4096, "bounded training examples required")
    ids = set()
    for row in examples:
        require(isinstance(row, dict) and set(row) == {
            "id", "question_id", "family", "split", "request", "response", "kind", "source_sha256"
        }, "unexpected training fields")
        require(row["split"] == "train" and row["family"] not in forbidden_families,
                "held-out family or nontraining row cannot enter optimizer")
        require(all(c.text_id(row[k]) for k in ("id", "question_id", "family")) and row["id"] not in ids,
                "invalid or duplicate training identity")
        ids.add(row["id"])
        require(c.sha(row["source_sha256"]), "supervision source pin missing")
        public_text(row["request"])
        require(isinstance(row["response"], str) and row["response"].strip()
                and len(row["response"].encode()) <= 8192, "invalid training response")
        require(row["kind"] in ("annotated_answer", "empty_refusal"), "unregistered supervision kind")
        if row["kind"] == "empty_refusal":
            require(not row["request"]["evidence"] and row["response"] == REFUSAL,
                    "absence control must really be empty and retain prescribed refusal")
        else:
            require(bool(row["request"]["evidence"]) and row["response"] != REFUSAL,
                    "positive supervision must not be an always-refuse target")
    require({r["kind"] for r in examples} == {"annotated_answer", "empty_refusal"},
            "both answering and abstention supervision are required")


def permuted_positive_targets(examples):
    """Only positive responses move. Empty-evidence supervision stays identical.

    A fixed cyclic permutation preserves the positive response multiset. This
    is a negative control, not new training examples or an independent dataset.
    """
    validate_examples(examples)
    result = deepcopy(examples)
    indices = [i for i, row in enumerate(result) if row["kind"] == "annotated_answer"]
    require(len({result[i]["response"] for i in indices}) >= 2, "positive shuffle needs distinct responses")
    targets = [result[i]["response"] for i in indices]
    for j, i in enumerate(indices):
        result[i]["response"] = targets[(j + 1) % len(indices)]
    return result


def compile_supervision(tokenizer, example, *, input_cap, response_cap, position_cap):
    """Use exact template token IDs; mask ALL prompt tokens from the loss.

    Full-template tokenization must preserve the generation prefix exactly.
    No concatenation of independently tokenized strings, target truncation or
    loss over evidence/prompt is permitted.
    """
    require(all(type(x) is int and x > 0 for x in (input_cap, response_cap, position_cap)), "invalid token caps")
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": public_text(example["request"])}]
    prefix = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
    full = tokenizer.apply_chat_template(messages + [{"role": "assistant", "content": example["response"]}],
                                          tokenize=True, add_generation_prompt=False)
    require(isinstance(prefix, list) and prefix and isinstance(full, list)
            and all(type(i) is int and i >= 0 for i in full), "invalid training token sequence")
    require(full[:len(prefix)] == prefix, "assistant training prefix differs from inference")
    target_count = len(full) - len(prefix)
    require(len(prefix) <= input_cap and 0 < target_count <= response_cap and len(full) <= position_cap,
            "whole training prompt/response exceeds cap; no truncation")
    ids = torch.tensor([full], dtype=torch.long)
    labels = ids.clone()
    labels[:, :len(prefix)] = -100
    return {"input_ids": ids, "attention_mask": torch.ones_like(ids), "labels": labels}, {
        "prefix_tokens": len(prefix), "response_tokens": target_count,
        "input_ids_sha256": tensor_digest(ids), "labels_sha256": tensor_digest(labels),
        "response_only_loss": True,
    }


def fit_response_adapter(backend, examples, output: Path, *, forbidden_families=(), epochs=None,
                         loss_profile="response-ce-v1"):
    """Fit a disposable candidate and reload saved bytes, never publish it.

    response-ce-v1 retains the historical single-example schedule and loss.
    Paired profiles reuse this exact lifecycle but accumulate the two contexts
    before one update, recording their four actual likelihood forwards.
    """
    validate_examples(examples, forbidden_families)
    require(loss_profile in ("response-ce-v1", "paired-response-ce-v1", "paired-evidence-margin-v1"),
            "unregistered response objective")
    paired = loss_profile != "response-ce-v1"
    epochs = TRAINING["epochs"] if epochs is None else epochs
    require(type(epochs) is int and 1 <= epochs <= 8, "epoch bound")
    require(not hasattr(backend.loaded, "peft_config"), "fresh base required; no stacked hidden adapter")
    require(all(not p.requires_grad for p in backend.loaded.parameters()), "base must already be frozen")
    before_examples = c.digest(examples)
    position_cap = backend.loaded.config.max_position_embeddings
    objective = {"name": loss_profile, "paired_context_accumulation": paired}
    if paired:
        import five_reader_evidence_pairs as pairs
        batches = pairs.prepare(backend.tokenizer, examples, position_cap=position_cap)
        objective.update(margin_nats_per_token=pairs.MARGIN_NATS_PER_TOKEN,
                         contrast_weight=pairs.CONTRAST_WEIGHT if loss_profile == pairs.MARGIN else 0.0,
                         likelihood_normalization="mean_assistant_token_logp_including_eos",
                         countertarget_backward=loss_profile == pairs.MARGIN)
    else:
        batches = [compile_supervision(backend.tokenizer, row, input_cap=TRAINING["maximum_input_tokens"],
                   response_cap=TRAINING["maximum_response_tokens"], position_cap=position_cap) for row in examples]
    output.mkdir(parents=True, exist_ok=False)
    c.write_new(output / "training-plan.json", {"profile": PROFILE, "training": TRAINING,
        "actual_epochs": epochs, "examples_sha256": before_examples,
        "training_families": sorted({r["family"] for r in examples}),
        "forbidden_families": sorted(forbidden_families), "examples": len(examples),
        "training_forward_counter": FORWARD_COUNTER, "loss_objective": objective,
        "training_units": len(batches), "supervision_semantics": "caller_supplied_not_self_authenticated"})
    original_tensors = dict(backend.loaded.state_dict())
    original_digest = state_digest(original_tensors)
    rng = random.Random(TRAINING["seed"])
    with torch.random.fork_rng(devices=[]), torch.inference_mode(False), torch.enable_grad():
        torch.manual_seed(TRAINING["seed"])
        config = LoraConfig(r=TRAINING["rank"], lora_alpha=TRAINING["alpha"],
                            target_modules=TRAINING["targets"], lora_dropout=0.0,
                            bias="none", task_type="CAUSAL_LM")
        model = get_peft_model(backend.loaded, config)
        trainable = [(n, p) for n, p in model.named_parameters() if p.requires_grad]
        require(trainable and all("lora_" in n for n, _ in trainable), "non-LoRA weight became trainable")
        initial_adapter_digest = state_digest(get_peft_model_state_dict(model))
        optimizer = torch.optim.AdamW([p for _, p in trainable], lr=TRAINING["learning_rate"])
        model.eval()
        steps = tokens = supervised_tokens = scored_tokens = 0
        previous = "0" * 64
        losses = []
        forward_owner = training_forward_owner(model)
        with measured() as training_cost, count_forwards(forward_owner) as forwards:
            with (output / "optimizer-journal.jsonl").open("xb") as stream:
                for epoch in range(epochs):
                    order = list(range(len(batches)))
                    rng.shuffle(order)
                    for index in order:
                        batch, token_record = batches[index]
                        start = time.perf_counter()
                        before_forwards = forwards["model_calls"]
                        unit_id = token_record["pair_id"] if paired else examples[index]["id"]
                        previous = c.journal_append(stream, {"event": "optimizer_started", "epoch": epoch,
                            "index": index, "example_id": unit_id, **token_record}, previous)
                        optimizer.zero_grad(set_to_none=True)
                        diagnostics = {}
                        try:
                            if paired:
                                loss, diagnostics = pairs.backward_pair(model, batch, loss_profile)
                            else:
                                loss = model(**batch, use_cache=False).loss
                                require(bool(torch.isfinite(loss)), "nonfinite response loss")
                                loss.backward()
                            torch.nn.utils.clip_grad_norm_([p for _, p in trainable], 1.0, error_if_nonfinite=True)
                            optimizer.step()
                        except Exception as error:
                            previous = c.journal_append(stream, {"event": "optimizer_failed_or_unknown", "epoch": epoch,
                                "index": index, "error_type": type(error).__name__,
                                "observed_decoder_forwards": forwards["model_calls"] - before_forwards,
                                "wall_seconds": time.perf_counter()-start, "retry_permitted": False}, previous)
                            raise
                        steps += 1
                        tokens += token_record["input_tokens"] if paired else batch["input_ids"].numel()
                        supervised_tokens += token_record["target_fit_tokens"] if paired else token_record["response_tokens"]
                        scored_tokens += token_record["response_tokens"]
                        losses.append(float(loss.detach()))
                        previous = c.journal_append(stream, {"event": "optimizer_finished", "epoch": epoch,
                            "index": index, "loss": losses[-1], "wall_seconds": time.perf_counter()-start,
                            "pre_update_conditional_diagnostics": diagnostics,
                            "observed_decoder_forwards": forwards["model_calls"] - before_forwards}, previous)
        require(forwards["model_calls"] == steps * (4 if paired else 1),
                "decoder observations differ from fixed training execution")
        optimizer_bytes = sum(v.numel()*v.element_size() for s in optimizer.state.values()
                              for v in s.values() if isinstance(v, torch.Tensor))
        optimizer.zero_grad(set_to_none=True)
        final_adapter_digest = state_digest(get_peft_model_state_dict(model))
        require(initial_adapter_digest != final_adapter_digest, "optimizer left adapter unchanged")
        require(state_digest(original_tensors) == original_digest and c.digest(examples) == before_examples,
                "response learning mutated frozen base or input examples")
        model.save_pretrained(str(output / "adapter"), safe_serialization=True, save_embedding_layers=False)
        raw_base = model.unload()
        restored = PeftModel.from_pretrained(raw_base, str(output / "adapter"), is_trainable=False,
                                            local_files_only=True)
        require(state_digest(get_peft_model_state_dict(restored)) == final_adapter_digest, "adapter reload mismatch")
        require(state_digest(original_tensors) == original_digest, "reload mutated base tensors")
        require(all(not p.requires_grad for p in restored.parameters()), "reloaded evaluation model is trainable")
        backend.loaded = restored.eval()
    backend.close()
    receipt = {"profile": PROFILE, "training_examples": len(examples), "optimizer_steps": steps,
        "input_tokens_processed": tokens, "supervised_tokens_processed": supervised_tokens,
        "scored_response_tokens_processed": scored_tokens, "loss_objective": objective,
        "base_tensor_sha256": original_digest, "base_unchanged": True,
        "initial_adapter_sha256": initial_adapter_digest, "adapter_tensor_sha256": final_adapter_digest,
        "trainable_parameters": sum(p.numel() for _, p in trainable),
        "trainable_parameter_bytes": sum(p.numel()*p.element_size() for _, p in trainable),
        "optimizer_tensor_bytes": optimizer_bytes, "training_forwards": forwards["model_calls"],
        "training_forward_counter": FORWARD_COUNTER, "counter_owner_class": type(forward_owner).__name__,
        "training_cost": training_cost, "checkpoint_reload_equal": True,
        "files": {p.relative_to(output).as_posix(): c.file_sha(p) for p in (output / "adapter").rglob("*") if p.is_file()},
        "independent_semantic_sufficiency": False, "calibrated_stop_value": False,
        "production_accepted": False}
    c.write_new(output / "training-receipt.json", receipt)
    return receipt
