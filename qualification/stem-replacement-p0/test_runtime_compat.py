"""Runtime API preflight contract tests; no original 400M/421M checkpoint download."""
from __future__ import annotations

import unittest
from unittest import mock

import runtime_compat


class RuntimeCompatContract(unittest.TestCase):
    def test_source_gate_never_authorizes_model_selection(self):
        record=runtime_compat.source_contract()
        self.assertEqual(record["authority"],"DENY_ALL")
        self.assertEqual(record["disposition"],"HOLD_NO_GO")
        for key in ("original_model_weights_loaded","real_pretrained_encoder_forward_verified",
                    "publisher_signature_verified","production_promotion_permitted",
                    "physical_cell_split_permitted"):
            self.assertIs(record[key],False)

    def test_tiny_real_torch_safe_serialization(self):
        try:
            import torch
        except ImportError:
            self.skipTest("Torch available only in physical-runtime host")
        receipt=runtime_compat.safe_tensor_roundtrip()
        self.assertEqual(receipt["actual_tiny_trainable_scalars"],36)
        self.assertTrue(receipt["real_torch_weights_only_roundtrip"])

    def test_runtime_smoke_will_fail_closed_on_partial_host(self):
        with mock.patch.object(runtime_compat,"modernbert_runtime_smoke",side_effect=ValueError("no modernbert")):
            with self.assertRaisesRegex(ValueError,"no modernbert"):
                runtime_compat.run()

    def test_runtime_smoke_will_fail_closed_on_missing_laya(self):
        with mock.patch.object(runtime_compat,"modernbert_runtime_smoke",return_value={}),\
                mock.patch.object(runtime_compat,"laya_installed_api_smoke",side_effect=ValueError("no laya")):
            with self.assertRaisesRegex(ValueError,"no laya"):
                runtime_compat.run()


if __name__ == "__main__": unittest.main()
