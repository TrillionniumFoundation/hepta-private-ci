"""Synthetic controls for the source-only corrected t=0 contract."""

import copy
import json
import unittest
from pathlib import Path

from qualification.hcsn_currentstate_n256_corrected_t0_contract import contract


ROOT = Path(__file__).parent


def valid_record():
    packet_ids = [f"{index:064x}" for index in range(1, 9)]
    return {
        "schema": "hcsn-n256-corrected-t0-capsule-receipt-v1",
        "identity": contract.IDENTITY,
        "bindings": contract.expected_bindings(),
        "time": "0",
        "lane": "warm",
        "lane_order": 0,
        "semantics": {
            "channels": 5,
            "interior_nodes": 255,
            "phase_packets": 8,
            "phase_schema": ["end", "identity", "mass", "signed_content", "start"],
            "reset": "0.3131468965881033",
            "upper": "permanently_active_nonreturning",
        },
        "blocks": contract.BLOCKS,
        "coordinate_counts": {
            "compared": 2656,
            "equal": 2656,
            "mismatches": 0,
            "packet": 56,
            "state": 2600,
            "total": 2656,
        },
        "packet_ids": packet_ids,
        "counts": contract.expected_future_counts(),
        "canonical_decode_roundtrip_exact": True,
        "independent_comparison_exact": True,
        "capsule_bytes": 23581,
        "capsule_sha256": "a" * 64,
        "historical_negative_and_unknown_preserved": True,
        "cold_load_qualified": False,
        "largegrid_qualification": False,
        "production_adoption": False,
        "all_closed": False,
    }


class ContractControls(unittest.TestCase):
    def test_source_request_is_exact_hold(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        self.assertEqual(contract.validate_source_request(request), request)

    def test_future_record_shape_is_exact(self):
        record = valid_record()
        self.assertEqual(contract.validate_future_capsule_record(record), record)
        self.assertEqual(len(contract.record_sha256(record)), 64)

    def test_historical_capsule_bindings_do_not_transfer(self):
        record = valid_record()
        record["bindings"]["candidate_source_sha256"] = contract.HISTORICAL_CANDIDATE_SHA256
        record["bindings"]["oracle_adapter_sha256"] = contract.HISTORICAL_ORACLE_SHA256
        with self.assertRaisesRegex(contract.ContractError, "binding mismatch"):
            contract.validate_future_capsule_record(record)

    def test_phase_totals_cannot_replace_release_density(self):
        record = valid_record()
        record["bindings"]["phase_original_sha256"] = "b" * 64
        with self.assertRaisesRegex(contract.ContractError, "binding mismatch"):
            contract.validate_future_capsule_record(record)

    def test_legacy_content_alias_rejects(self):
        record = valid_record()
        record["semantics"]["phase_schema"] = ["content", "end", "identity", "mass", "start"]
        with self.assertRaisesRegex(contract.ContractError, "semantics mismatch"):
            contract.validate_future_capsule_record(record)

    def test_wrong_reset_or_returning_upper_rejects(self):
        for field, value in (("reset", "0.32"), ("upper", "returning_tail")):
            with self.subTest(field=field):
                record = valid_record()
                record["semantics"][field] = value
                with self.assertRaisesRegex(contract.ContractError, "semantics mismatch"):
                    contract.validate_future_capsule_record(record)

    def test_non_t0_or_wrong_lane_rejects(self):
        for field, value in (("time", ".001"), ("lane", "cold"), ("lane_order", 1)):
            with self.subTest(field=field):
                record = valid_record()
                record[field] = value
                with self.assertRaisesRegex(contract.ContractError, "warm t=0"):
                    contract.validate_future_capsule_record(record)

    def test_coordinate_denominator_rejects(self):
        for field in ("compared", "equal", "packet", "state", "total"):
            with self.subTest(field=field):
                record = valid_record()
                record["coordinate_counts"][field] -= 1
                with self.assertRaisesRegex(contract.ContractError, "denominator mismatch"):
                    contract.validate_future_capsule_record(record)

    def test_block_shape_and_order_rejects(self):
        wrong_shape = valid_record()
        wrong_shape["blocks"] = copy.deepcopy(contract.BLOCKS)
        wrong_shape["blocks"]["active"] = [5, 2, 254]
        wrong_order = valid_record()
        wrong_order["blocks"] = dict(reversed(list(contract.BLOCKS.items())))
        for record in (wrong_shape, wrong_order):
            with self.assertRaisesRegex(contract.ContractError, "block roster"):
                contract.validate_future_capsule_record(record)

    def test_packet_loss_duplicate_and_order_reject(self):
        variants = []
        missing = valid_record()
        missing["packet_ids"].pop()
        variants.append(missing)
        duplicate = valid_record()
        duplicate["packet_ids"][-1] = duplicate["packet_ids"][0]
        variants.append(duplicate)
        reversed_order = valid_record()
        reversed_order["packet_ids"].reverse()
        variants.append(reversed_order)
        for record in variants:
            with self.assertRaisesRegex(contract.ContractError, "packet"):
                contract.validate_future_capsule_record(record)

    def test_wrong_input_grid_or_roster_rejects(self):
        for field in ("input_bundle_sha256", "roster_identity"):
            with self.subTest(field=field):
                record = valid_record()
                record["bindings"][field] = "c" * 64
                with self.assertRaisesRegex(contract.ContractError, "binding mismatch"):
                    contract.validate_future_capsule_record(record)

    def test_cost_or_scope_inflation_rejects(self):
        record = valid_record()
        record["counts"]["matrix_exponential_actions"] = 1
        with self.assertRaisesRegex(contract.ContractError, "cost mismatch"):
            contract.validate_future_capsule_record(record)
        for flag in ("cold_load_qualified", "largegrid_qualification", "production_adoption", "all_closed"):
            with self.subTest(flag=flag):
                record = valid_record()
                record[flag] = True
                with self.assertRaisesRegex(contract.ContractError, "grants"):
                    contract.validate_future_capsule_record(record)

    def test_capsule_bound_and_digest_reject(self):
        for value in (0, contract.MAX_CAPSULE_BYTES + 1, True):
            with self.subTest(value=value):
                record = valid_record()
                record["capsule_bytes"] = value
                with self.assertRaisesRegex(contract.ContractError, "allocation"):
                    contract.validate_future_capsule_record(record)
        record = valid_record()
        record["capsule_sha256"] = "not-a-sha"
        with self.assertRaisesRegex(contract.ContractError, "SHA-256"):
            contract.validate_future_capsule_record(record)


if __name__ == "__main__":
    unittest.main()
