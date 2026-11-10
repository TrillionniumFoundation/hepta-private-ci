"""Actual local checker calls are engineering fixtures, not independent trials."""

from pathlib import Path
from contextlib import closing
from dataclasses import asdict, replace
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from .checker_effects import CheckerSpec, EffectScope, PairedPanel, fit_checker_effects
from .contracts import digest
from .prospective import FrozenAttempt, ShadowJournal
from .shadow_risk import Prediction, Snapshot, Target, TerminalLabel
from .shadow_schedule import CheckObservation, observation_context
from .treatment import TreatmentJournal


class TreatmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "journal.sqlite"
        self.target = Target(
            "local-artifact", "unchanged_artifact_wrong", 3, digest("read-only")
        )
        self.predictions = tuple(
            Prediction(
                Snapshot(str(i), "heldout", digest(i), self.target, 0, (1,)),
                0.3,
                digest("risk"),
            )
            for i in range(4)
        )
        self.checkers = (CheckerSpec("readback", digest("readback-v1"), 0.1),)
        scope = EffectScope(
            self.target.domain,
            self.target.event,
            0,
            3,
            self.target.continuation_policy_sha256,
            observation_context(self.predictions[0].snapshot),
        )
        panels = tuple(
            PairedPanel(
                str(i),
                "training",
                digest([i, "calibration"]),
                scope,
                ("readback",),
                (self.checkers[0].version_sha256,),
                ("fail" if i % 2 else "pass",),
                bool(i % 2),
                digest([i, "label"]),
                (digest([i, "checker"]),),
            )
            for i in range(8)
        )
        self.effects = fit_checker_effects(
            panels,
            scope=scope,
            checkers=self.checkers,
            training_groups=("training",),
            heldout_groups=("heldout",),
        )
        self.shadow = ShadowJournal.create(
            self.path,
            target=self.target,
            roster=tuple(
                FrozenAttempt(
                    p.snapshot.trajectory_id, "heldout", p.snapshot.subject_sha256
                )
                for p in self.predictions
            ),
            frontiers=(0, 2),
            risk_model_sha256=digest("risk"),
            checker_model_sha256=self.effects.model_sha256,
            scheduler_sha256=digest("scheduler"),
            producer_id="producer",
            evaluator_id="separate-reader",
            evaluator_version_sha256=digest("evaluator"),
        )
        self.journal = TreatmentJournal.create(self.shadow, self.checkers)

    def choose(self, index=0, **changes):
        args = dict(
            prediction=self.predictions[index],
            effects=self.effects,
            observations=(),
            actions=("accept", "reject"),
            losses=((0, 100), (5, 5)),
            remaining_budget=1,
            hard_checks_complete=True,
        )
        args.update(changes)
        return self.journal.choose(**args)

    def disposition(self, identity="0", disposition="reject", **changes):
        args = dict(
            hard_checks_complete=True, gate_evidence_sha256=digest("host-gates")
        )
        args.update(changes)
        self.journal.record_disposition(identity, disposition, **args)

    def label(self, identity, disposition, error):
        prediction = self.predictions[int(identity)]
        label = TerminalLabel(
            identity,
            "heldout",
            prediction.snapshot.subject_sha256,
            self.target,
            disposition,
            error,
            3,
            digest([identity, "truth"]) if error is not None else None,
            "not-observed" if error is None else None,
        )
        self.shadow.label(
            label, evaluator_id="separate-reader", authenticate=lambda *args: True
        )

    def finish_all(self, primary="reject", truth=True):
        for identity, disposition, error in (
            ("0", primary, truth),
            ("1", "accept", False),
            ("2", "interrupted", None),
            ("3", "unknown", False),
        ):
            self.shadow.finish(identity, disposition)
            self.label(identity, disposition, error)

    def test_real_read_only_subprocess_and_recovery_preserve_full_roster(self):
        self.shadow.record(self.predictions[0])
        choice = self.choose()
        self.assertEqual(choice["status"], "check")
        self.journal.start(choice["record_sha256"], "original-op")
        artifact = Path(self.temporary.name) / "artifact.json"
        artifact.write_text('{"answer": 7}', encoding="utf-8")
        started = time.perf_counter()
        process = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json,sys; print('pass' if json.load(open(sys.argv[1]))['answer']==7 else 'fail')",
                str(artifact),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        costs = dict(
            wall_seconds=time.perf_counter() - started,
            cpu_seconds=None,
            energy_joules=None,
        )
        evidence = digest(
            dict(
                stdout=process.stdout,
                stderr=process.stderr,
                returncode=process.returncode,
            )
        )
        self.journal = TreatmentJournal(ShadowJournal(self.path))
        self.journal.complete("original-op", process.stdout.strip(), evidence, costs)
        self.disposition(disposition="accept")
        self.finish_all(primary="accept", truth=False)
        report = self.journal.report()
        self.assertEqual(
            (report["trajectories"], report["acceptance_coverage"]), (4, 0.5)
        )
        self.assertEqual(report["accepted_error_missing_label_bounds"], [0.0, 0.0])
        self.assertEqual(
            report["all_trajectory_false_accept_missing_label_bounds"], [0.0, 0.0]
        )
        self.assertEqual(report["production_authority"], "NONE")
        self.assertEqual(report["scientific_admission"], "HOLD")
        self.assertFalse(report["full_physical_cost_complete"])
        self.assertEqual(report, TreatmentJournal(ShadowJournal(self.path)).report())

    def test_pending_check_reconciles_after_original_host_completion(self):
        self.shadow.record(self.predictions[0])
        choice = self.choose()
        self.journal.start(choice["record_sha256"], "original-op")
        self.disposition(disposition="interrupted")
        self.finish_all(primary="interrupted", truth=None)
        before = self.journal.report()
        self.journal = TreatmentJournal(ShadowJournal(self.path))
        self.journal.complete(
            "original-op",
            "fail",
            digest("retained-original-reply"),
            dict(wall_seconds=None, cpu_seconds=None, energy_joules=None),
        )
        self.assertNotEqual(before, self.journal.report())
        with self.assertRaises(ValueError):
            self.journal.start(choice["record_sha256"], "retry")

    def test_invalid_costs_cannot_silently_become_zero(self):
        self.shadow.record(self.predictions[0])
        self.journal.start(self.choose()["record_sha256"], "original-op")
        for cost in (-1, float("nan"), float("inf"), 1e308, True, "0"):
            with self.subTest(cost=cost), self.assertRaises(ValueError):
                self.journal.complete(
                    "original-op",
                    "pass",
                    digest("reply"),
                    dict(wall_seconds=cost, cpu_seconds=None, energy_joules=None),
                )
        with self.assertRaises(ValueError):
            self.journal.complete("original-op", "pass", digest("reply"), {})

    def test_multiple_attempts_keep_distinct_original_operations_and_pending_state(
        self,
    ):
        for index in range(3):
            self.shadow.record(self.predictions[index])
            choice = self.choose(index)
            self.journal.start(choice["record_sha256"], "operation-" + str(index))
        self.journal = TreatmentJournal(ShadowJournal(self.path))
        for index, outcome in ((0, "pass"), (1, "fail")):
            self.journal.complete(
                "operation-" + str(index),
                outcome,
                digest([index, "reply"]),
                dict(wall_seconds=0.1, cpu_seconds=None, energy_joules=None),
            )
        self.finish_all()
        report = self.journal.report()
        self.assertEqual(report["pending_operation_ids"], ["operation-2"])
        self.assertEqual(
            [
                report["treatments"][str(i)]["operations"][0]["operation_id"]
                for i in range(3)
            ],
            ["operation-0", "operation-1", "operation-2"],
        )

    def test_unrecorded_prediction_and_model_drift_refuse(self):
        with self.assertRaises(ValueError):
            self.choose()
        self.shadow.record(self.predictions[0])
        with self.assertRaises(ValueError):
            self.choose(prediction=replace(self.predictions[0], probability=0.9))
        with self.assertRaises(ValueError):
            self.choose(effects=replace(self.effects, model_sha256=digest("different")))
        self.choose()

    def test_registry_is_create_only_and_frozen_before_forecasts(self):
        with self.assertRaises((ValueError, sqlite3.DatabaseError)):
            TreatmentJournal.create(self.shadow, self.checkers)
        other = Path(self.temporary.name) / "other.sqlite"
        with (
            closing(sqlite3.connect(self.path)) as source,
            closing(sqlite3.connect(other)) as destination,
        ):
            source.backup(destination)
        with closing(sqlite3.connect(other)) as connection, connection:
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall():
                if name not in ("frozen", "events"):
                    connection.execute('DROP TABLE "' + name.replace('"', '""') + '"')
        shadow = ShadowJournal(other)
        shadow.record(self.predictions[0])
        with self.assertRaises(ValueError):
            TreatmentJournal.create(shadow, self.checkers)

    def test_original_operation_never_replays_and_unknown_is_an_observed_result(self):
        self.shadow.record(self.predictions[0])
        choice = self.choose()
        self.journal.start(choice["record_sha256"], "original-op")
        for operation in ("original-op", "new-op"):
            with self.assertRaises(ValueError):
                self.journal.start(choice["record_sha256"], operation)
        self.journal.complete(
            "original-op",
            "unknown",
            digest("lost-readback"),
            dict(wall_seconds=0.1, cpu_seconds=None, energy_joules=None),
        )
        with self.assertRaises(ValueError):
            self.journal.complete(
                "original-op",
                "pass",
                digest("later"),
                dict(wall_seconds=0.2, cpu_seconds=None, energy_joules=None),
            )
        self.disposition(disposition="unknown")
        self.finish_all(primary="unknown", truth=None)
        self.assertEqual(
            self.journal.report()["by_disposition"]["unknown"]["known_labels"], 1
        )

    def test_no_post_finish_choice_dispatch_or_changed_disposition(self):
        self.shadow.record(self.predictions[0])
        choice = self.choose()
        self.disposition()
        self.finish_all()
        for operation in (
            lambda: self.choose(),
            lambda: self.journal.start(choice["record_sha256"], "late-op"),
            lambda: self.disposition(disposition="accept"),
        ):
            with self.assertRaises(ValueError):
                operation()

    def test_observation_cannot_be_injected_without_actual_operation(self):
        self.shadow.record(self.predictions[0])
        observation = CheckObservation(
            "readback",
            self.checkers[0].version_sha256,
            digest(asdict(self.predictions[0].snapshot)),
            "pass",
            digest("invented"),
        )
        with self.assertRaises(ValueError):
            self.choose(observations=(observation,))

    def test_accept_requires_literal_host_gate_and_pending_cannot_accept(self):
        for gate in (False, None, 1, "yes"):
            with self.subTest(gate=gate), self.assertRaises(ValueError):
                self.disposition(disposition="accept", hard_checks_complete=gate)
        self.shadow.record(self.predictions[0])
        choice = self.choose()
        self.journal.start(choice["record_sha256"], "original-op")
        with self.assertRaises(ValueError):
            self.disposition(disposition="accept")

    def test_repair_cannot_silently_change_terminal_estimand(self):
        self.shadow.record(self.predictions[0])
        with self.assertRaises(ValueError):
            self.choose(actions=("accept", "repair"))

    def test_expected_treatment_checkpoint_rejects_truncation(self):
        self.shadow.record(self.predictions[0])
        self.choose()
        with self.shadow._transaction() as connection:
            root = self.journal._read(connection)[4]
        TreatmentJournal(ShadowJournal(self.path), expected_ledger_sha256=root)
        with self.shadow._transaction() as connection:
            connection.execute("DELETE FROM treatment_events")
        with self.assertRaisesRegex(ValueError, "ledger root changed"):
            TreatmentJournal(ShadowJournal(self.path), expected_ledger_sha256=root)

    def test_terminal_disposition_mismatch_refuses_joined_report(self):
        self.disposition(disposition="reject")
        self.finish_all(primary="accept", truth=True)
        with self.assertRaises(ValueError):
            self.journal.report()


if __name__ == "__main__":
    unittest.main()
