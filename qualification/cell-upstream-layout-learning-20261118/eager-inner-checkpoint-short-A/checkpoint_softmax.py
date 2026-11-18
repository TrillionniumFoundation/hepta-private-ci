"""Original Qwen2 eager attention with checkpointed FP32 softmax row blocks.

Derived from transformers 4.57.3 modeling_qwen2.py (Apache-2.0),
byte SHA256 08742a7c82a8713bc22f632f01c97b7eca3ef0e947180e7d6c9beec4897c4ff8.
QK and AV use the original full matrix shapes; only independent softmax rows
are partitioned and recomputed. This is a new training engine, not zero-cost.
"""

import contextlib
import copy

NAME = "eager_checkpointed_softmax"
QUERY_ROWS = 128


class Tracker:
    def __init__(self):
        self.reset()

    def reset(self):
        self.phase = "forward"
        self.counts = {}

    def add(self, name):
        key = self.phase + ":" + name
        self.counts[key] = self.counts.get(key, 0) + 1

    @contextlib.contextmanager
    def scope(self, name):
        self.add(name + "_entered")
        try:
            yield
        finally:
            self.add(name + "_exited")

    def contexts(self):
        return self.scope("softmax_original"), self.scope("softmax_recompute")

    def snapshot(self):
        return copy.deepcopy(self.counts)


TRACKER = Tracker()


def eager_checkpointed_softmax(
    module, query, key, value, attention_mask, scaling, dropout=0.0, **kwargs
):
    import torch
    from torch.utils.checkpoint import checkpoint
    from transformers.models.qwen2.modeling_qwen2 import repeat_kv

    if dropout != 0.0:
        raise ValueError("this frozen engine requires zero attention dropout")
    TRACKER.add("attention_function_started")
    key_states = repeat_kv(key, module.num_key_value_groups)
    value_states = repeat_kv(value, module.num_key_value_groups)
    attn_weights = torch.matmul(query, key_states.transpose(2, 3)) * scaling
    if attention_mask is not None:
        causal_mask = attention_mask[:, :, :, : key_states.shape[-2]]
        attn_weights = attn_weights + causal_mask

    dtype = query.dtype

    def softmax_rows(block):
        TRACKER.add("softmax_function_started")
        result = torch.nn.functional.softmax(block, dim=-1, dtype=torch.float32).to(
            dtype
        )
        TRACKER.add("softmax_function_completed")
        return result

    parts = []
    for start in range(0, attn_weights.shape[-2], QUERY_ROWS):
        block = attn_weights[:, :, start : start + QUERY_ROWS, :]
        if torch.is_grad_enabled() and block.requires_grad:
            result = checkpoint(
                softmax_rows,
                block,
                use_reentrant=False,
                preserve_rng_state=True,
                context_fn=TRACKER.contexts,
                determinism_check="default",
            )
        else:
            result = softmax_rows(block)
        parts.append(result)
    attn_weights = torch.cat(parts, dim=-2)
    attn_weights = torch.nn.functional.dropout(
        attn_weights, p=dropout, training=module.training
    )
    attn_output = torch.matmul(attn_weights, value_states)
    attn_output = attn_output.transpose(1, 2).contiguous()
    TRACKER.add("attention_function_completed")
    return attn_output, attn_weights


def register():
    from transformers import AttentionInterface
    from transformers.masking_utils import AttentionMaskInterface, eager_mask

    AttentionInterface.register(NAME, eager_checkpointed_softmax)
    AttentionMaskInterface.register(NAME, eager_mask)
