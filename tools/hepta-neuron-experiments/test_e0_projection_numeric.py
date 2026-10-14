"""Synthetic numerical-oracle controls; no pretrained model, Worker or effect."""
import hashlib
import json
import math
import os
import struct
import tempfile
import unittest
from pathlib import Path

import e0_projection_numeric as m


def h(x):
    return hashlib.sha256(x).hexdigest()


def projection_digest(p):
    z = hashlib.sha256(m.P_DOMAIN)
    for name in ("encoder_digest", "preprocessor_digest", "runtime_digest",
                 "normalizer_digest", "representation"):
        z.update(m.field(p[name]))
    for name in ("input_width", "output_width", "rank"):
        z.update(m.u64(p[name]))
    for name in ("a_q24", "b_q24", "bias_q24"):
        z.update(m.u64(len(p[name])))
        for n in p[name]:
            z.update(m.i64(n))
    return z.hexdigest()


def source_digest(raw, length=768, tokens=41):
    z = hashlib.sha256(m.F_DOMAIN)
    z.update(m.u64(length))
    z.update(raw)
    z.update(m.u64(tokens))
    z.update(b"mean")
    return z.hexdigest()


def binding_digest(c, p):
    z = hashlib.sha256(m.B_DOMAIN)
    for x in (c["scope_digest"], c["revocation_frontier_digest"],
              p["encoder_digest"], p["preprocessor_digest"],
              p["runtime_digest"], c["source_input_digest"],
              c["feature_digest"], c["projection_digest"]):
        z.update(m.field(x))
    z.update(m.u64(c["generation"]))
    z.update(m.u64(len(c["expected_output_q24"])))
    for x in c["expected_output_q24"]:
        z.update(m.i64(x))
    return z.hexdigest()


class E0NumericOracleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.feature_file = self.root / "feature-f32.bin"
        self.projector_file = self.root / "projector.json"
        self.trial_file = self.root / "trial.json"
        self.f32 = [0.0] * 768
        self.f32[-1] = .25
        self.out = [0] * 256
        self.out[-1] = m.Q // 4
        self.projector = {
            "schema": m.P_SCHEMA, "shadow_only": True, "production_authorized": False,
            "training_lineage_digest": "e" * 64, "encoder_digest": "a" * 64,
            "preprocessor_digest": "b" * 64, "runtime_digest": "c" * 64,
            "normalizer_digest": "d" * 64, "representation": "mean",
            "input_width": 768, "output_width": 256, "rank": 1,
            "a_q24": [0] * 767 + [m.Q],
            "b_q24": [0] * 255 + [m.Q],
            "bias_q24": [0] * 256,
        }
        self.contract = {
            "schema": m.C_SCHEMA, "source_kind": "local_f32_capture_untrusted",
            "feature_file": str(self.feature_file),
            "feature_file_sha256": "0" * 64, "feature_digest": "0" * 64,
            "token_count": 41, "projection_manifest": str(self.projector_file),
            "projection_file_sha256": "0" * 64, "projection_digest": "0" * 64,
            "source_input_digest": "1" * 64, "scope_digest": "2" * 64,
            "revocation_frontier_digest": "3" * 64, "generation": 7,
            "head_input_width": 256, "expected_output_q24": self.out[:],
            "projected_input_digest": "0" * 64,
        }
        self.freeze()

    def freeze(self):
        raw = struct.pack(">768f", *self.f32)
        self.feature_file.write_bytes(raw)
        self.contract["feature_file_sha256"] = h(raw)
        self.contract["feature_digest"] = source_digest(raw)
        self.projector["projection_digest"] = projection_digest(self.projector)
        content = (json.dumps(self.projector, separators=(",", ":"), sort_keys=True) + "\n").encode()
        self.projector_file.write_bytes(content)
        self.contract["projection_file_sha256"] = h(content)
        self.contract["projection_digest"] = self.projector["projection_digest"]
        self.contract["projected_input_digest"] = binding_digest(self.contract, self.projector)
        self.trial_file.write_text(json.dumps(self.contract))

    def run_trial(self, changes=None):
        self.trial_file.write_text(json.dumps(self.contract | (changes or {})))
        return m.calculate(self.trial_file)

    def test_exact_768_to_256_uses_final_source_coordinate(self):
        result = self.run_trial()
        self.assertEqual((result["input_width"], result["output_width"], result["rank"]), (768, 256, 1))
        self.assertTrue(result["numeric_oracle_agrees"])
        self.assertFalse(result["encoder_actually_invoked"])
        self.assertFalse(result["neuron_checkpoint_committed"])
        self.assertEqual(self.out[-1], 1 << 22)
        # Independent golden for the Rust V1 canonical Q24 input vector domain
        # and u64-count / signed-big-endian-i64 encoding.
        self.assertEqual(result["neuron_v1_input_feature_digest"],
                         "f7c508aca0ca8bcb8a927efeb0c65bc02c98b212e124d3ac74fa10da1b79b5e3")
        self.assertNotEqual(result["computed_q24_sha256"], h(bytes(256 * 8)))

    def test_hidden_source_change_with_recomputed_source_sha_is_detected(self):
        self.f32[-1] = .5
        self.freeze()  # the reported precomputed Q24 remains .25
        with self.assertRaisesRegex(m.NumericGateError, "numerical mismatch"):
            self.run_trial()

    def test_reported_q24_change_with_recomputed_binding_digest_is_detected(self):
        self.contract["expected_output_q24"][-1] += 1
        self.contract["projected_input_digest"] = binding_digest(self.contract, self.projector)
        with self.assertRaisesRegex(m.NumericGateError, "numerical mismatch"):
            self.run_trial()

    def test_physically_modified_projector_is_rejected(self):
        self.projector_file.write_bytes(b"tampered")
        with self.assertRaisesRegex(m.NumericGateError, "SHA256 mismatch"):
            self.run_trial()

    def test_tampered_coefficients_after_rehash_cannot_preserve_result(self):
        # Preserve a nonzero source-tail path, but change its magnitude so
        # numeric recomputation (not merely tail connectivity) rejects.
        self.projector["a_q24"][-1] = m.Q // 2
        self.freeze()
        with self.assertRaisesRegex(m.NumericGateError, "numerical mismatch"):
            self.run_trial()

    def test_wrong_source_width_is_not_implicitly_sliced(self):
        raw = struct.pack(">256f", *self.f32[:256])
        self.feature_file.write_bytes(raw)
        self.contract["feature_file_sha256"] = h(raw)
        with self.assertRaisesRegex(m.NumericGateError, "source f32 width mismatch"):
            self.run_trial()

    def test_reregistered_prefix_only_projector_cannot_masquerade_as_full_encoder(self):
        self.projector["a_q24"][767] = 0
        self.projector["a_q24"][0] = m.Q
        self.f32[0] = .25
        self.freeze()
        with self.assertRaisesRegex(m.NumericGateError, "implicit slice"):
            self.run_trial()

    def test_tail_weight_without_live_output_is_not_a_feature_path(self):
        self.projector["b_q24"][-1] = 0
        self.freeze()
        with self.assertRaisesRegex(m.NumericGateError, "implicit slice"):
            self.run_trial()

    def test_wrong_head_width_is_rejected(self):
        with self.assertRaisesRegex(m.NumericGateError, "Head width mismatch"):
            self.run_trial({"head_input_width": 128})

    def test_nonfinite_and_out_of_bounds_f32_rejected_even_with_fresh_hashes(self):
        for bad in (float("nan"), float("inf"), 9.0):
            with self.subTest(bad=bad):
                self.f32[-1] = bad
                self.freeze()
                with self.assertRaisesRegex(m.NumericGateError, "nonfinite/out-of-range"):
                    self.run_trial()

    def test_bound_scope_generation_and_parent_identity(self):
        with self.assertRaisesRegex(m.NumericGateError, "scoped projected-input binding mismatch"):
            self.run_trial({"scope_digest": "f" * 64})
        with self.assertRaisesRegex(m.NumericGateError, "scoped projected-input binding mismatch"):
            self.run_trial({"generation": 8})
        with self.assertRaisesRegex(m.NumericGateError, "scoped projected-input binding mismatch"):
            self.run_trial({"source_input_digest": "a" * 64})

    def test_wrong_manifest_semantic_digest_and_rank_rejected(self):
        self.projector["a_q24"][-1] = 0
        raw = (json.dumps(self.projector) + "\n").encode()
        self.projector_file.write_bytes(raw)
        self.contract["projection_file_sha256"] = h(raw)
        with self.assertRaisesRegex(m.NumericGateError, "semantic digest mismatch"):
            self.run_trial()
        self.projector["rank"] = 0
        self.freeze()
        with self.assertRaisesRegex(m.NumericGateError, "projection width/rank"):
            self.run_trial()

    def test_symlink_and_hardlink_rejected(self):
        link = self.root / "source-link.bin"
        link.symlink_to(self.feature_file)
        with self.assertRaisesRegex(m.NumericGateError, "symlinked artifact"):
            self.run_trial({"feature_file": str(link)})
        linked = self.root / "hardlink.bin"
        os.link(self.feature_file, linked)
        with self.assertRaisesRegex(m.NumericGateError, "exclusive regular file"):
            self.run_trial()

    def test_duplicate_json_field_or_claimed_authority_rejected(self):
        raw = self.trial_file.read_text()
        self.trial_file.write_text(raw[:-1] + ',"source_kind":"production_signed"}')
        with self.assertRaisesRegex(m.NumericGateError, "duplicate JSON key"):
            m.calculate(self.trial_file)
        with self.assertRaisesRegex(m.NumericGateError, "unknown/missing JSON fields"):
            self.run_trial({"production_accepted": True})

    def test_exact_integer_rounding_negative_ties(self):
        self.assertEqual(m.round_q48(m.Q // 2), 0)
        self.assertEqual(m.round_q48(3 * m.Q // 2), 2)
        self.assertEqual(m.round_q48(-m.Q // 2), 0)
        self.assertEqual(m.round_q48(-3 * m.Q // 2), -2)
        self.assertEqual(m.q24_scalar(-.25), -(m.Q // 4))
        with self.assertRaisesRegex(m.NumericGateError, "unrepresentable"):
            m.round_q48(9 * m.Q * m.Q)

    def test_result_never_contains_runtime_authority(self):
        result = self.run_trial()
        self.assertEqual(result["non_authorizing"], True)
        self.assertTrue(all(result[k] is False for k in
                            ("encoder_actually_invoked", "stem_projection_operator_executed",
                             "neuron_worker_invoked", "neuron_checkpoint_committed",
                             "independent_outcome_proven")))


if __name__ == "__main__":
    unittest.main()
