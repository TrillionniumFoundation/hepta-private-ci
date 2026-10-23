"""Signed independent-observer / host-meter NDU-DMGP shadow audit negatives."""
import base64
import hashlib
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
                    "run_id": f"run:{episode}:{arm}:{window}",
                    "trace_digest": hashlib.sha256(
                        f"{episode}:{arm}:{window}".encode()).hexdigest(),
                    "input_digest": hashlib.sha256(
                        f"input:{episode}".encode()).hexdigest(),
                    "artifact_digest": A}
        observer = dict(identity, role="independent_observer", actor_id="actor",
                        observer_id="independent", evidence_kind="independent_observation",
                        observed_at=at, quality=.9, risk=.1,
                        perceptual_evaluator_digest=P,
                        source_to_output_verified=True, output_to_source_verified=True,
                        source_to_output_evidence_digest=hashlib.sha256(
                            f"{episode}:{arm}:forward".encode()).hexdigest(),
                        output_to_source_evidence_digest=hashlib.sha256(
                            f"{episode}:{arm}:reverse".encode()).hexdigest(),
                        cross_modal_claims_digest=hashlib.sha256(
                            f"{episode}:{arm}:claims".encode()).hexdigest(),
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
                           expected_objective=H, expected_evaluator_digest=P,
                             expected_device_digest=H, training_cutoff=100)

    def test_accepted_signatures_keep_no_promotion_authority(self):
        accepted = self.verify(self.pair())
        self.assertEqual(accepted["episode"], "e1")
        self.assertEqual(accepted["quality"], .9)
        report = audit_trial_file({"schema": "hepta.ndu-dmgp.signed-trials.v1",
                                   "trials": [self.pair(arm=arm) for arm in
                                              ("A0", "A1", "A2", "A3", "A4", "A5")]},
                                  self.public_obs, self.public_meter,
                                  expected_objective=H, expected_evaluator_digest=P,
                             expected_device_digest=H, training_cutoff=100)
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
                             expected_objective=H, expected_evaluator_digest=P,
                             expected_device_digest=H, training_cutoff=100)

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
            ("meter", {"device_digest": "0" * 64}),
            ("observer", {"modalities": [{}]}),
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
                        expected_objective="0" * 64, expected_evaluator_digest=P,
                        expected_device_digest=H, training_cutoff=100)
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
                             expected_objective=H, expected_evaluator_digest=P,
                             expected_device_digest=H, training_cutoff=100)
        bad["trials"] = rows + [self.pair(arm="A0", window="train", at=80)]
        with self.assertRaisesRegex(EvidenceRejected, "episode leakage"):
            audit_trial_file(bad, self.public_obs, self.public_meter,
                             expected_objective=H, expected_evaluator_digest=P,
                             expected_device_digest=H, training_cutoff=100)


    def test_physical_run_and_source_replay_across_episodes_rejected(self):
        arms = ("A0", "A1", "A2", "A3", "A4", "A5")
        first = [self.pair(arm=arm, episode="e1") for arm in arms]
        repeated_run = [self.pair(arm=arm, episode="e2") for arm in arms]
        stolen_run = first[0]["observer"]["payload"]["run_id"]
        for role, key in (("observer", self.private_obs), ("meter", self.private_meter)):
            payload = dict(repeated_run[0][role]["payload"], run_id=stolen_run)
            repeated_run[0][role] = self.signature(payload, key)
        with self.assertRaisesRegex(EvidenceRejected, "physical runs"):
            self.audit(first + repeated_run)

        reused_input = [self.pair(arm=arm, episode="e2") for arm in arms]
        same_input = first[0]["observer"]["payload"]["input_digest"]
        for row in reused_input:
            for role, key in (("observer", self.private_obs), ("meter", self.private_meter)):
                payload = dict(row[role]["payload"], input_digest=same_input)
                row[role] = self.signature(payload, key)
        with self.assertRaisesRegex(EvidenceRejected, "reused source input"):
            self.audit(first + reused_input)

    def audit(self, trials):
        return audit_trial_file(
            {"schema": "hepta.ndu-dmgp.signed-trials.v1", "trials": trials},
            self.public_obs, self.public_meter,
            expected_objective=H, expected_evaluator_digest=P,
            expected_device_digest=H, training_cutoff=100,
        )

    def test_unmetered_or_temporally_impossible_host_work_rejected(self):
        for field, value in (
            ("peak_rss_bytes", 0),
            ("energy_joules", 0),
            ("decoder_ms", 500),
            ("controller_ms", 500),
            ("peak_rss_bytes", 10**1000),
        ):
            entry = self.pair()
            payload = dict(entry["meter"]["payload"], **{field: value})
            entry["meter"] = self.signature(payload, self.private_meter)
            with self.subTest(field=field, value=str(value)[:20]):
                with self.assertRaises(EvidenceRejected):
                    self.verify(entry)

    def test_simultaneous_heldout_uses_multiplicity_bound_not_unadjusted_se(self):
        arms = ("A0", "A1", "A2", "A3", "A4", "A5")
        trials = []
        for i in range(32):
            for arm in arms:
                row = self.pair(arm=arm, episode=f"future-{i}")
                quality = .99 if arm == "A5" else .01
                obs = dict(row["observer"]["payload"], quality=quality)
                row["observer"] = self.signature(obs, self.private_obs)
                trials.append(row)
        result = self.audit(trials)
        self.assertFalse(result["production_blockers_closed"])
        self.assertEqual(result["matched_episode_counts"]["future"], 32)
        self.assertEqual(set(result["paired_future_quality"]), set(arms) - {"A5"})
        for contrast in result["paired_future_quality"].values():
            self.assertEqual(contrast["method"], "bonferroni-hoeffding")
            self.assertFalse(contrast["independent_clusters_verified"])
            self.assertGreater(contrast["quality_delta_familywise_lcb95"], 0)



    def test_unsigned_or_reused_perceptual_evidence_never_suffices(self):
        for mutation in (
            {"source_to_output_evidence_digest": ""},
            {"cross_modal_claims_digest": "0" * 64},
            {"output_to_source_evidence_digest": None},
        ):
            entry = self.pair()
            payload = dict(entry["observer"]["payload"], **mutation)
            entry["observer"] = self.signature(payload, self.private_obs)
            with self.subTest(mutation=mutation), self.assertRaisesRegex(
                    EvidenceRejected, "perceptual evidence"):
                self.verify(entry)

        entry = self.pair()
        payload = dict(entry["observer"]["payload"])
        payload["output_to_source_evidence_digest"] = payload[
            "source_to_output_evidence_digest"]
        entry["observer"] = self.signature(payload, self.private_obs)
        with self.assertRaisesRegex(EvidenceRejected, "separately identified"):
            self.verify(entry)



if __name__ == "__main__":
    unittest.main()
