"""SELECT question relevance on identical nonempty evidence, no new fitting.

Use the ALREADY selected donor and its original question. The old mismatched
question generation is reused exactly, not regenerated until it looks better.
Availability/weak preferences are not semantic correctness or Reader admission.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
import math
import five_causal_experiments as c
import reader_content_swap as swap

PROFILE = "hepta.reader.select-same-source-question.v1"
ARMS = ("frozen_reader", "repeat_empty", "nonempty_aligned", "nonempty_reversed")
REFUSAL = "I do not have enough evidence."
ORDER = ("answer_matched", "refusal_matched", "answer_mismatched", "refusal_mismatched")


def build_plan(inventory, previous_cases):
    """Do not search another donor, inspect model scores, or drop a recipient."""
    c.require(isinstance(inventory, dict) and inventory.get("profile") ==
              "hepta.reader.select-donor-inventory.v1", "wrong existing SELECT inventory")
    c.require(isinstance(previous_cases, list) and previous_cases, "prior public census required")
    before = c.digest([inventory, previous_cases])
    selected = [x for x in previous_cases if x["split"] == "select"]
    c.require(selected == inventory["public_cases"], "previous SELECT input census changed")
    recipients = inventory["recipients"]
    c.require(isinstance(recipients, list) and 0 < len(recipients) <= 32, "bounded recipients")
    pool, comparisons = {}, {}
    for record in inventory["pool"]:
        c.require(record["split"] == "select" and c.sha(record["question_id"])
                  and record["question_id"] not in pool, "non-SELECT or duplicate donor")
        c.validate_public(record["request"])
        c.require(isinstance(record["answer_body"], str) and record["answer_body"].strip(), "donor body missing")
        pool[record["question_id"]] = record
    for item in inventory["comparisons"]:
        c.require(item["split"] == "select" and item["question_id"] not in comparisons, "comparison partition/identity")
        comparisons[item["question_id"]] = item
    previous, seen, units, public = {}, set(), [], {}
    for case in selected:
        key = (case["question_id"], case["condition"])
        c.require(key not in previous and case["condition"] in ("own_sources", "empty", "donor_sources"), "duplicate/unknown old condition")
        previous[key] = case
    for recipient in recipients:
        qid, original = recipient["question_id"], recipient["original_question_id"]
        c.require(recipient["split"] == "select" and c.digest(original) == qid and qid not in seen,
                  "recipient identity or partition")
        seen.add(qid)
        c.require(all((original, name) in previous for name in ("own_sources", "empty", "donor_sources")), "missing old condition")
        c.require(all(previous[(original, name)]["family"] == recipient["family"]
                      for name in ("own_sources", "empty", "donor_sources")), "recipient family drift")
        unit = {"question_id": qid, "original_question_id": original, "family": recipient["family"],
                "split": "select", "donor_question_id": recipient["donor_question_id"],
                "status": "unavailable_reference_or_donor", "matched_request_id": None,
                "matched_request": None, "mismatched_request": None, "response": None}
        item = comparisons.get(qid)
        if item is not None and item["status"] == "available":
            donor_id = item["donor_question_id"]
            c.require(donor_id == recipient["donor_question_id"] and donor_id in pool and qid in pool,
                      "selected donor not bound to existing pool")
            donor = pool[donor_id]
            c.require(donor["family"] != recipient["family"] and donor["family"] == item["donor_family"], "cross-family donor changed")
            matched, provenance = swap.neutral_request(donor["request"])
            mismatched = deepcopy(item["requests"]["donor_sources"])
            own, _ = swap.neutral_request(pool[qid]["request"])
            c.require(own == item["requests"]["own_sources"] == previous[(original, "own_sources")]["request"], "old recipient sources changed")
            c.require(mismatched == previous[(original, "donor_sources")]["request"], "old donor input changed")
            c.require(item["answers"] == [pool[qid]["answer_body"], donor["answer_body"]]
                      and donor["answer_body"] != REFUSAL, "donor answer annotation changed")
            c.validate_public(matched); c.validate_public(mismatched)
            c.require(matched["evidence"] and matched["evidence"] == mismatched["evidence"]
                      and len(matched["evidence"]) == len(own["evidence"])
                      and matched["options"] == mismatched["options"]
                      and matched["question"] != mismatched["question"], "identical source/different question relation lost")
            key = c.digest(matched)
            public.setdefault(key, {"request_id": key, "request": deepcopy(matched)})
            unit.update(status="available", matched_request_id=key, matched_request=matched,
                        mismatched_request=mismatched, donor_family=donor["family"], provenance=provenance,
                        response=donor["answer_body"] + " " + " ".join("[" + e["id"] + "]" for e in matched["evidence"]))
        else:
            c.require(previous[(original, "donor_sources")]["request"] is None, "missing donor has an executable old source")
        units.append(unit)
    c.require(set(comparisons) <= seen and len(selected) == 3 * len(recipients), "extra or missing SELECT recipient")
    c.require(c.digest([inventory, previous_cases]) == before, "input mutated")
    return {"schema": PROFILE, "units": units, "public_requests": [public[k] for k in sorted(public)],
            "previous_select_inputs_sha256": c.digest(selected), "inventory_sha256": c.digest(inventory),
            "planned_recipients": len(units), "available_pairs": sum(u["status"] == "available" for u in units),
            "unique_new_generation_requests_per_arm": len(public), "new_optimizer_updates": 0,
            "donor_selection_changed": False, "negative_semantics": "weak_question_swap",
            "independent_confirmation": False, "production_accepted": False}


def join_previous(cases, raw, arms=ARMS):
    """Bind ALL old trial slots; retain unavailable slots and unmodified answers."""
    c.require(isinstance(cases, list) and cases and len(cases) <= 256, "bounded old public cases")
    c.require(arms and len(set(arms)) == len(arms), "unique old model arms required")
    c.require(isinstance(raw, list) and len(raw) == len(cases) * len(arms), "old raw census differs")
    indexed = {}
    for row in raw:
        c.require(row["arm"] in arms and row["trial_id"] not in indexed, "duplicate/unknown raw trial")
        indexed[row["trial_id"]] = row
    joined = {arm: {} for arm in arms}
    for arm in arms:
        for slot, case in enumerate(cases):
            identity = {k: case[k] for k in ("question_id", "family", "split", "condition")}
            tid = c.digest([arm, slot, identity])
            c.require(tid in indexed, "raw answer missing from old slot")
            row = indexed[tid]
            c.require(row["arm"] == arm and all(row[k] == v for k, v in identity.items()), "raw identity differs from request")
            request = case["request"]
            if request is None:
                c.require(row["status"] == "unavailable_source_or_donor" and row["answer"] is None
                          and row["evidence_ids"] == [], "unavailable old input became an answer")
            else:
                c.validate_public(request)
                c.require(row["status"] == "succeeded" and isinstance(row["answer"], str)
                          and row["public_request_sha256"] == c.digest(request)
                          and row["evidence_ids"] == [e["id"] for e in request["evidence"]], "old successful answer/input binding failed")
            if case["split"] == "select":
                key = (c.digest(case["question_id"]), case["condition"])
                c.require(key not in joined[arm], "duplicate old SELECT condition")
                joined[arm][key] = deepcopy(row)
    return joined


def compile_unit(tokenizer, unit, *, position_cap):
    import torch
    import five_reader_response_learning as learning
    c.require(unit["status"] == "available" and unit["split"] == "select", "unavailable comparison")
    variants = [learning.compile_supervision(tokenizer, {"request": request, "response": response},
        input_cap=learning.TRAINING["maximum_input_tokens"], response_cap=learning.TRAINING["maximum_response_tokens"],
        position_cap=position_cap) for request in (unit["matched_request"], unit["mismatched_request"])
        for response in (unit["response"], REFUSAL)]
    for a, b in ((0, 1), (2, 3)):
        x, xm = variants[a]; y, ym = variants[b]
        c.require(xm["prefix_tokens"] == ym["prefix_tokens"] and torch.equal(
            x["input_ids"][:, :xm["prefix_tokens"]], y["input_ids"][:, :ym["prefix_tokens"]]), "targets changed causal prefix")
    for a, b in ((0, 2), (1, 3)):
        x, xm = variants[a]; y, ym = variants[b]
        c.require(torch.equal(x["input_ids"][:, xm["prefix_tokens"]:], y["input_ids"][:, ym["prefix_tokens"]:]), "answer suffix differs across questions")
    x, xm = variants[0]; y, ym = variants[2]
    c.require(not torch.equal(x["input_ids"][:, :xm["prefix_tokens"]], y["input_ids"][:, :ym["prefix_tokens"]]), "different questions have identical neural inputs")
    x, xm = variants[0]; y, ym = variants[1]
    c.require(not torch.equal(x["input_ids"][:, xm["prefix_tokens"]:], y["input_ids"][:, ym["prefix_tokens"]:]), "answer and refusal collapsed to identical tokens")
    return variants


def preference(scores):
    c.require(isinstance(scores, (list, tuple)) and len(scores) == 4 and all(
        type(v) in (float, int) and math.isfinite(v) and v <= 0.000001 for v in scores), "four finite mean log scores")
    matched, mismatched = scores[0] - scores[1], scores[3] - scores[2]
    return {"mean_response_logp": dict(zip(ORDER, scores)), "matched_answer_margin": matched,
            "mismatched_refusal_margin": mismatched, "question_interaction": matched + mismatched,
            "both_weak_preferences_positive": matched > 0 and mismatched > 0,
            "semantic_accuracy": None, "reader_adequacy_established": False}


def behavior(matched, mismatched):
    """Nonrefusal is not a correct answer; always-refuse cannot pass this proxy."""
    valid = all(r.get("status") == "succeeded" and isinstance(r.get("answer"), str) for r in (matched, mismatched))
    if not valid:
        return {"jointly_observed": False, "matched_refusal": None, "mismatched_refusal": None,
                "weak_selective_behavior": None, "semantic_accuracy": None}
    mr, xr = (r["answer"].strip() == REFUSAL for r in (matched, mismatched))
    return {"jointly_observed": True, "matched_refusal": mr, "mismatched_refusal": xr,
            "weak_selective_behavior": not mr and xr, "semantic_accuracy": None}


def summarize(rows):
    c.require(isinstance(rows, list) and rows and len({r["question_id"] for r in rows}) == len(rows), "unique planned audit recipients")
    valid = [r for r in rows if r["status"] == "succeeded"]
    families = defaultdict(list)
    for row in valid:
        value = row["preference"]["question_interaction"]
        c.require(type(value) in (int, float) and math.isfinite(value), "nonfinite interaction")
        families[row["family"]].append(value)
    observed = [r for r in rows if r.get("behavior", {}).get("jointly_observed")]
    return {"planned_pairs": len(rows), "scored_pairs": len(valid), "unavailable_or_failed": len(rows)-len(valid),
        "both_weak_preferences_positive": sum(r["preference"]["both_weak_preferences_positive"] for r in valid),
        "mean_interaction": math.fsum(r["preference"]["question_interaction"] for r in valid)/len(valid) if valid else None,
        "family_macro_interaction": math.fsum(math.fsum(xs)/len(xs) for xs in families.values())/len(families) if families else None,
        "jointly_observed_generation_pairs": len(observed),
        "matched_refusals": sum(r["behavior"]["matched_refusal"] for r in observed),
        "mismatched_refusals": sum(r["behavior"]["mismatched_refusal"] for r in observed),
        "weak_selective_generation_pairs": sum(r["behavior"]["weak_selective_behavior"] for r in observed),
        "means_conditional_on_scoring": True, "donor_reuse_independent": False,
        "semantic_accuracy": None, "confidence_interval": None, "candidate_admitted": False}
