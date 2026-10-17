"""Synthetic controls: no-evidence generation is isolated from the six Cell arms."""

from dataclasses import asdict
import unittest

from native import Question, digest
from stem_reader_zero_evidence import (
    PHASES,
    generate_empty_evidence_controls,
    evaluate_empty_evidence_controls,
)


def samples():
    return [
        (
            phase,
            Question(
                f"{phase}-{i}",
                f"family-{phase}-{i}",
                f"scope-{phase}-{i}",
                "What did the user say?",
                "2023-04-10",
            ),
        )
        for phase in PHASES
        for i in range(8)
    ]


def fake(q, evidence, record_key):
    if evidence != ():
        raise AssertionError("control can never request evidence")
    if not record_key.startswith("no-evidence/"):
        raise AssertionError("wrong diagnostic identity")
    return "Unsupported fixture answer [E1]", dict(
        generator_identity="reader-pin",
        generator_profile="profile-pin",
        observable_query=asdict(q),
        delivered_evidence=[],
        canonical_request_digest=digest(
            (
                "reader-pin",
                "profile-pin",
                asdict(q),
                [],
            )
        ),
        actual_reader_execution=True,
    )


class NoEvidenceControlsTests(unittest.TestCase):
    def controls(self, generator=fake):
        return generate_empty_evidence_controls(
            samples(),
            generator,
            reader_identity="reader-pin",
            reader_profile="profile-pin",
        )

    def test_complete_label_free_generation_and_receipt_identity(self):
        rows = self.controls()
        self.assertEqual(len(rows), 32)
        self.assertEqual(sum(r["status"] == "succeeded" for r in rows), 32)
        self.assertTrue(all(r["evidence_count"] == 0 for r in rows))
        self.assertTrue(all(not r["answer_target_opened_by_generation"] for r in rows))
        self.assertEqual(rows[0]["receipt"]["delivered_evidence"], [])

    def test_nonexact_or_duplicate_phase_census_fails_before_any_model_call(self):
        for cases in (
            samples()[:-1],
            samples()[:-1] + [samples()[0]],
            list(reversed(samples())),
        ):
            invocations = []

            def side_effect(*args):
                invocations.append(1)
                return fake(*args)

            with self.assertRaisesRegex(ValueError, "32 unique preregistered"):
                generate_empty_evidence_controls(
                    cases,
                    side_effect,
                    reader_identity="reader-pin",
                    reader_profile="profile-pin",
                )
            self.assertEqual(invocations, [])

    def test_normalized_source_family_is_bound_without_reading_labels(self):
        matched = samples()
        family = {q.identity: "component:" + q.family for _, q in matched}
        rows = generate_empty_evidence_controls(
            matched,
            fake,
            reader_identity="reader-pin",
            reader_profile="profile-pin",
            family_by_question=family,
        )
        self.assertTrue(all(r["family"] == family[r["question_id"]] for r in rows))
        with self.assertRaisesRegex(ValueError, "32 unique"):
            generate_empty_evidence_controls(
                matched,
                fake,
                reader_identity="reader-pin",
                reader_profile="profile-pin",
                family_by_question={q.identity: q.family for _, q in matched[:-1]},
            )

    def test_failed_generation_stays_in_denominator(self):
        counts = [0]

        def one_fail(q, evidence, record_key):
            counts[0] += 1
            if q.identity == "select-2":
                raise RuntimeError("real Reader error")
            return fake(q, evidence, record_key)

        rows = self.controls(one_fail)
        self.assertEqual(counts[0], 32)
        self.assertEqual(sum(x["status"] == "failed" for x in rows), 1)
        targets = {q.identity: object() for _, q in samples()}
        report = evaluate_empty_evidence_controls(
            rows,
            targets,
            lambda answer, target: 0.5,
        )
        self.assertEqual(report["per_phase"]["select"]["failed"], 1)
        self.assertEqual(report["per_phase"]["select"]["answer_scored"], 7)
        self.assertEqual(
            report["per_phase"]["select"]["all_planned_diagnostic_f1_bounds"],
            [7 * 0.5 / 8, (7 * 0.5 + 1) / 8],
        )
        self.assertFalse(report["policy_scores_modified"])

    def test_any_returned_evidence_or_wrong_profile_is_rejected(self):
        def tamper(q, evidence, key):
            raw, receipt = fake(q, evidence, key)
            receipt["delivered_evidence"] = [{"label": "E1"}]
            return raw, receipt

        rows = self.controls(tamper)
        self.assertTrue(all(row["status"] == "failed" for row in rows))
        self.assertEqual(rows[0]["error_type"], "ValueError")

        def wrong_profile(q, evidence, key):
            raw, receipt = fake(q, evidence, key)
            receipt["generator_profile"] = "another-reader"
            return raw, receipt

        self.assertTrue(
            all(r["status"] == "failed" for r in self.controls(wrong_profile))
        )

    def test_unsupported_citation_markers_are_not_semantically_verified(self):
        rows = self.controls()
        targets = {q.identity: object() for _, q in samples()}
        report = evaluate_empty_evidence_controls(
            rows,
            targets,
            lambda answer, target: 1.0,
        )
        self.assertEqual(report["planned_controls"], 32)
        self.assertEqual(
            report["per_phase"]["transfer"]["unbound_evidence_marker_count"], 8
        )
        self.assertIsNone(
            report["per_phase"]["transfer"]["semantic_citation_precision"]
        )
        self.assertFalse(report["independent_gold_evidence_verified"])
        self.assertFalse(report["production_accepted"])

    def test_unscored_targets_and_failures_do_not_become_perfect_answers(self):
        rows = self.controls()
        targets = {q.identity: object() for _, q in samples()}
        result = evaluate_empty_evidence_controls(
            rows,
            targets,
            lambda answer, target: None,
        )
        self.assertIsNone(result["per_phase"]["select"]["diagnostic_f1_mean"])
        self.assertEqual(
            result["per_phase"]["select"]["all_planned_diagnostic_f1_bounds"], [0, 1]
        )

    def test_duplicate_score_record_and_invalid_f1_reject(self):
        rows = self.controls()
        targets = {q.identity: object() for _, q in samples()}
        for corrupt in ("duplicate", "invalid"):
            if corrupt == "duplicate":
                data = rows[:-1] + [rows[0]]
                with self.assertRaisesRegex(ValueError, "duplicate"):
                    evaluate_empty_evidence_controls(
                        data,
                        targets,
                        lambda answer, target: 1.0,
                    )
            else:
                with self.assertRaisesRegex(ValueError, "invalid diagnostic"):
                    evaluate_empty_evidence_controls(
                        rows,
                        targets,
                        lambda answer, target: float("nan"),
                    )


if __name__ == "__main__":
    unittest.main()
