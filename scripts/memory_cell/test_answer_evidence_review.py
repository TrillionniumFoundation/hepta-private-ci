"""Hermetic answer-review tests. Fake grades are fixtures, never human evidence."""
from copy import deepcopy
import unittest

import five_causal_experiments as c
import answer_evidence_review as r


def fixture():
    own = {"question": "Where is the fixture?", "options": [], "evidence": [
        {"id": "S1", "position": 0, "modality": "text", "asset_sha256": None, "text": "The fixture is in Paris."}]}
    donor = deepcopy(own); donor["evidence"][0]["text"] = "The other fixture is in Rome."
    cases = []
    for q in ("q0", "q1"):
        for condition, request in (("own_sources", own), ("donor_sources", donor if q == "q0" else None),
                                   ("empty", own | {"evidence": []})):
            cases.append({"question_id": q, "family": "family-"+q, "split": "select",
                          "condition": condition, "request": deepcopy(request)})
    raw = []
    for arm in r.ARMS:
        for case in cases:
            request = case["request"]
            row = {k: case[k] for k in ("question_id", "family", "split", "condition")}
            row.update(arm=arm, trial_id=c.digest([arm, row]),
                       status="succeeded" if request is not None else "unavailable_recipient_annotation_or_source",
                       answer=None if request is None else ("No evidence." if not request["evidence"] else "Paris [S1]"),
                       evidence_ids=[] if request is None else [e["id"] for e in request["evidence"]])
            if request is not None:
                row["public_request_sha256"] = c.digest(request)
            raw.append(row)
    return cases, raw


def packet():
    cases, raw = fixture()
    return r.build_packet(cases, raw, secret=b"x"*32)


def grade(p, reviewer):
    evidence, answers = r.templates(p)
    evidence["reviewer_id"] = answers["reviewer_id"] = reviewer
    contexts = {x["context_id"]: x["request"] for x in p["contexts"]}
    candidates = {x["answer_id"]: x for x in p["answers"]}
    def quote(req):
        source = req["evidence"][0]
        return [{"source_id": source["id"], "start": 0, "end": len(source["text"]), "text": source["text"]}]
    for row in evidence["contexts"]:
        req = contexts[row["context_id"]]
        row.update(sufficiency="sufficient" if req["evidence"] else "insufficient", rationale="Fixture judgment only.",
                   quotes=quote(req) if req["evidence"] else [])
    answers["evidence_pass_sha256"] = c.digest(evidence)
    for row in answers["answers"]:
        req = contexts[candidates[row["answer_id"]]["context_id"]]
        row.update(response_kind="answer" if req["evidence"] else "abstention", correctness="correct",
                   grounding="supported" if req["evidence"] else "unassessable",
                   quotes=quote(req) if req["evidence"] else [], rationale="Fixture, not actual semantic review.")
    return evidence, answers


def audits():
    result = {}
    for arm in r.ARMS:
        rows = []
        for i in range(2):
            values = [-3., -1., -6., -.5] if arm == "frozen_reader" else [-2.5, -.8, -8., -.5]
            rows.append({"question_id": "q"+str(i), "family": "family-"+str(i), "split": "select",
                         "donor_question_id": "d"+str(i), "status": "succeeded",
                         "audit": r.control.interaction(values)})
        result[arm] = rows
    return result


class PacketTests(unittest.TestCase):
    def test_exact_bytes_and_deduplication_keep_all_slots(self):
        cases, raw = fixture(); old = deepcopy((cases, raw))
        p, mapping = r.build_packet(cases, raw, secret=b"x"*32)
        self.assertEqual((cases, raw), old)
        self.assertEqual(len(p["contexts"]), 3)
        self.assertEqual(len(p["answers"]), 3)
        self.assertEqual(len(mapping["slots"]), 18)
        self.assertEqual(sum(s["status"] == "succeeded" for s in mapping["slots"]), 15)
        self.assertEqual({x["answer"] for x in p["answers"]}, {"Paris [S1]", "No evidence."})

    def test_reviewer_fields_hide_arm_condition_reference_and_multiplicity(self):
        p, _ = packet()
        for row in p["contexts"]:
            self.assertEqual(set(row), {"context_id", "request"})
        for row in p["answers"]:
            self.assertEqual(set(row), {"answer_id", "context_id", "answer"})
        for hidden in (*r.ARMS, "donor_question_id", "trial_id", "reference_answer", "multiplicity"):
            self.assertNotIn(hidden, c.canonical(p).decode())

    def test_masking_secret_changes_ids_not_source_or_answer(self):
        cases, raw = fixture()
        a, _ = r.build_packet(cases, raw, secret=b"a"*32)
        b, _ = r.build_packet(cases, raw, secret=b"b"*32)
        self.assertFalse({x["answer_id"] for x in a["answers"]} & {x["answer_id"] for x in b["answers"]})
        self.assertEqual(sorted(c.digest(x["request"]) for x in a["contexts"]), sorted(c.digest(x["request"]) for x in b["contexts"]))

    def test_fixed_secret_is_order_independent(self):
        cases, raw = fixture()
        a = r.build_packet(cases, raw, secret=b"z"*32)
        b = r.build_packet(list(reversed(cases)), list(reversed(raw)), secret=b"z"*32)
        self.assertEqual(a[0], b[0])
        self.assertEqual(a[1]["slots"], b[1]["slots"])

    def rejected(self, transform):
        cases, raw = fixture(); transform(cases, raw)
        with self.assertRaises((c.Invalid, KeyError, TypeError)):
            r.build_packet(cases, raw, secret=b"x"*32)

    def test_missing_raw_slot_rejected(self):
        self.rejected(lambda cases, raw: raw.pop())

    def test_duplicate_result_rejected(self):
        self.rejected(lambda cases, raw: raw.__setitem__(-1, deepcopy(raw[0])))

    def test_unknown_arm_rejected(self):
        self.rejected(lambda cases, raw: raw[0].update(arm="chosen-winner"))

    def test_changed_public_input_hash_rejected(self):
        self.rejected(lambda cases, raw: raw[0].update(public_request_sha256="a"*64))

    def test_changed_delivered_citations_rejected(self):
        self.rejected(lambda cases, raw: raw[0].update(evidence_ids=["not-delivered"]))

    def test_test_partition_rejected(self):
        self.rejected(lambda cases, raw: cases[0].update(split="test"))

    def test_unavailable_cannot_be_fabricated_success(self):
        self.rejected(lambda cases, raw: raw[4].update(status="succeeded", answer="invented"))

    def test_empty_masking_secret_rejected(self):
        cases, raw = fixture()
        with self.assertRaises(c.Invalid): r.build_packet(cases, raw, secret=b"")

    def test_mutated_packet_rejected(self):
        p, m = packet(); p["answers"][0]["answer"] += " changed"
        with self.assertRaises(c.Invalid): r.validate_link(p, m)

    def test_arm_swap_in_custodian_mapping_rejected(self):
        p, m = packet(); m["slots"][0]["arm"] = "other-model"
        with self.assertRaises(c.Invalid): r.validate_link(p, m)

    def test_failed_calls_are_not_reviewed_as_successful_answers(self):
        cases, raw = fixture(); raw[0]["status"] = "timeout_with_observed_output"
        p, m = r.build_packet(cases, raw, secret=b"x"*32)
        failed = next(x for x in m["slots"] if x["trial_id"] == raw[0]["trial_id"])
        self.assertIsNone(failed["answer_id"])
        self.assertEqual(len(m["slots"]), 18)


class ReviewTests(unittest.TestCase):
    def test_unfilled_templates_are_not_reviews(self):
        p, _ = packet()
        with self.assertRaises(c.Invalid): r.validate_review(p, *r.templates(p))

    def test_valid_fixture_review_and_non_authority(self):
        p, m = packet(); reviews = [grade(p, "fixture-a"), grade(p, "fixture-b")]
        report = r.summarize_reviews(p, m, reviews, [r.review_digest(*x) for x in reviews])
        self.assertEqual(sum(x["planned"] for x in report["rows"]), 18)
        self.assertEqual(sum(x["unavailable_or_failed"] for x in report["rows"]), 3)
        self.assertFalse(report["formal_reader_gate_issued"])
        self.assertFalse(report["reviewer_independence_verified"])
        self.assertFalse(report["production_accepted"])

    def test_missing_external_pin_rejected(self):
        p, m = packet(); reviews = [grade(p, "fixture-a"), grade(p, "fixture-b")]
        with self.assertRaises(c.Invalid): r.summarize_reviews(p, m, reviews, [None, None])

    def test_wrong_pin_rejected(self):
        p, m = packet(); reviews = [grade(p, "fixture-a"), grade(p, "fixture-b")]
        with self.assertRaises(c.Invalid): r.summarize_reviews(p, m, reviews, ["a"*64, "b"*64])

    def test_same_review_identity_is_not_two_reviewers(self):
        p, m = packet(); reviews = [grade(p, "fixture-a"), grade(p, "fixture-a")]
        with self.assertRaises(c.Invalid): r.summarize_reviews(p, m, reviews, [r.review_digest(*x) for x in reviews])

    def test_disagreement_never_uses_better_grade(self):
        p, m = packet(); reviews = [grade(p, "fixture-a"), grade(p, "fixture-b")]
        reviews[1][1]["answers"][0]["correctness"] = "incorrect"
        result = r.summarize_reviews(p, m, reviews, [r.review_digest(*x) for x in reviews])
        self.assertGreater(sum(x["disagreement"] for x in result["rows"]), 0)

    def test_missing_evidence_row_rejected(self):
        p, _ = packet(); ev, a = grade(p, "fixture-a"); ev["contexts"].pop(); a["evidence_pass_sha256"] = c.digest(ev)
        with self.assertRaises(c.Invalid): r.validate_review(p, ev, a)

    def test_missing_answer_row_rejected(self):
        p, _ = packet(); ev, a = grade(p, "fixture-a"); a["answers"].pop()
        with self.assertRaises(c.Invalid): r.validate_review(p, ev, a)

    def test_stale_evidence_pass_hash_rejected(self):
        p, _ = packet(); ev, a = grade(p, "fixture-a"); ev["contexts"][0]["rationale"] = "Edited"
        with self.assertRaises(c.Invalid): r.validate_review(p, ev, a)

    def test_invented_quote_rejected(self):
        request = fixture()[0][0]["request"]
        with self.assertRaises(c.Invalid):
            r.check_quotes([dict(source_id="S1", start=0, end=3, text="LIE")], request)

    def test_quote_must_use_delivered_source(self):
        request = fixture()[0][0]["request"]
        with self.assertRaises(c.Invalid):
            r.check_quotes([dict(source_id="S9", start=0, end=3, text="The")], request)

    def test_quote_offsets_cannot_be_boolean(self):
        request = fixture()[0][0]["request"]
        with self.assertRaises(c.Invalid):
            r.check_quotes([dict(source_id="S1", start=False, end=3, text="The")], request)

    def test_supported_substantive_answer_requires_quote(self):
        p, _ = packet(); ev, a = grade(p, "fixture-a")
        next(x for x in a["answers"] if x["response_kind"] == "answer")["quotes"] = []
        with self.assertRaises(c.Invalid): r.validate_review(p, ev, a)

    def test_empty_context_cannot_be_called_sufficient_without_evidence(self):
        p, _ = packet(); ev, a = grade(p, "fixture-a")
        next(x for x in ev["contexts"] if x["sufficiency"] == "insufficient")["sufficiency"] = "sufficient"
        a["evidence_pass_sha256"] = c.digest(ev)
        with self.assertRaises(c.Invalid): r.validate_review(p, ev, a)


class DecompositionTests(unittest.TestCase):
    def test_positive_interaction_does_not_imply_own_answer_preferred(self):
        result = r.decompose(audits())
        for row in result["records"]:
            self.assertGreater(row["interaction_change"], 0)
            self.assertFalse(row["candidate_own_answer_preferred"])
            self.assertAlmostEqual(row["interaction_change"], row["own_margin_change"]-row["donor_margin_change"])
        self.assertEqual(result["new_model_calls"], 0)

    def test_wrong_donor_cannot_be_paired(self):
        data = audits(); data["aligned_8"][0]["donor_question_id"] = "other"
        with self.assertRaises(c.Invalid): r.decompose(data)

    def test_missing_pair_not_imputed_zero(self):
        data = audits()
        for rows in data.values(): rows[0].update(status="unavailable", audit=None)
        result = r.decompose(data)
        self.assertEqual(result["summaries"][0]["planned"], 2)
        self.assertEqual(result["summaries"][0]["scored"], 1)
        self.assertNotIn("interaction_change", result["records"][0])

    def test_corrupt_interaction_fails(self):
        data = audits(); data["aligned_8"][0]["audit"]["difference_in_differences"] = 1000
        with self.assertRaises(c.Invalid): r.decompose(data)

    def test_nonfinite_score_fails(self):
        data = audits(); data["aligned_8"][0]["audit"]["mean_response_logp"][r.control.ORDER[0]] = float("nan")
        with self.assertRaises(c.Invalid): r.decompose(data)

    def test_different_denominator_fails(self):
        data = audits(); data["aligned_8"].pop()
        with self.assertRaises(c.Invalid): r.decompose(data)

    def test_family_macro_is_not_unequal_task_weighting(self):
        data = audits()
        result = r.decompose(data)
        for summary in result["summaries"]:
            self.assertEqual(summary["task_means"], summary["family_macro_means"])


if __name__ == "__main__":
    unittest.main()
