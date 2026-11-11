"""Fail-closed E0 projection preflight fixture tests; not real pretrained inference."""
import json
import tempfile
import unittest
from pathlib import Path
from e0_projection_gate import verify_contract, GateError, sha_file


class ProjectionPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.art = self.root / "projection.bin"
        self.art.write_bytes(b"controlled mathematical projection fixture")
        self.obj = dict(schema="hepta.neuron.e0-projection-preflight.v1",
                        encoder_width=768, projection_width=256, head_input_width=256,
                        projection_artifact=str(self.art), projection_sha256=sha_file(self.art),
                        projected_features_q24=[0]*256, feature_source_sha256="b"*64,
                        source_kind="externally_observed_not_authenticated")
        self.path = self.root / "contract.json"

    def check(self, **updates):
        self.path.write_text(json.dumps(self.obj | updates))
        return verify_contract(self.path)

    def test_nominal_compatibility_claim_remains_non_authorizing(self):
        result = self.check()
        self.assertEqual(result["neuron_input_width"], 256)
        self.assertFalse(result["real_encoder_invocation_authenticated"])
        self.assertFalse(result["projection_applied_to_encoder_proven"])
        self.assertFalse(result["neuron_tick_committed"])

    def test_wide_features_fail_without_projection(self):
        with self.assertRaisesRegex(GateError, "ceiling"):
            self.check(projection_width=768, head_input_width=768, projected_features_q24=[0]*768)

    def test_implicit_slice_fails(self):
        with self.assertRaisesRegex(GateError, "width mismatch"):
            self.check(projected_features_q24=[0]*128)

    def test_head_mismatch_fails(self):
        with self.assertRaisesRegex(GateError, "Head width"):
            self.check(head_input_width=128)

    def test_invalid_q24_fails(self):
        with self.assertRaisesRegex(GateError, "invalid Q24"):
            self.check(projected_features_q24=[0]*255 + [9*(1<<24)])
        with self.assertRaisesRegex(GateError, "invalid Q24"):
            self.check(projected_features_q24=[0]*255 + [0.1])

    def test_physical_artifact_drift_fails(self):
        self.check()
        self.art.write_bytes(b"mutated")
        with self.assertRaisesRegex(GateError, "bytes drift"):
            verify_contract(self.path)

    def test_unknown_fields_fail(self):
        with self.assertRaisesRegex(GateError, "unknown"):
            self.check(digest_only_claim="pass")

    def test_wrong_source_kind_fails(self):
        with self.assertRaisesRegex(GateError, "source type"):
            self.check(source_kind="production_signed")


if __name__ == "__main__":
    unittest.main()
