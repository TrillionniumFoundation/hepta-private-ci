"""Public registration rejects malformed signed values before owner mutation."""

from dataclasses import replace
import unittest

from control_engineering_v2 import WorkerRegistrationReceipt
from control_engineering_v2.control_plane import EngineeringError
import test_product_claim_admission as product_fixtures


class WorkerRegistrationTypedAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = product_fixtures.ProductClaimAdmissionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def signed_registration(self, **changes):
        fixture = self.fixture
        receipt = WorkerRegistrationReceipt(
            "new-worker", "worker-key", ("python",), 4, ("src",),
            "engineering_worker_identity", "identity-key",
            fixture.now, fixture.now + 100,
        )
        receipt = replace(receipt, **changes)
        return replace(
            receipt,
            signature=fixture.trust.sign(receipt, receipt.issuer, receipt.signing_identity),
        )

    def test_signed_timestamp_ranges_and_booleans_fail_without_owner_writes(self):
        fixture = self.fixture
        store = fixture.product.store
        anchor = fixture.product.audit_anchor()
        for observed, expires in (
            (-1, fixture.now + 100),
            (fixture.now, 2**63),
            (2**63, 2**63 + 1),
            (True, fixture.now + 100),
            (fixture.now, True),
            (fixture.now, fixture.now),
        ):
            with self.subTest(observed=observed, expires=expires):
                receipt = self.signed_registration(observed_unix_ns=observed, expires_unix_ns=expires)
                with self.assertRaisesRegex(EngineeringError, "worker_registration_stale"):
                    fixture.product.register_worker(receipt, now_ns=fixture.now)
                self.assertEqual(fixture.product.audit_anchor(), anchor)
                self.assertIsNone(store.connection.execute(
                    "SELECT 1 FROM worker_registrations WHERE worker_id='new-worker'"
                ).fetchone())

    def test_unhashable_and_non_string_signed_skills_raise_typed_error(self):
        fixture = self.fixture
        anchor = fixture.product.audit_anchor()
        for skills in (({},), ([],), (None,), (1,), (True,), ("python", "python")):
            with self.subTest(skills=skills):
                receipt = self.signed_registration(skills=skills)
                with self.assertRaisesRegex(EngineeringError, "invalid_worker_profile"):
                    fixture.product.register_worker(receipt, now_ns=fixture.now)
                self.assertEqual(fixture.product.audit_anchor(), anchor)
                self.assertIsNone(fixture.product.store.connection.execute(
                    "SELECT 1 FROM worker_registrations WHERE worker_id='new-worker'"
                ).fetchone())

    def test_sqlite_timestamp_boundaries_are_supported_and_replayable(self):
        fixture = self.fixture
        receipt = self.signed_registration(observed_unix_ns=0, expires_unix_ns=2**63 - 1)
        digest = fixture.product.register_worker(receipt, now_ns=fixture.now)
        row = fixture.product.store.connection.execute(
            "SELECT observed_unix_ns,expires_unix_ns FROM worker_registrations WHERE worker_id='new-worker'"
        ).fetchone()
        self.assertEqual(tuple(row), (0, 2**63 - 1))
        anchor = fixture.product.audit_anchor()
        self.assertEqual(fixture.product.register_worker(receipt, now_ns=fixture.now + 1), digest)
        self.assertEqual(fixture.product.audit_anchor(), anchor)


if __name__ == "__main__":
    unittest.main()
