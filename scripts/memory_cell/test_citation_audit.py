"""Boundary/interop tests, not independent semantic acceptance evidence."""
import copy
import unittest
from types import SimpleNamespace

from citation_audit import capture, judgement_payload, request_payload, sha, validate_judgement


def request(answer="The code is blue [E1]."):
    return {"query_id": "q.1", "scope": "scope.1", "experiment_digest": sha(b"experiment"),
            "family_digest": sha(b"family"), "prompt_digest": sha(b"prompt"),
            "question": "Which code?", "question_time": "2026-10-09T00:00:00Z", "answer": answer,
            "sources": [{"label": "E1", "id": "session.1", "root": sha(b"root"), "excerpt": "[E1] The code is blue."}]}


def judgement(answer="The code is blue [E1].", verdict="entailed", kind="factual"):
    raw = answer.encode("utf-8")
    return {"claims": [{"start": 0, "end": len(raw), "kind": kind}],
            "citations": [{"start": raw.index(b"[E1]"), "verdict": verdict}] if b"[E1]" in raw else []}


class CitationAuditTests(unittest.TestCase):
    def test_exact_binary_interchange_vector(self):
        self.assertEqual(sha(request_payload(request())), "6dba246cd74c04aaecd3d818feb5b9d3f7cdc4d4c71b1b44a26b634e35766d91")
        self.assertEqual(sha(judgement_payload(request(), judgement())), "c0f934320b8f6a5493d8bb60f96803178e46199a5096c89fb242bafa5d023f18")

    def test_reference_existence_never_means_entailment(self):
        observed = validate_judgement(request(), judgement(verdict="unsupported"), revoked_roots=set())
        self.assertEqual(observed["diagnostic_precision_ppm"], 0)
        self.assertFalse(observed["signed_evaluator_verified"])
        self.assertFalse(observed["production_accepted"])

    def test_unjudged_reference_remains_in_denominator(self):
        observed = validate_judgement(request(), judgement(verdict="unreviewed"), revoked_roots=set())
        self.assertEqual(observed["unreviewed_citations"], 1)
        self.assertEqual(observed["diagnostic_precision_ppm"], 0)

    def test_answer_omission_overlap_and_utf8_boundary_reject(self):
        for claims in (
            [{"start": 1, "end": 21, "kind": "factual"}],
            [{"start": 0, "end": 18, "kind": "factual"}],
            [{"start": 0, "end": 21, "kind": "factual"}, {"start": 0, "end": 1, "kind": "factual"}],
        ):
            value = judgement()
            value["claims"] = claims
            with self.assertRaises(ValueError):
                validate_judgement(request(), value, revoked_roots=set())
        answer = "蓝色 [E1]"
        value = judgement(answer)
        value["claims"][0]["start"] = 1
        with self.assertRaises(ValueError):
            validate_judgement(request(answer), value, revoked_roots=set())

    def test_missing_duplicate_and_misordered_citations_reject(self):
        for citations in ([], judgement()["citations"] * 2, [{"start": 0, "verdict": "entailed"}]):
            value = judgement()
            value["citations"] = citations
            with self.assertRaises(ValueError):
                validate_judgement(request(), value, revoked_roots=set())

    def test_undelivered_or_revoked_evidence_cannot_support_claim(self):
        value = request()
        value["sources"] = []
        with self.assertRaises(ValueError):
            validate_judgement(value, judgement(), revoked_roots=set())
        with self.assertRaises(ValueError):
            validate_judgement(request(), judgement(), revoked_roots={sha(b"root")})
        with self.assertRaises(ValueError):
            validate_judgement(request(), judgement(), revoked_roots=None)

    def test_citations_cannot_be_hidden_in_nonfactual_spans(self):
        for kind in ("nonfactual", "abstention", "unreviewed"):
            with self.assertRaises(ValueError):
                validate_judgement(request(), judgement(kind=kind), revoked_roots=set())

    def test_abstention_is_not_perfect_citation_precision(self):
        answer = "I do not know"
        observed = validate_judgement(request(answer), judgement(answer, kind="abstention"), revoked_roots=set())
        self.assertIsNone(observed["diagnostic_precision_ppm"])
        self.assertEqual(observed["factual_claims"], 0)

    def test_repeated_citations_are_distinct_occurrences(self):
        answer = "Blue [E1]; blue [E1]."
        value = judgement(answer)
        value["citations"].append({"start": answer.rindex("[E1]"), "verdict": "unsupported"})
        observed = validate_judgement(request(answer), value, revoked_roots=set())
        self.assertEqual(observed["citations"], 2)
        self.assertEqual(observed["diagnostic_precision_ppm"], 500_000)

    def test_all_answer_and_input_mutations_change_signed_payload(self):
        raw = request_payload(request())
        for field, value in (("answer", "not blue [E1]"), ("question", "Which account?"),
                             ("family_digest", sha(b"other family")), ("prompt_digest", sha(b"other prompt"))):
            record = request()
            record[field] = value
            self.assertNotEqual(raw, request_payload(record))
        record = request()
        record["sources"][0]["excerpt"] = "[E1] The code is red."
        self.assertNotEqual(raw, request_payload(record))

    def test_duplicate_sources_and_unbounded_or_noncanonical_input_reject(self):
        for modify in (
            lambda r: r["sources"].append(copy.deepcopy(r["sources"][0])),
            lambda r: r.update(answer="x" * 65537),
            lambda r: r.update(prompt_digest="0" * 64),
            lambda r: r.update(extra="undeclared"),
        ):
            record = request()
            modify(record)
            with self.assertRaises(ValueError):
                request_payload(record)

    def test_capture_has_no_gold_verdict_or_signature_default(self):
        record = request()
        q = SimpleNamespace(identity=record["query_id"], scope=record["scope"], content=record["question"], observed_at=record["question_time"])
        result = capture(q, record["answer"], {"input_ids_sha256": record["prompt_digest"], "delivered_evidence": record["sources"]},
                         experiment_digest=record["experiment_digest"], family_digest=record["family_digest"])
        self.assertEqual(result["request_sha256"], sha(request_payload(record)))
        self.assertIsNone(result["judgement"])
        self.assertIsNone(result["semantic_precision"])
        self.assertIsNone(result["generator_signature"])
        self.assertIsNone(result["evaluator_signature"])
