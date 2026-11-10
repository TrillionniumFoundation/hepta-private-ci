"""Fixture authentication proves binding/recovery, never independent custody."""

from contextlib import closing
from dataclasses import asdict, replace
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from .contracts import canonical_json, digest
from .prospective import FrozenAttempt, ShadowJournal
from .shadow_risk import Target, TerminalLabel


class LabelAttestationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "labels.sqlite"
        self.target = Target("fixture", "terminal_error", 3, digest("policy"))
        self.journal = ShadowJournal.create(
            self.path,
            target=self.target,
            roster=tuple(FrozenAttempt(str(i), "heldout", digest(i)) for i in range(2)),
            frontiers=(0,),
            risk_model_sha256=digest("risk"),
            checker_model_sha256=digest("checker"),
            scheduler_sha256=digest("scheduler"),
            producer_id="producer",
            evaluator_id="external-fixture",
            evaluator_version_sha256=digest("evaluator-v1"),
        )
        self.labels = tuple(
            TerminalLabel(
                str(i),
                "heldout",
                digest(i),
                self.target,
                "accept" if i == 0 else "unknown",
                False if i == 0 else None,
                3,
                digest("evidence") if i == 0 else None,
                None if i == 0 else "terminal_not_observed",
            )
            for i in range(2)
        )
        self.calls = []

    @staticmethod
    def signature(actor, label, version, manifest):
        # Test-only shared secret. Production uses the host's registered verifier.
        payload = canonical_json([actor, asdict(label), version, manifest]).encode()
        return hmac.new(b"engineering-fixture-key", payload, hashlib.sha256).hexdigest()

    def authenticate(self, actor, label, version, manifest, attestation):
        self.calls.append((actor, label.trajectory_id, version, manifest, attestation))
        return hmac.compare_digest(
            attestation, self.signature(actor, label, version, manifest)
        )

    def collect(self, *, legacy=False):
        for label in self.labels:
            self.journal.finish(label.trajectory_id, label.disposition)
            if legacy:
                self.journal.label(
                    label,
                    evaluator_id="external-fixture",
                    authenticate=lambda *args: True,
                )
            else:
                signature = self.signature(
                    "external-fixture",
                    label,
                    digest("evaluator-v1"),
                    self.journal.manifest_sha256,
                )
                self.journal.label(
                    label,
                    evaluator_id="external-fixture",
                    authenticate=self.authenticate,
                    attestation=signature,
                )

    def rewrite_chain(self, change):
        # An owner can recompute every unkeyed SQLite digest; authentication must still fail.
        with closing(sqlite3.connect(self.path)) as connection, connection:
            root = connection.execute("SELECT sha FROM frozen").fetchone()[0]
            for seq, body in connection.execute(
                "SELECT seq, body FROM events ORDER BY seq"
            ).fetchall():
                event = json.loads(body)
                change(event)
                event["previous_sha256"] = root
                root = digest(event)
                connection.execute(
                    "UPDATE events SET body=?, sha=? WHERE seq=?",
                    (canonical_json(event), root, seq),
                )

    def test_cold_recovery_reverifies_every_label_including_missing_truth(self):
        self.collect()
        checkpoint = self.journal.report()["ledger_sha256"]
        self.calls.clear()
        recovered = ShadowJournal(
            self.path,
            expected_manifest_sha256=self.journal.manifest_sha256,
            expected_ledger_sha256=checkpoint,
        )
        report = recovered.report(authenticate=self.authenticate)
        self.assertEqual([call[1] for call in self.calls], ["0", "1"])
        self.assertEqual(
            report["label_authentication"],
            dict(
                retained_attestations=2,
                legacy_labels_without_attestations=0,
                reverified_labels=2,
                all_roster_labels_reverified=True,
                independent_custody_established=False,
            ),
        )
        self.assertEqual(
            (
                report["trajectories"],
                report["known_labels"],
                report["scientific_admission"],
            ),
            (2, 1, "HOLD"),
        )
        self.assertFalse(
            recovered.report()["label_authentication"]["all_roster_labels_reverified"]
        )

    def test_legacy_callbacks_are_not_upgraded_to_retained_authentication(self):
        self.collect(legacy=True)
        recovered = ShadowJournal(self.path)
        self.assertEqual(
            recovered.report()["label_authentication"][
                "legacy_labels_without_attestations"
            ],
            2,
        )
        with self.assertRaisesRegex(ValueError, "legacy labels"):
            recovered.report(authenticate=lambda *args: True)

    def test_recomputed_hashes_cannot_authenticate_forged_truth(self):
        self.collect()

        def forge(event):
            if (
                event["kind"] == "label_attested"
                and event["value"]["label"]["trajectory_id"] == "0"
            ):
                event["value"]["label"]["error"] = True

        self.rewrite_chain(forge)
        with self.assertRaisesRegex(ValueError, "retained label authentication failed"):
            ShadowJournal(self.path).report(authenticate=self.authenticate)

    def test_revoked_or_truthy_verifiers_do_not_revalidate_old_labels(self):
        self.collect()
        for value in (False, None, 1, "verified"):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "authentication failed"),
            ):
                ShadowJournal(self.path).report(authenticate=lambda *args: value)

    def test_old_signature_wrong_issuer_and_unbounded_attestations_refuse_ingress(self):
        label = self.labels[0]
        self.journal.finish("0", "accept")
        stale = self.signature(
            "external-fixture",
            label,
            digest("evaluator-v0"),
            self.journal.manifest_sha256,
        )
        for attestation in (stale, "", "a" * 16385, {"signature": stale}):
            with (
                self.subTest(attestation_type=type(attestation)),
                self.assertRaises(ValueError),
            ):
                self.journal.label(
                    label,
                    evaluator_id="external-fixture",
                    authenticate=self.authenticate,
                    attestation=attestation,
                )
        with self.assertRaisesRegex(ValueError, "unregistered"):
            self.journal.label(
                label,
                evaluator_id="producer",
                authenticate=self.authenticate,
                attestation=stale,
            )

    def test_authentication_callback_cannot_race_the_reported_checkpoint(self):
        self.collect()
        mutated = False

        def racing_verifier(*args):
            nonlocal mutated
            if not mutated:
                mutated = True

                def forge(event):
                    if (
                        event["kind"] == "label_attested"
                        and event["value"]["label"]["trajectory_id"] == "0"
                    ):
                        event["value"]["label"]["evidence_sha256"] = digest("changed")

                self.rewrite_chain(forge)
            return self.authenticate(*args)

        with self.assertRaisesRegex(ValueError, "changed during authentication"):
            self.journal.report(authenticate=racing_verifier)

    def test_terminal_horizon_and_subject_are_covered_by_retained_signature(self):
        label = self.labels[0]
        signature = self.signature(
            "external-fixture",
            label,
            digest("evaluator-v1"),
            self.journal.manifest_sha256,
        )
        self.journal.finish("0", "accept")
        for changed in (
            replace(label, observed_step=4),
            replace(label, subject_sha256=digest("other")),
        ):
            with (
                self.subTest(changed=changed),
                self.assertRaisesRegex(ValueError, "authentication failed"),
            ):
                self.journal.label(
                    changed,
                    evaluator_id="external-fixture",
                    authenticate=self.authenticate,
                    attestation=signature,
                )

    def test_verifier_cannot_replace_the_label_bytes_it_checked(self):
        label = self.labels[0]
        self.journal.finish("0", "accept")
        signature = self.signature(
            "external-fixture",
            label,
            digest("evaluator-v1"),
            self.journal.manifest_sha256,
        )

        def mutating_verifier(actor, row, version, manifest, attestation):
            verified = self.authenticate(actor, row, version, manifest, attestation)
            object.__setattr__(row, "error", not row.error)
            return verified

        with self.assertRaisesRegex(ValueError, "label changed during authentication"):
            self.journal.label(
                label,
                evaluator_id="external-fixture",
                authenticate=mutating_verifier,
                attestation=signature,
            )
        with self.journal._transaction() as connection:
            self.assertEqual(self.journal._read(connection)[3], {})

    def test_reverification_refuses_verifier_normalization_of_signed_label(self):
        self.collect()

        def mutating_verifier(actor, row, version, manifest, attestation):
            verified = self.authenticate(actor, row, version, manifest, attestation)
            object.__setattr__(row, "observed_step", row.observed_step + 1)
            return verified

        with self.assertRaisesRegex(ValueError, "label changed during authentication"):
            ShadowJournal(self.path).report(authenticate=mutating_verifier)

    def test_python_numeric_equality_does_not_replace_canonical_signed_bytes(self):
        label = self.labels[0]
        normalized = asdict(label)
        normalized["error"] = 0
        payload = canonical_json(
            [
                "external-fixture",
                normalized,
                digest("evaluator-v1"),
                self.journal.manifest_sha256,
            ]
        ).encode()
        signature = hmac.new(
            b"engineering-fixture-key", payload, hashlib.sha256
        ).hexdigest()
        self.journal.finish("0", "accept")

        def normalizing_verifier(actor, row, version, manifest, attestation):
            object.__setattr__(row, "error", 0)
            return self.authenticate(actor, row, version, manifest, attestation)

        with self.assertRaisesRegex(ValueError, "label changed during authentication"):
            self.journal.label(
                label,
                evaluator_id="external-fixture",
                authenticate=normalizing_verifier,
                attestation=signature,
            )

    def test_recovery_detects_equal_but_noncanonical_normalization(self):
        self.collect()
        for field, value in (("error", 0), ("observed_step", 3.0)):

            def normalizing_verifier(actor, row, version, manifest, attestation):
                verified = self.authenticate(actor, row, version, manifest, attestation)
                object.__setattr__(row, field, value)
                return verified

            with (
                self.subTest(field=field),
                self.assertRaisesRegex(
                    ValueError, "label changed during authentication"
                ),
            ):
                ShadowJournal(self.path).report(authenticate=normalizing_verifier)
