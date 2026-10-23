"""Real-Ed25519 negative tests for signed A0-A5 admission (synthetic fixtures only)."""
import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

import test_signed_evidence as fixtures
from signed_evidence import EvidenceRejected
from signed_paired_assessment import assess_signed_paired


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


class SignedPairedAssessmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        for role in ("obs", "meter", "reg"):
            private = root / (role + "-private.pem")
            public = root / (role + "-public.pem")
            fixtures.openssl("genpkey", "-algorithm", "ed25519", "-out", private)
            fixtures.openssl("pkey", "-in", private, "-pubout", "-out", public)
            setattr(cls, "private_" + role, private)
            setattr(cls, "public_" + role, public)
        cls.pins = {
            "objective_digest": fixtures.H,
            "generation": 1,
            "critic_digest": "f" * 64,
            "snapshot_digest": fixtures.A,
            "encoder_digest": fixtures.I,
            "decoder_digest": fixtures.A,
            "runtime_digest": fixtures.P,
            "evaluator_digest": fixtures.P,
            "device_digest": fixtures.H,
        }
        cls.reg = {
            "role": "independent_registrar",
            "schema": "hepta.ndu-dmgp.signed-paired-a0-a5.v1",
            **cls.pins,
            "registered_at": 10,
            "training_cutoff": 100,
            "registrar_id": "independent-registrar",
            "actor_id": "actor",
            "observer_id": "independent",
            "meter_id": "external-meter",
            "familywise_alpha": .05,
            "max_end_to_end_ms": 400,
            "max_energy_joules": 10,
            "max_risk": 1,
            "price_per_ms": .0001,
            "price_per_joule": .001,
            "risk_price": .05,
            "max_av_skew_ms": 120,
            "required_modalities": ["text", "image", "audio", "video"],
            "future_roster": [
                {"episode": f"ep{i}", "input_digest": sha(f"input:ep{i}"),
                 "source_group_digest": sha(f"original-source:{i}")}
                for i in range(32)
            ],
        }
        b = cls("runTest")
        cls.signed_reg = b.signature(cls.reg, cls.private_reg)
        cls.rows = []
        for i in range(32):
            for arm in ("A0", "A1", "A2", "A3", "A4", "A5"):
                cls.rows.append(b.build(f"ep{i}", i, arm))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def signature(self, payload, private_key):
        return fixtures.SignedEvidenceTests.signature(self, payload, private_key)

    def build(self, ep, i, arm):
        row = fixtures.SignedEvidenceTests.pair(
            self, arm=arm, episode=ep, at=101 + i)
        obs = dict(row["observer"]["payload"],
                   critic_digest=self.pins["critic_digest"],
                   source_group_digest=sha(f"original-source:{i}"),
                   quality=.90 if arm == "A5" else .20)
        meter = dict(row["meter"]["payload"],
                     meter_id="external-meter",
                     source_group_digest=sha(f"original-source:{i}"))
        row["observer"] = self.signature(obs, self.private_obs)
        row["meter"] = self.signature(meter, self.private_meter)
        return row

    def assess(self, rows=None, registration=None, keys=None, pins=None):
        keys = keys or (self.public_reg, self.public_obs, self.public_meter)
        return assess_signed_paired(
            self.signed_reg if registration is None else registration,
            self.rows if rows is None else rows,
            registrar_public_key=keys[0],
            observer_public_key=keys[1],
            meter_public_key=keys[2],
            trusted_pins=self.pins if pins is None else pins,
        )

    def altered_row(self, role, field, value):
        rows = list(self.rows)
        modified = copy.deepcopy(rows[0])
        payload = dict(modified[role]["payload"], **{field: value})
        key = self.private_obs if role == "observer" else self.private_meter
        modified[role] = self.signature(payload, key)
        rows[0] = modified
        return rows

    def test_independently_signed_preregistered_paired_net_ndu_remains_advisory(self):
        result = self.assess()
        self.assertEqual(result["paired_future_episodes"], 32)
        self.assertEqual(set(result["paired_net_ndu"]),
                         {"A0", "A1", "A2", "A3", "A4"})
        for row in result["paired_net_ndu"].values():
            self.assertGreater(row["observed_mean_net_delta"], 0)
        self.assertFalse(result["production_blockers_closed"])
        self.assertFalse(result["external_sampling_independence_verified"])
        self.assertFalse(result["host_calibration_verified"])
        self.assertTrue(result["no_promotion_authority"])

    def test_signed_protocol_must_match_external_trusted_pins(self):
        mutated = self.signature(
            dict(self.reg, critic_digest="e" * 64), self.private_reg)
        with self.assertRaisesRegex(EvidenceRejected, "trusted frozen"):
            self.assess(registration=mutated)
        with self.assertRaises(EvidenceRejected):
            self.assess(pins=dict(self.pins, snapshot_digest="d" * 64))
        with self.assertRaisesRegex(EvidenceRejected, "keys must differ"):
            self.assess(keys=(self.public_obs, self.public_obs, self.public_meter))
        with self.assertRaisesRegex(EvidenceRejected, "untrusted or altered"):
            forged = copy.deepcopy(self.signed_reg)
            forged["payload"]["max_energy_joules"] = 1000
            self.assess(registration=forged)

    def test_immutable_objective_critic_model_source_and_required_outputs(self):
        for role, field, value in (
            ("observer", "critic_digest", "d" * 64),
            ("observer", "artifact_digest", "d" * 64),
            ("observer", "source_group_digest", "d" * 64),
            ("observer", "modalities", ["text"]),
            ("observer", "actor_id", "different-actor"),
            ("meter", "decoder_digest", "d" * 64),
            ("meter", "meter_id", "different-meter"),
        ):
            with self.subTest(role=role, field=field):
                with self.assertRaises(EvidenceRejected):
                    self.assess(rows=self.altered_row(role, field, value))

    def test_rejects_missing_arm_new_source_and_duplicate_work(self):
        with self.assertRaisesRegex(EvidenceRejected, "missing/extra"):
            self.assess(rows=self.rows[:-1])
        with self.assertRaisesRegex(EvidenceRejected, "different executions"):
            self.assess(rows=self.altered_row(
                "observer", "input_digest", sha("substituted-input")))
        repeated = list(self.rows)
        first = copy.deepcopy(repeated[0])
        existing_trace = self.rows[1]["observer"]["payload"]["trace_digest"]
        for role, key in (("observer", self.private_obs), ("meter", self.private_meter)):
            payload = dict(first[role]["payload"], trace_digest=existing_trace)
            first[role] = self.signature(payload, key)
        repeated[0] = first
        with self.assertRaisesRegex(EvidenceRejected, "reused physical"):
            self.assess(rows=repeated)

    def test_hard_risk_or_resource_ceiling_cannot_be_compensated_by_quality(self):
        for role, field, value in (
            ("observer", "risk", 1.01),
            ("meter", "energy_joules", 20.0),
            ("meter", "end_to_end_ms", 401),
        ):
            with self.subTest(field=field):
                with self.assertRaises(EvidenceRejected):
                    self.assess(rows=self.altered_row(role, field, value))


if __name__ == "__main__":
    unittest.main()
