"""Evidence-paired response objectives and teacher-forced diagnostics.

Mean response-token log probabilities are NOT calibrated answer probabilities.
No targets enter free generation. Support annotations are weak supervision;
empty-context preference does not prove semantic sufficiency on nonempty input.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

import torch
from torch.nn import functional as F

import five_causal_experiments as c
import five_reader_response_learning as learning

CE = "paired-response-ce-v1"
MARGIN = "paired-evidence-margin-v1"
OBJECTIVES = (CE, MARGIN)
MARGIN_NATS_PER_TOKEN = 1.0
CONTRAST_WEIGHT = 1.0
ORDER = ("answer_given_support", "refusal_given_support", "answer_given_empty", "refusal_given_empty")


def paired_examples(examples, *, training=True):
    """Require exactly one answer and one empty refusal for each same question.

    Diagnostic select rows retain their real split. They cannot be passed to
    the training preparation path. No conversion of select/test into TRAIN.
    """
    c.require(isinstance(examples, list) and 2 <= len(examples) <= 4096, "bounded response pair records required")
    if training:
        learning.validate_examples(examples)
    fields = {"id", "question_id", "family", "split", "request", "response", "kind", "source_sha256"}
    groups, ids = defaultdict(dict), set()
    for row in examples:
        c.require(isinstance(row, dict) and set(row) == fields, "response pair fields")
        c.require(all(c.text_id(row[k]) for k in ("id", "question_id", "family"))
                  and row["id"] not in ids and c.sha(row["source_sha256"]), "response pair identity")
        ids.add(row["id"])
        c.require(row["split"] in (("train",) if training else ("train", "select")), "unregistered pair partition")
        c.require(row["kind"] in ("annotated_answer", "empty_refusal"), "response pair kind")
        c.require(isinstance(row["response"], str) and row["response"].strip()
                  and len(row["response"].encode()) <= 8192, "response pair target")
        learning.public_text(row["request"])
        group = groups[row["question_id"]]
        c.require(row["kind"] not in group, "duplicate question/kind pair")
        group[row["kind"]] = row
    result = []
    for qid in sorted(groups):
        group = groups[qid]
        c.require(set(group) == {"annotated_answer", "empty_refusal"}, "incomplete question pair")
        positive, negative = group["annotated_answer"], group["empty_refusal"]
        c.require(all(positive[k] == negative[k] for k in ("question_id", "family", "split", "source_sha256")),
                  "pair metadata mismatch")
        c.require(bool(positive["request"]["evidence"]) and negative["request"] == positive["request"] | {"evidence": []},
                  "pair must differ only by actual evidence removal")
        c.require(negative["response"] == learning.REFUSAL and positive["response"] != learning.REFUSAL,
                  "paired targets cannot collapse to the same refusal")
        result.append((positive, negative))
    return result


def compile_pair(tokenizer, pair, *, position_cap):
    """Compile the same answer/refusal under both contexts without truncation."""
    positive, negative = pair
    rows = (positive, positive | {"response": negative["response"]},
            negative | {"response": positive["response"]}, negative)
    variants = [learning.compile_supervision(tokenizer, row,
        input_cap=learning.TRAINING["maximum_input_tokens"],
        response_cap=learning.TRAINING["maximum_response_tokens"], position_cap=position_cap) for row in rows]
    for left, right in ((0, 1), (2, 3)):
        a, am = variants[left]; b, bm = variants[right]
        c.require(am["prefix_tokens"] == bm["prefix_tokens"]
                  and torch.equal(a["input_ids"][:, :am["prefix_tokens"]], b["input_ids"][:, :bm["prefix_tokens"]]),
                  "response target changed the public context prefix")
    for left, right in ((0, 2), (1, 3)):
        a, am = variants[left]; b, bm = variants[right]
        c.require(torch.equal(a["input_ids"][:, am["prefix_tokens"]:], b["input_ids"][:, bm["prefix_tokens"]:]),
                  "same response differs between contexts")
    # Metadata-only intervention must not count as a distinct neural input.
    a, am = variants[0]; b, bm = variants[2]
    c.require(not torch.equal(a["input_ids"][:, :am["prefix_tokens"]], b["input_ids"][:, :bm["prefix_tokens"]]),
              "evidence conditions tokenize to identical input")
    return {"variants": variants}, {"pair_id": positive["question_id"],
        "input_tokens": sum(x[0]["input_ids"].numel() for x in variants),
        "response_tokens": sum(x[1]["response_tokens"] for x in variants),
        "target_fit_tokens": variants[0][1]["response_tokens"] + variants[3][1]["response_tokens"],
        "compiled_variants": {name: meta for name, (_, meta) in zip(ORDER, variants)},
        "response_only_loss": True}


def prepare(tokenizer, examples, *, position_cap):
    return [compile_pair(tokenizer, pair, position_cap=position_cap)
            for pair in paired_examples(examples, training=True)]


def mean_response_logp(logits, labels):
    """Causal one-token shift; no padding/prompt contribution or bag-of-words."""
    c.require(isinstance(logits, torch.Tensor) and logits.ndim == 3
              and labels.dtype == torch.long and labels.shape == logits.shape[:2]
              and logits.shape[1] >= 2, "causal score geometry")
    targets = labels[:, 1:].contiguous()
    mask = targets != -100
    c.require(bool(mask.any()), "no response tokens")
    c.require(bool(((targets[mask] >= 0) & (targets[mask] < logits.shape[-1])).all()), "response token outside vocabulary")
    values = logits[:, :-1, :].float().contiguous()
    c.require(bool(torch.isfinite(values).all()), "nonfinite causal logits")
    losses = F.cross_entropy(values.reshape(-1, values.shape[-1]), targets.reshape(-1),
                            ignore_index=-100, reduction="none").reshape_as(targets)
    return -losses[mask].mean()


def sequence_score(model, batch):
    output = model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"], use_cache=False)
    return mean_response_logp(output.logits, batch["labels"])


def part_loss(correct, incorrect, objective):
    c.require(objective in OBJECTIVES, "unregistered paired objective")
    value = -correct
    if objective == MARGIN:
        value = value + CONTRAST_WEIGHT * F.softplus(MARGIN_NATS_PER_TOKEN - (correct - incorrect))
    return value * 0.5


def metrics(scores):
    c.require(len(scores) == 4 and all(c.finite(float(v), -1e9, 0.000001) for v in scores), "invalid conditional log probabilities")
    support_margin = float(scores[0]) - float(scores[1])
    empty_margin = float(scores[3]) - float(scores[2])
    return {"mean_response_logp": dict(zip(ORDER, map(float, scores))),
            "supported_answer_margin": support_margin, "empty_refusal_margin": empty_margin,
            "evidence_interaction": support_margin + empty_margin,
            "both_conditional_preferences_positive": support_margin > 0 and empty_margin > 0,
            "calibrated_probability": False, "semantic_sufficiency": None}


def backward_pair(model, batch, objective):
    """Accumulate both context gradients before ONE optimizer step.

    Hold at most two response graphs, release them before the second context.
    CE also measures rejected-target likelihoods under no_grad for diagnosis;
    it does not backpropagate dummy zero losses to claim matched computation.
    """
    c.require(objective in OBJECTIVES, "unregistered paired objective")
    variants = batch["variants"]
    c.require(len(variants) == 4, "four actual context-target forwards required")
    scores, total = [None]*4, 0.0
    for good, bad in ((0, 1), (3, 2)):
        correct = sequence_score(model, variants[good][0])
        with torch.set_grad_enabled(objective == MARGIN):
            incorrect = sequence_score(model, variants[bad][0])
        loss = part_loss(correct, incorrect, objective)
        c.require(bool(torch.isfinite(loss)), "nonfinite paired loss")
        scores[good], scores[bad] = float(correct.detach()), float(incorrect.detach())
        total += float(loss.detach())
        loss.backward()
        del correct, incorrect, loss
    return torch.tensor(total), metrics(scores)


@torch.no_grad()
def diagnose(model, tokenizer, examples, *, position_cap):
    """Read-only teacher forcing, never generation with an answer-bearing prompt."""
    records = []
    for pair in paired_examples(examples, training=False):
        compiled, meta = compile_pair(tokenizer, pair, position_cap=position_cap)
        scores = [float(sequence_score(model, batch)) for batch, _ in compiled["variants"]]
        records.append({"question_id": pair[0]["question_id"], "family": pair[0]["family"],
            "split": pair[0]["split"], **meta, **metrics(scores)})
    return records
