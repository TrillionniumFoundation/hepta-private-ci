import dataclasses
import hashlib
import unittest

import e0_native_tick_handoff as m


def fixture(**changes):
    features = (0,) * 255 + (m.Q24 // 4,)
    return dataclasses.replace(m.DiagnosticTick(
        tick_id="tick.one", subject_id="scope.subject",
        logical_sequence=1, monotonic_time_micros=101,
        checkpoint_digest=m.ZERO_SHA,
        input_feature_digest=m.canonical_feature_vector_digest_v1(features),
        feature_vector_q24=features, objective_digest="a" * 64,
        ndu_snapshot_digest="b" * 64), **changes)


class TickBindingTests(unittest.TestCase):
    def test_original_neuron_v1_feature_digest_golden(self):
        self.assertEqual(fixture().input_feature_digest,
            "f7c508aca0ca8bcb8a927efeb0c65bc02c98b212e124d3ac74fa10da1b79b5e3")

    def test_readonly_handoff_preserves_three_distinct_identities(self):
        r = m.audit_readonly_handoff(fixture(), stem_projected_input_digest="c" * 64)
        self.assertEqual(r["neuron_model_request_input_digest"], r["neuron_v1_tick_semantic_digest"])
        self.assertNotEqual(r["stem_projected_input_digest"], r["neuron_model_request_input_digest"])
        self.assertNotEqual(r["neuron_v1_input_feature_digest"], r["neuron_model_request_input_digest"])
        self.assertFalse(r["actual_worker_called"])
        self.assertFalse(r["checkpoint_committed"])

    def test_scope_and_time_change_tick_only(self):
        t = fixture()
        for v in (dataclasses.replace(t, subject_id="other.subject"),
                  dataclasses.replace(t, monotonic_time_micros=102),
                  dataclasses.replace(t, objective_digest="d"*64),
                  dataclasses.replace(t, ndu_snapshot_digest="e"*64)):
            self.assertEqual(v.input_feature_digest, t.input_feature_digest)
            self.assertNotEqual(m.semantic_tick_digest_v1(v), m.semantic_tick_digest_v1(t))

    def test_q24_vector_mutation_with_stale_digest_is_rejected(self):
        t=fixture()
        changed = t.feature_vector_q24[:-1] + (t.feature_vector_q24[-1]+1,)
        with self.assertRaisesRegex(ValueError,"canonical feature digest mismatch"):
            m.semantic_tick_digest_v1(dataclasses.replace(t, feature_vector_q24=changed))

    def test_wrong_digest_cannot_impersonate_native_input(self):
        with self.assertRaisesRegex(ValueError, "canonical feature digest mismatch"):
            m.semantic_tick_digest_v1(fixture(input_feature_digest="c"*64))

    def test_subsequent_sequence_needs_checkpoint(self):
        with self.assertRaisesRegex(ValueError, "subsequent tick requires checkpoint"):
            m.semantic_tick_digest_v1(fixture(logical_sequence=2))
        t=fixture(logical_sequence=2, checkpoint_digest="c"*64)
        self.assertEqual(len(m.semantic_tick_digest_v1(t)),64)

    def test_first_sequence_cannot_claim_checkpoint(self):
        with self.assertRaisesRegex(ValueError, "first tick must have zero checkpoint"):
            m.semantic_tick_digest_v1(fixture(checkpoint_digest="c"*64))

    def test_zero_ndu_and_objective_cannot_pass(self):
        for edit in ({"objective_digest":m.ZERO_SHA}, {"ndu_snapshot_digest":m.ZERO_SHA}):
            with self.assertRaisesRegex(ValueError, "zero digest"):
                m.semantic_tick_digest_v1(fixture(**edit))

    def test_optional_body_and_modulator_are_bound(self):
        start=fixture()
        variants=[fixture(body_generation=0),fixture(body_generation=1),
                  fixture(modulator_digest="f"*64),
                  fixture(body_generation=1,modulator_digest="f"*64)]
        base=m.semantic_tick_digest_v1(start)
        self.assertEqual(len({base,*[m.semantic_tick_digest_v1(x) for x in variants]}),5)
        with self.assertRaisesRegex(ValueError, "zero digest"):
            m.semantic_tick_digest_v1(fixture(modulator_digest=m.ZERO_SHA))

    def test_feature_limits_are_never_silently_truncated(self):
        for vec in ((), (0,)*513, (9*m.Q24,), (0.0,), (True,)):
            with self.subTest(length=len(vec)):
                with self.assertRaisesRegex(ValueError, "feature"):
                    m.canonical_feature_vector_digest_v1(vec)

    def test_signed_big_endian_and_length_bind_identity(self):
        a=m.canonical_feature_vector_digest_v1((1,))
        b=m.canonical_feature_vector_digest_v1((-1,))
        c=m.canonical_feature_vector_digest_v1((1,0))
        self.assertEqual(len({a,b,c}),3)
        self.assertEqual(a,hashlib.sha256(m.FEATURE_DOMAIN + (1).to_bytes(8,"big") +
            (1).to_bytes(8,"big",signed=True)).hexdigest())

    def test_scope_reference_cannot_be_zero_or_fake_native_authority(self):
        with self.assertRaisesRegex(ValueError, "zero digest"):
            m.audit_readonly_handoff(fixture(),stem_projected_input_digest=m.ZERO_SHA)
        v=m.audit_readonly_handoff(fixture(),stem_projected_input_digest="c"*64)
        self.assertTrue(v["diagnostic_only"])
        self.assertFalse(v["grant_authenticated"])
        self.assertFalse(v["independent_witness_confirmed"])


if __name__=="__main__":
    unittest.main()
