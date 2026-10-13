"""Read-only response diagnostics: full targets, uncited bodies and first branch.

The uncited target is a TEACHER-FORCING ablation, never the training target or
an edited generated answer. First-branch logits compare two tokens under the
same causal prefix; they are not calibrated correctness or an independent judge.
"""
from __future__ import annotations

from copy import deepcopy

import torch
from torch.nn import functional as F

import five_causal_experiments as c
import five_reader_evidence_pairs as pairs
import five_reader_response_learning as learning

PROFILE = "hepta.reader.fit-audit.v1"
NAMES = (*pairs.ORDER, "body_given_support", "body_given_empty")


def body_example(positive):
    """Undo ONLY the exact citation suffix made by training_examples().

    No regex stripping: bracketed negations, numbers, or content inside the
    benchmark answer remain. An arbitrary answer without the registered suffix
    is unsupported, not silently normalized into an easier target.
    """
    evidence = positive["request"]["evidence"]
    c.require(positive["kind"] == "annotated_answer" and evidence,
              "annotated nonempty positive required")
    suffix = " " + " ".join("[" + e["id"] + "]" for e in evidence)
    response = positive["response"]
    c.require(isinstance(response, str) and response.endswith(suffix),
              "target lacks exactly appended delivered-citation suffix")
    body = response[:-len(suffix)]
    c.require(body.strip() and body == body.strip() and body != learning.REFUSAL,
              "empty or noncanonical uncited answer")
    result = deepcopy(positive)
    result["response"] = body
    return result


def target_ids(batch, meta):
    ids, mask, labels = (batch[k] for k in ("input_ids", "attention_mask", "labels"))
    start = meta["prefix_tokens"]
    c.require(isinstance(ids, torch.Tensor) and ids.dtype == torch.long
              and ids.ndim == 2 and ids.shape[0] == 1 and ids.shape[1] >= 2,
              "one unpadded causal sequence required")
    c.require(type(start) is int and 1 <= start < ids.shape[1]
              and labels.dtype == torch.long and labels.shape == ids.shape
              and mask.shape == ids.shape and bool((mask == 1).all()), "audit geometry")
    c.require(bool((labels[:, :start] == -100).all())
              and torch.equal(labels[:, start:], ids[:, start:])
              and meta["response_tokens"] == ids.shape[1] - start, "audit mask changed")
    return ids[0, start:].tolist()


def divergence(left, right):
    c.require(isinstance(left, list) and isinstance(right, list) and left and right
              and all(type(v) is int and v >= 0 for v in left + right), "response token lists")
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return index
    raise c.Invalid("identical or strict-prefix targets lack a comparable token branch")


def compile_audit(tokenizer, pair, *, position_cap):
    compiled, original_meta = pairs.compile_pair(tokenizer, pair, position_cap=position_cap)
    positive, negative = pair
    body = body_example(positive)
    variants = list(compiled["variants"])
    for row in (body, negative | {"response": body["response"]}):
        variants.append(learning.compile_supervision(tokenizer, row,
            input_cap=learning.TRAINING["maximum_input_tokens"],
            response_cap=learning.TRAINING["maximum_response_tokens"], position_cap=position_cap))
    for extra, full in ((4, 0), (5, 2)):
        a, am = variants[extra]; b, bm = variants[full]
        c.require(am["prefix_tokens"] == bm["prefix_tokens"] and torch.equal(
            a["input_ids"][:, :am["prefix_tokens"]], b["input_ids"][:, :bm["prefix_tokens"]]),
            "body ablation altered public prompt")
    targets = [target_ids(batch, meta) for batch, meta in variants]
    c.require(targets[4] == targets[5], "uncited answer differs across contexts")
    divergence(targets[0], targets[1]); divergence(targets[3], targets[2])
    return variants, {"original_pair": original_meta, "forwards_planned": len(variants),
        "uncited_target_sha256": c.digest(body["response"]),
        "input_tokens_scored": sum(batch["input_ids"].numel() for batch, _ in variants),
        "response_tokens_scored": sum(meta["response_tokens"] for _, meta in variants),
        "training_target_modified": False, "generated_answer_modified": False}


def token_readout(logits, batch, meta, *, alternative=None):
    """Causal shift once, with prompt/unused final logits outside the readout."""
    targets = target_ids(batch, meta)
    ids = batch["input_ids"]
    c.require(isinstance(logits, torch.Tensor) and logits.ndim == 3
              and tuple(logits.shape[:2]) == tuple(ids.shape) and logits.shape[-1] >= 2,
              "audit logit geometry")
    start = meta["prefix_tokens"]
    values = logits[0, start - 1:-1].detach().float()
    target = torch.tensor(targets, dtype=torch.long, device=values.device)
    c.require(bool(torch.isfinite(values).all()) and min(targets) >= 0
              and max(targets) < values.shape[-1], "nonfinite or invalid scored response")
    token_logp = -F.cross_entropy(values, target, reduction="none")
    greedy = values.argmax(-1)
    misses = (greedy != target).nonzero(as_tuple=False).flatten()
    prefix = int(misses[0]) if len(misses) else len(targets)
    result = {"target_token_ids": targets, "logp_by_token": token_logp.tolist(),
        "mean_response_logp": float(token_logp.mean()), "sum_response_logp": float(token_logp.sum()),
        "teacher_forced_top1_token_ids": greedy.tolist(),
        "matched_greedy_prefix_tokens": prefix,
        "entire_teacher_forced_path_is_greedy": prefix == len(targets),
        "input_ids_sha256": meta["input_ids_sha256"], "labels_sha256": meta["labels_sha256"]}
    if alternative is not None:
        at = divergence(targets, alternative)
        good, bad = targets[at], alternative[at]
        c.require(0 <= bad < values.shape[-1], "alternative token outside vocabulary")
        picked = int(greedy[at])
        result["first_branch"] = {"response_index": at, "good_token_id": good,
            "alternative_token_id": bad, "greedy_token_id": picked,
            "good_minus_alternative_logit": float(values[at, good] - values[at, bad]),
            "greedy_picks_good": picked == good, "greedy_picks_alternative": picked == bad,
            "greedy_picks_neither": picked not in (good, bad),
            "branch_prefix_reachable_by_greedy": prefix >= at,
            "same_causal_prefix_comparison": True}
    return result


@torch.no_grad()
def audit_one(model, tokenizer, pair, *, position_cap):
    c.require(not model.training and all(not p.requires_grad for p in model.parameters()),
              "audit requires a frozen evaluation model")
    variants, compilation = compile_audit(tokenizer, pair, position_cap=position_cap)
    targets = [target_ids(batch, meta) for batch, meta in variants]
    rows = []
    for index, (batch, meta) in enumerate(variants):
        output = model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"], use_cache=False)
        alt = targets[1] if index == 0 else targets[2] if index == 3 else None
        rows.append(token_readout(output.logits, batch, meta, alternative=alt))
        del output
    scores = [r["mean_response_logp"] for r in rows]
    return {"profile": PROFILE, "question_id": pair[0]["question_id"], "family": pair[0]["family"],
        "split": pair[0]["split"], "compilation": compilation, "sequences": dict(zip(NAMES, rows)),
        "full_target": pairs.metrics(scores[:4]),
        "uncited_target": pairs.metrics([scores[4], scores[1], scores[5], scores[3]]),
        "both_first_branches_choose_good": all(rows[i]["first_branch"]["greedy_picks_good"]
            and rows[i]["first_branch"]["branch_prefix_reachable_by_greedy"] for i in (0, 3)),
        "uncited_score_is_a_different_target_not_additive_attribution": True,
        "independent_semantic_judgment": False, "candidate_admitted": False}


def summarize(records):
    output = []
    for split in ("train", "select"):
        rows = [r for r in records if r["split"] == split]
        valid = [r for r in rows if r["status"] == "succeeded"]
        output.append({"split": split, "planned_pairs": len(rows), "scored_pairs": len(valid),
            "failed_pairs": len(rows) - len(valid),
            "full_target_both_positive": sum(r["audit"]["full_target"]["both_conditional_preferences_positive"] for r in valid),
            "uncited_target_both_positive": sum(r["audit"]["uncited_target"]["both_conditional_preferences_positive"] for r in valid),
            "greedy_both_first_branches": sum(r["audit"]["both_first_branches_choose_good"] for r in valid),
            "support_mean_full_margin": (sum(r["audit"]["full_target"]["supported_answer_margin"] for r in valid)/len(valid) if valid else None),
            "support_mean_uncited_margin": (sum(r["audit"]["uncited_target"]["supported_answer_margin"] for r in valid)/len(valid) if valid else None),
            "means_are_conditional_on_success": True, "semantic_accuracy": None})
    return output
