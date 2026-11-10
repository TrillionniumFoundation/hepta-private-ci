"""Independent-positive/negative contract tests for the bounded v4 semantic gate."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.ndu_bimodal.semantic_gate import PROFILE, evaluate, sha256


class SemanticGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.delivery = self.root / "delivered"
        self.delivery.mkdir()
        self.manifest_path = self.root / "frozen.json"
        self.bindings = {
            "public_sha256": "1" * 64,
            "checkpoint_sha256": "2" * 64,
            "binary_sha256": "3" * 64,
        }
        self.manifest = {
            "schema": PROFILE,
            "task_id": "registered-solid-red-card-01",
            "bindings": self.bindings,
            "target": {
                "accepted_text": ["red", "a red card"],
                "rgb": [255, 0, 0],
                "max_channel_error": 0,
                "max_mean_absolute_error": 0,
                "min_pixel_fraction": 1,
            },
            "limits": {
                "max_calls": 4,
                "max_native_wall_seconds": 2.0,
                "max_native_cpu_seconds": 2.0,
            },
        }
        self.text = b"red"
        self.image = b"P6\n16 16\n255\n" + bytes([255, 0, 0]) * 256
        self.call = {
            "kind": "submit",
            "status": "passed",
            "exit_code": 0,
            "request_sha256": "4" * 64,
            "stdout_sha256": "5" * 64,
            "stderr_sha256": "6" * 64,
            "wall_seconds": 0.25,
            "child_cpu_seconds": 0.20,
        }
        self.receipt = {
            **self.bindings,
            "action": "SUBMIT",
            "production_update": "no-update",
            "text_utf8": "red",
            "image_sha256": sha256(self.image),
            "calls": [self.call],
        }
        self.freeze()
        self.publish()

    def freeze(self):
        raw = json.dumps(self.manifest, sort_keys=True).encode()
        self.manifest_path.write_bytes(raw)
        self.trusted = hashlib.sha256(raw).hexdigest()

    def publish(self):
        (self.delivery / "generated.txt").write_bytes(self.text)
        (self.delivery / "generated.ppm").write_bytes(self.image)
        (self.delivery / "delivery.json").write_text(json.dumps(self.receipt))

    def assess(self):
        return evaluate(self.manifest_path, self.trusted, self.delivery)

    def test_both_modalities_pass_but_never_production_promote(self):
        result = self.assess()
        self.assertTrue(result["bounded_colour_card_pass"])
        self.assertEqual(result["decision"], "BOUNDED_TASK_PASS")
        self.assertFalse(result["production_adoption"])
        self.assertFalse(result["independent_evaluator_execution_verified"])
        self.assertFalse(result["whole_resource_budget_verified"])
        self.assertEqual(result["scientific_acceptance"], "HOLD_NO_GO")
        self.assertEqual(result["observed_native_cost"]["calls"], 1)

    def test_repetitive_text_fails_even_with_valid_utf8(self):
        self.text = b"ueeeeeeeeeeeeeeeeeeeeeeeeee"
        self.receipt["text_utf8"] = self.text.decode()
        self.publish()
        result = self.assess()
        self.assertFalse(result["text_exact_match"])
        self.assertFalse(result["bounded_colour_card_pass"])

    def test_image_wrong_colour_fails_even_when_decodable(self):
        self.image = b"P6\n16 16\n255\n" + bytes([0, 255, 0]) * 256
        self.receipt["image_sha256"] = sha256(self.image)
        self.publish()
        result = self.assess()
        self.assertTrue(result["text_exact_match"])
        self.assertFalse(result["image"]["pass"])
        self.assertFalse(result["bounded_colour_card_pass"])

    def test_image_fraction_rejects_single_wrong_pixel(self):
        self.image = self.image[:-3] + bytes([254, 0, 0])
        self.receipt["image_sha256"] = sha256(self.image)
        self.publish()
        self.assertFalse(self.assess()["bounded_colour_card_pass"])

    def test_noncanonical_codec_rejected_for_this_profile(self):
        self.image = b"P3\n16 16\n255\n" + bytes([255, 0, 0]) * 256
        self.receipt["image_sha256"] = sha256(self.image)
        self.publish()
        self.assertFalse(self.assess()["image"]["valid"])

    def test_genuine_manifest_freeze_blocks_retarget(self):
        self.manifest["target"]["accepted_text"] = ["ueeeeee"]
        self.manifest_path.write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(ValueError, "externally frozen"):
            self.assess()

    def test_identity_mismatch_rejected(self):
        self.receipt["checkpoint_sha256"] = "7" * 64
        self.publish()
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self.assess()

    def test_mutated_output_without_receipt_revision_rejected(self):
        self.text = b"green"
        self.publish()
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            self.assess()

    def test_mutated_image_without_receipt_revision_rejected(self):
        self.image = b"P6\n16 16\n255\n" + bytes([0, 0, 255]) * 256
        self.publish()
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            self.assess()

    def test_no_bypass_using_missing_modality(self):
        (self.delivery / "generated.ppm").unlink()
        with self.assertRaises(FileNotFoundError):
            self.assess()

    def test_budget_overrun_fails_without_confusing_wall_and_cpu(self):
        self.call["wall_seconds"] = 2.5
        self.publish()
        result = self.assess()
        self.assertFalse(result["observed_native_cost"]["within_declared_cap"])
        self.assertFalse(result["bounded_colour_card_pass"])

    def test_failed_native_call_rejected(self):
        self.call["status"] = "timeout"
        self.publish()
        with self.assertRaisesRegex(ValueError, "native call"):
            self.assess()

    def test_unapproved_production_transition_refused(self):
        self.receipt["production_update"] = "adopt"
        self.publish()
        with self.assertRaisesRegex(ValueError, "unadopted"):
            self.assess()

    def test_unknown_manifest_field_fails_closed(self):
        self.manifest["hint_from_future"] = True
        self.freeze()
        with self.assertRaisesRegex(ValueError, "private manifest"):
            self.assess()

    def test_duplicate_manifest_key_rejected(self):
        raw = self.manifest_path.read_bytes()
        self.manifest_path.write_bytes(raw[:-1] + b',"task_id":"rewritten"}')
        self.trusted = sha256(self.manifest_path.read_bytes())
        with self.assertRaisesRegex(ValueError, "duplicate JSON"):
            self.assess()

    def test_bool_budget_is_not_integer(self):
        self.manifest["limits"]["max_calls"] = True
        self.freeze()
        with self.assertRaisesRegex(ValueError, "call cap"):
            self.assess()

    def test_invalid_nonfinite_native_cost(self):
        self.call["wall_seconds"] = float("nan")
        self.publish()
        with self.assertRaisesRegex(ValueError, "nonfinite JSON"):
            self.assess()


if __name__ == "__main__":
    unittest.main()
