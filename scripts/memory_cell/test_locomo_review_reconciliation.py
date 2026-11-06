"""Synthetic review returns are not independent human semantic findings."""

import json
from pathlib import Path
import tempfile
import unittest

import locomo_review_reconciliation as audit
import locomo_sufficiency_worklist as work
from test_locomo_sufficiency_worklist import records


class ReviewReturnTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.packet = self.root / "packet"
        self.packet.mkdir()
        suff, answer = work.make_worklists(*records())
        files = {
            "sufficiency-only.json": dict(
                schema=work.SCHEMA,
                model_answers_in_this_worklist=False,
                reviewer_verdicts_recorded=0,
                review_cases=suff,
            ),
            "answer-and-citation.json": dict(
                schema=work.SCHEMA,
                original_reader_answers_unchanged=True,
                reviewer_verdicts_recorded=0,
                review_cases=answer,
            ),
        }
        shas = {
            name: work.write_once(self.packet / name, data)
            for name, data in files.items()
        }
        shas["manifest.json"] = work.write_once(
            self.packet / "manifest.json",
            dict(
                schema=work.SCHEMA,
                sufficiency_worklist_sha256=shas["sufficiency-only.json"],
                answer_citation_worklist_sha256=shas["answer-and-citation.json"],
                original_public_question_count=16,
                original_model_answers=32,
                original_published_source_family_proxies=2,
                source_sufficiency_decisions=0,
                answer_citation_review_decisions=0,
                independent_human_semantic_judgement=False,
                production_accepted=False,
            ),
        )
        (self.packet / "SHA256SUMS").write_text(
            "".join(f"{shas[name]}  ./{name}\n" for name in sorted(shas))
        )
        self.returns = self.root / "returns"
        audit.templates(self.packet, self.returns)

    def read(self, file):
        return json.loads((self.returns / file).read_text())

    def write(self, file, value):
        (self.returns / file).write_text(json.dumps(value))

    def check(self):
        return audit.reconcile(
            self.packet,
            self.returns / "source-return.json",
            self.returns / "answer-return.json",
        )

    def test_unreviewed_32_case_denominator_is_not_perfect_precision(self):
        result = self.check()
        self.assertEqual(result["questions"], 16)
        for arm in result["arms"].values():
            self.assertEqual(arm["planned"], 16)
            self.assertEqual(arm["citations_emitted"], 16)
            self.assertEqual(arm["citations_unreviewed"], 16)
            self.assertIsNone(arm["unverified_citation_fraction"])
        self.assertIsNone(result["independently_verified_semantic_precision"])
        self.assertFalse(result["production_accepted"])

    def test_verified_bytes_are_not_authenticated_human_semantics(self):
        src, answer = self.read("source-return.json"), self.read("answer-return.json")
        original = audit.originals(self.packet)[0][0]
        text = original["evidence"][0]["original_text"]
        src["rows"][0].update(
            sufficient=True,
            answer_from_sources="A source-only diagnostic answer",
            spans=[dict(label="E1", start=0, end=len(text.encode()), text=text)],
            reviewer_id="reviewer-claimed-1",
            reviewed_at="2026-10-13T09:00:00+08:00",
        )
        self.write("source-return.json", src)
        answer["source_return_sha256"] = audit.digest_bytes(
            (self.returns / "source-return.json").read_bytes()
        )
        row = answer["rows"][0]
        row.update(
            supported=True,
            chain_complete=True,
            reviewer_id="reviewer-claimed-2",
            reviewed_at="2026-10-13T09:01:00+08:00",
        )
        row["citations"][0].update(
            entailed=True, claim_start=0, claim_end=row["citations"][0]["marker_start"]
        )
        self.write("answer-return.json", answer)
        outcome = self.check()
        self.assertEqual(outcome["arms"]["lexical_k4"]["sufficient"], 1)
        self.assertEqual(outcome["arms"]["lexical_k4"]["claimed_complete_chains"], 1)
        self.assertEqual(outcome["arms"]["lexical_k4"]["citations_claimed_entailed"], 1)
        self.assertFalse(outcome["reviewer_identity_authenticated"])
        self.assertIsNone(outcome["independently_verified_semantic_precision"])

    def test_wrong_return_digest_fails_closed(self):
        answer = self.read("answer-return.json")
        answer["source_return_sha256"] = "0" * 64
        self.write("answer-return.json", answer)
        with self.assertRaises(ValueError):
            self.check()

    def test_row_loss_duplicate_or_reorder_fails(self):
        for mutation in ("missing", "duplicate", "reversed"):
            with self.subTest(mutation=mutation):
                answer = self.read("answer-return.json")
                if mutation == "missing":
                    answer["rows"].pop()
                elif mutation == "duplicate":
                    answer["rows"][1] = answer["rows"][0]
                else:
                    answer["rows"].reverse()
                self.write("answer-return.json", answer)
                with self.assertRaises(ValueError):
                    self.check()
                self.returns.joinpath("answer-return.json").unlink()
                answer = dict(
                    schema=audit.SCHEMA,
                    phase="answer-after-source",
                    authority_authenticated=False,
                    worklist_sha256=audit.originals(self.packet)[2][
                        "answer-and-citation.json"
                    ],
                    source_return_sha256=audit.digest_bytes(
                        (self.returns / "source-return.json").read_bytes()
                    ),
                    rows=[
                        dict(
                            review_id=r["review_id"],
                            supported=None,
                            chain_complete=None,
                            citations=audit.occurrences(r["unedited_reader_answer"]),
                            reviewer_id=None,
                            reviewed_at=None,
                        )
                        for r in audit.originals(self.packet)[1]
                    ],
                )
                self.write("answer-return.json", answer)

    def test_untrusted_authority_claim_is_rejected(self):
        for name in ("source-return.json", "answer-return.json"):
            with self.subTest(name=name):
                data = self.read(name)
                data["authority_authenticated"] = True
                self.write(name, data)
                with self.assertRaises(ValueError):
                    self.check()
                data["authority_authenticated"] = False
                self.write(name, data)

    def test_invalid_utf8_support_and_undelivered_span_fail(self):
        source = dict(evidence=[dict(label="E1", original_text="évidence")])
        for span in (
            dict(label="E1", start=1, end=4, text="vid"),
            dict(label="E9", start=0, end=1, text="x"),
            dict(label="E1", start=0, end=2, text="wrong"),
        ):
            with self.subTest(span=span), self.assertRaises(ValueError):
                audit.bound_support(source, span)

    def test_false_complete_chain_with_unjudged_citation_reject(self):
        ans = self.read("answer-return.json")
        ans["rows"][0].update(
            chain_complete=True,
            reviewer_id="reviewer-declared",
            reviewed_at="2026-10-13T00:00:00Z",
        )
        self.write("answer-return.json", ans)
        with self.assertRaises(ValueError):
            self.check()

    def test_original_packet_tampering_rejects(self):
        p = self.packet / "sufficiency-only.json"
        p.write_bytes(p.read_bytes().replace(b"scopeA", b"scopeZ"))
        with self.assertRaises(ValueError):
            audit.originals(self.packet)


if __name__ == "__main__":
    unittest.main()
