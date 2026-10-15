"""Tests against four REAL pinned successful 2026-10-15 GitHub Actions ZIPs.

No synthetic fallbacks. These are original retrospective predictions/scores,
not a new pretrained model forward or a new prospective effect evaluation.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import archived_e14_independent as audit

IDS = ('blind_source','blind_merge','score_source','score_merge')


def originals():
    d={k:os.environ.get('HEPTA_E14_'+k.upper()) for k in IDS}
    if not all(d.values()):
        raise ValueError('All four original E14 zipped artifacts MUST be given; no synthetic fallback')
    return {k:Path(p) for k,p in d.items()}


class ActualOriginalE14FourArchiveAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources=originals()
        cls.observed=audit.independent_review(cls.sources)

    def test_actual_original_two_profile_negative_result(self):
        x=self.observed
        self.assertEqual((x['cheap_original_human_correct'],x['full_original_human_correct']),(15,15))
        self.assertGreater(x['full_original_human_brier'],x['cheap_original_human_brier'])
        self.assertTrue(x['numeric_substage_descriptively_dominated_on_this_panel'])
        self.assertEqual(x['independent_human_passage_groups'],4)
        self.assertEqual(x['actual_human_answer_candidates'],33)

    def test_original_cpu_sums_recomputed_from_every_case(self):
        xs=self.observed['two_original_source_profiles']
        self.assertEqual(len(xs),2)
        self.assertEqual([(r['cheap_numeric_cpu_ns'],r['full_e12_numeric_cpu_ns']) for r in xs],
                         [(11006064,71045175),(7848257,51814496)])
        for row in xs:
            self.assertGreater(row['observed_full_to_cheap_numeric_cpu_ratio'],6.0)
            self.assertEqual(sum(g['answer_candidates'] for g in row['four_correlated_source_groups']),33)
            self.assertEqual(len(row['four_correlated_source_groups']),4)

    def test_original_no_model_forward_or_signer_claim(self):
        x=self.observed
        for k in ('full_serving_latency_or_energy_matched','online_NDU_controller_activated',
                  'general_FBSDE_inferiority_proven','model_or_NDU_promotion_permitted',
                  'prospective_original_human_tasks','statistical_superiority_certified'):
            self.assertFalse(x[k])
        self.assertEqual(x['actual_new_pretrained_model_forwards'],0)
        self.assertEqual(x['authority_posture'],'DENY_ALL')

    def test_raw_non_timing_decisions_match_exactly_across_hosts(self):
        a=audit.load(self.sources['blind_source'],'blind_source')
        b=audit.load(self.sources['blind_merge'],'blind_merge')
        self.assertEqual([audit.clean_row(r) for r in a['rows']],
                         [audit.clean_row(r) for r in b['rows']])
        self.assertEqual(sum(r['policy_arms']['cheap_one_map'] !=
                             r['policy_arms']['e12_full_tree'] for r in a['rows']),6)

    def test_exact_four_original_outer_sha_or_wrong_profile_rejected(self):
        for name in IDS:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as d:
                    dest=Path(d)/'tampered.zip'
                    dest.write_bytes(self.sources[name].read_bytes()+b'X')
                    with self.assertRaises(audit.AuditDenied):audit.load(dest,name)
        with self.assertRaises(audit.AuditDenied):
            audit.load(self.sources['blind_source'],'blind_merge')

    def test_incomplete_artifact_set_rejected(self):
        d=dict(self.sources); d.pop('blind_merge')
        with self.assertRaises((KeyError,audit.AuditDenied)):
            audit.independent_review(d)

    def test_untrusted_self_reported_quality_and_cpu_denied(self):
        src=audit.inspect_blind(audit.load(self.sources['blind_source'],'blind_source'))
        report=audit.load(self.sources['score_source'],'score_source')
        forged=copy.deepcopy(report)
        forged['evaluation_arms']['e12_full_tree']['correct']=34
        with self.assertRaises(audit.AuditDenied):audit.check_human_score(forged,src)
        forged=copy.deepcopy(report)
        forged['self_observed_local_python_numerical_cpu_ns']['cheap']=1
        with self.assertRaises(audit.AuditDenied):audit.check_human_score(forged,src)

    def test_false_model_or_authority_denied(self):
        doc=audit.load(self.sources['blind_source'],'blind_source')
        for field,value in (('original_labels_accessed',True),('production_accepted',True),
                            ('new_pretrained_forward_count',1),('actual_live_routing',True)):
            sample=copy.deepcopy(doc);sample[field]=value
            with self.subTest(field=field),self.assertRaises(audit.AuditDenied):
                audit.inspect_blind(sample)

    def test_missing_model_route_or_invalid_rational_bound_denied(self):
        doc=audit.load(self.sources['blind_source'],'blind_source')
        one=copy.deepcopy(doc)
        one['rows'][0]['policy_arms'].pop('e12_full_tree')
        with self.assertRaises(audit.AuditDenied):audit.inspect_blind(one)
        one=copy.deepcopy(doc)
        one['rows'][0]['cert']['mapped_residual']='1000/1'
        with self.assertRaises(audit.AuditDenied):audit.inspect_blind(one)

    def test_full_actual_run_create_once_without_raw_media_upload(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'observed.json'
            result=audit.independent_review(self.sources)
            f.write_bytes((json.dumps(result,sort_keys=True,separators=(',',':'))+'\n').encode())
            self.assertEqual(json.loads(f.read_text()),self.observed)
            self.assertFalse(any('raw_predictions' in k or 'labels' in k for k in result))

if __name__=='__main__': unittest.main()
