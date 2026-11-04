"""Synthetic mutation regressions for read-only hosted Q24 evidence audit."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from audit_native_q24_artifact import AUDIT_SCHEMA, AuditBlocked, JSON_NAME, audit

SOURCE = Path(__file__).resolve().parent / 'hepta-neuron-20-native-q24-20261015.zip'
SOURCE_SHA = '9c871918e306f6f0fa0c6f3864bd75ff9271df3829ce8b58108618fc99e93995'


class PhysicalResearchAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = json.loads(zipfile.ZipFile(SOURCE).read(JSON_NAME))

    def verify_changed(self, mutate, message: str):
        with tempfile.TemporaryDirectory() as d:
            document = copy.deepcopy(self.original)
            mutate(document)
            path = Path(d) / 'new.zip'
            with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(JSON_NAME, json.dumps(document, allow_nan=False))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(AuditBlocked, message):
                audit(path, digest)

    def test_original_archived_bytes_structurally_verified_no_promotion(self):
        report = audit(SOURCE, SOURCE_SHA)
        self.assertEqual(report['schema'], AUDIT_SCHEMA)
        self.assertEqual(report['observed_arm_budget_slots'], 20)
        self.assertEqual(report['observed_fresh_native_processes'], 40)
        self.assertEqual(report['distinct_physical_model_weight_digests'], 5)
        self.assertEqual(report['distinct_model_weight_digests_per_arm'],
                         {'v2': 1, 'v3': 1, 'ssm': 1, 'min_gru': 2})
        self.assertFalse(report['production_qualification'])
        self.assertFalse(report['model_winner_selected'])

    def test_zip_byte_tampering_fails_independent_source_pin(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'changed.zip'
            path.write_bytes(SOURCE.read_bytes() + b'\0')
            with self.assertRaisesRegex(AuditBlocked, 'ZIP bytes mismatch'):
                audit(path, SOURCE_SHA)

    def test_duplicate_physical_arm_tier_fails(self):
        self.verify_changed(lambda d: d['results'][1].update(
            arm=d['results'][0]['arm']), 'duplicate arm-tier')

    def test_missing_model_row_fails(self):
        self.verify_changed(lambda d: d['results'].pop(), 'model slots')

    def test_forged_twenty_distinct_model_claim_fails(self):
        self.verify_changed(lambda d: d['realized_budget_audit'].update(
            effective_independent_physical_model_comparisons=20), 'unique-model counts')

    def test_forged_matched_tier_admission_fails(self):
        self.verify_changed(lambda d: d['realized_budget_audit'].update(
            five_tier_exact_realized_parameter_design_valid=True), 'matched-budget')

    def test_unsupported_production_promotion_fails(self):
        self.verify_changed(lambda d: d.update(production_qualification=True), 'unsupported qualification')

    def test_forged_a0_attestation_fails(self):
        self.verify_changed(lambda d: d['frozen_a0_owner_revalidation'].update(
            a0_rechecked=True), 'false production A0')

    def test_forged_float_native_parity_fails(self):
        self.verify_changed(lambda d: d['results'][1]['float_surrogate_vs_native_q24_state_gap'].update(
            bitwise_float_to_q24_prediction_parity_proven=True), 'false floating parity')

    def test_fake_native_oracle_fails(self):
        self.verify_changed(lambda d: d['results'][2]['q24_head_integer_oracle'].update(
            all_native_head_logits_match_independent_integer_oracle=False), 'Head oracle')

    def test_missing_second_native_os_process_fails(self):
        self.verify_changed(lambda d: d['results'][3].update(fresh_process_count=1), 'double-execution')

    def test_positive_outcome_from_unrejected_negative_control_fails(self):
        self.verify_changed(lambda d: d['native_negative_cases'][0].update(
            rejected_by_native_rust=False), 'negative case not rejected')

    def test_nonfinite_gap_value_fails(self):
        self.verify_changed(lambda d: d['results'][4]['float_surrogate_vs_native_q24_state_gap'].update(
            max_probability_gap_ppm=-1), 'unbounded or nonnumeric')

    def test_total_q24_process_wall_is_not_promoted_as_device_latency(self):
        report = audit(SOURCE, SOURCE_SHA)
        self.assertIn('not_runtime_slo',
                      'observed_process_wall_micros_range_by_arm_not_runtime_slo')
        self.assertFalse(report['real_task_outcome_quality_verified'])


if __name__ == '__main__':
    unittest.main()
