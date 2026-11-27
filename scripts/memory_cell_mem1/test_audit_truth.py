"""Outcome mutations against a frozen input, independent of reported labels."""

import copy
import hashlib
import json
import unittest

import test_verify_results as evidence


class TruthVerificationTests(unittest.TestCase):
    setUp = evidence.EvidenceVerificationTests.setUp
    check = evidence.EvidenceVerificationTests.check

    def probe(self):
        return next(row for row in self.events if row["event"] == "probe")

    def test_forging_probe_answer_and_expected_together_is_rejected(self):
        row = self.probe()
        self.assertEqual((row["sources"], row["expected"]), (["A:0"], [6]))
        row["output"] = row["expected"] = [7]
        with self.assertRaisesRegex(ValueError, "expected differs from frozen"):
            self.check()

    def test_non_b_prequential_correct_flags_are_checked(self):
        for phase in ("A1", "A2"):
            row = next(
                r
                for r in self.events
                if r["event"] == "prequential" and r["phase"] == phase
            )
            with self.subTest(phase=phase):
                row["correct"] = not row["correct"]
                with self.assertRaisesRegex(ValueError, "correct differs from frozen"):
                    self.check()
                row["correct"] = not row["correct"]

    def test_b_prequential_labels_are_not_their_own_ground_truth(self):
        row = next(
            r for r in self.events if r["event"] == "prequential" and r["phase"] == "B"
        )
        row["expected"] = [(row["expected"][0] + 1) % 8]
        with self.assertRaisesRegex(ValueError, "expected differs from frozen"):
            self.check()

    def test_every_outcome_flag_is_derived_from_frozen_truth(self):
        row = self.probe()
        for field in (
            "eligible",
            "correct",
            "answered",
            "wrong_assertion",
            "stale_assertion",
            "invalid_assertion",
        ):
            with self.subTest(field=field):
                row[field] = not row[field]
                with self.assertRaisesRegex(ValueError, field + " differs from frozen"):
                    self.check()
                row[field] = not row[field]

    def test_truth_flags_require_booleans_not_equal_integers(self):
        row = self.probe()
        for field in (
            "eligible",
            "correct",
            "answered",
            "wrong_assertion",
            "stale_assertion",
            "invalid_assertion",
        ):
            with self.subTest(field=field):
                old = row[field]
                row[field] = int(old)
                with self.assertRaisesRegex(ValueError, field + " differs from frozen"):
                    self.check()
                row[field] = old

    def test_output_shape_type_and_label_domain_are_checked(self):
        row = self.probe()
        for output in (
            6,
            "6",
            [],
            [6, 6],
            [True],
            [6.0],
            ["6"],
            [None],
            [-1],
            [8],
            [float("nan")],
        ):
            with self.subTest(output=output):
                row["output"] = output
                with self.assertRaisesRegex(ValueError, "output must contain"):
                    self.check()

    def test_expected_labels_reject_boolean_integer_aliases(self):
        row = next(
            r for r in self.events if r["event"] == "probe" and r["expected"] == [1]
        )
        row["expected"] = [True]
        with self.assertRaisesRegex(ValueError, "expected must contain"):
            self.check()

    def test_missing_output_or_expected_is_not_an_abstention(self):
        row = next(
            r for r in self.events if r["event"] == "probe" and r["expected"] is None
        )
        for field in ("output", "expected"):
            with self.subTest(field=field):
                old = row.pop(field)
                with self.assertRaises(ValueError):
                    self.check()
                row[field] = old

    def test_frozen_fact_types_and_source_roster_are_checked_after_hashing(self):
        path = self.root / "inputs.json"
        original = json.loads(path.read_text())
        mutations = [
            ("label", True),
            ("label", 8),
            ("version", True),
            ("version", 2),
            ("live", 1),
            ("replay", 1),
            ("scope", "scope:other"),
            ("source", "B:0"),
            ("source", "unknown"),
            ("source", ["A:0"]),
        ]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(original)
                changed["0"]["initial_facts"][0][field] = value
                evidence.dump(path, changed)
                self.manifest["inputs_sha256"] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                with self.assertRaises(ValueError):
                    self.check()

    def test_frozen_fact_roster_cannot_be_missing_or_shortened(self):
        path = self.root / "inputs.json"
        original = json.loads(path.read_text())
        for records in (None, [], original["0"]["initial_facts"][:-1]):
            with self.subTest(records=records):
                changed = copy.deepcopy(original)
                changed["0"]["initial_facts"] = records
                evidence.dump(path, changed)
                self.manifest["inputs_sha256"] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                with self.assertRaisesRegex(ValueError, "frozen initial facts"):
                    self.check()

    def test_exposure_reset_and_read_only_probes_cannot_be_forged(self):
        rows = [
            next(r for r in self.events if r["event"] == "prequential"),
            next(
                r
                for r in self.events
                if r["event"] == "prequential"
                and r["phase"] == "B"
                and r["sources"] == ["A:8"]
            ),
            next(
                r
                for r in self.events
                if r["event"] == "prequential" and r["sources"] == ["B:3"]
            ),
        ]
        for row in rows:
            with self.subTest(sources=row["sources"], phase=row["phase"]):
                self.assertEqual(row["blocked"], [True])
                row["blocked"] = [False]
                with self.assertRaisesRegex(ValueError, "blocked differs"):
                    self.check()
                row["blocked"] = [True]

    def test_composition_keeps_one_exposure_flag_per_constituent(self):
        row = next(
            r
            for r in self.events
            if r["event"] == "probe" and r["panel"] == "composition"
        )
        self.assertEqual(row["blocked"], [False, True])
        for flags in ([False], [False, 1], [True, False], [False, False]):
            with self.subTest(flags=flags):
                row["blocked"] = flags
                with self.assertRaisesRegex(ValueError, "blocked differs"):
                    self.check()

    def test_honest_stale_failure_is_retained_but_cannot_be_hidden(self):
        rows = [
            r
            for r in self.events
            if r["event"] == "prequential"
            and r["phase"] == "B"
            and r["sources"] == ["A:8"]
        ]
        row = rows[1]
        row.update(
            output=[(row["expected"][0] - 3) % 8],
            correct=False,
            wrong_assertion=True,
            stale_assertion=True,
        )
        self.assertEqual(self.check()["production_adoption"], "NoUpdate")
        row["stale_assertion"] = False
        with self.assertRaisesRegex(ValueError, "stale_assertion differs"):
            self.check()

    def test_honest_invalid_failure_is_retained_but_cannot_be_hidden(self):
        row = next(
            r
            for r in self.events
            if r["event"] == "probe" and r["phase"] == "B" and r["panel"] == "revoked"
        )
        facts = json.loads((self.root / "inputs.json").read_text())["0"][
            "initial_facts"
        ]
        label = next(f["label"] for f in facts if f["source"] == "A:10")
        row.update(output=[label], answered=True, correct=False, invalid_assertion=True)
        self.result["panels"]["B"]["revoked"].update(
            accuracy=0.0, coverage=1.0, invalid_assertions=1
        )
        self.assertEqual(self.check()["scientific_qualification"], "HOLD")
        row["invalid_assertion"] = False
        with self.assertRaisesRegex(ValueError, "invalid_assertion differs"):
            self.check()


class StationaryTruthTests(unittest.TestCase):
    owner_change = False
    setUp = evidence.EvidenceVerificationTests.setUp
    check = evidence.EvidenceVerificationTests.check

    def test_stationary_owner_truth_is_preserved_through_b(self):
        self.assertEqual(self.check()["truth_audit"]["queries"], 300)
        row = next(
            r for r in self.events if r["event"] == "prequential" and r["phase"] == "B"
        )
        row["output"] = row["expected"] = [(row["expected"][0] + 3) % 8]
        with self.assertRaisesRegex(ValueError, "expected differs from frozen"):
            self.check()


if __name__ == "__main__":
    unittest.main()
