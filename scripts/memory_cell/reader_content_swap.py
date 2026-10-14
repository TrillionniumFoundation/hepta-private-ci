"""Nonempty evidence-content controls for already frozen Reader candidates.

No optimizer, candidate selection, sufficiency label or production admission.
Donor answers/sources are benchmark annotations, not independently established
false answers. Directed donor pairs are dependent observations, not new tasks.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import math

import five_causal_experiments as c

PROFILE = "hepta.reader.nonempty-content-swap.v1"
ORDER = ("own_answer_own_sources", "donor_answer_own_sources",
         "own_answer_donor_sources", "donor_answer_donor_sources")
CONDITIONS = ("own_sources", "donor_sources", "empty")


def neutral_request(request):
    """Use context-local citation IDs; preserve every source body and ordering.

    Positional labels are equal across equal-cardinality contexts. The source
    provenance mapping stays outside the model, never becomes a target hint.
    Dates already present in the source-time representation stay verbatim.
    """
    c.validate_public(request)
    out = deepcopy(request)
    provenance = []
    for i, (original, item) in enumerate(zip(request["evidence"], out["evidence"])):
        c.require(original["modality"] == "text" and original["asset_sha256"] is None,
                  "content control is text-only, not a media conversion")
        item["id"], item["position"] = "S" + str(i + 1), i
        provenance.append({"local_id": item["id"], "original_id": original["id"],
                           "original_position": original["position"],
                           "text_sha256": c.digest(original["text"])})
    c.validate_public(out)
    return out, provenance


def build_comparisons(records):
    """Choose one deterministic cross-family donor in the SAME partition.

    Equal source count; distinct annotated answer and source content. No model
    output, score, success flag, answer length or evaluation result is accepted.
    Unavailable donors remain in the census without replacement of recipients.
    """
    c.require(isinstance(records, list) and 1 <= len(records) <= 4096, "bounded recipient census")
    fields = {"question_id", "family", "split", "request", "answer_body"}
    seen, family_splits, source_splits = set(), {}, {}
    for r in records:
        c.require(isinstance(r, dict) and set(r) == fields, "content recipient fields")
        c.require(c.sha(r["question_id"]) and r["question_id"] not in seen
                  and c.text_id(r["family"]) and r["split"] in ("train", "select"),
                  "recipient identity or partition")
        seen.add(r["question_id"])
        c.validate_public(r["request"])
        c.require(1 <= len(r["request"]["evidence"]) <= 3, "one to three actual sources required")
        neutral_request(r["request"])
        c.require(isinstance(r["answer_body"], str) and r["answer_body"].strip()
                  and len(r["answer_body"].encode()) <= 8192, "uncited annotation required")
        c.require(family_splits.setdefault(r["family"], r["split"]) == r["split"], "family crosses partitions")
        for e in r["request"]["evidence"]:
            for key in (("id", e["id"]), ("body", c.digest(e["text"]))):
                c.require(source_splits.setdefault(key, r["split"]) == r["split"], "source crosses partitions")
    answer_key = lambda r: " ".join(r["answer_body"].casefold().split())
    body_key = lambda r: tuple(e["text"] for e in r["request"]["evidence"])
    result = []
    for r in sorted(records, key=lambda x: x["question_id"]):
        candidates = [d for d in records if d["split"] == r["split"] and d["family"] != r["family"]
                      and len(d["request"]["evidence"]) == len(r["request"]["evidence"])
                      and answer_key(d) != answer_key(r) and body_key(d) != body_key(r)]
        own, own_provenance = neutral_request(r["request"])
        item = {"question_id": r["question_id"], "family": r["family"], "split": r["split"],
                "status": "unavailable_donor", "donor_question_id": None, "donor_family": None,
                "requests": {"own_sources": own, "empty": own | {"evidence": []}, "donor_sources": None},
                "answers": None, "provenance": {"own_sources": own_provenance},
                "semantic_incompatibility_reviewed": False}
        if candidates:
            d = min(candidates, key=lambda x: c.digest([PROFILE, r["question_id"], x["question_id"]]))
            donor, donor_provenance = neutral_request(r["request"] | {"evidence": d["request"]["evidence"]})
            c.require(own["question"] == donor["question"] and own["options"] == donor["options"],
                      "donor changed recipient question")
            item.update(status="available", donor_question_id=d["question_id"], donor_family=d["family"],
                        answers=[r["answer_body"], d["answer_body"]])
            item["requests"]["donor_sources"] = donor
            item["provenance"]["donor_sources"] = donor_provenance
        result.append(item)
    return result


def generation_plan(previous_cases, comparisons):
    """Retain prior fixed TRAIN/SELECT generation recipients, including missing targets.

    Accept public inputs only. No answer/rival/donor provenance enters generate.
    Equal local citation labels are used for both nonempty controls.
    """
    lookup = {r["question_id"]: r for r in comparisons}
    chosen = defaultdict(dict)
    for case in previous_cases:
        c.require(case["split"] in ("train", "select"), "TEST cannot enter content audit")
        if case["condition"] not in ("support_only", "no_evidence"):
            continue
        key = case["question_id"]
        c.require(case["condition"] not in chosen[key], "duplicate prior generation condition")
        chosen[key][case["condition"]] = case
    result = []
    for qid, rows in sorted(chosen.items()):
        c.require(set(rows) == {"support_only", "no_evidence"}, "incomplete prior generation recipient")
        pos, empty = rows["support_only"], rows["no_evidence"]
        c.require((pos["family"], pos["split"]) == (empty["family"], empty["split"]), "generation identity drift")
        c.validate_public(empty["request"])
        c.require(not empty["request"]["evidence"], "empty control is not empty")
        own = neutral_request(pos["request"])[0] if pos["request"] is not None else None
        if own is not None:
            c.require(own | {"evidence": []} == empty["request"], "support changes question/options")
        comparison = lookup.get(c.digest(qid))
        if comparison is not None:
            c.require(comparison["family"] == pos["family"] and comparison["split"] == pos["split"]
                      and comparison["requests"]["own_sources"] == own, "likelihood/generation input mismatch")
        requests = {"own_sources": own, "empty": deepcopy(empty["request"]),
                    "donor_sources": None if comparison is None else comparison["requests"]["donor_sources"]}
        for condition in CONDITIONS:
            result.append({"question_id": qid, "family": pos["family"], "split": pos["split"],
                           "condition": condition, "request": deepcopy(requests[condition])})
    c.require(bool(result), "empty generation census")
    return result


def interaction(scores):
    c.require(len(scores) == 4 and all(type(x) in (int, float) and math.isfinite(x)
              and x <= 0.000001 for x in scores), "four finite mean-token log scores required")
    a, b, x, y = scores
    own_margin, swapped_margin = a - b, x - y
    return {"mean_response_logp": dict(zip(ORDER, scores)),
            "own_context_answer_margin": own_margin, "donor_context_answer_margin": swapped_margin,
            "difference_in_differences": own_margin - swapped_margin,
            "own_answer_beats_rival_on_own_sources": own_margin > 0,
            "semantic_accuracy": None, "donor_is_proven_false": False,
            "calibrated_probability": False}


def compile_comparison(tokenizer, comparison, *, position_cap):
    import torch
    import five_reader_response_learning as learning
    c.require(comparison["status"] == "available", "no valid donor for likelihood comparison")
    variants = []
    for context in ("own_sources", "donor_sources"):
        for body in comparison["answers"]:
            row = {"request": comparison["requests"][context], "response": body}
            variants.append(learning.compile_supervision(tokenizer, row,
                input_cap=learning.TRAINING["maximum_input_tokens"],
                response_cap=learning.TRAINING["maximum_response_tokens"], position_cap=position_cap))
    for left, right in ((0, 1), (2, 3)):
        a, am = variants[left]; b, bm = variants[right]
        c.require(am["prefix_tokens"] == bm["prefix_tokens"] and torch.equal(
            a["input_ids"][:, :am["prefix_tokens"]], b["input_ids"][:, :bm["prefix_tokens"]]),
            "answer changed the public causal prefix")
    for left, right in ((0, 2), (1, 3)):
        a, am = variants[left]; b, bm = variants[right]
        c.require(torch.equal(a["input_ids"][:, am["prefix_tokens"]:], b["input_ids"][:, bm["prefix_tokens"]:]),
                  "same answer token suffix changed across contexts")
    a, am = variants[0]; b, bm = variants[2]
    c.require(not torch.equal(a["input_ids"][:, :am["prefix_tokens"]], b["input_ids"][:, :bm["prefix_tokens"]]),
              "swapped sources are identical neural inputs")
    a, am = variants[0]; b, bm = variants[1]
    c.require(not torch.equal(a["input_ids"][:, am["prefix_tokens"]:], b["input_ids"][:, bm["prefix_tokens"]:]),
              "distinct annotations tokenize to identical answers")
    return variants


def score_comparison(model, variants):
    import torch
    from five_reader_evidence_pairs import sequence_score
    c.require(not model.training and all(not p.requires_grad for p in model.parameters()), "frozen Reader required")
    c.require(len(variants) == 4, "four compiled sequences required")
    with torch.no_grad():
        values = [float(sequence_score(model, batch)) for batch, _ in variants]
    return interaction(values) | {"compiled": {name: meta for name, (_, meta) in zip(ORDER, variants)},
                                 "projection_profile": "full-logits-v1", "parameter_updates": 0}


def summarize(records):
    result = []
    for split in ("train", "select"):
        rows = [r for r in records if r["split"] == split]
        valid = [r for r in rows if r["status"] == "succeeded"]
        families = defaultdict(list)
        for r in valid:
            families[r["family"]].append(r["audit"]["difference_in_differences"])
        result.append({"split": split, "planned_recipient_pairs": len(rows), "scored_pairs": len(valid),
            "unavailable_or_failed": len(rows) - len(valid), "recipient_families": len(families),
            "positive_interactions": sum(r["audit"]["difference_in_differences"] > 0 for r in valid),
            "mean_interaction": math.fsum(r["audit"]["difference_in_differences"] for r in valid)/len(valid) if valid else None,
            "family_macro_interaction": math.fsum(math.fsum(xs)/len(xs) for xs in families.values())/len(families) if families else None,
            "means_conditional_on_scoring": True, "donor_pairs_independent": False,
            "confidence_interval": None, "semantic_accuracy": None, "candidate_admitted": False})
    return result
