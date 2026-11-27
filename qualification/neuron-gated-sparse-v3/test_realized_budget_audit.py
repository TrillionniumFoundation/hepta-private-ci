#!/usr/bin/env python3
"""Self-contained, actual-byte safetensors tests; all evidence synthetic only."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from candidate_inventory import expected_geometry, Q
from realized_budget_audit import CAPS, ARMS, SOURCE_SCHEMA, audit


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def physical_safetensors(path: Path, arm: str, width: int, rank: int | None) -> tuple[str,int]:
    geometry=expected_geometry(arm,width,rank)
    header={}
    contents=bytearray()
    count=0
    for name,(dtype,shape) in sorted(geometry.items()):
        count+=__import__('math').prod(shape)
        region=bytearray()
        for _ in range(__import__('math').prod(shape)):
            if dtype=='I64':
                v=Q if name=='structure.projection' else (
                    Q//2 if name in ('temporal.gate_bias','temporal.decay_per_step') else 0)
                region+=struct.pack('<q',v)
            else:
                region+=struct.pack('<f', 0.0625 if name=='head.bias' else 0.0)
        start=len(contents);contents.extend(region)
        header[name]={'dtype':dtype,'shape':list(shape),
                      'data_offsets':[start,len(contents)]}
    raw_head=json.dumps(header,sort_keys=True,separators=(',',':')).encode()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(len(raw_head).to_bytes(8,'little')+raw_head+contents)
    return sha(path),count


def fixture(root: Path, *,width: int=16, profile: str='SYNTHETIC_FIXTURE_ONLY') -> tuple[str,dict]:
    receipt={
        'schema':SOURCE_SCHEMA,'evidence_class':profile,
        'candidate_optimizer_steps':2,'no_change_optimizer_steps':0,
        'production_qualification':False,'ndu_eligible':False,
        'models':[]
    }
    for cap in CAPS:
        rank = None if width < 1 else min(width,max(1,(cap - (4*width+1))//(4*width)))
        for arm in ARMS:
            r=rank if arm=='min_gru' else None
            name=f'{cap}/{arm}.safetensors'
            dig,count=physical_safetensors(root/name,arm,width,r)
            receipt['models'].append({
                'cap':cap,'arm':arm,'width':width,'rank':r,
                'weight_file':name,'weight_sha256':dig,
                'parameter_count':count,'optimizer_steps':2,
            })
    p=root/'training-receipt.json'
    p.write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    return sha(p),receipt


class TestRealizedBudgetAudit(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root=Path(self.dir.name)
        self.rec_sha,self.data=fixture(self.root)

    def save_receipt(self):
        (self.root/'training-receipt.json').write_text(json.dumps(self.data,sort_keys=True)+'\n')
        return sha(self.root/'training-receipt.json')

    def test_synthetic_20_files_only_four_unique_capacity_and_sha(self):
        r=audit(self.root,self.rec_sha,synthetic_fixture_only=True)
        self.assertEqual(r['physical_candidate_artifact_slots'],20)
        self.assertEqual(r['distinct_physical_candidate_contents'],4)
        self.assertEqual(r['effective_min_gru_capacity_tier_count'],1)
        self.assertTrue(all(x['all_five_tiers_same_physical_artifact'] for x in r['per_arm'].values()))
        self.assertFalse(r['all_arms_realized_at_equal_private_parameter_count_per_tier'])
        self.assertFalse(r['five_distinct_effective_min_gru_capacity_tiers'])
        self.assertFalse(r['same_size_head_to_head_quality_claim_admissible'])
        self.assertFalse(r['production_qualification'])
        self.assertFalse(r['ndu_eligible'])

    def test_genuinely_distinct_min_gru_capacity_variation(self):
        with tempfile.TemporaryDirectory() as d:
            rroot=Path(d)
            h,_=fixture(rroot,width=128)
            r=audit(rroot,h,synthetic_fixture_only=True)
            self.assertEqual(r['effective_min_gru_capacity_tier_count'],5)
            self.assertTrue(r['five_distinct_effective_min_gru_capacity_tiers'])
            self.assertEqual(r['distinct_physical_candidate_contents'],8)
            self.assertFalse(r['all_arms_realized_at_equal_private_parameter_count_per_tier'])
            self.assertFalse(r['same_size_head_to_head_quality_claim_admissible'])
            self.assertFalse(r['production_qualification'])

    def test_requires_opt_in_synthetic_evidence(self):
        with self.assertRaisesRegex(ValueError,'signed A0 format'):
            audit(self.root,self.rec_sha,synthetic_fixture_only=False)
        self.data['evidence_class']='SIGNED_A0_FORMAT_ONLY_NOT_HOST_EXECUTION'
        h=self.save_receipt()
        r=audit(self.root,h,synthetic_fixture_only=False)
        self.assertEqual(r['evidence_class'],'SIGNED_A0_FORMAT_NOT_EXECUTION')
        self.assertFalse(r['frozen_selected_v1_host_qualified'])

    def test_physical_sha_tamper_rejected(self):
        with (self.root/'2048'/'v3.safetensors').open('ab') as out:
            out.write(b'foreign bytes')
        with self.assertRaisesRegex(ValueError,'SHA256 mismatch'):
            audit(self.root,self.rec_sha,synthetic_fixture_only=True)

    def test_count_claim_changed_under_new_receipt_hash_rejected(self):
        self.data['models'][0]['parameter_count']+=1
        h=self.save_receipt()
        with self.assertRaisesRegex(ValueError,'physical private parameter count mismatch'):
            audit(self.root,h,synthetic_fixture_only=True)

    def test_missing_duplicate_or_wrong_slot_rejected(self):
        for mutation,needle in [('missing','5x4'),('duplicate','duplicate'),('path','path traversal')]:
            with self.subTest(mutation=mutation):
                original=copy.deepcopy(self.data)
                if mutation=='missing':self.data['models'].pop()
                if mutation=='duplicate':self.data['models'][1]['cap']=2048;self.data['models'][1]['arm']='v2'
                if mutation=='path':self.data['models'][0]['weight_file']='../V1.safetensors'
                h=self.save_receipt()
                with self.assertRaisesRegex(ValueError,needle):
                    audit(self.root,h,synthetic_fixture_only=True)
                self.data=original

    def test_cross_arm_width_drift_rejected(self):
        self.data['models'][0]['width']=32
        h=self.save_receipt()
        with self.assertRaisesRegex(ValueError,'wrong dtype or tensor shape'):
            audit(self.root,h,synthetic_fixture_only=True)

    def test_production_claims_rejected(self):
        for key in ('ndu_eligible','production_qualification'):
            with self.subTest(key=key):
                self.data[key]=True
                h=self.save_receipt()
                with self.assertRaisesRegex(ValueError,'claimed authority'):
                    audit(self.root,h,synthetic_fixture_only=True)
                self.data[key]=False

    def test_different_optim_steps_fails_closed(self):
        self.data['models'][-1]['optimizer_steps']=999
        h=self.save_receipt()
        with self.assertRaisesRegex(ValueError,'different learned model training'):
            audit(self.root,h,synthetic_fixture_only=True)

    def test_manifest_changed_without_sha_update_rejected(self):
        self.data['models'][0]['cap']=262144
        self.save_receipt()  # replace original bytes while keeping old pinned SHA
        with self.assertRaisesRegex(ValueError,'training receipt SHA mismatch'):
            audit(self.root,self.rec_sha,synthetic_fixture_only=True)


    def test_realized_parameter_gate_blocks_duplicate_ceiling_model_claims(self):
        result=audit(self.root,self.rec_sha,synthetic_fixture_only=True)
        self.assertFalse(result['five_tier_exact_realized_parameter_design_valid'])
        self.assertEqual(result['five_tier_design_admission'],'BLOCKED')
        self.assertEqual(result['effective_independent_physical_model_comparisons'],4)
        self.assertEqual(result['effective_independent_capacity_profile_comparisons'],4)
        self.assertEqual(set(result['five_tier_design_blockers']),{
            'DUPLICATED_CAPACITY_ACROSS_NOMINAL_TIERS',
            'IDENTICAL_PHYSICAL_WEIGHTS_IN_MULTIPLE_CEILINGS',
            'CROSS_ARM_REALIZED_PRIVATE_PARAMETERS_NOT_EQUAL',
        })
        for arm in ARMS:
            self.assertEqual(result['per_arm'][arm]['effective_redundant_nominal_ceiling_count'],4)
            self.assertEqual(result['per_arm'][arm]['duplicate_artifact_ceiling_groups'],[list(CAPS)])
        self.assertEqual(result['per_budget_ceiling']['2048']['realized_max_min_parameter_ratio'],
                         round(1089/33,6))

    def test_min_gru_five_shapes_do_not_make_four_arms_equal_sized(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            expected,_=fixture(root,width=128)
            result=audit(root,expected,synthetic_fixture_only=True)
            self.assertEqual(result['per_arm']['min_gru']['distinct_realized_capacity_shapes'],5)
            self.assertFalse(result['five_distinct_effective_capacity_tiers_across_every_arm'])
            self.assertFalse(result['five_tier_exact_realized_parameter_design_valid'])
            self.assertEqual(result['effective_independent_capacity_profile_comparisons'],8)
            self.assertFalse(result['same_size_head_to_head_quality_claim_admissible'])

    def test_cli_hard_gate_emits_audit_then_fails_closed(self):
        import contextlib
        import io
        import sys
        from unittest.mock import patch
        from realized_budget_audit import main
        report=self.root/'strict-audit.json'
        args=['realized_budget_audit.py','--trained-root',str(self.root),
              '--receipt-sha256',self.rec_sha,'--synthetic-canary',
              '--require-five-tier-matched-design','--report',str(report)]
        with patch.object(sys,'argv',args), contextlib.redirect_stderr(io.StringIO()) as err:
            status=main()
        self.assertEqual(status,2)
        self.assertIn('BLOCKED_FIVE_TIER_REALIZED_DESIGN',err.getvalue())
        outcome=json.loads(report.read_text())
        self.assertFalse(outcome['five_tier_exact_realized_parameter_design_valid'])
        self.assertFalse(outcome['ndu_eligible'])
        self.assertEqual(outcome['decision'],'NO_MODEL_PROMOTION')

    def test_optional_compute_claims_are_not_trusted_as_flops(self):
        for row in self.data['models']:
            row.update(cpu_seconds=0.04,wall_seconds=0.06,
                       optimizer_state_bytes_estimate=320,
                       quantization_saturations=0)
        observed=audit(self.root,self.save_receipt(),synthetic_fixture_only=True)
        self.assertEqual(observed['per_arm']['v2']['by_parameter_ceiling'][0][
            'optimizer_state_bytes_estimate_claimed'],320)
        self.assertTrue(observed['per_budget_ceiling']['2048'][
            'shared_training_steps_not_equal_training_flops'])
        self.assertFalse(observed['matched_training_compute_independently_verified'])

    def test_silent_quantization_saturation_and_partial_costs_rejected(self):
        self.data['models'][0]['quantization_saturations']=1
        with self.assertRaisesRegex(ValueError,'silently changed parameters'):
            audit(self.root,self.save_receipt(),synthetic_fixture_only=True)
        self.data['models'][0]['quantization_saturations']=0
        self.data['models'][0]['cpu_seconds']=1.0
        with self.assertRaisesRegex(ValueError,'partial resource/cost telemetry'):
            audit(self.root,self.save_receipt(),synthetic_fixture_only=True)
        self.data['models'][0].update(wall_seconds=-0.1,
                                       optimizer_state_bytes_estimate=10)
        with self.assertRaisesRegex(ValueError,'negative training/optimizer cost'):
            audit(self.root,self.save_receipt(),synthetic_fixture_only=True)


if __name__=='__main__':
    unittest.main()
