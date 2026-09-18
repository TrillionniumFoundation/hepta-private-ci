from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from control_engineering_v2 import (
    CanonicalSourceReceipt,
    EngineeringStore,
    HmacTrustStore,
    WorkEnvelope,
)
from control_engineering_v2.control_plane import DENIED_AUTHORITIES
from control_engineering_v2.orchestration import (
    CompletionReceipt,
    EngineeringWorkPackage,
    LeadershipReceipt,
    ReviewCapacity,
    WorkerCapacity,
    issue_authenticated_work_envelope,
    schedule_engineering_work,
)


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.envelope = WorkEnvelope(
            "env",
            "a" * 40,
            "b" * 40,
            "1" * 64,
            "2" * 64,
            "owner",
            ("src",),
            tuple(sorted(DENIED_AUTHORITIES)),
            8,
            10_000,
        )
        self.trust = HmacTrustStore(
            {
                ("work_executor", "worker-key"): b"work",
                ("coordination_authority", "leader-key"): b"leader",
                ("source_authority", "source-key"): b"source",
            }
        )

    def completion(self):
        value = CompletionReceipt(
            "done",
            self.envelope.source_commit,
            self.envelope.source_tree,
            "previous-generation",
            "3" * 64,
            "completed",
            "work_executor",
            "worker-key",
            90,
            1000,
        )
        return replace(
            value,
            signature=self.trust.sign(value, value.issuer, value.signing_identity),
        )

    def leadership(self):
        value = LeadershipReceipt(
            "cluster",
            "leader",
            7,
            self.envelope.source_commit,
            self.envelope.source_tree,
            "coordination_authority",
            "leader-key",
            90,
            1000,
        )
        return replace(
            value,
            signature=self.trust.sign(value, value.issuer, value.signing_identity),
        )

    def package(self):
        return EngineeringWorkPackage(
            1,
            "pkg",
            ("done",),
            ("src/pkg",),
            ("python",),
            2,
            1,
            ("architecture_reviewer",),
            10,
            5,
            1,
        )

    def test_authenticated_predecessor_and_resource_model_drive_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "db.sqlite3") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                plan = schedule_engineering_work(
                    store,
                    self.envelope,
                    (self.package(),),
                    (WorkerCapacity("worker", ("python",), 4, 1),),
                    (ReviewCapacity("architecture_reviewer", 1),),
                    ci_capacity_units=1,
                    completion_receipts=(self.completion(),),
                    verifier=self.trust,
                    generation_id="generation",
                    now_ns=self.now,
                )
        self.assertEqual(plan.integration_order, ("pkg",))
        self.assertEqual(plan.assignments[0].worker_id, "worker")
        self.assertEqual(plan.merge_queue[0].package_id, "pkg")
        self.assertFalse(plan.merge_queue[0].merge_authority)
        self.assertFalse(plan.merge_authority)

    def test_forged_completion_receipt_rejects(self):
        forged = replace(self.completion(), signature="0" * 64)
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "db.sqlite3") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                with self.assertRaisesRegex(ValueError, "completion_receipt_signature"):
                    schedule_engineering_work(
                        store,
                        self.envelope,
                        (self.package(),),
                        (WorkerCapacity("worker", ("python",), 4, 1),),
                        (ReviewCapacity("architecture_reviewer", 1),),
                        ci_capacity_units=1,
                        completion_receipts=(forged,),
                        verifier=self.trust,
                        generation_id="generation",
                        now_ns=self.now,
                    )

    def test_distributed_mode_requires_authenticated_leadership_epoch(self):
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "db.sqlite3") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                with self.assertRaisesRegex(ValueError, "leadership_receipt_required"):
                    schedule_engineering_work(
                        store,
                        self.envelope,
                        (),
                        (),
                        (),
                        ci_capacity_units=0,
                        completion_receipts=(),
                        verifier=self.trust,
                        generation_id="generation-a",
                        distributed=True,
                        now_ns=self.now,
                    )
                plan = schedule_engineering_work(
                    store,
                    self.envelope,
                    (),
                    (),
                    (),
                    ci_capacity_units=0,
                    completion_receipts=(),
                    verifier=self.trust,
                    generation_id="generation-b",
                    distributed=True,
                    leadership=self.leadership(),
                    now_ns=self.now,
                )
        self.assertEqual(plan.leadership_epoch, 7)
        self.assertIsNotNone(plan.leadership_digest)

    def test_skill_ci_and_review_capacity_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "db.sqlite3") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                plan = schedule_engineering_work(
                    store,
                    self.envelope,
                    (self.package(),),
                    (WorkerCapacity("worker", ("rust",), 4, 1),),
                    (ReviewCapacity("architecture_reviewer", 0),),
                    ci_capacity_units=0,
                    completion_receipts=(self.completion(),),
                    verifier=self.trust,
                    generation_id="generation",
                    now_ns=self.now,
                )
        self.assertEqual(plan.assignments, ())
        self.assertTrue(plan.blocked)

    def test_authenticated_source_receipt_binds_envelope_before_persistence(self):
        source = CanonicalSourceReceipt(
            "TrillionniumFoundation/hepta-private-ci",
            self.envelope.source_commit,
            self.envelope.source_tree,
            "4" * 64,
            "source_authority",
            "source-key",
            90,
            1000,
        )
        source = replace(
            source,
            signature=self.trust.sign(source, source.issuer, source.signing_identity),
        )
        calls = {
            ("rev-parse", "--verify", f"{self.envelope.source_commit}^{{commit}}"):
                self.envelope.source_commit,
            ("rev-parse", f"{self.envelope.source_commit}^{{tree}}"):
                self.envelope.source_tree,
            ("config", "--get", "remote.origin.url"):
                "https://github.com/TrillionniumFoundation/hepta-private-ci.git",
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with EngineeringStore(root / "db.sqlite3") as store:
                with mock.patch(
                    "control_engineering_v2.orchestration._git",
                    side_effect=lambda _root, *args: calls[args],
                ):
                    issued = issue_authenticated_work_envelope(
                        store,
                        root,
                        "TrillionniumFoundation/hepta-private-ci",
                        source,
                        self.envelope,
                        self.trust,
                        expected_document_set_digest="4" * 64,
                        now_ns=self.now,
                    )
        self.assertEqual(issued.envelope_id, self.envelope.envelope_id)


if __name__ == "__main__":
    unittest.main()
