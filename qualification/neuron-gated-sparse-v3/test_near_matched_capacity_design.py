"""Research-only, pure-math capacity gate tests; NEVER evidence of trained weights."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import near_matched_capacity_design as design


class ProposedMatchedCapacityTests(unittest.TestCase):
    def test_every_arm_material_tensor_count_exact(self):
        for w in (5, 32, 64, 256):
            for h in (5, 32, 64, 256):
                for arm, extra in [('v2', 0), ('v3', 3*h), ('ssm', 2*h)]:
                    row = design.geometry(w, arm, h)
                    self.assertEqual(row['adapter_trainable_parameters'], (w+1)*h)
                    self.assertEqual(row['head_trainable_parameters'], h+1)
                    self.assertEqual(row['fixed_native_q24_identity_projection_parameters'], h)
                    self.assertEqual(row['temporal_trainable_parameters'], extra)
                    self.assertEqual(row['complete_proposed_private_parameters'],
                                     (w+3)*h+1+extra)
                    self.assertEqual(sum(__import__('math').prod(dims)
                                         for dims in row['unmaterialized_tensor_shapes'].values()),
                                     row['complete_proposed_private_parameters'])
                for rank in (1, 4):
                    row = design.geometry(w, 'min_gru', h, rank)
                    self.assertEqual(row['temporal_trainable_parameters'],
                                     4*rank*h+2*h)
                    self.assertEqual(row['complete_proposed_private_parameters'],
                                     (w+5+4*rank)*h+1)

    def test_proposed_two_low_tiers_feasible_with_realized_geometry(self):
        result = design.audit(feature_width=32)
        self.assertEqual(result['proposed_near_match_ceiling_values'], [2048,8192])
        self.assertEqual(result['blocked_ceiling_values'], [16384,65536,262144])
        self.assertEqual(result['maximum_allowed_unfilled_budget_ppm'], 20000)
        for tier in result['tiers'][:2]:
            self.assertTrue(tier['every_arm_within_declared_gap'])
            self.assertEqual(set(tier['candidate_geometries']), set(design.ARMS))
            for arm, row in tier['candidate_geometries'].items():
                self.assertLessEqual(row['complete_proposed_private_parameters'],
                                     tier['nominal_ceiling'])
                self.assertLessEqual((tier['nominal_ceiling']-
                                      row['complete_proposed_private_parameters'])*1000000,
                                     20000*tier['nominal_ceiling'])
                self.assertEqual(row['shared_frozen_feature_width'], 32)
                self.assertFalse(tier['actual_physical_weights_created'])
                self.assertFalse(tier['native_q24_adapter_supported'])

    def test_32d_known_two_tier_shapes(self):
        r=design.audit(feature_width=32)
        actual = {}
        for tier in r['tiers'][:2]:
            actual[tier['nominal_ceiling']]={
                arm:(row['private_temporal_width'],row['min_gru_rank'],
                     row['complete_proposed_private_parameters'])
                for arm,row in tier['candidate_geometries'].items()}
        self.assertEqual(actual, {
            2048: {'v2':(58,None,2031),'v3':(53,None,2015),
                   'ssm':(55,None,2036),'min_gru':(45,2,2026)},
            8192: {'v2':(234,None,8191),'v3':(215,None,8171),
                   'ssm':(221,None,8178),'min_gru':(182,2,8191)},
        })

    def test_high_tiers_cannot_be_faked_by_nominal_ceilings(self):
        result=design.audit(feature_width=32)
        for tier in result['tiers'][2:]:
            self.assertFalse(tier['every_arm_within_declared_gap'])
            self.assertEqual(tier['result'], 'BLOCKED_REALIZED_GEOMETRY')
            self.assertLessEqual(tier['candidate_geometries']['v2'][
                'complete_proposed_private_parameters'],8961)
        self.assertFalse(result['fake_capacity_padding_permitted'])
        self.assertEqual(result['authority'], 'DENY_ALL')
        self.assertFalse(result['production_qualification'])
        self.assertFalse(result['ndu_eligible'])

    def test_none_or_mismatched_rank_rejected(self):
        for value in (0, -1, 33, True, None, 4.0, '4'):
            with self.subTest(value=value), self.assertRaises(design.Invalid):
                design.geometry(32,'min_gru',32,value)
        with self.assertRaises(design.Invalid):
            design.geometry(32,'v3',32,1)
        with self.assertRaises(design.Invalid):
            design.geometry(32,'CfC',32)

    def test_invalid_width_and_loose_budget_tolerance_rejected(self):
        for feature in (0, 4, -1, 257, True, None, 32.0, '32'):
            with self.subTest(feature=feature), self.assertRaises(design.Invalid):
                design.audit(feature_width=feature)
        for gap in (20_001, 1_000_000, -1, True, 20000.0):
            with self.subTest(gap=gap), self.assertRaises(design.Invalid):
                design.audit(feature_width=32, max_gap_ppm=gap)
        for rank in (0, 17, True, '4'):
            with self.subTest(rank=rank), self.assertRaises(design.Invalid):
                design.audit(feature_width=32, max_rank=rank)

    def test_duplicate_out_of_order_foreign_caps_rejected(self):
        for caps in ((2048,2048),(8192,2048),(), [2048,8192],
                     (2048,16383),(True,), (262145,), (2048.0,)):
            with self.subTest(caps=caps), self.assertRaises(design.Invalid):
                design.audit(feature_width=32,caps=caps)

    def test_strict_zero_gap_prevents_any_near_match_claim(self):
        data=design.audit(feature_width=32,max_gap_ppm=0)
        self.assertEqual(data['proposed_near_match_ceiling_values'],[])
        self.assertEqual(data['blocked_ceiling_values'],list(design.CAPS))

    def test_no_model_result_or_authority_sneaks_into_digest(self):
        a=design.audit(feature_width=32)
        b=design.audit(feature_width=32)
        self.assertEqual(a,b)
        payload={k:v for k,v in a.items() if k!='planning_payload_sha256'}
        canonical=json.dumps(payload,separators=(',',':'),sort_keys=True,
                             allow_nan=False).encode()
        self.assertEqual(a['planning_payload_sha256'],hashlib.sha256(canonical).hexdigest())
        self.assertFalse(a['physical_weight_shas_observed'])
        self.assertFalse(a['future_window_utility_verified'])
        self.assertFalse(a['original_fixed_width_training_profile_reusable_without_change'])
        self.assertEqual(a['decision'],'NO_MODEL_PROMOTION')

    def test_cli_create_once_refuses_overwriting_earlier_study(self):
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp)/'planned.json'
            command=[sys.executable,str(Path(design.__file__)),
                     '--feature-width','32','--output',str(dest)]
            first=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(first.returncode,0,first.stderr)
            j=json.loads(dest.read_text())
            self.assertEqual(j['compatible_proposed_ceiling_count'],2)
            self.assertFalse(j['real_shared_encoder_or_worker_invoked'])
            before=dest.read_bytes()
            second=subprocess.run(command,capture_output=True,text=True)
            self.assertNotEqual(second.returncode,0)
            self.assertIn('BLOCKED_NEAR_MATCHED_CAPACITY',second.stderr)
            self.assertEqual(before,dest.read_bytes())

    def test_cli_rejects_loose_2_1percent_and_nondigits(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'x.json'
            cmd=[sys.executable,str(Path(design.__file__)),
                 '--feature-width','32','--max-gap-ppm','21000','--output',str(path)]
            bad=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(bad.returncode,2)
            self.assertFalse(path.exists())


if __name__=='__main__':
    unittest.main()
