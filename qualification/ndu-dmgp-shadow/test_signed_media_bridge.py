"""Real OpenSSL signature and physical four-modal codec bridge tests."""
import copy
import hashlib
from pathlib import Path
import shutil
import unittest

import test_signed_evidence as evidence_fixtures
import test_decoded_media_audit as media_fixtures
from decoded_media_audit import DecodedMediaRejected, audit_decoded_media
from signed_evidence import EvidenceRejected
from signed_media_bridge import plan_fingerprint, verify_signed_decoded_media


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "Codec tests require ffmpeg; dedicated CI job enforces tools")
class SignedMediaBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        evidence_fixtures.SignedEvidenceTests.setUpClass()
        media_fixtures.DecodedMediaAuditTests.setUpClass()
        cls.tmp = evidence_fixtures.SignedEvidenceTests.tmp
        cls.private_obs = evidence_fixtures.SignedEvidenceTests.private_obs
        cls.private_meter = evidence_fixtures.SignedEvidenceTests.private_meter
        cls.public_obs = evidence_fixtures.SignedEvidenceTests.public_obs
        cls.public_meter = evidence_fixtures.SignedEvidenceTests.public_meter
        cls.root = media_fixtures.DecodedMediaAuditTests.root

    @classmethod
    def tearDownClass(cls):
        media_fixtures.DecodedMediaAuditTests.tearDownClass()
        evidence_fixtures.SignedEvidenceTests.tearDownClass()

    def signature(self, payload, key):
        return evidence_fixtures.SignedEvidenceTests.signature(self, payload, key)

    def build(self):
        entry = evidence_fixtures.SignedEvidenceTests.pair(
            self, episode="media-001", arm="A5", at=101)
        plan = copy.deepcopy(media_fixtures.DecodedMediaAuditTests.plan)
        plan["input_digest"] = entry["observer"]["payload"]["input_digest"]
        plan["max_skew_ms"] = 120
        manifest = copy.deepcopy(media_fixtures.DecodedMediaAuditTests.manifest)
        manifest["input_digest"] = plan["input_digest"]
        receipt = audit_decoded_media(plan, manifest, asset_root=self.root)
        frozen = plan_fingerprint(plan)
        for role, priv in (("observer", self.private_obs),
                           ("meter", self.private_meter)):
            payload = dict(entry[role]["payload"],
                           media_plan_digest=frozen,
                           decoded_media_content_digest=receipt["content_digest"])
            entry[role] = self.signature(payload, priv)
        return entry, plan, manifest, frozen

    def verify(self, entry, plan, manifest, frozen, root=None, **kwargs):
        return verify_signed_decoded_media(
            entry, plan, manifest,
            asset_root=self.root if root is None else root,
            observer_public_key=kwargs.get("observer_public_key", self.public_obs),
            meter_public_key=kwargs.get("meter_public_key", self.public_meter),
            trusted_plan_digest=frozen,
            expected_objective=evidence_fixtures.H,
            expected_evaluator_digest=evidence_fixtures.P,
            expected_device_digest=evidence_fixtures.H,
            training_cutoff=100,
        )

    def test_genuine_ed25519_dual_signer_to_decoded_original_bytes(self):
        entry, plan, manifest, frozen = self.build()
        report = self.verify(entry, plan, manifest, frozen)
        self.assertTrue(report["signed_observer_and_meter_binding_verified"])
        self.assertTrue(report["original_media_bytes_decoded"])
        for unsupported in ("production_blockers_closed",
                            "observer_independent_perceptual_truth_verified",
                            "device_energy_calibration_verified",
                            "external_signer_key_custody_verified"):
            self.assertFalse(report[unsupported])

    def test_independent_plan_pin_rejects_output_time_reregister(self):
        entry, plan, manifest, frozen = self.build()
        plan["timeline"][0]["entity"] = "rewritten-after-output"
        with self.assertRaisesRegex(DecodedMediaRejected, "frozen media plan"):
            self.verify(entry, plan, manifest, frozen)

    def test_new_content_digest_cannot_be_spliced_into_old_signatures(self):
        entry, plan, manifest, frozen = self.build()
        manifest["outputs"][0]["events"][0]["start_ms"] += 1
        with self.assertRaisesRegex(EvidenceRejected, "signer does not bind"):
            self.verify(entry, plan, manifest, frozen)

    def test_observer_and_meter_must_sign_same_media(self):
        entry, plan, manifest, frozen = self.build()
        payload = dict(entry["meter"]["payload"],
                       decoded_media_content_digest="e" * 64)
        entry["meter"] = self.signature(payload, self.private_meter)
        with self.assertRaisesRegex(EvidenceRejected, "signer does not bind"):
            self.verify(entry, plan, manifest, frozen)

    def test_fake_signature_or_missing_reference_fails_closed(self):
        entry, plan, manifest, frozen = self.build()
        entry["observer"]["payload"]["decoded_media_content_digest"] = "e" * 64
        with self.assertRaises(EvidenceRejected):
            self.verify(entry, plan, manifest, frozen)
        entry, plan, manifest, frozen = self.build()
        payload = dict(entry["observer"]["payload"])
        del payload["decoded_media_content_digest"]
        entry["observer"] = self.signature(payload, self.private_obs)
        with self.assertRaisesRegex(EvidenceRejected, "signer does not bind"):
            self.verify(entry, plan, manifest, frozen)

    def test_refuse_signer_key_collision_and_changed_input(self):
        entry, plan, manifest, frozen = self.build()
        with self.assertRaisesRegex(EvidenceRejected, "key role collision"):
            self.verify(entry, plan, manifest, frozen,
                        meter_public_key=self.public_obs)
        entry, plan, manifest, frozen = self.build()
        plan["input_digest"] = hashlib.sha256(b"other_input").hexdigest()
        # The signed plan fingerprint remains prior to the changed input.
        with self.assertRaisesRegex(DecodedMediaRejected, "frozen media plan"):
            self.verify(entry, plan, manifest, frozen)

    def test_modality_mismatch_from_signed_observer_rejected(self):
        entry, plan, manifest, frozen = self.build()
        obs = dict(entry["observer"]["payload"], modalities=["text"])
        entry["observer"] = self.signature(obs, self.private_obs)
        with self.assertRaisesRegex(EvidenceRejected, "different decoded output"):
            self.verify(entry, plan, manifest, frozen)


if __name__ == "__main__":
    unittest.main()