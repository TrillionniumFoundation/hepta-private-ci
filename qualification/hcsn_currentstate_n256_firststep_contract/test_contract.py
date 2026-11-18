"""Synthetic controls for the source-only N256 first-step contract."""

import copy
import json
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_firststep_contract import contract
from qualification.hcsn_currentstate_n256_firststep_contract import static_inspector


ROOT = Path(__file__).parent
REPOSITORY = ROOT.parents[1]


def valid_receipt():
    return {
        "schema": "hcsn-n256-corrected-firststep-receipt-v1",
        "identity": contract.IDENTITY,
        "target": contract.expected_target(),
        "coordinate_counts": {
            "state": 2600,
            "packet": 67128,
            "total": 69728,
            "compared": 69728,
            "equal": 69728,
            "mismatches": 0,
        },
        "packet_count": 9,
        "calls": {
            "candidate_dynamic_steps": 1,
            "candidate_sparse_exponential_actions": 2,
            "oracle_dynamic_steps": 1,
            "oracle_dense_exponentials": 2,
            "canonical_decode_calls": 2,
            "canonical_encode_calls": 2,
            "torch_calls": 0,
            "optimizer_steps": 0,
        },
        "candidate_oracle_bitwise_equal": True,
        "canonical_roundtrip_bytes_equal": True,
        "canonical_roundtrip_coordinate_rows_equal": True,
        "serialized_packet_output_coordinates": 264,
        "capsule_bytes": 600000,
        "historical_negative_and_unknown_preserved": True,
        "full_roster_qualification": False,
        "largegrid_qualification": False,
        "production_adoption": False,
        "all_closed": False,
    }


class ContractControls(unittest.TestCase):
    def test_source_request_is_exact_hold(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        self.assertEqual(contract.validate_request(request), request)

    def test_static_inspection_binds_originals_without_execution(self):
        report = static_inspector.inspect(ROOT, REPOSITORY)
        self.assertEqual(report["status"], "PASS_SOURCE_ONLY_FIRSTSTEP_CONTRACT_HOLD")
        self.assertEqual(report["authentic_firststep_coordinates"], 0)

    def test_future_receipt_exact_shape(self):
        receipt = valid_receipt()
        self.assertEqual(contract.validate_future_receipt(receipt), receipt)
        self.assertTrue(contract.canonical_json(receipt).startswith("{"))

    def test_coordinate_or_packet_loss_rejects(self):
        for field in ("state", "packet", "total", "compared", "equal"):
            with self.subTest(field=field):
                receipt = valid_receipt()
                receipt["coordinate_counts"][field] -= 1
                with self.assertRaisesRegex(contract.ContractError, "denominator"):
                    contract.validate_future_receipt(receipt)
        receipt = valid_receipt()
        receipt["packet_count"] = 8
        with self.assertRaisesRegex(contract.ContractError, "packet denominator"):
            contract.validate_future_receipt(receipt)

    def test_future_exact_call_counts_reject(self):
        fields = {
            "candidate_dynamic_steps": (0, 2),
            "candidate_sparse_exponential_actions": (1, 3),
            "oracle_dynamic_steps": (0, 2),
            "oracle_dense_exponentials": (1, 3),
            "canonical_decode_calls": (1, 3),
            "canonical_encode_calls": (1, 3),
        }
        for field, values in fields.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    receipt = valid_receipt()
                    receipt["calls"][field] = value
                    with self.assertRaisesRegex(contract.ContractError, "exact call count mismatch"):
                        contract.validate_future_receipt(receipt)

    def test_torch_optimizer_and_scope_inflation_reject(self):
        for field in ("torch_calls", "optimizer_steps"):
            with self.subTest(field=field):
                receipt = valid_receipt()
                receipt["calls"][field] = 1
                with self.assertRaisesRegex(contract.ContractError, "Torch or optimizer"):
                    contract.validate_future_receipt(receipt)
        for field in (
            "full_roster_qualification",
            "largegrid_qualification",
            "production_adoption",
            "all_closed",
        ):
            with self.subTest(field=field):
                receipt = valid_receipt()
                receipt[field] = True
                with self.assertRaisesRegex(contract.ContractError, "grants"):
                    contract.validate_future_receipt(receipt)

    def test_exact_comparison_and_roundtrip_reject(self):
        for field in (
            "candidate_oracle_bitwise_equal",
            "canonical_roundtrip_bytes_equal",
            "canonical_roundtrip_coordinate_rows_equal",
        ):
            with self.subTest(field=field):
                receipt = valid_receipt()
                receipt[field] = False
                with self.assertRaises(contract.ContractError):
                    contract.validate_future_receipt(receipt)
        receipt = valid_receipt()
        receipt["serialized_packet_output_coordinates"] = 0
        with self.assertRaisesRegex(contract.ContractError, "omits packet output"):
            contract.validate_future_receipt(receipt)

    def test_source_intent_cannot_self_admit(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        variants = []
        enabled = copy.deepcopy(request)
        enabled["numerical_execution_allowed"] = True
        variants.append(enabled)
        keyed = copy.deepcopy(request)
        keyed["required_future_admission"]["unique_execution_key"] = "not-allowed"
        variants.append(keyed)
        sourced = copy.deepcopy(request)
        sourced["future_sources"]["candidate_step_sha256"] = "a" * 64
        variants.append(sourced)
        for variant in variants:
            with self.assertRaises(contract.ContractError):
                contract.validate_request(variant)


if __name__ == "__main__":
    unittest.main()
