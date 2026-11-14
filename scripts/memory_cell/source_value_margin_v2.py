"""Explicit source-only margin over value tokens, permitting unequal lengths.

The positive forward supplies both ordinary completion CE (including EOS) and
the value score. Negative values come only from the admitted live source facts.
This objective neither changes the old source_margin nor constrains generation.
"""

import json

import torch
import torch.nn.functional as F

from grounded_protocol import completion_ids


def check_value_receipt_size(receipt, layout):
    """Match the existing LoRAReader.save manifest schema before accepting fit.

    Both file hashes will be 64 ASCII characters; their values do not affect the
    exact serialized byte count. Large inherited ancestry must fail the write,
    rather than return a receipt that the 256 KiB checkpoint reader cannot load.
    """
    manifest = dict(
        schema="hepta.memory-lora-candidate.v2",
        base_identity=receipt["base_identity"],
        scope=receipt["scope"],
        roots=receipt["roots"],
        tensor_layout=layout,
        adapter_sha256="0" * 64,
        config_sha256="0" * 64,
        training=receipt,
        model_install_authority=False,
        production_accepted=False,
    )
    size = len(json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False).encode())
    if size > 256 * 1024:
        raise ValueError(
            "value margin receipt exceeds the checkpoint manifest byte bound"
        )
    return size


def summarize_value_charges(charges):
    """Keep checkpoint receipts bounded even at the 4096-update public limit."""
    return dict(
        margin=1.0,
        margin_weight=1.0,
        positive_ce_includes_eos=True,
        margin_includes_eos=False,
        steps=len(charges),
        **{
            key: sum(charge[key] for charge in charges)
            for key in (
                "actual_model_forwards",
                "actual_input_tokens",
                "actual_supervised_tokens",
                "positive_ce_tokens",
                "positive_margin_tokens",
                "negative_margin_tokens",
                "actual_projection_positions",
            )
        },
        **{
            key + "_mean": sum(charge[key] for charge in charges) / len(charges)
            for key in (
                "positive_ce",
                "positive_value_mean_logp",
                "negative_value_mean_logp",
                "hinge",
            )
        },
    )


def distinct_value_negatives(facts, value_tokens):
    """Stable distinct-token-value candidates, preferring the same relation."""
    result = []
    for i, fact in enumerate(facts):
        seen = {tuple(value_tokens[i])}
        candidates = []
        for j in sorted(
            range(len(facts)),
            key=lambda j: (facts[j]["relation"] != fact["relation"], j),
        ):
            value = tuple(value_tokens[j])
            if facts[j]["value"] != fact["value"] and value not in seen:
                candidates.append(j)
                seen.add(value)
        if not candidates:
            raise ValueError("value margin requires distinct live source token values")
        result.append(candidates)
    return result


def value_margin_loss(model, tokenizer, prompt, positive, negative, *, maximum):
    """CE + relu(1 + mean_logp(negative value) - mean_logp(positive value)).

    The same nonempty prompt is used for both teacher-forced forwards. EOS is a
    positive CE target only: neither value score contains EOS. The full CPU decoder
    projection is charged, including the unused final projection in each forward.
    """
    if (
        type(prompt) is not list
        or not prompt
        or any(type(token) is not int or token < 0 for token in prompt)
        or type(positive) is not str
        or type(negative) is not str
        or positive == negative
        or type(maximum) is not int
        or not 2 <= maximum <= 256
    ):
        raise ValueError("bounded source-only value margin inputs required")
    positive_ids, labels = completion_ids(tokenizer, prompt, positive, maximum=maximum)
    negative_ids, _ = completion_ids(tokenizer, prompt, negative, maximum=maximum)
    positive_values = positive_ids[len(prompt) : -1]
    negative_values = negative_ids[len(prompt) : -1]
    if (
        positive_values == negative_values
        or not 1 <= len(positive_values) < 16
        or not 1 <= len(negative_values) < 16
    ):
        raise ValueError("distinct bounded source value tokens required")
    base = model.get_base_model() if hasattr(model, "get_base_model") else model
    vocab = base.config.vocab_size
    if (
        type(vocab) is not int
        or not 1 <= vocab <= 2_000_000
        or max(positive_ids + negative_ids) >= vocab
        or next(model.parameters()).device.type != "cpu"
    ):
        raise ValueError("registered CPU decoder vocabulary required")
    scores, positive_ce = [], None
    for ids, values, is_positive in (
        (positive_ids, positive_values, True),
        (negative_ids, negative_values, False),
    ):
        x = torch.tensor([ids], dtype=torch.long)
        arguments = dict(
            input_ids=x,
            attention_mask=torch.ones_like(x),
            use_cache=False,
            return_dict=True,
        )
        if is_positive:
            arguments["labels"] = torch.tensor([labels], dtype=torch.long)
        output = model(**arguments)
        if output.logits.shape != (1, len(ids), vocab):
            raise ValueError("decoder changed the full source projection")
        start = len(prompt) - 1
        value_logits = output.logits[0, start : start + len(values)].float()
        score = -F.cross_entropy(value_logits, torch.tensor(values, dtype=torch.long))
        if is_positive:
            positive_ce = output.loss
        scores.append(score)
    hinge = F.relu(1.0 + scores[1] - scores[0])
    loss = positive_ce + hinge
    if any(
        value.ndim != 0 or not torch.isfinite(value)
        for value in (positive_ce, *scores, hinge, loss)
    ):
        raise ValueError("nonfinite or nonscalar source value margin")
    return loss, dict(
        objective="source_value_margin_v2",
        margin=1.0,
        margin_weight=1.0,
        positive_ce_includes_eos=True,
        margin_includes_eos=False,
        positive_ce=float(positive_ce.detach()),
        positive_value_mean_logp=float(scores[0].detach()),
        negative_value_mean_logp=float(scores[1].detach()),
        hinge=float(hinge.detach()),
        actual_model_forwards=2,
        actual_input_tokens=len(positive_ids) + len(negative_ids),
        actual_supervised_tokens=len(positive_values) + 1 + len(negative_values),
        positive_ce_tokens=len(positive_values) + 1,
        positive_margin_tokens=len(positive_values),
        negative_margin_tokens=len(negative_values),
        actual_projection_positions=len(positive_ids) + len(negative_ids),
        prompt_detached=False,
    )
