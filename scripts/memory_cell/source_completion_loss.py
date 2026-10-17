"""Opt-in completion-only vocabulary projection, not a new training objective.

The full prompt still goes through every decoder layer with gradients enabled.
Only vocabulary projections whose targets are ignored are omitted. Input-token,
optimizer-step and supervised-token accounting must remain unchanged.
"""

import inspect

import torch
import torch.nn.functional as F

BACKENDS = ("full", "supervised_positions")


def completion_loss(model, ids, labels, *, backend="full"):
    """Use the original loss or select exactly the positions predicting targets.

    This bounded single-example path has no padding, auxiliary losses, smoothing,
    accumulation normalization or custom targets. The opt-in model contract is
    Qwen2ForCausalLM's logits_to_keep interface in the pinned Transformers 4.57.1.
    A caller already owns model admission; this is not an authorization check.
    """
    if backend not in BACKENDS:
        raise ValueError("unregistered source loss backend")
    if (
        not isinstance(ids, (list, tuple))
        or not isinstance(labels, (list, tuple))
        or not 2 <= len(ids) <= 2112
        or len(ids) != len(labels)
        or any(type(i) is not int or i < 0 for i in ids)
        or any(type(i) is not int for i in labels)
    ):
        raise ValueError("bounded single completion example required")
    starts = [i for i, token in enumerate(labels) if token != -100]
    if (
        not starts
        or starts[0] == 0
        or starts != list(range(starts[0], len(ids)))
        or list(labels[starts[0] :]) != list(ids[starts[0] :])
    ):
        raise ValueError("nonempty masked prompt and exact contiguous targets required")
    base = model.get_base_model() if hasattr(model, "get_base_model") else model
    vocab = base.config.vocab_size
    if type(vocab) is not int or not 1 <= vocab <= 2_000_000 or max(ids) >= vocab:
        raise ValueError("invalid source token or vocabulary size")
    if backend == "supervised_positions" and (
        base.config.model_type != "qwen2"
        or "logits_to_keep" not in inspect.signature(base.forward).parameters
    ):
        raise ValueError("source loss slicing requires the registered Qwen2 interface")
    # Current source writer is a single CPU reader. Do not silently enable sharding.
    if next(model.parameters()).device.type != "cpu":
        raise ValueError("source loss backend is registered for the CPU writer")
    x = torch.tensor([ids], dtype=torch.long)
    y = torch.tensor([labels], dtype=torch.long)
    if backend == "full":
        output = model(
            input_ids=x,
            attention_mask=torch.ones_like(x),
            labels=y,
            use_cache=False,
            return_dict=True,
        )
        loss = output.loss
        projected = len(ids)
    else:
        # Target at c is predicted at c-1, including the first completion token.
        # The final EOS is supervised; the projection AFTER EOS is unnecessary.
        positions = torch.arange(starts[0] - 1, len(ids) - 1, dtype=torch.long)
        output = model(
            input_ids=x,
            attention_mask=torch.ones_like(x),
            use_cache=False,
            return_dict=True,
            logits_to_keep=positions,
        )
        logits = output.logits
        if logits.shape != (1, len(starts), vocab):
            raise ValueError("model ignored or changed requested projection positions")
        loss = F.cross_entropy(
            logits.float().reshape(-1, vocab), y[:, starts[0] :].reshape(-1)
        )
        projected = len(starts)
    if loss.ndim != 0 or not torch.isfinite(loss):
        raise ValueError("nonfinite or nonscalar source loss")
    return loss, dict(
        backend=backend,
        input_tokens=len(ids),
        supervised_tokens=len(starts),
        full_projection_positions=len(ids),
        actual_projection_positions=projected,
        prompt_detached=False,
    )
