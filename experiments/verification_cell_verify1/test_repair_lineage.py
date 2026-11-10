"""Synthetic custody fixtures only; no real repair or independent task result."""

from dataclasses import asdict
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from .contracts import canonical_json, digest
from .cost_ledger import CostItem, CostReceipt
from .prospective import FrozenAttempt, ShadowJournal
from .repair_lineage import RepairLineage
from .shadow_risk import Target, TerminalLabel


def owner_verify(manifest, claim, attestation):
    return attestation == digest(["synthetic-owner-only", manifest, claim])


def label_verify(issuer, label, version, manifest, attestation):
    return attestation == digest(
        ["synthetic-label-only", issuer, asdict(label), version, manifest]
    )


class RepairLineageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.journals = []
        for side in ("parent", "child"):
            target = Target("artifact", "goal_wrong", 3, digest(side + "-policy"))
            roster = tuple(
                FrozenAttempt(key, "group", digest([side, key]))
                for key in ("repair", "none", "abstain", "missing", "pending")
            )
            self.journals.append(
                ShadowJournal.create(
                    root / (side + ".sqlite"),
                    target=target,
                    roster=roster,
                    frontiers=(0,),
                    risk_model_sha256=digest("risk"),
                    checker_model_sha256=digest("checker"),
                    scheduler_sha256=digest("scheduler"),
                    producer_id="producer",
                    evaluator_id="evaluator",
                    evaluator_version_sha256=digest("evaluator"),
                )
            )
        self.parent, self.child = self.journals
        self.repair = RepairLineage.create(
            self.parent,
            self.child,
            study_id="fixture-study",
            owner_id="original-owner",
            owner_version_sha256=digest("owner"),
            cost_roster=(
                CostItem("owner-cost", "repair", "repair", "owner", "clock"),
                CostItem("label-cost", "study", "evaluation", "evaluator", "clock"),
            ),
        )

    def proof(self, claim):
        with self.parent._transaction() as db:
            manifest = self.repair._read(db)[0]
        return digest(["synthetic-owner-only", manifest, claim])

    def record(self, claim):
        self.repair.record(
            claim, attestation=self.proof(claim), authenticate=owner_verify
        )

    def start(self, key="repair", operation="original-op"):
        claim = self.repair.prepare(key, operation, digest("advisory-choice"))
        self.record(claim)
        return claim

    def label(self, journal, key, error):
        with journal._transaction() as db:
            manifest = journal._read(db)[0]
        row = next(row for row in manifest["roster"] if row["trajectory_id"] == key)
        label = TerminalLabel(
            **row,
            target=Target(**manifest["target"]),
            disposition="accept",
            error=error,
            observed_step=3,
            evidence_sha256=digest([key, error]),
            missing_reason=None,
        )
        journal.finish(key, "accept")
        attestation = digest(
            [
                "synthetic-label-only",
                "evaluator",
                asdict(label),
                digest("evaluator"),
                journal.manifest_sha256,
            ]
        )
        journal.label(
            label,
            evaluator_id="evaluator",
            authenticate=label_verify,
            attestation=attestation,
        )
        return label

    def test_full_denominator_recovery_and_separate_target_labels(self):
        self.start()
        self.start("pending", "pending-op")
        for key, status in (("none", "no_repair"), ("abstain", "abstained")):
            self.repair.record(
                dict(attempt_id=key, status=status, reason="original host decision")
            )
        old = self.label(self.parent, "repair", True)
        new = self.label(self.child, "repair", False)
        self.record(
            self.repair.completion(
                "repair", "completed", digest("actual-child-readback")
            )
        )
        report = self.repair.report(
            authenticate_owner=owner_verify, authenticate_labels=label_verify
        )
        self.assertEqual(
            report["disposition_counts"],
            dict(
                unrecorded=1, no_repair=1, abstained=1, pending=1, failed=0, completed=1
            ),
        )
        self.assertEqual(
            (
                report["planned_attempts"],
                report["authenticated_label_pairs"],
                report["observed_error_corrections"],
                report["observed_errors_induced"],
            ),
            (5, 1, 1, 0),
        )
        self.assertFalse(report["full_physical_cost_complete"])
        self.assertEqual(
            report["costs"]["missing_operations"], ["label-cost", "owner-cost"]
        )
        recovered = RepairLineage(
            self.parent,
            self.child,
            expected_manifest_sha256=report["manifest_sha256"],
            expected_ledger_sha256=report["ledger_sha256"],
        )
        self.assertEqual(recovered.report()["attempts"]["pending"], "pending")
        with self.assertRaises(ValueError):
            recovered.prepare(
                "pending", "new-operation-is-not-recovery", digest("choice")
            )
        with self.assertRaises(ValueError):
            self.parent.label(
                new,
                evaluator_id="evaluator",
                authenticate=lambda *args: True,
                attestation="wrong target",
            )
        with self.parent._transaction() as db:
            self.assertEqual(self.parent._read(db)[3]["repair"], old)

    def test_old_receipt_operation_replay_and_truthy_callback_refuse(self):
        claim = self.start()
        for value in (False, 1, "true", None):
            prepared = self.repair.prepare("pending", "another-op", digest("choice"))
            with self.assertRaises(ValueError):
                self.repair.record(
                    prepared,
                    attestation=self.proof(prepared),
                    authenticate=lambda *args, v=value: v,
                )
        with self.assertRaises(ValueError):
            self.record(claim)
        with self.assertRaises(ValueError):
            self.repair.prepare("pending", "original-op", digest("choice"))
        other = self.repair.prepare("pending", "another-op", digest("choice"))
        with self.assertRaises(ValueError):
            self.repair.record(
                other, attestation=self.proof(claim), authenticate=owner_verify
            )

    def test_rehashing_a_changed_completion_does_not_authenticate_it(self):
        self.start()
        self.record(
            self.repair.completion("repair", "failed", digest("failed-readback"))
        )
        with closing(sqlite3.connect(self.parent.path)) as db, db:
            seq, body = db.execute(
                "SELECT seq,body FROM repair_events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            event = json.loads(body)
            event["claim"]["status"] = "completed"
            db.execute(
                "UPDATE repair_events SET body=?,sha=? WHERE seq=?",
                (canonical_json(event), digest(event), seq),
            )
        self.assertIsNone(self.repair.report()["observed_error_corrections"])
        with self.assertRaises(ValueError):
            self.repair.report(
                authenticate_owner=owner_verify, authenticate_labels=label_verify
            )

    def test_source_drift_and_changed_external_checkpoint_refuse(self):
        before = self.repair.report()
        self.start()
        with self.assertRaisesRegex(ValueError, "external checkpoint"):
            RepairLineage(
                self.parent,
                self.child,
                expected_manifest_sha256=before["manifest_sha256"],
                expected_ledger_sha256=before["ledger_sha256"],
            )
        with closing(sqlite3.connect(self.child.path)) as db, db:
            manifest = json.loads(db.execute("SELECT body FROM frozen").fetchone()[0])
            manifest["roster"][0]["subject_sha256"] = digest(
                "substituted repaired artifact"
            )
            db.execute(
                "UPDATE frozen SET body=?,sha=?",
                (canonical_json(manifest), digest(manifest)),
            )
        with self.assertRaises(ValueError):
            RepairLineage(
                self.parent,
                ShadowJournal(self.child.path),
                expected_manifest_sha256=before["manifest_sha256"],
            )

    def test_callback_mutation_and_parent_advance_refuse_intent(self):
        claim = self.repair.prepare("repair", "op", digest("choice"))

        def mutate(manifest, value, proof):
            valid = owner_verify(manifest, value, proof)
            value["choice_sha256"] = digest("changed-after-verification")
            return valid

        with self.assertRaises(ValueError):
            self.repair.record(
                claim, attestation=self.proof(claim), authenticate=mutate
            )

        def advance(manifest, value, proof):
            self.parent.finish("none", "unknown")
            return owner_verify(manifest, value, proof)

        with self.assertRaisesRegex(ValueError, "stale repair source"):
            self.repair.record(
                claim, attestation=self.proof(claim), authenticate=advance
            )
        self.assertEqual(self.repair.report()["disposition_counts"]["unrecorded"], 5)

    def test_rehashed_recovery_manifest_cannot_make_owner_its_evaluator(self):
        with closing(sqlite3.connect(self.parent.path)) as db, db:
            manifest = json.loads(
                db.execute("SELECT body FROM repair_frozen").fetchone()[0]
            )
            manifest["owner_id"] = "evaluator"
            root = digest(manifest)
            db.execute(
                "UPDATE repair_frozen SET body=?,sha=?",
                (canonical_json(manifest), root),
            )
        with self.assertRaisesRegex(ValueError, "owner cannot also"):
            RepairLineage(self.parent, self.child, expected_manifest_sha256=root)

    def test_missing_or_unauthenticated_labels_never_count_corrections(self):
        self.start()
        self.record(self.repair.completion("repair", "completed", digest("readback")))
        report = self.repair.report(
            authenticate_owner=owner_verify, authenticate_labels=label_verify
        )
        self.assertEqual(report["terminal_repairs_without_both_known_labels"], 1)
        self.assertIsNone(report["observed_error_corrections"])
        self.label(self.parent, "repair", False)
        self.label(self.child, "repair", True)
        self.assertIsNone(self.repair.report()["observed_errors_induced"])
        report = self.repair.report(
            authenticate_owner=owner_verify, authenticate_labels=label_verify
        )
        self.assertEqual(
            (report["observed_error_corrections"], report["observed_errors_induced"]),
            (0, 1),
        )
        self.start("none", "failed-op")
        self.label(self.parent, "none", False)
        self.label(self.child, "none", True)
        self.record(
            self.repair.completion(
                "none", "failed", digest("failed-operation-readback")
            )
        )
        report = self.repair.report(
            authenticate_owner=owner_verify, authenticate_labels=label_verify
        )
        self.assertEqual(
            (report["disposition_counts"]["failed"], report["observed_errors_induced"]),
            (1, 2),
        )
        self.assertEqual(
            (report["scientific_admission"], report["production_authority"]),
            ("HOLD", "NONE"),
        )

    def test_cost_authentication_cannot_hide_missing_declared_work(self):
        with self.parent._transaction() as db:
            manifest = self.repair._read(db)[0]
        receipts = [
            CostReceipt(
                CostItem(**row),
                "completed",
                0,
                10**9,
                0.1,
                100,
                1.0,
                0.0,
                digest(row),
                (),
            )
            for row in manifest["cost_roster"]
        ]
        self.assertFalse(
            self.repair.report(cost_receipts=receipts)["full_physical_cost_complete"]
        )
        partial = self.repair.report(
            cost_receipts=receipts[:1],
            cost_attestation="synthetic-completeness-claim",
            authenticate_cost=lambda *args: True,
        )
        self.assertFalse(partial["full_physical_cost_complete"])
        self.assertEqual(partial["costs"]["missing_operations"], ["label-cost"])
        with self.assertRaises(ValueError):
            self.repair.report(
                cost_receipts=receipts,
                cost_attestation="not-literal-true",
                authenticate_cost=lambda *args: 1,
            )

    def test_child_writer_excluded_before_intent_insert_and_through_parent_commit(self):
        marks = []

        def child_is_locked():
            with closing(sqlite3.connect(self.child.path, timeout=0)) as probe:
                try:
                    with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                        probe.execute("BEGIN IMMEDIATE")
                finally:
                    probe.rollback()

        class GuardedCommit(sqlite3.Connection):
            def commit(connection):
                if connection.in_transaction and connection.total_changes:
                    child_is_locked()
                    marks.append("parent_commit_while_child_locked")
                return super().commit()

        @contextmanager
        def parent_transaction():
            db = sqlite3.connect(self.parent.path, factory=GuardedCommit)
            try:
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

        claim = self.repair.prepare("repair", "original-race-op", digest("choice"))
        proof, original_read, calls = self.proof(claim), self.repair._read, 0

        def read(db, **kwargs):
            nonlocal calls
            snapshot = original_read(db, **kwargs)
            calls += 1
            if calls == 2:
                child_is_locked()
                marks.append("child_locked_before_intent_insert")
            return snapshot

        with (
            patch.object(self.parent, "_transaction", parent_transaction),
            patch.object(self.repair, "_read", read),
        ):
            self.repair.record(claim, attestation=proof, authenticate=owner_verify)
        with closing(sqlite3.connect(self.parent.path)) as db, db:
            db.execute("DROP TABLE repair_events")
            db.execute("DROP TABLE repair_frozen")
        with patch.object(self.parent, "_transaction", parent_transaction):
            RepairLineage.create(
                self.parent,
                self.child,
                study_id="freeze-lock-fixture",
                owner_id="owner",
                owner_version_sha256=digest("owner"),
                cost_roster=(CostItem("cost", "study", "repair", "owner", "clock"),),
            )
        self.assertEqual(
            marks,
            [
                "child_locked_before_intent_insert",
                "parent_commit_while_child_locked",
                "parent_commit_while_child_locked",
            ],
        )

    def test_hardlinked_parent_and_child_refuse_before_locking(self):
        alias = self.parent.path.with_name("hardlink.sqlite")
        os.link(self.parent.path, alias)
        child = ShadowJournal(alias)
        with patch.object(
            child,
            "_transaction",
            side_effect=AssertionError("same-file child lock attempted"),
        ):
            with self.assertRaisesRegex(ValueError, "distinct exact"):
                RepairLineage(
                    self.parent,
                    child,
                    expected_manifest_sha256=self.repair.manifest_sha256,
                )
            with self.assertRaisesRegex(ValueError, "distinct exact"):
                RepairLineage.create(
                    self.parent,
                    child,
                    study_id="samefile",
                    owner_id="owner",
                    owner_version_sha256=digest("owner"),
                    cost_roster=(
                        CostItem("cost", "study", "repair", "owner", "clock"),
                    ),
                )
