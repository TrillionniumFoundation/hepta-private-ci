from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from control_engineering_v2 import (
    CanonicalSourceReceipt,
    EngineeringCapacity,
    EngineeringStore,
    EngineeringWorkPackage,
    HmacTrustStore,
    WorkerProfile,
    WorkEnvelope,
    issue_signed_work_envelope,
    plan_engineering_work,
)
from control_engineering_v2.control_plane import DENIED_AUTHORITIES, EngineeringError


class OrchestrationAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.now = 5_000_000
        self.envelope = WorkEnvelope(
            "env", "a" * 40, "b" * 40, "c" * 64, "d" * 64,
            "developer-productivity", ("src",), tuple(sorted(DENIED_AUTHORITIES)),
            8, self.now + 1_000_000,
        )
        self.trust = HmacTrustStore({})

    def plan(self, store, packages, workers, generation_id="generation", envelope=None):
        return plan_engineering_work(
            store, envelope or self.envelope, packages, workers, (), self.trust,
            EngineeringCapacity(8, ()), generation_id=generation_id, now_ns=self.now,
        )

    def test_preserves_only_rust_worker_for_rust_package(self):
        packages = (
            EngineeringWorkPackage(
                0, "python", (), ("src/python",), required_skills=("python",),
                expected_value_q32=100,
            ),
            EngineeringWorkPackage(
                0, "rust", (), ("src/rust",), required_skills=("rust",),
                capacity_units=2, expected_value_q32=90,
            ),
        )
        workers = (
            WorkerProfile("flexible", ("python", "rust"), 2, ("src",)),
            WorkerProfile("python-only", ("python",), 1, ("src",)),
        )
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                plan = self.plan(store, packages, workers)
                self.assertEqual(
                    tuple((row.package_id, row.worker_id) for row in plan.assignments),
                    (("python", "python-only"), ("rust", "flexible")),
                )
                self.assertEqual(plan.blocked, ())
                reordered = self.plan(
                    store, reversed(packages), reversed(workers), "reordered",
                )
                self.assertEqual(reordered.assignments, plan.assignments)
                self.assertEqual(reordered.base_schedule_digest, plan.base_schedule_digest)

    def test_preserves_worker_with_broad_scope_for_outside_narrow_scope(self):
        packages = (
            EngineeringWorkPackage(
                0, "narrow", (), ("src/narrow/file",), expected_value_q32=100,
            ),
            EngineeringWorkPackage(
                0, "broad", (), ("src/broad/file",), capacity_units=2,
                expected_value_q32=90,
            ),
        )
        workers = (
            WorkerProfile("flexible", (), 2, ("src",)),
            WorkerProfile("narrow-only", (), 1, ("src/narrow",)),
        )
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                plan = self.plan(store, packages, workers)
                self.assertEqual(
                    tuple((row.package_id, row.worker_id) for row in plan.assignments),
                    (("narrow", "narrow-only"), ("broad", "flexible")),
                )
                self.assertEqual(plan.blocked, ())

    def test_malformed_identity_collections_fail_closed_before_publication(self):
        package = EngineeringWorkPackage(0, "package", (), ("src/package",))
        worker = WorkerProfile("worker", (), 1, ("src",))
        cases = (
            (replace(package, package_id=[]), worker, "invalid_package_id"),
            (package, replace(worker, worker_id=[]), "invalid_worker_id"),
            (package, replace(worker, skills=([],)), "invalid_worker_skill"),
            (replace(package, required_skills=([],)), worker, "invalid_required_skill"),
            (replace(package, review_roles=([],)), worker, "invalid_required_review_role"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                anchor = store.audit_anchor()
                for invalid_package, invalid_worker, code in cases:
                    with self.subTest(code=code):
                        with self.assertRaisesRegex(EngineeringError, code):
                            self.plan(store, (invalid_package,), (invalid_worker,))
                        self.assertEqual(store.audit_anchor(), anchor)
                self.assertEqual(
                    store.connection.execute(
                        "SELECT count(*) FROM assignment_generations"
                    ).fetchone()[0],
                    0,
                )

    def test_boolean_envelope_fields_cannot_match_integer_owner_fields(self):
        envelope = replace(self.envelope, maximum_assignments=1)
        package = EngineeringWorkPackage(0, "package", (), ("src/package",))
        worker = WorkerProfile("worker", (), 1, ("src",))
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                store.issue_work_envelope(envelope, now_ns=self.now)
                for changes, code in (
                    ({"maximum_assignments": True}, "invalid_assignment_limit"),
                    ({"revision": True}, "invalid_envelope_revision"),
                ):
                    with self.subTest(code=code):
                        with self.assertRaisesRegex(EngineeringError, code):
                            self.plan(
                                store, (package,), (worker,),
                                envelope=replace(envelope, **changes),
                            )

    def test_input_byte_preflight_rejects_below_record_count_limit_without_mutation(self):
        packages = tuple(
            EngineeringWorkPackage(
                0, f"package-{index}", (), (f"src/{index}/" + "x" * 900,),
            )
            for index in range(300)
        )
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                anchor = store.audit_anchor()
                with self.assertRaisesRegex(EngineeringError, "orchestration_input_byte_limit"):
                    self.plan(store, packages, (WorkerProfile("worker", (), 300, ("src",)),))
                self.assertEqual(store.audit_anchor(), anchor)
                self.assertEqual(
                    store.connection.execute(
                        "SELECT count(*) FROM assignment_generations"
                    ).fetchone()[0],
                    0,
                )

    def test_signed_source_cannot_admit_null_identities_or_impossible_observation_time(self):
        trust = HmacTrustStore({("source_authority", "source"): b"source-key"})
        source = CanonicalSourceReceipt(
            "acme/repository", "9" * 40, "8" * 40,
            self.envelope.source_commit, self.envelope.source_tree, "f" * 64,
            "source_authority", "source", self.now - 1, self.envelope.expires_unix_ns,
        )
        cases = (
            ({"source_commit": "0" * 40}, "source_identity_mismatch"),
            ({"source_tree": "0" * 40}, "source_identity_mismatch"),
            ({"document_set_digest": "0" * 64}, "invalid_document_set_digest"),
            ({"observed_unix_ns": -1}, "source_receipt_stale"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                for changes, code in cases:
                    with self.subTest(code=code, changes=changes):
                        receipt = replace(source, **changes)
                        receipt = replace(receipt, signature=trust.sign(receipt, receipt.issuer, receipt.signing_identity))
                        envelope_changes = {
                            key: value for key, value in changes.items()
                            if key in ("source_commit", "source_tree")
                        }
                        with self.assertRaisesRegex(EngineeringError, code):
                            issue_signed_work_envelope(
                                store, replace(self.envelope, **envelope_changes), receipt, trust,
                                expected_repository="acme/repository",
                                expected_document_set_digest=receipt.document_set_digest,
                                now_ns=self.now,
                            )
                self.assertEqual(
                    store.connection.execute("SELECT count(*) FROM work_envelopes").fetchone()[0],
                    0,
                )


if __name__ == "__main__":
    unittest.main()
