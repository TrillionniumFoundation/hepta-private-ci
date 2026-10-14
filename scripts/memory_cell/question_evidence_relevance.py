"""TRAIN-only weak relevance supervision on identical nonempty source bytes.

A cross-family donor annotation is NOT proof of semantic incompatibility. The
new objective is an explicitly experimental weak label, never Reader admission.
All original answer/empty units survive; unavailable donors add no fabricated
negative. No SELECT/TEST labels, answer repairs, fallback donors or new optimizer.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

import five_causal_experiments as c
import reader_content_swap as swap

REPEAT_EMPTY = "repeat-empty-question-v1"
ALIGNED = "nonempty-question-relevance-v1"
REVERSED = "reversed-question-relevance-v1"
PROFILES = (REPEAT_EMPTY, ALIGNED, REVERSED)
SCHEMA = "hepta.reader.train-question-relevance.v1"
REFUSAL = "I do not have enough evidence."
FIELDS = {"id", "question_id", "family", "split", "request", "response", "kind", "source_sha256"}


def build_plan(examples, forbidden_families=()):
    """Bind donors to the old comparator and retain the full original cohort."""
    c.require(isinstance(examples, list) and 2 <= len(examples) <= 4096, "bounded training census")
    groups, ids, pins = defaultdict(dict), set(), set()
    for row in examples:
        c.require(isinstance(row, dict) and set(row) == FIELDS, "relevance training fields")
        c.require(row["split"] == "train" and row["family"] not in forbidden_families,
                  "only non-forbidden TRAIN may supply relevance pairs")
        c.require(c.sha(row["question_id"]) and c.sha(row["source_sha256"])
                  and c.text_id(row["id"]) and c.text_id(row["family"])
                  and row["id"] not in ids, "invalid training identity")
        ids.add(row["id"]); pins.add(row["source_sha256"])
        c.validate_public(row["request"])
        c.require(row["kind"] in ("annotated_answer", "empty_refusal")
                  and row["kind"] not in groups[row["question_id"]], "duplicate or invalid pair member")
        groups[row["question_id"]][row["kind"]] = row
    c.require(len(pins) == 1, "one bound supervision source required")
    records = []
    for qid, group in sorted(groups.items()):
        c.require(set(group) == {"annotated_answer", "empty_refusal"}, "incomplete original pair")
        a, n = group["annotated_answer"], group["empty_refusal"]
        c.require(all(a[k] == n[k] for k in ("family", "split", "source_sha256"))
                  and n["request"] == a["request"] | {"evidence": []}
                  and n["response"] == REFUSAL, "original answer/empty pairing changed")
        evidence = a["request"]["evidence"]
        suffix = " " + " ".join("[" + e["id"] + "]" for e in evidence)
        answer = a["response"]
        c.require(evidence and isinstance(answer, str) and answer.endswith(suffix), "exact appended source suffix required")
        body = answer[:-len(suffix)]
        c.require(body and body == body.strip() and body != REFUSAL, "nonempty original annotated body required")
        records.append({"question_id": qid, "family": a["family"], "split": "train",
                        "request": deepcopy(a["request"]), "answer_body": body})
    comparisons = swap.build_comparisons(records)
    lookup = {r["question_id"]: r for r in records}
    units = []
    for comparison in comparisons:
        qid, donor_id = comparison["question_id"], comparison["donor_question_id"]
        unit = {"question_id": qid, "family": lookup[qid]["family"], "split": "train",
                "donor_question_id": donor_id, "status": comparison["status"],
                "matched_request": None, "mismatched_request": None, "donor_response": None}
        if comparison["status"] == "available":
            donor = lookup[donor_id]
            matched, provenance = swap.neutral_request(donor["request"])
            mismatched = deepcopy(comparison["requests"]["donor_sources"])
            c.require(matched["evidence"] == mismatched["evidence"] and matched["options"] == mismatched["options"] and
                      matched["question"] != mismatched["question"], "same sources must receive genuinely different questions")
            # Targets share identical citation suffixes in both contexts.
            target = donor["answer_body"] + " " + " ".join("["+e["id"]+"]" for e in matched["evidence"])
            unit.update(matched_request=matched, mismatched_request=mismatched,
                        donor_response=target, donor_family=donor["family"], provenance=provenance)
        units.append(unit)
    return {"schema": SCHEMA, "examples_sha256": c.digest(examples), "units": units,
            "planned_pairs": len(units), "available_extra_pairs": sum(r["status"] == "available" for r in units),
            "donor_selection": "unchanged_reader_content_swap_identity_rule_on_TRAIN_only",
            "unavailable_original_pairs_retained": True, "negative_semantics": "weak_cross_family_question_swap",
            "independent_incompatibility_review": False, "production_accepted": False}


def extra_examples(unit, profile):
    c.require(profile in PROFILES, "unknown relevance profile")
    c.require(unit["split"] == "train", "nontraining relevance unit")
    if unit["status"] == "unavailable_donor":
        return []
    c.require(unit["status"] == "available", "unknown relevance availability")
    matched, mismatched = deepcopy(unit["matched_request"]), deepcopy(unit["mismatched_request"])
    c.validate_public(matched); c.validate_public(mismatched)
    c.require(matched["evidence"] and matched["evidence"] == mismatched["evidence"]
              and matched["options"] == mismatched["options"] and matched["question"] != mismatched["question"], "question-source manipulation changed")
    if profile == REPEAT_EMPTY:
        mismatched["evidence"] = []
    return [{"request": req, "response": target}
            for req in (matched, mismatched) for target in (unit["donor_response"], REFUSAL)]


def directions(profile):
    c.require(profile in PROFILES, "unknown relevance profile")
    return ((1, 0), (2, 3)) if profile == REVERSED else ((0, 1), (3, 2))


def prepare(tokenizer, examples, *, position_cap, profile):
    """Preflight every profile before choosing one; never replace long donors."""
    import torch
    import five_reader_evidence_pairs as pairs
    import five_reader_response_learning as learning
    c.require(profile in PROFILES, "unknown relevance profile")
    plan = build_plan(examples)
    originals = pairs.prepare(tokenizer, examples, position_cap=position_cap)
    units = {u["question_id"]: u for u in plan["units"]}
    result = []
    for original, meta in originals:
        unit = units[meta["pair_id"]]
        all_profiles = {}
        for kind in PROFILES:
            variants = [learning.compile_supervision(tokenizer, r,
                input_cap=learning.TRAINING["maximum_input_tokens"],
                response_cap=learning.TRAINING["maximum_response_tokens"], position_cap=position_cap)
                for r in extra_examples(unit, kind)]
            if variants:
                for a, b in ((0, 1), (2, 3)):
                    x, xm = variants[a]; y, ym = variants[b]
                    c.require(xm["prefix_tokens"] == ym["prefix_tokens"] and torch.equal(
                        x["input_ids"][:, :xm["prefix_tokens"]], y["input_ids"][:, :ym["prefix_tokens"]]),
                        "extra targets changed public causal prefix")
                for a, b in ((0, 2), (1, 3)):
                    x, xm = variants[a]; y, ym = variants[b]
                    c.require(torch.equal(x["input_ids"][:, xm["prefix_tokens"]:],
                                          y["input_ids"][:, ym["prefix_tokens"]:]), "extra target suffix drift")
                x, xm = variants[0]; y, ym = variants[2]
                c.require(not torch.equal(x["input_ids"][:, :xm["prefix_tokens"]],
                                          y["input_ids"][:, :ym["prefix_tokens"]]),
                          "different questions/contexts became identical neural inputs")
            all_profiles[kind] = variants
        extra = all_profiles[profile]
        out = deepcopy(meta)
        out.update(relevance_profile=profile, donor_question_id=unit["donor_question_id"],
                   extra_status=unit["status"], expected_decoder_forwards=4+len(extra),
                   input_tokens=meta["input_tokens"]+sum(b["input_ids"].numel() for b, _ in extra),
                   response_tokens=meta["response_tokens"]+sum(m["response_tokens"] for _, m in extra),
                   target_fit_tokens=meta["target_fit_tokens"]+sum(extra[g][1]["response_tokens"]
                       for g, _ in directions(profile) if extra),
                   extra_compilation=[m for _, m in extra])
        result.append(({"original": original, "extra": extra, "profile": profile}, out))
    return result


def backward(model, batch):
    """Reuse the original paired loss and ONE optimizer; max two live graphs."""
    import torch
    import five_reader_evidence_pairs as pairs
    profile = batch["profile"]
    order = directions(profile)
    c.require(len(batch["extra"]) in (0, 4), "incomplete relevance contexts")
    total, original = pairs.backward_pair(model, batch["original"], pairs.MARGIN,
                                          projection_profile="full-logits-v1")
    value, scores = float(total), [None] * len(batch["extra"])
    for good, bad in order if batch["extra"] else ():
        right = pairs.sequence_score(model, batch["extra"][good][0])
        wrong = pairs.sequence_score(model, batch["extra"][bad][0])
        loss = pairs.part_loss(right, wrong, pairs.MARGIN)
        c.require(bool(torch.isfinite(loss)), "nonfinite relevance loss")
        value += float(loss.detach())
        scores[good], scores[bad] = float(right.detach()), float(wrong.detach())
        loss.backward()
        del right, wrong, loss
    return torch.tensor(value), {"original": original, "relevance_profile": profile,
                                "extra_log_scores": scores, "negative_is_weak_supervision": True}
