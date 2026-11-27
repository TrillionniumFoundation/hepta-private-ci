"""Frozen-roster collection, label authentication and recovery contracts."""

from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest

from .prospective import FrozenAttempt, ShadowJournal
from .contracts import canonical_json, digest
from .shadow_risk import Prediction, Snapshot, Target, TerminalLabel


RISK, CHECKER, SCHEDULER, SUBJECT, VERSION, POLICY = (str(i) * 64 for i in range(1, 7))
TARGET = Target("local-documents", "terminal_goal_wrong", 3, POLICY)


class ProspectiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "shadow.sqlite"
        self.roster = tuple(FrozenAttempt(str(i), "heldout", SUBJECT) for i in range(4))

    def create(self, **changes):
        args = dict(
            target=TARGET,
            roster=self.roster,
            frontiers=(0, 2),
            risk_model_sha256=RISK,
            checker_model_sha256=CHECKER,
            scheduler_sha256=SCHEDULER,
            producer_id="producer",
            evaluator_id="independent-reader",
            evaluator_version_sha256=VERSION,
        )
        args.update(changes)
        return ShadowJournal.create(self.path, **args)

    def prediction(self, identity="0", step=0):
        return Prediction(
            Snapshot(identity, "heldout", SUBJECT, TARGET, step, (0.2,)), 0.2, RISK
        )

    def label(self, identity="0", disposition="accept", error=False):
        return TerminalLabel(
            identity,
            "heldout",
            SUBJECT,
            TARGET,
            disposition,
            error,
            3,
            "a" * 64 if error is not None else None,
            "terminal_not_observed" if error is None else None,
        )

    def ingest(self, journal, label, **changes):
        args = dict(evaluator_id="independent-reader", authenticate=lambda *args: True)
        args.update(changes)
        return journal.label(label, **args)

    def test_mixed_dispositions_no_prediction_and_reopen_keep_full_denominator(self):
        journal = self.create()
        journal.record(self.prediction())
        journal = ShadowJournal(self.path)
        journal.record(self.prediction(step=2))
        for identity, disposition, truth in (
            ("0", "accept", False),
            ("1", "reject", True),
            ("2", "interrupted", None),
            ("3", "unknown", False),
        ):
            journal.finish(identity, disposition)
            self.ingest(journal, self.label(identity, disposition, truth))
        report = ShadowJournal(self.path).report()
        self.assertEqual(
            (
                report["trajectories"],
                report["known_labels"],
                report["trajectories_with_predictions"],
                report["acceptance_coverage"],
            ),
            (4, 3, 1, 0.25),
        )
        self.assertEqual(report["accepted_error_missing_label_bounds"], [0.0, 0.0])
        self.assertEqual(
            report["by_disposition"]["interrupted"]["missing_reasons"],
            {"terminal_not_observed": 1},
        )
        self.assertEqual(
            [
                report["by_step"][str(step)]["missing_prediction_count"]
                for step in (0, 2)
            ],
            [3, 3],
        )
        self.assertTrue(report["prospective_order_enforced"])
        self.assertEqual(
            {
                key: report[key]
                for key in (
                    "wall_clock_prospectiveness_proved",
                    "independent_evaluation_established",
                    "full_physical_cost_complete",
                )
            },
            dict(
                wall_clock_prospectiveness_proved=False,
                independent_evaluation_established=False,
                full_physical_cost_complete=False,
            ),
        )
        self.assertEqual(
            (report["production_authority"], report["scientific_admission"]),
            ("NONE", "HOLD"),
        )
        self.assertEqual(report, ShadowJournal(self.path).report())

    def test_duplicate_and_late_forecasts_cannot_replace_prior_evidence(self):
        journal = self.create()
        journal.record(self.prediction())
        with self.assertRaises(ValueError):
            journal.record(replace(self.prediction(), probability=0.9))
        journal.finish("0", "accept")
        with self.assertRaises(ValueError):
            journal.record(self.prediction(step=2))
        with self.assertRaises(ValueError):
            journal.finish("0", "reject")
        self.ingest(journal, self.label())
        with self.assertRaises(ValueError):
            self.ingest(journal, self.label(error=True))
        journal.record(self.prediction(identity="1", step=2))
        with self.assertRaises(ValueError):
            journal.record(self.prediction(identity="1", step=0))

    def test_frozen_model_roster_subject_frontier_and_target_bind_predictions(self):
        journal = self.create()
        prediction = self.prediction()
        invalid = (
            replace(prediction, model_sha256="f" * 64),
            replace(
                prediction,
                snapshot=replace(prediction.snapshot, trajectory_id="unknown"),
            ),
            replace(
                prediction,
                snapshot=replace(prediction.snapshot, subject_sha256="f" * 64),
            ),
            replace(
                prediction, snapshot=replace(prediction.snapshot, source_group="train")
            ),
            replace(prediction, snapshot=replace(prediction.snapshot, observed_step=1)),
            replace(
                prediction,
                snapshot=replace(
                    prediction.snapshot, target=replace(TARGET, event="other")
                ),
            ),
        )
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValueError):
                journal.record(item)
        journal.record(prediction)

    def test_labels_need_original_disposition_horizon_and_authenticated_evaluator(self):
        journal = self.create()
        with self.assertRaises(ValueError):
            self.ingest(journal, self.label())
        journal.finish("0", "accept")
        invalid = (
            self.label(disposition="reject"),
            replace(self.label(), subject_sha256="f" * 64),
            replace(self.label(), target=replace(TARGET, event="other")),
        )
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValueError):
                self.ingest(journal, item)
        with self.assertRaises(ValueError):
            replace(self.label(), observed_step=2)
        with self.assertRaises(ValueError):
            self.ingest(journal, self.label(), evaluator_id="producer")
        for response in (False, None, 1, "authenticated"):
            with self.subTest(response=response), self.assertRaises(ValueError):
                self.ingest(journal, self.label(), authenticate=lambda *args: response)
        calls = []

        def authenticate(actor, label, version, manifest_sha256):
            self.assertRegex(manifest_sha256, r"^[0-9a-f]{64}$")
            calls.append((actor, label, version, manifest_sha256))
            return True

        self.ingest(journal, self.label(), authenticate=authenticate)
        self.assertEqual(
            [call[:3] for call in calls],
            [("independent-reader", self.label(), VERSION)],
        )

    def test_incomplete_roster_refuses_reporting_and_existing_file_refuses_create(self):
        journal = self.create()
        with self.assertRaises((FileExistsError, ValueError)):
            self.create()
        with self.assertRaises(ValueError):
            journal.report()
        for attempt in self.roster:
            journal.finish(attempt.trajectory_id, "unknown")
        with self.assertRaises(ValueError):
            journal.report()
        for attempt in self.roster:
            self.ingest(journal, self.label(attempt.trajectory_id, "unknown", None))
        self.assertEqual(journal.report()["accepted_error_missing_label_bounds"], None)
        self.assertEqual(
            journal.report()["by_step"]["0"]["missing_prediction_count"], 4
        )

    def test_create_rejects_ambiguous_roster_and_same_producer_evaluator(self):
        for changes in (
            dict(roster=(self.roster[0], self.roster[0])),
            dict(frontiers=(0, 0)),
            dict(frontiers=(3,)),
            dict(evaluator_id="producer"),
            dict(risk_model_sha256="bad"),
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.create(**changes)
        journal = self.create()
        self.assertIsNotNone(journal)

    def test_corrupt_storage_never_becomes_empty_success(self):
        self.path.write_bytes(b"invalid sqlite evidence")
        with self.assertRaises((ValueError, sqlite3.DatabaseError)):
            ShadowJournal(self.path).report()

    def test_expected_ledger_checkpoint_rejects_truncated_valid_history(self):
        journal = self.create()
        journal.record(self.prediction())
        with journal._transaction() as connection:
            retained = journal._read(connection)[4]
        recovered = ShadowJournal(self.path, expected_ledger_sha256=retained)
        recovered.record(self.prediction(step=2))
        with self.assertRaisesRegex(ValueError, "retained checkpoint"):
            ShadowJournal(self.path, expected_ledger_sha256=retained)
        with journal._transaction() as connection:
            current = journal._read(connection)[4]
            connection.execute("DELETE FROM events WHERE seq = 2")
        with self.assertRaisesRegex(ValueError, "retained checkpoint"):
            ShadowJournal(self.path, expected_ledger_sha256=current)
        ShadowJournal(self.path, expected_ledger_sha256=retained)

    def test_frozen_manifest_remains_pinned_on_live_and_expected_reopen(self):
        import json

        journal = self.create()
        root = journal.manifest_sha256
        with closing(sqlite3.connect(self.path)) as connection, connection:
            manifest = json.loads(
                connection.execute("SELECT body FROM frozen").fetchone()[0]
            )
            manifest["scheduler_sha256"] = "f" * 64
            connection.execute(
                "UPDATE frozen SET body=?, sha=?",
                (canonical_json(manifest), digest(manifest)),
            )
        with self.assertRaises(ValueError):
            journal.record(self.prediction())
        with self.assertRaises(ValueError):
            ShadowJournal(self.path, expected_manifest_sha256=root)

    def test_malformed_manifest_refuses_recovery(self):
        self.create()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE frozen SET body='[]'")
        with self.assertRaises(ValueError):
            ShadowJournal(self.path)

    def test_changed_event_digest_refuses_reopen(self):
        journal = self.create()
        journal.record(self.prediction())
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "UPDATE events SET sha = ? WHERE seq = (SELECT MAX(seq) FROM events)",
                ("f" * 64,),
            )
        with self.assertRaises(ValueError):
            ShadowJournal(self.path).report()
