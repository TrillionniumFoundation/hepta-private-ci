"""Opt-in assistant-position vocabulary projection; no context truncation.

The complete unpadded input still traverses the causal decoder. Only the LM
head's vocabulary projection is restricted to positions that predict masked-in
assistant labels, including EOS. No cache reuse, detached context, vocabulary
approximation, changed labels or candidate/serving authority.
"""
from __future__ import annotations

from contextlib import contextmanager
import torch
from torch.nn import functional as F

FULL = "full-logits-v1"
ASSISTANT = "assistant-logits-v1"
PROFILES = (FULL, ASSISTANT)


def response_positions(batch):
    if not isinstance(batch, dict) or set(batch) != {"input_ids", "attention_mask", "labels"}:
        raise ValueError("exact compiled batch fields required")
    ids, mask, labels = (batch[k] for k in ("input_ids", "attention_mask", "labels"))
    if (not all(isinstance(x, torch.Tensor) for x in (ids, mask, labels))
            or ids.dtype != torch.long or labels.dtype != torch.long
            or ids.ndim != 2 or ids.shape[0] != 1 or not 2 <= ids.shape[1] <= 8192
            or mask.shape != ids.shape or labels.shape != ids.shape
            or mask.device != ids.device or labels.device != ids.device
            or not bool((mask == 1).all()) or not bool((ids >= 0).all())):
        raise ValueError("one bounded unpadded sequence on one device required")
    active = (labels[0] != -100).nonzero(as_tuple=False).flatten()
    if not len(active) or int(active[0]) < 1:
        raise ValueError("assistant suffix needs a nonempty masked prompt")
    start = int(active[0])
    expected = torch.arange(start, ids.shape[1], device=ids.device)
    if not torch.equal(active, expected) or not torch.equal(labels[:, start:], ids[:, start:]):
        raise ValueError("labels must be the exact contiguous assistant suffix")
    # Position start-1 predicts the FIRST response token. Final input position
    # predicts a token outside the target and is deliberately not projected.
    return active - 1, labels[0, start:]


def selected_logp(logits, targets):
    if (not isinstance(logits, torch.Tensor) or logits.ndim != 3
            or logits.shape[0] != 1 or logits.shape[1] != targets.numel()
            or logits.shape[2] < 2 or targets.dtype != torch.long
            or targets.device != logits.device or not bool(torch.isfinite(logits).all())
            or not bool(((targets >= 0) & (targets < logits.shape[2])).all())):
        raise ValueError("backend must return exactly the requested finite logits")
    # Positions are already causally shifted: do NOT shift this suffix again.
    return -F.cross_entropy(logits[0].float(), targets, reduction="mean")


def sequence_score(model, batch):
    positions, targets = response_positions(batch)
    output = model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"],
                   use_cache=False, logits_to_keep=positions)
    return selected_logp(output.logits, targets)


def qualify_model(model):
    """Narrow host contract for the pinned official Llama/PEFT path.

    Actual pretrained equivalence is checked in the dedicated qualification
    lane. Unsupported models fail explicitly; no full-projection fallback.
    """
    from transformers.models.llama.modeling_llama import LlamaForCausalLM
    from peft import PeftModelForCausalLM
    from peft.tuners.lora import LoraModel
    if type(model) is PeftModelForCausalLM:
        if type(model.base_model) is not LoraModel:
            raise ValueError("only existing LoRA wrapper is qualified")
        model = model.get_base_model()
    if type(model) is not LlamaForCausalLM:
        raise ValueError("assistant projection requires exact official LlamaForCausalLM")
    if model.training or model.config._attn_implementation != "eager":
        raise ValueError("frozen-dropout eager decoder execution required")
    if getattr(model, "is_gradient_checkpointing", False):
        raise ValueError("checkpoint-recomputed forwards require separate qualification")


@contextmanager
def projection_meter(causal_model):
    """Observed LM-head output bytes, NOT allocator peak or whole-model FLOPs."""
    head = causal_model.get_output_embeddings()
    if not isinstance(head, torch.nn.Module):
        raise ValueError("actual vocabulary projection module required")
    receipt = {"head_calls": 0, "projected_positions": 0, "produced_logit_bytes": 0,
               "max_output_tensor_bytes": 0, "peak_process_memory_measured": False}
    def observe(_module, _args, output):
        if not isinstance(output, torch.Tensor) or output.ndim != 3:
            raise ValueError("unexpected LM head output")
        size = output.numel() * output.element_size()
        receipt["head_calls"] += 1
        receipt["projected_positions"] += output.shape[0] * output.shape[1]
        receipt["produced_logit_bytes"] += size
        receipt["max_output_tensor_bytes"] = max(receipt["max_output_tensor_bytes"], size)
    hook = head.register_forward_hook(observe)
    try:
        yield receipt
    finally:
        hook.remove()
