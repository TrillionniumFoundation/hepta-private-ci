"""SQLite scalar admission fails with typed errors and no owner effects."""

from dataclasses import replace
import unittest

from control_engineering_v2 import WorkPackage
from control_engineering_v2.control_plane import EngineeringError, STORE_TABLES
import test_product_claim_admission as product_fixtures


MAX_INTEGER = 2**63 - 1


class OwnerScalarAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = product_fixtures.ProductClaimAdmissionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.product = self.fixture.product
        self.store = self.product.store

    def snapshot(self):
        return {
            table: tuple(tuple(row) for row in self.store.connection.execute(
                f"SELECT * FROM {table} ORDER BY rowid"
            ))
            for table in sorted(STORE_TABLES)
        }

    def reject_unchanged(self, operation, code):
        before = self.snapshot()
        anchor = self.product.audit_anchor()
        with self.assertRaisesRegex(EngineeringError, code):
            operation()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.product.audit_anchor(), anchor)

    def test_product_envelope_sqlite_scalars_and_denied_elements_are_typed(self):
        for field, code in (
            ("expires_unix_ns", "invalid_envelope_expiry"),
            ("revision", "invalid_envelope_revision"),
        ):
            for value in (0, -1, True, 1.0, 2**63):
                with self.subTest(field=field, value=value):
                    envelope = replace(self.fixture.envelope, envelope_id="new", **{field: value})
                    self.reject_unchanged(
                        lambda: self.product.admit_repository_envelope(envelope, now_ns=self.fixture.now), code,
                    )
        for item in ({}, [], None, True):
            with self.subTest(denied=item):
                envelope = replace(
                    self.fixture.envelope, envelope_id="new",
                    denied_authorities=(item,) + self.fixture.envelope.denied_authorities[1:],
                )
                self.reject_unchanged(
                    lambda: self.product.admit_repository_envelope(envelope, now_ns=self.fixture.now),
                    "authority_ceiling_incomplete",
                )

    def test_owner_time_and_audit_cursor_reject_out_of_range_scalars(self):
        self.fixture.lease()
        for value in (-1, True, 1.0, 2**63):
            with self.subTest(time=value):
                self.reject_unchanged(
                    lambda: self.store.transition_path_lease(
                        "lease", expected_revision=1, authority_epoch=1,
                        disposition="release", now_ns=value,
                    ), "invalid_time",
                )
                self.reject_unchanged(
                    lambda: self.store.record_integration_decision(
                        "decision", "a" * 64, False, (), now_ns=value,
                    ), "invalid_time",
                )
            with self.subTest(cursor=value):
                self.reject_unchanged(
                    lambda: self.store.audit_projection(after_sequence=value), "invalid_audit_query",
                )

    def test_lease_acquisition_epoch_and_expiry_have_sqlite_bounds(self):
        for field, code in (("authority_epoch", "invalid_authority_epoch"), ("expires_unix_ns", "invalid_lease_expiry")):
            for value in (0, -1, True, 1.0, 2**63):
                with self.subTest(field=field, value=value):
                    arguments = {"authority_epoch": 1, "expires_unix_ns": self.fixture.now + 100, field: value}
                    self.reject_unchanged(
                        lambda: self.product.acquire_lease(
                            "new", "env", "worker", ("src/new",),
                            now_ns=self.fixture.now, **arguments,
                        ), code,
                    )

    def test_lease_transition_cas_rejects_bool_float_and_out_of_range(self):
        self.fixture.lease()
        for field, code in (("expected_revision", "invalid_lease_revision"), ("authority_epoch", "invalid_authority_epoch")):
            for value in (0, -1, True, 1.0, 2**63):
                with self.subTest(field=field, value=value):
                    arguments = {"expected_revision": 1, "authority_epoch": 1, field: value}
                    self.reject_unchanged(
                        lambda: self.store.transition_path_lease(
                            "lease", disposition="release", now_ns=self.fixture.now + 2, **arguments,
                        ), code,
                    )
        self.reject_unchanged(
            lambda: self.store.transition_path_lease(
                "lease", expected_revision=1, authority_epoch=1,
                disposition={}, now_ns=self.fixture.now + 2,
            ), "invalid_lease_transition",
        )
        self.reject_unchanged(
            lambda: self.store.transition_path_lease(
                "lease", expected_revision=1, authority_epoch=1,
                disposition="renew", new_expiry_unix_ns=2**63, now_ns=self.fixture.now + 2,
            ), "invalid_lease_expiry",
        )

    def test_lease_revision_exhaustion_rolls_back_transition_and_expiration(self):
        self.fixture.lease()
        # Prepare the representable terminal counter value. This mutable owner
        # counter would otherwise require MAX_INTEGER - 1 prior transitions.
        with self.store._transaction():
            self.store.connection.execute(
                "UPDATE path_leases SET revision=? WHERE lease_id='lease'", (MAX_INTEGER,),
            )
        self.reject_unchanged(
            lambda: self.store.transition_path_lease(
                "lease", expected_revision=MAX_INTEGER, authority_epoch=1,
                disposition="release", now_ns=self.fixture.now + 2,
            ), "lease_revision_exhausted",
        )
        self.reject_unchanged(
            lambda: self.product.acquire_lease(
                "new", "env", "worker", ("src/new",), authority_epoch=1,
                expires_unix_ns=self.fixture.now + 700_000, now_ns=self.fixture.now + 500_001,
            ), "lease_revision_exhausted",
        )

    def test_int64_boundaries_and_json_only_priority_remain_supported(self):
        envelope = replace(
            self.fixture.envelope, envelope_id="boundary",
            expires_unix_ns=MAX_INTEGER, revision=MAX_INTEGER,
        )
        self.assertEqual(self.product.admit_repository_envelope(envelope, now_ns=0), envelope)
        row = self.store.connection.execute(
            "SELECT expires_unix_ns,revision,created_unix_ns FROM work_envelopes WHERE envelope_id='boundary'"
        ).fetchone()
        self.assertEqual(tuple(row), (MAX_INTEGER, MAX_INTEGER, 0))
        lease = self.product.acquire_lease(
            "boundary-lease", "boundary", "worker", ("src/boundary",),
            authority_epoch=MAX_INTEGER, expires_unix_ns=MAX_INTEGER, now_ns=0,
        )
        self.assertEqual((lease.epoch, lease.expires_unix_ns, lease.issued_unix_ns), (MAX_INTEGER, MAX_INTEGER, 0))
        anchor = self.product.audit_anchor()
        self.assertEqual(self.product.acquire_lease(
            "boundary-lease", "boundary", "worker", ("src/boundary",),
            authority_epoch=MAX_INTEGER, expires_unix_ns=MAX_INTEGER, now_ns=0,
        ), lease)
        self.assertEqual(self.product.audit_anchor(), anchor)
        schedule = self.store.schedule_ready_packages(
            "boundary", (WorkPackage(2**80, "huge-priority", (), ("src/free",)),), (),
            generation_id="huge-priority", now_ns=0,
        )
        self.assertEqual(schedule.assigned, ("huge-priority",))
        self.store.record_integration_decision("boundary-decision", "a" * 64, False, (), now_ns=MAX_INTEGER)
        self.assertEqual(self.store.audit_anchor()["createdUnixNs"], MAX_INTEGER)
        before = self.snapshot()
        self.assertEqual(self.store.audit_projection(after_sequence=MAX_INTEGER), ())
        self.assertEqual(self.snapshot(), before)

    def test_non_iterable_inputs_and_surrogate_ids_paths_fail_without_effects(self):
        envelope = replace(self.fixture.envelope, envelope_id="new", denied_authorities=None)
        self.reject_unchanged(
            lambda: self.product.admit_repository_envelope(envelope, now_ns=self.fixture.now), "invalid_iterable",
        )
        for paths, code in ((None, "invalid_paths"), (("\ud800",), "invalid_path")):
            with self.subTest(paths=paths):
                self.reject_unchanged(
                    lambda: self.product.acquire_lease(
                        "new", "env", "worker", paths, authority_epoch=1,
                        expires_unix_ns=self.fixture.now + 100, now_ns=self.fixture.now,
                    ), code,
                )
        for label, value in (("lease_id", "\ud800"), ("holder", "\ud800")):
            with self.subTest(label=label):
                arguments = {"lease_id": "new", "holder": "worker", label: value}
                self.reject_unchanged(
                    lambda: self.product.acquire_lease(
                        envelope_id="env", paths=("src/new",), authority_epoch=1,
                        expires_unix_ns=self.fixture.now + 100, now_ns=self.fixture.now, **arguments,
                    ), "invalid_" + label,
                )
        self.reject_unchanged(
            lambda: self.store.schedule_ready_packages(
                "env", (WorkPackage(0, "bad", None, ("src/bad",)),), (),
                generation_id="bad", now_ns=self.fixture.now,
            ), "invalid_iterable",
        )

    def test_generator_execution_errors_are_preserved_without_owner_effects(self):
        error = TypeError("producer failure")

        def paths():
            yield "src/new"
            raise error

        def packages():
            yield WorkPackage(0, "job", (), ("src/job",))
            raise error

        for operation in (
            lambda: self.product.acquire_lease(
                "new", "env", "worker", paths(), authority_epoch=1,
                expires_unix_ns=self.fixture.now + 100, now_ns=self.fixture.now,
            ),
            lambda: self.store.schedule_ready_packages(
                "env", packages(), (), generation_id="bad", now_ns=self.fixture.now,
            ),
        ):
            before = self.snapshot()
            anchor = self.product.audit_anchor()
            with self.assertRaises(TypeError) as observed:
                operation()
            self.assertIs(observed.exception, error)
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(self.product.audit_anchor(), anchor)


if __name__ == "__main__":
    unittest.main()
