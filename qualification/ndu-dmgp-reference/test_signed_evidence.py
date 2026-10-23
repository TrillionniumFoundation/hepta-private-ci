"""Signed independent-observer / host-meter NDU-DMGP shadow audit negatives."""
import base64
import subprocess
import tempfile
import unittest
from pathlib import Path

from signed_evidence import (
    EvidenceRejected, audit_trial_file, canonical_json, verify_pair,
)

H = "a" * 64
I = "b" * 64
A = "c" * 64
T = "d" * 64
P = "e" * 64


def openssl(*args):
    process = subprocess.run(["openssl", *map(str, args)], check=True,
                             capture_output=True, timeout=10)
    return process.stdout


class SignedEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.private_obs = root / "observer-private.pem"
        cls.public_obs = root / "observer-public.pem"
        cls.private_meter = root / "meter-private.pem"
        cls.public_meter = root / "meter-public.pem"
        for priv, pub in ((cls.private_obs, cls.public_obs),
                          (cls.private_meter, cls.public_meter)):
            openssl("genpkey", "-algorithm", "ed25519", "-out", priv)
            openssl("pkey", "-in", priv, "-pubout", "-out", pub)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def signature(self, payload, private_key):
        root = Path(self.tmp.name)
        with tempfile.TemporaryDirectory(dir=root) as path:
            msg = Path(path) / "message"
            sig = Path(path) / "signature"
            msg.write_bytes(canonical_json(payload))
            openssl("pkeyutl", "-sign", "-inkey", private_key,
                    "-rawin", "-in", msg, "-out", sig)
            return {"payload": payload, "signature_b64": base64.b64encode(sig.read_bytes()).decode()}

    def pair(self, *, arm="A5", episode="e1", window="future", at=101):
        identity = {"objective_digest": H, "generation": 1,
                    "episode": episode, "arm": arm, "window": window,
                    "run_id": "run-0", "trace_digest": T,
                    "input_digest": I, "artifact_digest": A}
        observer = dict(identity, role="independent_observer", actor_id="actor",
                        observer_id="independent", evidence_kind="independent_observation",
                        observed_at=at, quality=.9, risk=.1,
                        perceptual_evaluator_digest=P,
                        source_to_output_verified=True, output_to_source_verified=True,
                        modalities=["text", "image", "audio", "video"], av_skew_ms=90)
        meter = dict(identity, role="host_meter", source="host_metered",
                     gpu_seconds=.05, cpu_seconds=.1, energy_joules=3.2,
                     end_to_end_ms=310, controller_ms=20, encoder_ms=40,
                     decoder_ms=200, peak_rss_bytes=123000, peak_vram_bytes=456000,
                     device_digest=H, encoder_digest=I, decoder_digest=A,
                     runtime_digest=P)
        return {"observer": self.signature(observer, self.private_obs),
                "meter": self.signature(meter, self.private_meter)}

    def verify(self, entry):
        return verify_pair(entry, self.public_obs, self.public_meter,
                           expected_objective=H, training_cutoff=100)

    def test_accepted_signatures_keep_no_promotion_authority(self):
        accepted = self.verify(self.pair())
        self.assertEqual(accepted["episode"], "e1")
        self.assertEqual(accepted["quality"], .9)
        report = audit_trial_file({"schema": "hepta.ndu-dmgp.signed-trials.v1",
                                   "trials": [self.pair(arm=arm) for arm in
                                              ("A0", "A1", "A2", "A3", "A4", "A5")]},
                                  self.public_obs, self.public_meter,
                                  expected_objective=H, training_cutoff=100)
        self.assertFalse(report["production_blockers_closed"])
        self.assertTrue(report["no_promotion_authority"])
        self.assertIn("insufficient independent future matched episodes",
                      report["diagnostic_reasons"])

    def test_altered_observation_or_meter_signature_rejected(self):
        for which, key, value in (("observer", "quality", .01),
                                  ("meter", "gpu_seconds", 0.)):
            pair = self.pair()
            pair[which]["payload"][key] = value
            with self.subTest(which=which), self.assertRaises(EvidenceRejected):
                self.verify(pair)

    def test_swapped_roles_and_key_are_rejected(self):
        with self.assertRaises(EvidenceRejected):
            self.verify({"observer": self.pair()["meter"],
                         "meter": self.pair()["observer"]})
        with self.assertRaises(EvidenceRejected):
            audit_trial_file({"schema": "hepta.ndu-dmgp.signed-trials.v1",
                              "trials": [self.pair()]},
                             self.public_obs, self.public_obs,
                             expected_objective=H, training_cutoff=100)

    def test_cross_signed_trace_drift_is_rejected(self):
        entry = self.pair()
        meter = dict(entry["meter"]["payload"], trace_digest="f" * 64)
        entry["meter"] = self.signature(meter, self.private_meter)
        with self.assertRaisesRegex(EvidenceRejected, "different executions"):
            self.verify(entry)

    def test_missing_independent_semantic_or_real_meter_is_rejected(self):
        for which, mutation in (
            ("observer", {"source_to_output_verified": False}),
            ("observer", {"perceptual_evaluator_digest": ""}),
            ("observer", {"av_skew_ms": 1000}),
            ("observer", {"evidence_kind": "synthetic_reference"}),
            ("observer", {"observer_id": "actor"}),
            ("meter", {"decoder_ms": 0}),
            ("meter", {"energy_joules": -1}),
            ("meter", {"source": "synthetic_reference"}),
        ):
            entry = self.pair()
            payload = dict(entry[which]["payload"], **mutation)
            entry[which] = self.signature(payload,
                                          self.private_obs if which == "observer"
                                          else self.private_meter)
            with self.subTest(which=which, mutation=mutation), self.assertRaises(EvidenceRejected):
                self.verify(entry)

    def test_objective_generation_time_split_fail_closed(self):
        with self.assertRaises(EvidenceRejected):
            verify_pair(self.pair(), self.public_obs, self.public_meter,
                        expected_objective="0" * 64, training_cutoff=100)
        entry = self.pair(window="train", at=110)
        with self.assertRaisesRegex(EvidenceRejected, "after frozen cutoff"):
            self.verify(entry)
        entry = self.pair(window="retention", at=90)
        with self.assertRaisesRegex(EvidenceRejected, "before frozen cutoff"):
            self.verify(entry)

    def test_duplicated_cohort_or_train_future_leakage_rejected(self):
        rows = [self.pair(arm=arm) for arm in ("A0", "A1", "A2", "A3", "A4", "A5")]
        bad = {"schema": "hepta.ndu-dmgp.signed-trials.v1", "trials": rows+rows[:1]}
        with self.assertRaisesRegex(EvidenceRejected, "duplicate trial"):
            audit_trial_file(bad, self.public_obs, self.public_meter,
                             expected_objective=H, training_cutoff=100)
        bad["trials"] = rows + [self.pair(arm="A0", window="train", at=80)]
        with self.assertRaisesRegex(EvidenceRejected, "episode leakage"):
            audit_trial_file(bad, self.public_obs, self.public_meter,
                             expected_objective=H, training_cutoff=100)


if __name__ == "__main__":
    unittest.main()
