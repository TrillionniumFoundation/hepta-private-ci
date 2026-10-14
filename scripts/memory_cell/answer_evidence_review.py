"""Post-generation evidence review of a pinned SELECT run, with no new model calls.

Review packets omit arm/condition/reference labels; a separate custodian map
retains every original slot. Masking does not prove reviewer independence.
Empty templates, missing reviews and disagreements never become model approval.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import hmac
import math
import os
from pathlib import Path
import secrets

import five_causal_experiments as c
import reader_content_swap as control

PROFILE = "hepta.reader.answer-evidence-review.v1"
ARTIFACT_ID = 11863981474
ARCHIVE_SHA = "aeb4113b6d2baace0a042f960876861c78b5449b6d9dac404dee2e5c041e46fa"
EXECUTED_SOURCE = "1672d4b3debb65bf0d7198464d9dc0c55811f08e"
RAW_SHA = "df6b77484d73ceda023e946d791d8244d1777506eeaf211a5c450a7dc8280adf"
INVENTORY_SHA = "fc825d382b1686f47efa4aa40c7d366b1f9f3a80457b78412dde7dcccea73ba5"
ARMS = ("frozen_reader", "aligned_8", "shuffled_8")
CONDITIONS = ("own_sources", "donor_sources", "empty")
QUALITY_FIELDS = ("response_kind", "correctness", "grounding")
ALLOWED = {
    "response_kind": ("answer", "abstention", "other"),
    "correctness": ("correct", "partially_correct", "incorrect", "unassessable"),
    "grounding": ("supported", "mixed", "unsupported", "unassessable"),
}
RUBRIC = {
    "first_pass": "Judge source sufficiency from question and delivered evidence BEFORE reading answers. Save evidence-pass.json first.",
    "sufficient": "Delivered sources suffice to answer the question; cite exact evidence spans. Session time is not automatically event time.",
    "insufficient": "Important information is missing or sources do not establish the requested fact. Nonempty input alone is not sufficient.",
    "uncertain": "Use when source completeness or interpretation cannot be determined; do not invent facts or consult other packets.",
    "second_pass": "Read answer bytes unchanged. Judge correctness and evidence support separately; fluent paraphrases need not match a reference string.",
    "grounding": "Supported substantive answers need source quotes. Quotes bind provenance, but software cannot verify entailment.",
    "abstention": "Use abstention only when no substantive answer or unsupported factual assertion is made. Evaluate partial answers as answers.",
    "limits": "No arm, hidden reference, candidate score or donor label is supplied. An outside independent owner must authorize reviewers; this packet is not authorization.",
}


def key(row):
    return row["question_id"], row["condition"]


def opaque(secret, domain, value):
    c.require(isinstance(secret, bytes) and len(secret) >= 32, "fresh 32-byte masking secret required")
    return hmac.new(secret, domain.encode() + b"\0" + c.canonical(value), hashlib.sha256).hexdigest()


def build_packet(cases, raw, *, secret):
    """Exact source join and deduplication, not score-based selection.

    A unique input is reviewed once for sufficiency; identical input+answer
    bytes are reviewed once for quality, with all trial multiplicities private.
    """
    c.require(isinstance(cases, list) and 0 < len(cases) <= 96, "bounded public cases required")
    inputs = {}
    for row in cases:
        c.require(set(row) == {"question_id", "family", "split", "condition", "request"}
                  and row["split"] == "select" and row["condition"] in CONDITIONS
                  and isinstance(row["question_id"], str) and row["question_id"], "public case identity")
        c.require(key(row) not in inputs, "duplicate public case")
        if row["request"] is not None:
            c.validate_public(row["request"])
        inputs[key(row)] = row
    questions = {r["question_id"] for r in cases}
    c.require(set(inputs) == {(q, condition) for q in questions for condition in CONDITIONS}, "missing planned condition")
    c.require(isinstance(raw, list) and len(raw) == len(inputs) * len(ARMS), "raw slot denominator differs")
    contexts, answers, slots, seen, trial_ids = {}, {}, [], set(), set()
    for row in raw:
        arm, ident = row.get("arm"), key(row)
        c.require(arm in ARMS and ident in inputs and (arm, ident) not in seen, "duplicate or unregistered result")
        seen.add((arm, ident))
        c.require(c.sha(row.get("trial_id")) and row["trial_id"] not in trial_ids, "trial identity invalid")
        trial_ids.add(row["trial_id"])
        original = inputs[ident]
        c.require(row["split"] == "select" and row["family"] == original["family"], "source family changed")
        req = original["request"]
        slot = {k: row[k] for k in ("trial_id", "question_id", "family", "split", "condition", "arm", "status")}
        slot.update(context_id=None, answer_id=None, public_request_sha256=None, answer_sha256=None)
        if req is not None:
            cid = opaque(secret, "context", req)
            contexts[cid] = {"context_id": cid, "request": deepcopy(req)}
            slot.update(context_id=cid, public_request_sha256=c.digest(req))
        if row["status"] == "succeeded":
            c.require(req is not None and row.get("public_request_sha256") == c.digest(req), "answer/input binding differs")
            c.require(isinstance(row.get("answer"), str) and len(row["answer"].encode()) <= 131072, "raw answer invalid")
            c.require(row.get("evidence_ids") == [e["id"] for e in req["evidence"]], "delivered citation IDs changed")
            aid = opaque(secret, "answer", [req, row["answer"]])
            answers[aid] = {"answer_id": aid, "context_id": cid, "answer": row["answer"]}
            slot.update(answer_id=aid, answer_sha256=c.digest(row["answer"]))
        else:
            c.require(row["status"] in ("unavailable_recipient_annotation_or_source", "failed", "blocked_model",
                                        "not_executed", "timeout_with_observed_output"), "unknown execution status")
            # Failed/timeout bytes stay only in the immutable original artifact;
            # they are not silently admitted as successful answers for review.
        slots.append(slot)
    ordered_slots = sorted(slots, key=lambda r: r["trial_id"])
    packet = {"schema": PROFILE, "rubric": RUBRIC, "assignment_commitment": c.digest(ordered_slots),
              "contexts": [contexts[k] for k in sorted(contexts)],
              "answers": [answers[k] for k in sorted(answers)]}
    binding = {"schema": PROFILE + ".custodian", "packet_sha256": c.digest(packet), "slots": ordered_slots,
               "raw_canonical_sha256": c.digest(raw), "cases_canonical_sha256": c.digest(cases),
               "masking_secret_exported": False, "reviewer_independence_verified": False}
    validate_link(packet, binding)
    return packet, binding


def validate_link(packet, binding):
    c.require(packet.get("schema") == PROFILE and binding.get("schema") == PROFILE + ".custodian"
              and binding.get("packet_sha256") == c.digest(packet), "review packet digest mismatch")
    c.require(c.sha(packet.get("assignment_commitment")) and c.digest(binding["slots"]) == packet["assignment_commitment"],
              "custodian assignment commitment changed")
    c.require(len({s["trial_id"] for s in binding["slots"]}) == len(binding["slots"]), "duplicate custodian trial")
    contexts = {x["context_id"]: x for x in packet["contexts"]}
    answers = {x["answer_id"]: x for x in packet["answers"]}
    c.require(len(contexts) == len(packet["contexts"]) and len(answers) == len(packet["answers"]), "duplicate packet identity")
    for item in answers.values():
        c.require(item["context_id"] in contexts, "answer context missing")
    for slot in binding["slots"]:
        c.require(slot["arm"] in ARMS and slot["split"] == "select" and slot["condition"] in CONDITIONS, "invalid custodian slot")
        if slot["context_id"] is not None:
            c.require(slot["context_id"] in contexts and c.digest(contexts[slot["context_id"]]["request"]) ==
                      slot["public_request_sha256"], "custodian context changed")
        if slot["status"] == "succeeded":
            a = answers.get(slot["answer_id"])
            c.require(a is not None and a["context_id"] == slot["context_id"]
                      and c.digest(a["answer"]) == slot["answer_sha256"], "custodian answer changed")
        else:
            c.require(slot["answer_id"] is None, "failed slot is not a successful answer")
    c.require({s["answer_id"] for s in binding["slots"] if s["answer_id"]} == set(answers), "orphan answer")
    return contexts, answers


def templates(packet):
    pin = c.digest(packet)
    evidence = {"schema": PROFILE + ".evidence-pass", "packet_sha256": pin, "reviewer_id": None,
                "contexts": [{"context_id": r["context_id"], "sufficiency": None, "quotes": [], "rationale": None}
                             for r in packet["contexts"]]}
    answer = {"schema": PROFILE + ".answer-pass", "packet_sha256": pin, "reviewer_id": None,
              "evidence_pass_sha256": None,
              "answers": [{"answer_id": r["answer_id"], **{k: None for k in QUALITY_FIELDS},
                           "quotes": [], "rationale": None} for r in packet["answers"]]}
    return evidence, answer


def check_quotes(quotes, request):
    c.require(isinstance(quotes, list) and len(quotes) <= 64, "bounded evidence quotes required")
    sources = {e["id"]: e["text"] for e in request["evidence"]}
    for quote in quotes:
        c.require(isinstance(quote, dict) and set(quote) == {"source_id", "start", "end", "text"}, "quote fields")
        sid, start, end = quote["source_id"], quote["start"], quote["end"]
        c.require(sid in sources and type(start) is int and type(end) is int
                  and 0 <= start < end <= len(sources[sid]) and sources[sid][start:end] == quote["text"],
                  "quote is not an exact delivered-source span")


def validate_review(packet, evidence, answers):
    pin = c.digest(packet)
    c.require(evidence.get("schema") == PROFILE + ".evidence-pass"
              and answers.get("schema") == PROFILE + ".answer-pass"
              and evidence.get("packet_sha256") == answers.get("packet_sha256") == pin,
              "review belongs to another packet")
    who = evidence.get("reviewer_id")
    c.require(c.text_id(who) and answers.get("reviewer_id") == who
              and answers.get("evidence_pass_sha256") == c.digest(evidence), "reviewer or evidence-first binding missing")
    contexts = {x["context_id"]: x["request"] for x in packet["contexts"]}
    candidates = {x["answer_id"]: x for x in packet["answers"]}
    ev, ans = {}, {}
    for row in evidence["contexts"]:
        c.require(set(row) == {"context_id", "sufficiency", "quotes", "rationale"}
                  and row["context_id"] in contexts and row["context_id"] not in ev, "evidence review census")
        c.require(row["sufficiency"] in ("sufficient", "insufficient", "uncertain"), "ungraded sufficiency")
        req = contexts[row["context_id"]]
        check_quotes(row["quotes"], req)
        c.require(isinstance(row["rationale"], str) and 0 < len(row["rationale"].strip()) <= 8192, "evidence rationale required")
        if row["sufficiency"] == "sufficient":
            c.require(bool(row["quotes"]), "sufficiency must cite delivered evidence")
        ev[row["context_id"]] = row
    c.require(set(ev) == set(contexts), "incomplete evidence review")
    for row in answers["answers"]:
        c.require(set(row) == {"answer_id", *QUALITY_FIELDS, "quotes", "rationale"}
                  and row["answer_id"] in candidates and row["answer_id"] not in ans, "answer review census")
        c.require(all(row[k] in ALLOWED[k] for k in QUALITY_FIELDS), "ungraded answer")
        req = contexts[candidates[row["answer_id"]]["context_id"]]
        check_quotes(row["quotes"], req)
        c.require(isinstance(row["rationale"], str) and 0 < len(row["rationale"].strip()) <= 8192, "answer rationale required")
        if row["response_kind"] == "answer" and row["grounding"] == "supported":
            c.require(bool(row["quotes"]), "supported substantive answer requires source spans")
        ans[row["answer_id"]] = row
    c.require(set(ans) == set(candidates), "incomplete answer review")
    return who, ev, ans


def review_digest(evidence, answers):
    return c.digest({"evidence": evidence, "answers": answers})


def summarize_reviews(packet, binding, reviews, pins):
    """Require independently supplied pins, but never claim human authentication.

    This is a descriptive review agreement report, NOT the external Reader gate.
    A pin cannot prove that two accounts are different independent humans.
    """
    validate_link(packet, binding)
    c.require(len(reviews) == len(pins) == 2 and all(c.sha(p) for p in pins), "two external review pins required")
    parsed = []
    for (evidence, answers), pin in zip(reviews, pins):
        c.require(hmac.compare_digest(review_digest(evidence, answers), pin), "review pin mismatch")
        parsed.append(validate_review(packet, evidence, answers))
    c.require(parsed[0][0] != parsed[1][0], "review identities must differ")
    counts = defaultdict(Counter)
    for slot in binding["slots"]:
        row = counts[(slot["arm"], slot["condition"])]
        row["planned"] += 1
        if slot["status"] != "succeeded":
            row["unavailable_or_failed"] += 1
            continue
        cid, aid = slot["context_id"], slot["answer_id"]
        ev = [x[1][cid]["sufficiency"] for x in parsed]
        ans = [x[2][aid] for x in parsed]
        row["reviewed_successful_slots"] += 1
        agree = ev[0] == ev[1] and all(ans[0][k] == ans[1][k] for k in QUALITY_FIELDS)
        if not agree:
            row["disagreement"] += 1
            continue
        a = ans[0]
        row["categorical_agreement"] += 1
        if ev[0] == "sufficient" and a["response_kind"] == "answer" and a["correctness"] == "correct" and a["grounding"] == "supported":
            row["agreed_correct_supported_answer"] += 1
        elif ev[0] == "insufficient" and a["response_kind"] == "abstention":
            row["agreed_appropriate_abstention"] += 1
        else:
            row["other_or_unassessable"] += 1
    fields = ("planned", "unavailable_or_failed", "reviewed_successful_slots", "disagreement", "categorical_agreement",
              "agreed_correct_supported_answer", "agreed_appropriate_abstention", "other_or_unassessable")
    return {"schema": PROFILE + ".agreement", "packet_sha256": c.digest(packet),
            "review_pins": pins, "rows": [{"arm": arm, "condition": condition, **{f: count[f] for f in fields}}
                                          for (arm, condition), count in sorted(counts.items())],
            "reviewer_independence_verified": False, "formal_reader_gate_issued": False,
            "reader_adequacy_established": False, "production_accepted": False,
            "confidence_interval": None, "missing_slots_not_imputed": True}


def decompose(by_arm):
    """I = own-margin minus donor-margin; neither component is semantic accuracy."""
    c.require(set(by_arm) == set(ARMS), "three frozen model audits required")
    lookup = {}
    for arm, rows in by_arm.items():
        index = {}
        for r in rows:
            c.require(r["split"] == "select" and r["question_id"] not in index, "audit identity mismatch")
            index[r["question_id"]] = r
        lookup[arm] = index
    ids = set(lookup[ARMS[0]])
    c.require(ids and all(set(x) == ids for x in lookup.values()), "audit denominators differ")
    records = []
    for qid in sorted(ids):
        base = lookup["frozen_reader"][qid]
        for arm in ARMS[1:]:
            candidate = lookup[arm][qid]
            c.require(all(candidate[k] == base[k] for k in ("family", "split", "donor_question_id")), "paired donor differs")
            record = {"question_id": qid, "family": base["family"], "candidate": arm,
                      "baseline": "frozen_reader", "status": "unavailable_or_failed"}
            if base["status"] == candidate["status"] == "succeeded":
                original, changed = [], []
                for r, dest in ((base, original), (candidate, changed)):
                    scores = r["audit"]["mean_response_logp"]
                    c.require(set(scores) == set(control.ORDER), "four score names differ")
                    dest.extend(scores[k] for k in control.ORDER)
                    computed = control.interaction(dest)
                    c.require(math.isclose(computed["difference_in_differences"], r["audit"]["difference_in_differences"],
                                           rel_tol=1e-10, abs_tol=1e-10), "stored interaction not reproducible")
                da, db, dx, dy = [b-a for a, b in zip(original, changed)]
                record.update(status="succeeded", own_answer_logp_change=da, rival_own_logp_change=db,
                    own_margin_change=da-db, donor_margin_change=dx-dy, interaction_change=(da-db)-(dx-dy),
                    candidate_own_answer_margin=changed[0]-changed[1], baseline_own_answer_margin=original[0]-original[1],
                    candidate_own_answer_preferred=changed[0] > changed[1])
            records.append(record)
    summaries = []
    fields = ("own_answer_logp_change", "rival_own_logp_change", "own_margin_change", "donor_margin_change", "interaction_change")
    for arm in ARMS[1:]:
        all_rows = [r for r in records if r["candidate"] == arm]
        valid = [r for r in all_rows if r["status"] == "succeeded"]
        families = defaultdict(list)
        for r in valid:
            families[r["family"]].append(r)
        means = {f: math.fsum(r[f] for r in valid)/len(valid) if valid else None for f in fields}
        macro = {f: math.fsum(math.fsum(r[f] for r in rs)/len(rs) for rs in families.values())/len(families)
                 if families else None for f in fields}
        summaries.append({"candidate": arm, "planned": len(all_rows), "scored": len(valid),
                          "task_means": means, "family_macro_means": macro,
                          "own_answer_preferred": sum(r["candidate_own_answer_preferred"] for r in valid)})
    return {"schema": PROFILE + ".decomposition", "records": records, "summaries": summaries,
            "new_model_calls": 0, "post_hoc_descriptive": True, "semantic_accuracy": None,
            "reader_adequacy_established": False, "production_accepted": False}


def run(archive, work, output):
    from reader_content_swap_trial import extract_verified
    root, verified = extract_verified(archive, work, ARCHIVE_SHA)
    c.require((root/"source/tested-commit.txt").read_text().strip() == EXECUTED_SOURCE, "wrong completed source")
    study = root/"study"
    report, plan = c.load(study/"report.json"), c.load(study/"plan.json")
    c.require(report.get("schema") == "hepta.reader.select-content-validation-result.v1"
              and report.get("errors") == [] and report.get("plan_sha256") == c.digest(plan)
              and set(report["arms"]) == set(ARMS), "completed study identity differs")
    c.require(c.file_sha(study/"raw-answers.json") == report["raw_sha256"] == RAW_SHA
              and c.file_sha(study/"inventory-plan.json") == report["inventory_sha256"] == INVENTORY_SHA, "input seals differ")
    raw, cases = c.load(study/"raw-answers.json"), c.load(study/"public-inputs.json")
    inv = c.load(study/"inventory-plan.json")
    c.require(cases == inv["public_cases"] and c.digest(cases) == inv["complete_public_cases_sha256"], "inventory/input mismatch")
    c.require(len(raw) == report["planned_generation_rows"] and sum(x["status"] == "succeeded" for x in raw) ==
              report["successful_model_calls"], "saved execution denominator differs")
    for arm in ARMS:
        rows = c.load(study/(arm+"-raw.json"))
        seal = c.load(study/(arm+"-raw-seal.json"))
        c.require(c.file_sha(study/(arm+"-raw.json")) == seal["sha256"] and seal["before_teacher_forcing"] is True
                  and rows == [x for x in raw if x["arm"] == arm], "arm generation seal differs")
    packet, binding = build_packet(cases, raw, secret=secrets.token_bytes(32))
    binding.update(source_artifact_id=ARTIFACT_ID, source_archive_sha256=ARCHIVE_SHA,
                   raw_file_sha256=RAW_SHA, executed_source=EXECUTED_SOURCE)
    evidence, answers = templates(packet)
    decomposition = decompose({arm: c.load(study/(arm+"-content-audit.json")) for arm in ARMS})
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    # Export separately. Seeing custodian/ or the original study can unblind a reviewer.
    c.write_new(output/"evidence-first/contexts.json", {"schema": PROFILE, "packet_sha256": c.digest(packet),
                "rubric": RUBRIC, "contexts": packet["contexts"]})
    c.write_new(output/"evidence-first/evidence-pass-template.json", evidence)
    c.write_new(output/"answer-second/packet.json", packet)
    c.write_new(output/"answer-second/answer-pass-template.json", answers)
    c.write_new(output/"custodian/assignment-map.json", binding)
    c.write_new(output/"custodian/decomposition.json", decomposition)
    inputs = {key(x): x for x in cases}
    inspection = [{"arm": row["arm"], "question_id": row["question_id"], "condition": row["condition"],
                   "status": row["status"], "request": inputs[key(row)]["request"], "answer": row.get("answer")}
                  for row in raw]
    c.write_new(output/"custodian/raw-inspection.json", inspection)
    summary = {"schema": PROFILE + ".preparation", "verified_input": verified,
               "planned_slots": len(raw), "successful_slots": sum(row["status"] == "succeeded" for row in raw),
               "unique_contexts": len(packet["contexts"]), "unique_answer_reviews": len(packet["answers"]),
               "packet_sha256": c.digest(packet), "new_model_calls": 0, "new_optimizer_updates": 0,
               "reviews_received": 0, "independent_semantic_result": None, "formal_reader_gate_issued": False,
               "production_accepted": False}
    c.write_new(output/"custodian/summary.json", summary)
    print("ANSWER_REVIEW_PREPARATION", c.canonical(summary).decode(), flush=True)
    print("CONTENT_DECOMPOSITION", c.canonical(decomposition).decode(), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("archive", type=Path)
    prepare.add_argument("--work", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    grade = commands.add_parser("agreement")
    for field in ("packet", "binding", "evidence-a", "answers-a", "evidence-b", "answers-b", "output"):
        grade.add_argument("--"+field, type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        run(args.archive, args.work, args.output)
    else:
        reviews = [(c.load(args.evidence_a), c.load(args.answers_a)), (c.load(args.evidence_b), c.load(args.answers_b))]
        result = summarize_reviews(c.load(args.packet), c.load(args.binding), reviews,
                                   [os.environ.get("HEPTA_ANSWER_REVIEW_PIN_A"), os.environ.get("HEPTA_ANSWER_REVIEW_PIN_B")])
        c.write_new(args.output, result)


if __name__ == "__main__":
    main()
