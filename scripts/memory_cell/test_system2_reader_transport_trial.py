"""Hermetic frozen Reader view registration, provenance and failure accounting."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from system2_reader_capacity_reference import ARMS
from system2_reader_paired_capacity_audit import STRONG_READER_ID, open_strong
from system2_reader_transport_trial import (
    CASE_COUNT,
    COMMIT_PATTERN,
    FRESH_INDICES,
    FRESH_NAME,
    NEW_CALLS,
    REPEATED_COHORTS,
    REUSED_CALLS,
    VIEWS,
    extra_cases,
    line_messages,
    planned_positions,
    registered_cohorts,
    run,
    score_pairs,
)


class FakeReader:
    identity = STRONG_READER_ID

    def __init__(self, answer="I do not have enough evidence."):
        self.text = answer
        self.calls = []
        self.frozen_verified = False

    def answer(self, case, docs, arm):
        self.calls.append((case.question.identity, arm))
        return self.text, self.receipt()

    def receipt(self):
        return dict(
            reader_identity=self.identity,
            model_revision="a338b55dd21219a5f4da42bc11a9313d1a27d4cc",
            bundle_digest="unit-bundle",
            delivered_evidence=[],
            token_limit=1024,
            trainable_parameters=0,
            answer_postprocessed=False,
            input_tokens=37,
            generated_tokens=8,
            cpu_time_ns=1000,
        )

    def verify_frozen(self):
        self.frozen_verified = True


class StubBundle:
    def seal(self):
        return "unit-bundle"

    def delivered(self):
        return []


def fake_original(groups):
    return {
        (case.question.identity, arm): dict(
            status="succeeded",
            answer="I do not have enough evidence.",
            reader=FakeReader().receipt(),
        )
        for name in REPEATED_COHORTS[:2]
        for case in groups[name]
        for arm in ARMS
    }


class TransportTests(unittest.TestCase):
    def test_fixed_three_cohorts_and_question_disjointness(self):
        groups = registered_cohorts()
        self.assertEqual(set(groups), set(REPEATED_COHORTS))
        self.assertEqual([len(groups[k]) for k in REPEATED_COHORTS], [20, 20, 20])
        self.assertEqual(tuple(FRESH_INDICES), tuple(range(40, 60)))
        ids = [c.question.identity for group in groups.values() for c in group]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(extra_cases()), CASE_COUNT)

    def test_320_new_calls_160_archived_controls(self):
        groups = registered_cohorts()
        positions = planned_positions(groups)
        self.assertEqual((len(positions), NEW_CALLS, REUSED_CALLS), (320, 320, 160))
        self.assertEqual(sum(name == FRESH_NAME for name, *_ in positions), 160)
        self.assertEqual(sum(view == "lines" for *_, view in positions), 240)
        self.assertEqual(sum(view == "json" for *_, view in positions), 80)
        self.assertEqual(
            len({(c.question.identity, arm, view) for _, c, arm, view in positions}),
            NEW_CALLS,
        )

    def test_same_evidence_bytes_and_original_question_in_transport(self):
        case = extra_cases()[0]
        d = [
            dict(
                label="E1",
                observed_at="2026-08-05T12:00:00+00:00",
                excerpt="Device DEV-XYZ requires clearance token TOK-ABC1234.",
            ),
            dict(
                label="E2",
                observed_at="2026-08-05T12:00:00+00:00",
                excerpt='Archived note: "quoted" data.',
            ),
        ]
        msg = line_messages(case.question, d)
        self.assertEqual([m["role"] for m in msg], ["system", "user"])
        self.assertIn(case.question.content, msg[1]["content"])
        self.assertIn(case.question.observed_at, msg[1]["content"])
        for item in d:
            self.assertIn(item["label"], msg[1]["content"])
            self.assertIn(
                json.dumps(item["excerpt"], ensure_ascii=False), msg[1]["content"]
            )
            self.assertEqual(
                msg[1]["content"].count("text=" + json.dumps(item["excerpt"])), 1
            )
        self.assertNotIn(case.answer, msg[1]["content"])

    def test_empty_evidence_explicitly_none_without_source_label(self):
        case = extra_cases()[0]
        msg = line_messages(case.question, [])
        self.assertIn("(none)", msg[1]["content"])
        self.assertNotIn("E1", msg[1]["content"])
        self.assertEqual(len(VIEWS), 2)

    def test_malformed_evidence_fails_closed(self):
        case = extra_cases()[0]
        for bad in (
            None,
            "some string",
            [dict(label="E1")],
            [{"label": 0, "excerpt": "x", "observed_at": "x"}],
            [{}] * 9,
        ):
            with self.assertRaises(ValueError):
                line_messages(case.question, bad)

    def test_no_answer_labels_enter_transport(self):
        case = extra_cases()[0]
        d = [dict(label="E1", observed_at="x", excerpt="A quoted line.")]
        a = line_messages(case.question, d)
        # Deliberately alter the hidden registered answer without changing the
        # observable question or evidence: the model input is unchanged.
        from dataclasses import replace

        changed = replace(case, answer="TOK-HIDDEN-CHANGED")
        b = line_messages(changed.question, d)
        self.assertEqual(a, b)

    def test_externally_pinned_parent_original_evidence_matches(self):
        archive = os.environ.get("HEPTA_STRONG_READER_ARCHIVE")
        if not archive or not Path(archive).is_file():
            self.skipTest("externally pinned original model ZIP not mounted")
        _, plan, old = open_strong(Path(archive))
        from system2_reader_capacity_reference import selected, COHORTS

        groups = registered_cohorts()
        self.assertEqual(plan["reference_reader_identity"], STRONG_READER_ID)
        checked = 0
        for name in COHORTS:
            for case in groups[name]:
                for arm in ARMS:
                    docs = selected(case, arm)
                    previous = old[case.question.identity, arm]
                    delivery = previous["reader"]["delivered_evidence"]
                    self.assertEqual(
                        [s["original_id"] for s in delivery], [d.identity for d in docs]
                    )
                    self.assertEqual(
                        [s["excerpt"] for s in delivery], [d.content for d in docs]
                    )
                    self.assertEqual(
                        [s["observed_at"] for s in delivery],
                        [d.observed_at for d in docs],
                    )
                    checked += 1
        self.assertEqual(checked, REUSED_CALLS)

    def test_study_hash_registration(self):
        self.assertTrue(COMMIT_PATTERN.fullmatch("a" * 40))
        self.assertIsNone(COMMIT_PATTERN.fullmatch("z" * 40))
        self.assertIsNone(COMMIT_PATTERN.fullmatch("a" * 39))

    def test_hermetic_complete_runner_records_all_new_predictions(self):
        groups = registered_cohorts()
        original = fake_original(groups)
        reader = FakeReader()
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "system2_reader_transport_trial.expected_parent",
                return_value=(
                    original,
                    dict(verified_parent_sha256="p" * 64, baseline_raw_sha256="q" * 64),
                ),
            ),
            patch("system2_reader_transport_trial.selected", return_value=()),
            patch(
                "system2_reader_transport_trial.evidence",
                return_value=(StubBundle(), {}, "frontier"),
            ),
            patch(
                "system2_reader_transport_trial.run_line_reader",
                side_effect=(
                    lambda model, case, docs, arm: (model.text, model.receipt())
                ),
            ),
        ):
            out = Path(tmp) / "run"
            result = run(
                out,
                reader,
                parent_archive=Path("irrelevant"),
                source_commit="f" * 40,
                groups=groups,
            )
            self.assertEqual(
                (result["planned_new"], result["recorded_new"], result["failed_new"]),
                (320, 320, 0),
            )
            self.assertEqual(result["prior_json_reused"], 160)
            self.assertEqual(len(result["results"]), len(REPEATED_COHORTS) * len(ARMS))
            self.assertTrue(reader.frozen_verified)
            raw = (out / "raw-answers.jsonl").read_bytes()
            seal = json.loads((out / "raw-seal.json").read_text())
            self.assertEqual(seal["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(seal["rows"], 320)
            self.assertEqual(
                len(json.loads((out / "paired-scores.json").read_text())), 240
            )
            self.assertEqual(len((out / "starts.jsonl").read_text().splitlines()), 320)
            self.assertEqual(
                result["candidate_disposition"], "reader_transport_not_qualified"
            )

    def test_interruption_retains_failure_and_inflight_unknown(self):
        groups = registered_cohorts()
        original = fake_original(groups)
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "system2_reader_transport_trial.expected_parent",
                return_value=(
                    original,
                    dict(verified_parent_sha256="p" * 64, baseline_raw_sha256="q" * 64),
                ),
            ),
            patch("system2_reader_transport_trial.selected", return_value=()),
            patch(
                "system2_reader_transport_trial.run_line_reader",
                side_effect=KeyboardInterrupt("stop"),
            ),
        ):
            out = Path(tmp) / "failed"
            with self.assertRaises(KeyboardInterrupt):
                run(
                    out,
                    FakeReader(),
                    parent_archive=Path("none"),
                    source_commit="b" * 40,
                    groups=groups,
                )
            fail = json.loads((out / "failure.json").read_text())
            self.assertFalse(fail["complete"])
            self.assertTrue(fail["cost_of_inflight_call_unknown"])
            self.assertFalse((out / "raw-seal.json").exists())
            self.assertEqual(
                len((out / "raw-answers.jsonl").read_text().splitlines()), 1
            )

    def test_source_integrity_mismatch_is_not_scored(self):
        groups = registered_cohorts()
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "system2_reader_transport_trial.expected_parent",
                return_value=(
                    fake_original(groups),
                    dict(verified_parent_sha256="p" * 64, baseline_raw_sha256="q" * 64),
                ),
            ),
            patch("system2_reader_transport_trial.selected", return_value=()),
            patch(
                "system2_reader_transport_trial.evidence",
                return_value=(StubBundle(), {}, "frontier"),
            ),
            patch(
                "system2_reader_transport_trial.run_line_reader",
                return_value=(
                    "I do not have enough evidence.",
                    dict(
                        reader_identity="WRONG",
                        bundle_digest="unit-bundle",
                        delivered_evidence=[],
                        model_revision="a338b55dd21219a5f4da42bc11a9313d1a27d4cc",
                        token_limit=1024,
                        trainable_parameters=0,
                        answer_postprocessed=False,
                    ),
                ),
            ),
        ):
            out = Path(tmp) / "fail"
            with self.assertRaises(ValueError):
                run(
                    out,
                    FakeReader(),
                    parent_archive=Path("none"),
                    source_commit="c" * 40,
                    groups=groups,
                )
            self.assertFalse((out / "summary.json").exists())
            self.assertEqual(
                json.loads((out / "failure.json").read_text())["recorded"], 0
            )

    def test_missing_pair_denominator_rejected(self):
        groups = registered_cohorts()
        with self.assertRaises(ValueError):
            score_pairs([], fake_original(groups), groups)

    def test_model_identity_and_source_sha_preconditions(self):
        groups = registered_cohorts()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                run(
                    Path(tmp) / "bad",
                    FakeReader(),
                    parent_archive=Path("no"),
                    source_commit="wrong",
                    groups=groups,
                )
            self.assertFalse((Path(tmp) / "bad").exists())


if __name__ == "__main__":
    unittest.main()
