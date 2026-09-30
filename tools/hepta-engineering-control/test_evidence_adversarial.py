"""Authenticated observations must still bind exact plans and real key material."""

from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest

from control_engineering_v2 import EngineeringError, EngineeringStore, semantic_digest
from control_engineering_v2.evidence import verify_integration_evidence
from control_engineering_v2.git_security import run_git
from control_engineering_v2.deployment_evidence import verify_production_acceptance_evidence
from control_engineering_v2.external_controls import verify_external_key_custody
from control_engineering_v2.integration_controller import publish_integration_queue
from control_engineering_v2.key_custody_continuity import (
    MAX_CUSTODY_KEYS,
    key_set_digest,
    verify_key_custody_continuity,
)
import test_deployment_evidence as deployment_fixture
import test_external_controls as external_fixture
import test_integration_controller as integration_fixture
import test_key_custody_continuity as continuity_fixture
import test_control_engineering_v2 as evidence_fixture


class EvidenceAdversarialTests(unittest.TestCase):
    def test_source_evidence_requires_real_checks_and_nonempty_generator_identity(self):
        fixture = evidence_fixture.EvidenceTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        original = fixture.signed_receipts()
        variants = (
            (1, "checks_digest", "0" * 64, "invalid_source_checks_digest"),
            (3, "generator_principal", "", "invalid_generator_principal"),
            (3, "generator_signing_identity", "", "invalid_generator_signing_identity"),
            (0, "observed_unix_ns", -1, "source_receipt_stale"),
        )
        for index, field, value, reason in variants:
            with self.subTest(field=field):
                values = list(original)
                receipt = replace(values[index], **{field: value})
                issuer = receipt.issuer if index != 3 else receipt.evaluator_principal
                identity = (receipt.signing_identity if index != 3
                            else receipt.evaluator_signing_identity)
                values[index] = replace(
                    receipt, signature=fixture.trust.sign(receipt, issuer, identity)
                )
                result = verify_integration_evidence(
                    fixture.root, "TrillionniumFoundation/hepta-private-ci",
                    *values, fixture.trust,
                    expected_document_set_digest=fixture.document_digest,
                    now_ns=fixture.now,
                )
                self.assertFalse(result.eligible_for_independent_review)
                self.assertIn(reason, result.reasons)

    def test_empty_origin_cannot_qualify_exact_source_evidence(self):
        fixture = evidence_fixture.EvidenceTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        run_git(fixture.root, "config", "remote.origin.url", "")
        result = verify_integration_evidence(
            fixture.root, "TrillionniumFoundation/hepta-private-ci",
            *fixture.signed_receipts(), fixture.trust,
            expected_document_set_digest=fixture.document_digest, now_ns=fixture.now,
        )
        self.assertFalse(result.eligible_for_independent_review)
        self.assertIn("repository_remote_mismatch", result.reasons)

    def test_custody_rejects_same_public_key_under_distinct_subjects_and_handles(self):
        fixture = external_fixture.ExternalControlTests()
        fixture.setUp()
        values = list(fixture.custody_set())
        values[1] = fixture.sign(
            replace(values[1], public_key_digest=values[0].public_key_digest)
        )
        with self.assertRaisesRegex(EngineeringError, "key_custody_role_separation"):
            verify_external_key_custody(values, fixture.trust, now_ns=fixture.now)

    def test_continuity_rejects_same_public_key_under_role_aliases(self):
        fixture = continuity_fixture.KeyCustodyContinuityTests()
        fixture.setUp()
        genesis = fixture.genesis()
        keys = list(genesis.current_keys)
        keys[1] = replace(keys[1], public_key_digest=keys[0].public_key_digest)
        receipt = fixture.sign(replace(genesis, current_keys=tuple(keys)))
        with self.assertRaisesRegex(EngineeringError, "key_custody_role_separation"):
            verify_key_custody_continuity(
                receipt, fixture.trust,
                expected_repository=fixture.repository,
                expected_source_sha=fixture.source_sha,
                expected_merge_sha=fixture.merge_sha, now_ns=fixture.now,
            )

    def test_rotation_rejects_reusing_old_public_keys_with_new_aliases(self):
        fixture = continuity_fixture.KeyCustodyContinuityTests()
        fixture.setUp()
        previous = fixture.genesis()
        aliased = tuple(
            replace(key, key_id="new-" + key.key_id,
                    subject_signing_identity="new-" + key.subject_signing_identity)
            for key in previous.current_keys
        )
        receipt = fixture.sign(replace(
            previous, rotation_epoch=2, rotation_state="dual_window",
            previous_set_digest=semantic_digest(asdict(previous)),
            current_keys=aliased, retiring_keys=previous.current_keys,
            dual_window_expires_unix_ns=fixture.now + 500,
        ))
        with self.assertRaisesRegex(EngineeringError, "key_custody_rotation_reuse"):
            verify_key_custody_continuity(
                receipt, fixture.trust, previous_receipt=previous,
                expected_repository=fixture.repository,
                expected_source_sha=fixture.source_sha,
                expected_merge_sha=fixture.merge_sha, now_ns=fixture.now,
            )

    def test_key_digest_stops_consuming_after_the_admission_bound(self):
        fixture = continuity_fixture.KeyCustodyContinuityTests()
        key = fixture.keys("bounded")[0]
        consumed = []

        def oversized():
            for index in range(MAX_CUSTODY_KEYS + 2):
                consumed.append(index)
                if index > MAX_CUSTODY_KEYS:
                    self.fail("key collection exhausted beyond its admission bound")
                yield key

        with self.assertRaisesRegex(EngineeringError, "key_custody_current_keys"):
            key_set_digest(oversized(), rotation_epoch=1)
        self.assertEqual(len(consumed), MAX_CUSTODY_KEYS + 1)

    def test_queue_cannot_publish_packages_absent_from_the_persisted_plan(self):
        fixture = integration_fixture.IntegrationControllerTests()
        fixture.setUp()
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "store.db") as store:
                original = fixture.plan(store)
                forged = replace(
                    original,
                    assignments=tuple(replace(row, package_id="forged")
                                      for row in original.assignments),
                    integration_order=("forged",),
                    merge_queue=tuple(replace(row, package_id="forged")
                                      for row in original.merge_queue),
                )
                with self.assertRaisesRegex(
                    EngineeringError, "orchestration_generation_mismatch"
                ):
                    publish_integration_queue(
                        store, forged, queue_generation_id="forged-queue",
                        base_commit=fixture.base_commit, base_tree=fixture.base_tree,
                        now_ns=fixture.now + 1,
                    )
                self.assertEqual(store.connection.execute(
                    "SELECT COUNT(*) FROM integration_queue_generations"
                ).fetchone()[0], 0)
                accepted = publish_integration_queue(
                    store, original, queue_generation_id="valid-queue",
                    base_commit=fixture.base_commit, base_tree=fixture.base_tree,
                    now_ns=fixture.now + 1,
                )
                self.assertEqual(accepted.state, "active")

    def _deployment_values(self, index, **changes):
        fixture = deployment_fixture.DeploymentEvidenceTests()
        fixture.setUp()
        values = list(fixture.evidence())
        values[index] = fixture.signed(replace(values[index], **changes))
        if index < 3:
            field = ("deployment_receipt_digest", "recovery_receipt_digest",
                     "rollback_receipt_digest")[index]
            values[3] = fixture.signed(replace(
                values[3], **{field: semantic_digest(asdict(values[index]))}
            ))
        return fixture, values

    def test_production_receipt_success_requires_exact_boolean_true(self):
        fields = ("passed", "integrity_verified", "rollback_succeeded", "accepted")
        for index, field in enumerate(fields):
            for value in (1, "false", [True]):
                with self.subTest(field=field, value=value):
                    fixture, values = self._deployment_values(index, **{field: value})
                    with self.assertRaisesRegex(
                        EngineeringError, "production_evidence_negative_observation"
                    ):
                        verify_production_acceptance_evidence(
                            *values, fixture.trust, now_ns=fixture.now
                        )

    def test_empty_artifact_digest_cannot_qualify_a_deployment(self):
        fixture, values = self._deployment_values(0, artifact_digest="0" * 64)
        with self.assertRaisesRegex(EngineeringError, "invalid_artifact_digest"):
            verify_production_acceptance_evidence(
                *values, fixture.trust, now_ns=fixture.now
            )

    def test_rollback_requires_a_distinct_predecessor(self):
        fixture, values = self._deployment_values(2, predecessor_commit="a" * 40)
        with self.assertRaisesRegex(
            EngineeringError, "production_evidence_rollback_predecessor"
        ):
            verify_production_acceptance_evidence(
                *values, fixture.trust, now_ns=fixture.now
            )


if __name__ == "__main__":
    unittest.main()
