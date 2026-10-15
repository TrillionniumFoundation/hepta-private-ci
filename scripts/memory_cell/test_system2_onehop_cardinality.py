"""Exact archival provenance, no target leakage, and cardinality failure bounds."""

from dataclasses import replace, asdict
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from native import digest as native_digest
from system2_multihop_trial import ABSTAIN, evidence
from system2_multihop_evidence import parse_relation
from system2_onehop_cardinality import (
    ARMS,
    LABEL_ONLY,
    PARENT_RAW_SHA256,
    PARENT_SHA256,
    POSITIVE,
    READER_IDENTITY,
    READER_PROFILE,
    census,
    cases,
    choose_onehop,
    load_parent,
    run,
    score_one,
)

ARCHIVE = Path(
    os.environ.get(
        "HEPTA_SYSTEM2_ONEHOP_PARENT",
        "/mnt/data/hepta-onehop-reader-hosted-b3817457.zip",
    )
)


def standin_parent():
    # Only for isolated plumbing tests. The one authenticated integration
    # test MUST use the original ZIP and its externally pinned digest.
    return dict(
        manifest_entries=28,
        rows={
            (c.question.identity, a): dict(
                qid=c.question.identity, answer="historic output"
            )
            for c in cases()
            for a in (
                "single_fact",
                "fact_plus_distractors",
                "distractors_only",
                "no_evidence",
            )
        },
    )


class FakeReader:
    def __init__(self, *, fail_at=None, hallucinate=False):
        self.calls = 0
        self.fail_at = fail_at
        self.hallucinate = hallucinate

    def answer(self, q, bundle, _orig, *, frontier, revoked, token_limit):
        self.calls += 1
        if self.fail_at == self.calls:
            raise RuntimeError("injected unavailable Reader")
        assert token_limit == 1024 and not revoked
        assert bundle.source_frontier == frontier
        documents = bundle.delivered()
        query_target = re.search(r"by device (DEV-[A-F0-9]+)\?", q.content).group(1)
        appropriate = [
            (i + 1, e[3])
            for i, row in enumerate(documents)
            if (e := parse_relation(type("Doc", (), {"content": row["excerpt"]})()))
            and e[0] == "device"
            and e[1] == query_target
            and e[2] == "token"
        ]
        if appropriate:
            i, token = appropriate[0]
            answer = f"{token} [E{i}]"
        else:
            answer = "TOK-0000000 [E1]" if self.hallucinate else ABSTAIN
        return answer, dict(
            reader_identity=READER_IDENTITY,
            reader_profile=READER_PROFILE,
            query_digest=native_digest(asdict(q)),
            bundle_digest=bundle.seal(),
            delivered_evidence=documents,
            input_tokens=120,
            token_limit=1024,
            trainable_parameters=0,
            answer_postprocessed=False,
            generated_tokens=12,
        )


class OneHopCardinalityTests(unittest.TestCase):
    def test_fixed_20_questions_seven_arms(self):
        registered = cases()
        self.assertEqual((len(registered), len(ARMS)), (20, 7))
        self.assertEqual(len({c.question.identity for c in registered}), 20)
        self.assertEqual(len(POSITIVE), 5)

    def test_exact_registered_source_counts_and_grounding(self):
        for case in cases():
            needed = case.required_id
            for arm, count in (
                ("target_decoy_two_first", 2),
                ("target_decoy_two_last", 2),
                ("target_context_two", 2),
                ("target_decoys_three_last", 3),
                ("target_context_three", 3),
                ("decoy_one", 1),
                ("decoy_two", 2),
            ):
                docs = choose_onehop(case, arm)
                self.assertEqual(len(docs), count)
                self.assertEqual(needed in [d.identity for d in docs], arm in POSITIVE)
                self.assertEqual(len({d.identity for d in docs}), count)

    def test_no_gold_answer_or_required_id_used_in_selection(self):
        for c in cases():
            bad = replace(c, answer="TOK-CORRUPTED", required_id="missing")
            for arm in ARMS:
                self.assertEqual(choose_onehop(c, arm), choose_onehop(bad, arm))

    def test_original_target_and_context_unique_with_observable_provenance(self):
        for c in cases():
            fact = choose_onehop(c, "target_decoy_two_first")[0]
            contexts = choose_onehop(c, "target_context_three")[1:]
            self.assertEqual(fact.identity, c.required_id)
            self.assertTrue(
                all(
                    (e := parse_relation(d))
                    and not (e[0] == "device" and e[2] == "token")
                    for d in contexts
                )
            )
            docs = choose_onehop(c, "target_decoy_two_last")
            bundle, orig, frontier = evidence(c, docs, "target_decoy_two_last")
            bundle.validate(c.question, orig, frontier=frontier, revoked=set())
            self.assertEqual(
                [d["original_id"] for d in bundle.delivered()],
                [d.identity for d in docs],
            )

    def test_unknown_arm_and_wrong_source_scope_rejected(self):
        c = cases()[0]
        with self.assertRaises(ValueError):
            choose_onehop(c, "oracle")
        docs = list(c.documents)
        docs[0] = replace(docs[0], scope="wrong")
        with self.assertRaises(ValueError):
            choose_onehop(replace(c, documents=tuple(docs)), "target_context_three")

    def test_correct_fact_with_actual_bound_citation_and_wrong_label(self):
        c = cases()[0]
        docs = choose_onehop(c, "target_decoy_two_last")
        base = f"{c.answer} [E2]"
        result = score_one(c, "target_decoy_two_last", [d.identity for d in docs], base)
        self.assertTrue(result["grounded_answer_success"])
        self.assertTrue(result["cites_required_source"])
        wrong = score_one(
            c, "target_decoy_two_last", [d.identity for d in docs], f"{c.answer} [E1]"
        )
        self.assertFalse(wrong["grounded_answer_success"])
        self.assertTrue(wrong["correct_single_token"])

    def test_missing_evidence_correct_string_not_accepted(self):
        c = cases()[0]
        docs = choose_onehop(c, "decoy_one")
        r = score_one(c, "decoy_one", [d.identity for d in docs], c.answer + " [E1]")
        self.assertTrue(r["target_token_mentioned"])
        self.assertTrue(r["unsupported_token_copy"])
        self.assertFalse(r["grounded_answer_success"])

    def test_label_only_echo_is_not_an_answer(self):
        c = cases()[0]
        docs = choose_onehop(c, "target_context_three")
        r = score_one(
            c, "target_context_three", [d.identity for d in docs], "E1\n\nE2\n\nE3"
        )
        self.assertTrue(r["label_only_answer"])
        self.assertFalse(r["grounded_answer_success"])
        self.assertTrue(LABEL_ONLY.fullmatch("E1 E2 E3"))
        self.assertFalse(LABEL_ONLY.fullmatch("TOK-ABCD123 [E1]"))

    def test_refusal_classified_separately(self):
        c = cases()[0]
        docs = choose_onehop(c, "decoy_two")
        r = score_one(c, "decoy_two", [d.identity for d in docs], ABSTAIN)
        self.assertTrue(r["strict_abstention"])
        self.assertFalse(r["grounded_answer_success"])

    def test_missing_duplicate_and_invalid_census_fails_closed(self):
        c = cases()[0]
        rows = [
            dict(qid=c.question.identity, arm=arm, status="succeeded") for arm in ARMS
        ]
        self.assertEqual(census(rows, (c,))["planned"], 7)
        for bad in (
            rows[:-1],
            rows + rows[:1],
            rows[:-1] + [dict(rows[-1], status="queued")],
        ):
            with self.assertRaises(ValueError):
                census(bad, (c,))

    @unittest.skipUnless(ARCHIVE.is_file(), "pinned historical ZIP not staged")
    def test_archived_full_zip_and_raw_80_are_reverified(self):
        receipt = load_parent(ARCHIVE)
        self.assertEqual(receipt["sha256"], PARENT_SHA256)
        self.assertEqual(receipt["original_seal"], PARENT_RAW_SHA256)
        self.assertEqual(receipt["manifest_entries"], 28)
        self.assertEqual(len(receipt["rows"]), 80)

    def test_wrong_outer_sha_before_any_untrusted_archive_parsing(self):
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "bad.zip"
            fake.write_bytes(b"different content")
            with self.assertRaises(ValueError):
                load_parent(fake)

    def test_real_runner_with_fake_reader_seals_every_result(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "result"
            with patch(
                "system2_onehop_cardinality.load_parent", return_value=standin_parent()
            ):
                ca, summ = run(
                    out, FakeReader(), ARCHIVE, source_commit="a" * 40, count=2
                )
            self.assertEqual((ca["planned"], ca["recorded"], ca["failed"]), (14, 14, 0))
            self.assertEqual(
                sum(x["grounded_answers"] for x in summ if x["arm"] in POSITIVE), 10
            )
            raw = (out / "raw-answers.jsonl").read_bytes()
            seal = json.loads((out / "raw-seal.json").read_text())
            self.assertEqual(
                seal,
                dict(
                    sha256=hashlib.sha256(raw).hexdigest(),
                    rows=14,
                    scoring_started=False,
                ),
            )
            self.assertTrue((out / "summary.json").is_file())

    def test_runner_retains_reader_failures_without_negative_imputation(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "failed"
            with patch(
                "system2_onehop_cardinality.load_parent", return_value=standin_parent()
            ):
                with self.assertRaises(RuntimeError):
                    run(
                        out,
                        FakeReader(fail_at=3),
                        ARCHIVE,
                        source_commit="b" * 40,
                        count=1,
                    )
            rows = [
                json.loads(x)
                for x in (out / "raw-answers.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(rows), 7)
            self.assertEqual(sum(r["status"] == "failed" for r in rows), 1)
            self.assertTrue(any(r.get("incomplete_cost_unknown") for r in rows))
            self.assertFalse(
                json.loads((out / "run-failure.json").read_text())[
                    "incomplete_work_not_free"
                ]
                is False
            )
            self.assertEqual(
                json.loads((out / "summary.json").read_text())["census"]["failed"], 1
            )

    def test_invalid_commit_fails_before_reading_archive(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "no"
            with self.assertRaises(ValueError):
                run(out, FakeReader(), ARCHIVE, source_commit="invalid")
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
