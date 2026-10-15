"""Checks the narrow recovery boundary without performing model inference."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import native_token_schema_recovery as recovery


class MembershipCompatibilityTest(unittest.TestCase):
    def setUp(self):
        self.membership = dict(schema=recovery.PROTOCOL_SCHEMA,
            partitions={"train": ["train-a"], "final": ["final-b"]},
            final_case_ids=["case-b"], previous_design_sha256="old-design")
        self.design = dict(self.membership, schema=recovery.CAMPAIGN_SCHEMA,
            verifier={"steps": 1000})

    def test_maps_only_schema_without_mutating_inputs(self):
        before = copy.deepcopy((self.design, self.membership))
        mapped = recovery.compatible_membership(self.design, self.membership)
        self.assertEqual(mapped, dict(self.membership, schema=recovery.CAMPAIGN_SCHEMA))
        self.assertEqual((self.design, self.membership), before)
        self.assertIsNot(mapped, self.membership)

    def test_rejects_each_non_schema_drift_and_unknown_field(self):
        for key in ("partitions", "final_case_ids", "previous_design_sha256", "unexpected"):
            changed = dict(self.membership, **{key: "tampered"})
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "non-schema"):
                recovery.compatible_membership(self.design, changed)

    def test_rejects_unknown_namespace_in_either_document(self):
        for which in ("design", "membership"):
            design, membership = copy.deepcopy((self.design, self.membership))
            (design if which == "design" else membership)["schema"] = "other.v2"
            with self.subTest(which=which), self.assertRaisesRegex(ValueError, "schema"):
                recovery.compatible_membership(design, membership)

    def test_refuses_any_prior_native_final_output_before_other_reads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "seed-41" / "final").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "first native final"):
                recovery.preflight(SimpleNamespace(output=root))

    def test_original_full_validation_repeats_and_restores_on_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "design.json").write_text(json.dumps(self.design))
            args = SimpleNamespace(output=root)
            frozen, manifests, parts = object(), object(), object()
            original = lambda _: (parts, self.membership, frozen, manifests)
            attestation = {"recovery_source_sha256": "unused-after-error"}

            def original_evaluate(repeated_args):
                actual = recovery.driver.training_inputs(repeated_args)
                self.assertIs(actual[0], parts)
                self.assertIs(actual[2], frozen)
                self.assertIs(actual[3], manifests)
                self.assertEqual(actual[1], dict(self.membership, schema=recovery.CAMPAIGN_SCHEMA))
                raise RuntimeError("stop before inference")

            with patch.object(recovery, "preflight", return_value=(self.membership, attestation)), \
                    patch.object(recovery.driver, "training_inputs", original), \
                    patch.object(recovery.driver, "evaluate", original_evaluate):
                with self.assertRaisesRegex(RuntimeError, "before inference"):
                    recovery.evaluate(args)
                self.assertIs(recovery.driver.training_inputs, original)
            self.assertTrue((root / "schema-recovery-start.json").is_file())
            self.assertFalse((root / "schema-recovery-completion.json").exists())


if __name__ == "__main__":
    unittest.main()
