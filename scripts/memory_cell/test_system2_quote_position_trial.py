"""No model calls: strict historical receipt replay and position-matched audit."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from system2_quote_position_trial import (
    BASELINE_OUTPUT_LIMIT,
    PARENT_ARCHIVE_SHA256,
    PARENT_SEAL_SHA256,
    PLANNED_NEW_CALLS,
    READER_IDENTITY,
    load_parent,
    paired_sources,
    run,
    summarize,
)
from system2_multihop_stress import ATTACK_INDICES

ARCHIVE = Path(
    os.environ.get(
        "HEPTA_SYSTEM2_STRESS_ARCHIVE",
        "/mnt/data/hepta-quote-stress-hosted-76672c8.zip",
    )
)


class Bundle:
    def __init__(self, selected):
        self.selected = tuple(selected)

    def seal(self):
        return hashlib.sha256(
            ",".join(d.identity for d in self.selected).encode()
        ).hexdigest()


def local_evidence(case, selected, arm):
    if arm != "neutral_first" or len(selected) != 4:
        raise ValueError("unexpected condition")
    return (
        Bundle(selected),
        {d.identity: d for d in case.documents},
        "frontier-test-only",
    )


class DummyReader:
    def __init__(self, profile, *, fail=False, fake=False):
        self.profile, self.fail, self.fake, self.calls = profile, fail, fake, []

    def answer(self, query, bundle, originals, *, frontier, revoked, token_limit):
        self.calls.append(
            (query.identity, [d.identity for d in bundle.selected], token_limit)
        )
        if self.fail:
            raise RuntimeError("injected Reader failure")
        text = (
            "TOK-FAKE99"
            if self.fake and len(self.calls) == 1
            else "I do not have enough evidence."
        )
        return text, dict(
            reader_identity=READER_IDENTITY,
            reader_profile=self.profile,
            generated_tokens=12,
            input_tokens=200,
            trainable_parameters=0,
            answer_postprocessed=False,
            production_accepted=False,
            bundle_digest=bundle.seal(),
        )


class MatchedQuoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ARCHIVE.is_file():
            raise unittest.SkipTest("pinned completed stress ZIP required")
        cls.parent = load_parent(ARCHIVE)

    def test_external_zip_and_source_manifest_verification(self):
        self.assertEqual(
            hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(), PARENT_ARCHIVE_SHA256
        )
        self.assertEqual(self.parent["raw_sha256"], PARENT_SEAL_SHA256)
        self.assertEqual(self.parent["verified_files"], 33)
        self.assertEqual(
            (len(self.parent["cases"]), len(self.parent["by_key"])), (5, 30)
        )

    def test_parent_corrupt_outer_archive_rejected_before_reader(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "mutated.zip"
            shutil.copyfile(ARCHIVE, p)
            with p.open("r+b") as f:
                f.seek(45)
                c = f.read(1)
                f.seek(45)
                f.write(bytes([c[0] ^ 1]))
            with self.assertRaises(ValueError):
                load_parent(p)

    def test_parent_reader_identity_is_unique(self):
        self.assertTrue(self.parent["reader_profile"])
        self.assertTrue(
            all(
                r["reader"]["reader_identity"] == READER_IDENTITY
                for r in self.parent["by_key"].values()
            )
        )

    def test_no_online_target_or_required_source_leak(self):
        for case in self.parent["cases"]:
            neutral, selected, _, attack = paired_sources(case)
            changed = replace(case, answer="TOK-FAKE-UNRELATED", required_ids=())
            n2, s2, _, a2 = paired_sources(changed)
            self.assertEqual(
                (neutral.documents, neutral.question, selected, attack),
                (n2.documents, n2.question, s2, a2),
            )

    def test_fixed_original_task_registry(self):
        self.assertEqual(PLANNED_NEW_CALLS, len(ATTACK_INDICES))
        for case in self.parent["cases"]:
            self.assertEqual(case.hops, 3)
            self.assertTrue(case.attack_distractor)

    def test_quote_always_E1_and_true_facts_always_E2_E3_E4(self):
        for case in self.parent["cases"]:
            neutral, selected, attack, attacked = paired_sources(case)
            self.assertEqual(neutral.question, attack.question)
            self.assertEqual(
                [d.identity for d in selected[1:]], [d.identity for d in attacked[1:]]
            )
            self.assertNotEqual(selected[0].content, attacked[0].content)
            self.assertNotIn("TOK-FAKE99", selected[0].content)

    def test_real_historical_attack_content_mentioned_once(self):
        positives = [
            r
            for (qid, arm), r in self.parent["by_key"].items()
            if arm == "attack_first" and "TOK-FAKE99" in r["answer"].upper()
        ]
        self.assertEqual(len(positives), 1)

    def test_real_original_strict_success_remains_zero(self):
        # All presealed parent rows are replay-scored by load_parent; no new
        # model calls or homemade acceptance transformations are allowed.
        for case in self.parent["cases"]:
            row = self.parent["by_key"][(case.question.identity, "attack_first")]
            self.assertEqual(row["status"], "succeeded")
            self.assertTrue(
                1 <= row["reader"]["generated_tokens"] <= BASELINE_OUTPUT_LIMIT
            )

    def test_healthy_fake_runner_seals_exact_five_new_calls(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "out"
            fake = DummyReader(self.parent["reader_profile"])
            with patch(
                "system2_quote_position_trial.evidence", side_effect=local_evidence
            ):
                out = run(ARCHIVE, dest, fake, source_commit="a" * 40)
            self.assertEqual(
                (out["planned"], out["recorded"], out["failed"]), (5, 5, 0)
            )
            self.assertEqual(len(fake.calls), 5)
            self.assertTrue(
                all(call[2] == 1024 and len(call[1]) == 4 for call in fake.calls)
            )
            raw = (dest / "raw-answers.jsonl").read_bytes()
            seal = json.loads((dest / "raw-seal.json").read_text())
            self.assertEqual(
                (seal["rows"], seal["sha256"]), (5, hashlib.sha256(raw).hexdigest())
            )
            self.assertFalse(seal["scoring_started"])
            self.assertEqual(out["attack_first_fake_mentions"], 1)
            self.assertEqual(out["neutral_first_fake_mentions"], 0)
            self.assertTrue(all(row["same_E2_E3_E4"] for row in out["per_question"]))

    def test_fake_neutral_output_detected_as_new_hallucination(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "out"
            fake = DummyReader(self.parent["reader_profile"], fake=True)
            with patch(
                "system2_quote_position_trial.evidence", side_effect=local_evidence
            ):
                out = run(ARCHIVE, dest, fake, source_commit="b" * 40)
            self.assertEqual(out["neutral_first_fake_mentions"], 1)
            self.assertFalse(out["independent_attack_defense_certified"])

    def test_failed_reader_denominator_not_fabricated(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "failed"
            fake = DummyReader(self.parent["reader_profile"], fail=True)
            with patch(
                "system2_quote_position_trial.evidence", side_effect=local_evidence
            ):
                with self.assertRaisesRegex(RuntimeError, "failed calls retained"):
                    run(ARCHIVE, dest, fake, source_commit="c" * 40)
            report = json.loads((dest / "summary.json").read_text())
            self.assertEqual((report["recorded"], report["failed"]), (5, 5))
            self.assertEqual(report["neutral_first_fake_mentions"], 0)
            self.assertEqual(report["neutral_first_unknown"], 5)
            self.assertEqual(report["attack_first_fake_mentions"], 1)
            self.assertTrue(
                json.loads((dest / "run-failure.json").read_text())[
                    "missing_or_failed_work_unknown"
                ]
            )

    def test_unsafe_model_profile_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "out"
            fake = DummyReader("wrong")
            with patch(
                "system2_quote_position_trial.evidence", side_effect=local_evidence
            ):
                with self.assertRaises(RuntimeError):
                    run(ARCHIVE, dest, fake, source_commit="d" * 40)
            self.assertEqual(
                len((dest / "raw-answers.jsonl").read_text().splitlines()), 5
            )

    def test_unexpected_interrupt_retains_started_journal(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "int"
            with patch(
                "system2_quote_position_trial.evidence", side_effect=KeyboardInterrupt
            ):
                with self.assertRaises(KeyboardInterrupt):
                    run(
                        ARCHIVE,
                        dest,
                        DummyReader(self.parent["reader_profile"]),
                        source_commit="e" * 40,
                    )
            self.assertEqual(len((dest / "starts.jsonl").read_text().splitlines()), 1)
            self.assertTrue((dest / "run-failure.json").is_file())
            self.assertFalse((dest / "summary.json").exists())

    def test_invalid_sha_rejected_without_starting(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "out"
            with self.assertRaises(ValueError):
                run(
                    ARCHIVE,
                    dest,
                    DummyReader(self.parent["reader_profile"]),
                    source_commit="bad",
                )
            self.assertFalse(dest.exists())

    def test_duplicate_rows_cannot_be_scored_as_complete(self):
        c = self.parent["cases"][0]
        fake = dict(qid=c.question.identity, status="failed")
        with self.assertRaises(ValueError):
            summarize(self.parent, [fake] * 5)

    def test_failed_attempts_keep_categorical_uncertainty(self):
        rows = [
            dict(qid=c.question.identity, status="failed") for c in self.parent["cases"]
        ]
        out = summarize(self.parent, rows)
        self.assertEqual((out["failed"], out["succeeded"]), (5, 0))
        self.assertEqual(out["attack_first_fake_mentions"], 1)
        self.assertTrue(all(item["new_score_unknown"] for item in out["per_question"]))


if __name__ == "__main__":
    unittest.main()
