"""Model-free worklist checks. Fixture answers are not research evidence."""

from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest

import locomo_sufficiency_worklist as work


def records():
    cases, docs, selections, answers = [], {}, {}, []
    for n in range(16):
        qid = f"q{n:02d}"
        family = "fA" if n < 8 else "fB"
        scope = "scopeA" if n < 8 else "scopeB"
        keys = []
        for j in range(8):
            sid = f"{scope}/{qid}/s{j}"
            content = f"Evidence for the question: {n}, source {j}."
            docs[sid] = dict(
                identity=sid,
                content=content,
                root=scope,
                scope=scope,
                observed_at="2026-01-01T00:00:00+00:00",
            )
            keys.append(sid)
        cases.append(
            dict(
                question_id=qid,
                question=f"What happened in story {n}?",
                observation_time="2026-01-01T00:00:00+00:00",
                family_proxy_digest=family,
                source_census_sha256="source-" + qid,
                scope=scope,
            )
        )
        for arm, size in (("lexical_k4", 4), ("lexical_k8", 8)):
            chosen = keys[:size]
            selections[(qid, arm)] = dict(selected=chosen)
            delivered = []
            for i, sid in enumerate(chosen, 1):
                d = docs[sid]
                delivered.append(
                    dict(
                        label=f"E{i}",
                        original_id=sid,
                        excerpt=d["content"],
                        root=scope,
                        scope=scope,
                        source_start=0,
                        source_end=len(d["content"].encode()),
                        source_digest=work.native_digest(d["content"]),
                    )
                )
            answers.append(
                dict(
                    question_id=qid,
                    arm=arm,
                    family_proxy_digest=family,
                    source_census_sha256="source-" + qid,
                    status="succeeded",
                    answer=f"The detail was present [E1] ({qid}).",
                    selected=chosen,
                    receipt=dict(
                        reader_identity=work.MODEL_ID,
                        reader_profile="reader-profile",
                        token_limit=2048,
                        answer_postprocessed=False,
                        production_accepted=False,
                        trainable_parameters=0,
                        semantic_citation_precision=None,
                        semantic_sufficiency=None,
                        delivered_evidence=delivered,
                        input_tokens=250,
                        generated_tokens=16,
                        seconds=3.5,
                    ),
                )
            )
    return (
        dict(splits=dict(evaluation=cases)),
        docs,
        selections,
        answers,
        dict(model_profile="reader-profile"),
    )


class WorklistTests(unittest.TestCase):
    def test_expected_census_and_source_first_embargo(self):
        a, b = work.make_worklists(*records())
        self.assertEqual((len(a), len(b)), (32, 32))
        self.assertEqual(len({row["review_id"] for row in a}), 32)
        self.assertEqual([x["review_id"] for x in a], [x["review_id"] for x in b])
        self.assertEqual(len(a[0]["evidence"]), 4)
        self.assertEqual(len(a[1]["evidence"]), 8)
        for source_only, answer in zip(a, b, strict=True):
            self.assertNotIn("unedited_reader_answer", source_only)
            self.assertNotIn("reader_answer", source_only)
            self.assertNotIn("expected", source_only)
            self.assertIsNone(source_only["sufficient_to_answer"])
            self.assertIsNone(source_only["reviewer_identity"])
            self.assertIsNone(answer["answer_supported_by_delivered_sources"])
            self.assertIsNone(answer["cited_claims_entailed"])
            self.assertIsNone(answer["citation_chain_complete"])

    def test_mutated_original_excerpt_fails(self):
        args = list(records())
        args[3][0]["receipt"]["delivered_evidence"][0]["excerpt"] += " TAMPER"
        with self.assertRaises(ValueError):
            work.make_worklists(*args)

    def test_source_digest_and_length_binding(self):
        for key, value in (("source_digest", "wrong"), ("source_end", -1)):
            with self.subTest(key=key):
                args = list(records())
                args[3][0]["receipt"]["delivered_evidence"][0][key] = value
                with self.assertRaises(ValueError):
                    work.make_worklists(*args)

    def test_reader_weights_and_budget_are_frozen(self):
        for key, value in (
            ("reader_identity", "other"),
            ("token_limit", 4096),
            ("trainable_parameters", 1),
            ("answer_postprocessed", True),
            ("semantic_citation_precision", 0.99),
        ):
            with self.subTest(key=key):
                args = list(records())
                args[3][0]["receipt"][key] = value
                with self.assertRaises(ValueError):
                    work.make_worklists(*args)

    def test_missing_answer_and_forged_status_refuse(self):
        for name, value in (("answer", ""), ("status", "failed")):
            with self.subTest(name=name):
                args = list(records())
                args[3][1][name] = value
                with self.assertRaises(ValueError):
                    work.make_worklists(*args)

    def test_changed_selection_or_extra_source_rejected(self):
        args = list(records())
        args[2][("q00", "lexical_k8")]["selected"] = list(
            reversed(args[2][("q00", "lexical_k8")]["selected"])
        )
        args[3][1]["selected"] = list(args[2][("q00", "lexical_k8")]["selected"])
        with self.assertRaises(ValueError):
            work.make_worklists(*args)

    def test_incomplete_question_or_family_census_fails(self):
        args = list(records())
        args[0]["splits"]["evaluation"].pop()
        with self.assertRaises(ValueError):
            work.make_worklists(*args)
        args = list(records())
        args[0]["splits"]["evaluation"][0]["family_proxy_digest"] = "third"
        with self.assertRaises(ValueError):
            work.make_worklists(*args)

    def test_undelivered_citation_is_visible_not_promoted(self):
        args = list(records())
        args[3][0]["answer"] = "Incorrect citation [E9]"
        _, b = work.make_worklists(*args)
        self.assertEqual(b[0]["undelivered_cited_labels"], ["E9"])
        self.assertIsNone(b[0]["cited_claims_entailed"])

    def test_json_field_injection_and_nonfinite_fails_closed(self):
        for data in (b'{"id":1,"id":2}', b'{"x":NaN}'):
            with self.assertRaises(ValueError):
                work.read_json(data)

    def test_changed_outer_zip_cannot_be_substituted(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "not-the-published-original.zip"
            path.write_bytes(b"not an immutable original archive")
            with self.assertRaises(ValueError):
                work.pinned_zip(path, "public")

    def test_manifest_never_issues_an_unreviewed_judgement(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "doc.json"
            h = work.write_once(
                p,
                dict(
                    sufficiency=None,
                    semantic_entailment=None,
                    production_accepted=False,
                ),
            )
            self.assertEqual(work.digest_bytes(p.read_bytes()), h)
            with self.assertRaises(FileExistsError):
                work.write_once(p, {"overwritten": True})
            self.assertFalse(json.loads(p.read_text())["production_accepted"])


if __name__ == "__main__":
    unittest.main()
