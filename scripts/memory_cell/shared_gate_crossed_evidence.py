"""Crossed evidence audit of SAVED small Heads; no fitting or answer targets.

One-way same-evidence ranking can be caused by a question-only preference.
Close the existing SELECT pair to a 2x2 rectangle using its two ORIGINAL
sources. The interaction cancels arbitrary additive question/evidence effects.
Crossed negatives remain weak labels, not independently adjudicated truth.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
import math

import five_causal_experiments as c
import shared_question_gate as gate
import reader_content_swap as swap

PROFILE = "hepta.cell.saved-gate-crossed-evidence.v1"
ORDER = ("aa", "ab", "ba", "bb")
# The first gate run failed before loading. Bind only the explicitly corrected
# CLI run; do not accept its failure artifact or select the latest branch ref.
GATE_SOURCE = "592b5b645ada09c335f942ce7ca11561d5eb2cf1"
GATE_RUN = 38526481788
GATE_ARTIFACT = "hepta-shared-question-gate-development"
REPLAY_ATOL = 1e-6
REPLAY_RTOL = 1e-5


def index(rows, key):
    c.require(isinstance(rows, list) and all(isinstance(r, dict) and key in r for r in rows), "invalid inventory")
    result = {r[key]: r for r in rows}
    c.require(len(result) == len(rows), "duplicate inventory identity")
    return result


def component(kind, owner, value):
    scope = ["select", owner, kind]
    text = c.canonical(value).decode("utf-8")
    return {"key": c.digest([gate.REPRESENTATION, scope, text]), "scope": scope, "text": text}


def build_plan(original, selected, inventory):
    """Use fixed existing recipients/donors; no label-dependent reselection."""
    c.require(original.get("schema") == gate.PROFILE + ".inputs"
              and original.get("representation") == gate.REPRESENTATION
              and selected.get("schema") == "hepta.reader.select-same-source-question.v1"
              and selected.get("inventory_sha256") == c.digest(inventory), "unbound original plans")
    before = c.digest([original, selected, inventory])
    originals = index([u for u in original["units"] if u["split"] == "select"], "question_id")
    units = index(selected["units"], "question_id")
    pool = index(inventory["pool"], "question_id")
    comparisons = index(inventory["comparisons"], "question_id")
    features = index(original["features"], "key")
    c.require(set(originals) == set(units) and units, "changed SELECT recipient denominator")
    c.require(all(r["split"] == "select" for r in inventory["pool"]), "non-SELECT source")
    for f in features.values():
        c.require(set(f) == {"key", "scope", "text"}
                  and f["key"] == c.digest([gate.REPRESENTATION, f["scope"], f["text"]]), "old feature identity drift")
    extra, result = {}, []
    for qid, unit in units.items():
        old = originals[qid]
        c.require(unit["split"] == old["split"] == "select" and old["family"] == unit["family"]
                  and old["status"] == unit["status"], "old pair identity drift")
        out = {"pair_id": old["pair_id"], "question_id": qid, "family": unit["family"],
               "donor_question_id": unit["donor_question_id"], "split": "select",
               "status": unit["status"], "variants": []}
        if unit["status"] != "available":
            c.require(unit["status"] == "unavailable_reference_or_donor" and not old["variants"], "missing pair repaired")
            result.append(out)
            continue
        donor = unit["donor_question_id"]
        c.require(qid in pool and donor in pool and donor != qid, "original source missing")
        a, _ = swap.neutral_request(pool[qid]["request"])
        b, _ = swap.neutral_request(pool[donor]["request"])
        c.validate_public(a); c.validate_public(b)
        cross = deepcopy(a); cross["evidence"] = deepcopy(b["evidence"])
        c.require(a == comparisons[qid]["requests"]["own_sources"]
                  and b == unit["matched_request"] and cross == unit["mismatched_request"], "original question/source changed")
        c.require(pool[qid]["family"] == unit["family"] and pool[donor]["family"] == unit["donor_family"]
                  and unit["family"] != unit["donor_family"], "source scope mismatch")
        c.require(a["options"] == b["options"] and a["question"] != b["question"]
                  and a["evidence"] and len(a["evidence"]) == len(b["evidence"])
                  and a["evidence"] != b["evidence"]
                  and all(e["modality"] == "text" for r in (a, b) for e in r["evidence"]), "degenerate rectangle")
        qa = component("question", unit["family"], {k: a[k] for k in ("question", "options")})
        qb = component("question", unit["donor_family"], {k: b[k] for k in ("question", "options")})
        ea = component("evidence", unit["family"], {"evidence": a["evidence"]})
        eb = component("evidence", unit["donor_family"], {"evidence": b["evidence"]})
        for f in (qa, qb, eb):
            c.require(features.get(f["key"]) == f, "old component was not encoded under this scope")
        c.require(old["variants"] == [
            {"role": "matched", "question_key": qb["key"], "evidence_key": eb["key"], "public_request_sha256": c.digest(b)},
            {"role": "mismatched", "question_key": qa["key"], "evidence_key": eb["key"], "public_request_sha256": c.digest(cross)}], "old score ordering changed")
        if ea["key"] in features:
            c.require(features[ea["key"]] == ea, "old own-evidence bytes differ")
        else:
            c.require(ea["key"] not in extra or extra[ea["key"]] == ea, "new feature collision")
            extra[ea["key"]] = ea
        for role, q, e in (("aa", qa, ea), ("ab", qa, eb), ("ba", qb, ea), ("bb", qb, eb)):
            out["variants"].append({"role": role, "question_key": q["key"], "evidence_key": e["key"]})
        result.append(out)
    c.require(before == c.digest([original, selected, inventory]), "input mutated")
    return {"schema": PROFILE + ".inputs", "units": result,
            "additional_features": [extra[k] for k in sorted(extra)],
            "original_public_plan_sha256": c.digest(original), "selected_pair_plan_sha256": c.digest(selected),
            "inventory_sha256": c.digest(inventory), "score_order": list(ORDER),
            "new_optimizer_updates": 0, "new_donor_selection": False,
            "crossed_negative_semantics": "weak_original_cross_family_pair_not_certified_false",
            "semantic_accuracy": None, "production_accepted": False}


def interaction(scores):
    c.require(isinstance(scores, list) and len(scores) == 4
              and all(c.finite(x, -1e12, 1e12) for x in scores), "invalid four-corner logits")
    aa, ab, ba, bb = scores
    own_q, donor_q = aa-ba, bb-ab
    own_e, donor_e = aa-ab, bb-ba
    return {"interaction": math.fsum([aa, -ab, -ba, bb]),
            "own_evidence_question_margin": own_q, "donor_evidence_question_margin": donor_q,
            "own_question_evidence_margin": own_e, "donor_question_evidence_margin": donor_e,
            "both_question_rankings": own_q > 0 and donor_q > 0,
            "both_evidence_rankings": own_e > 0 and donor_e > 0,
            "all_four_threshold_directions": aa > 0 and bb > 0 and ab < 0 and ba < 0,
            "semantic_accuracy": None, "reader_adequacy_established": False}


def summarize(units, predictions):
    planned, observed = index(units, "pair_id"), index(predictions, "pair_id")
    c.require(planned and set(planned) == set(observed), "changed crossed denominator")
    values, families, missing, failed = [], defaultdict(list), 0, 0
    for key, unit in planned.items():
        row = observed[key]
        if unit["status"] != "available":
            c.require(row["status"] == "unavailable" and row["logits"] is None, "unavailable pair imputed")
            missing += 1
        elif row["status"] == "failed":
            c.require(row["logits"] is None, "failed pair became logits")
            failed += 1
        else:
            c.require(row["status"] == "succeeded", "unregistered prediction state")
            value = interaction(row["logits"])
            values.append(value); families[unit["family"]].append(value["interaction"])
    means = [math.fsum(v)/len(v) for v in families.values()]
    return {"planned_pairs": len(planned), "scored_pairs": len(values), "unavailable_pairs": missing,
            "failed_pairs": failed, "families": len(families),
            "mean_interaction": math.fsum(v["interaction"] for v in values)/len(values) if values else None,
            "family_macro_interaction": math.fsum(means)/len(means) if means else None,
            "positive_interactions": sum(v["interaction"] > 0 for v in values),
            **{k: sum(v[k] for v in values) for k in ("both_question_rankings", "both_evidence_rankings", "all_four_threshold_directions")},
            "means_conditional_on_scoring": True, "confidence_interval": None,
            "semantic_accuracy": None, "independent_confirmation": False, "production_accepted": False}
