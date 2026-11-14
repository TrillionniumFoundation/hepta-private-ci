"""V18 source-only and adversarial fixtures. No original Reader calls."""
import copy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

import v15_system2_split_shadow as v15
from test_v16_reader_system2_bridge import fixture, h
from v18_grounded_utility import (SCHEMA, source_first_seal, review_grounded, load_json)


def source_roster(parts):
    v14_plan,_,_,study=parts[:4]
    cases=[]
    for c in study['cases']:
        cid=c['id']
        original=next(x for x in v14_plan['cases'] if x['id']==cid)
        sources={name:h('source-bytes:'+cid+':'+name) for name in
                 original['arms']['sufficient']['evidence_ids']}
        cases.append({'case_id':cid,'sources':sources,'nodes':[
           {'node_id':node['id'], 'request_sha256':node['request_sha256'],
            'delivered_evidence_ids':list(sources)} for node in c['nodes']]})
    return {'schema':SCHEMA+'.source-roster','source_only':True,
            'frozen_before_predictions':True,'production_authorized':False,
            'v14_plan_sha256':v15.sha_obj(v14_plan),
            'v15_study_sha256':v15.sha_obj(study),'cases':cases}


def observed_citations(parts,roster,seal):
    records=[]
    roots={c['case_id']:c for c in roster['cases']}
    original={r['case_id']:r for r in parts[1]['records']
              if r['reader']=='candidate' and r['arm']=='sufficient'}
    for r in parts[5]['records']:
        cid,arm=r['case_id'],r['arm']
        sources=list(roots[cid]['sources'])
        citations=(original[cid]['cited_evidence_ids'] if arm=='stop'
                   else sources[:1])
        records.append({'case_id':cid,'arm':arm,
            'terminal_request_sha256':r['terminal_request_sha256'],
            'answer_sha256':r['answer_sha256'],
            'cited_evidence_ids':citations,'abstained':False})
    return {'schema':SCHEMA+'.citation-inventory',
            'v18_prelabel_sha256':v15.sha_obj(seal),
            'v15_execution_sha256':v15.sha_obj(parts[5]),
            'model_output_source':'external_original_required',
            'sealed_before_adjudication':True,
            'reviewer_independence_unverified':True,
            'production_authorized':False,'records':records}


def sample():
    parts=fixture()
    roster=source_roster(parts)
    seal=source_first_seal(parts[0],parts[3],roster)
    citation=observed_citations(parts,roster,seal)
    return parts,roster,seal,citation


def report(s):
    parts,roster,seal,citation=s
    return review_grounded(*parts[:7],parts[7],roster,seal,citation)


class V18GroundedTests(unittest.TestCase):
    def setUp(self):self.s=sample()

    def bad(self,change):
        v=copy.deepcopy(self.s)
        change(v)
        with self.assertRaises(ValueError):report(v)

    def test_original_raw_ndu_win_has_zero_grounded_win(self):
        r=report(self.s)
        self.assertEqual(r['decision'],'HOLD_NO_GO')
        self.assertEqual(r['per_arm_descriptive']['ndu_shadow']['raw_correct'],1)
        self.assertEqual(r['per_arm_descriptive']['ndu_shadow']['grounded_correct'],0)
        self.assertEqual(r['per_arm_descriptive']['ndu_shadow']['unsupported_raw_correct'],1)
        self.assertEqual(r['grounded_system2_vs_baselines_descriptive']['stop']
                         ['grounded_correct_delta'],0)
        self.assertEqual(r['v14_grounded_reader_count'],0)
        for f in ('source_authority_authenticated','independent_citation_evaluator_authenticated',
                  'model_host_authentication_verified','system2_activation_authorized',
                  'real_world_expected_utility_qualified','production_authorized'):
            self.assertFalse(r[f])

    def test_original_source_bound_claimed_grounded_gain_still_no_go(self):
        study=self.s[0]
        for r in study[6]['results']:
            if (r['case_id'],r['arm'])==('q1','ndu_shadow'):
                r['citations_entailed']=True
        r=report(self.s)
        self.assertEqual(r['per_arm_descriptive']['ndu_shadow']['grounded_correct'],1)
        self.assertGreater(r['grounded_system2_vs_baselines_descriptive']['stop']
                           ['grounded_correct_delta'],0)
        self.assertFalse(r['independent_citation_evaluator_authenticated'])

    def test_source_roster_identity(self):
        self.assertEqual(self.s[2],source_first_seal(self.s[0][0],self.s[0][3],self.s[1]))
        self.assertFalse(self.s[2]['source_identity_authenticated'])

    def test_reject_missing_source_case(self):
        self.bad(lambda v:v[1]['cases'].pop())

    def test_reject_duplicate_case_roster(self):
        self.bad(lambda v:v[1]['cases'][1].update(case_id='q1'))

    def test_reject_source_snapshot_change(self):
        self.bad(lambda v:v[1]['cases'][0]['sources'].update({'sufficient-q1':h('changed')}))

    def test_reject_foreign_source(self):
        self.bad(lambda v:v[3]['records'][0].update(cited_evidence_ids=['foreign']))

    def test_reject_foreign_evidence_node(self):
        self.bad(lambda v:v[1]['cases'][0]['nodes'][0].update(delivered_evidence_ids=['invalid']))

    def test_reject_missing_root_evidence(self):
        self.bad(lambda v:v[1]['cases'][0]['nodes'][0].update(delivered_evidence_ids=[]))

    def test_reject_duplicate_catalog_citations(self):
        self.bad(lambda v:v[3]['records'][0].update(cited_evidence_ids=['sufficient-q1']*2))

    def test_reject_wrong_terminal_answer(self):
        self.bad(lambda v:v[3]['records'][0].update(answer_sha256=h('forged')))

    def test_reject_wrong_terminal_request(self):
        self.bad(lambda v:v[3]['records'][0].update(terminal_request_sha256=h('forged')))

    def test_reject_unanchored_reference_to_original_reader(self):
        self.bad(lambda v:v[3]['records'][0].update(cited_evidence_ids=['critical-q1']))

    def test_reject_abstention_mismatch_to_v14(self):
        self.bad(lambda v:v[3]['records'][0].update(abstained=True))

    def test_reject_unanchored_V15_entailment_without_evidence(self):
        self.s[0][6]['results'][0]['citations_entailed']=True
        self.bad(lambda v:next(r for r in v[3]['records']
                if (r['case_id'],r['arm'])==('q1','stop')).update(cited_evidence_ids=[]))

    def test_reject_tampered_prelabel_digest(self):
        self.bad(lambda v:v[2].update(v18_source_roster_sha256=h('other')))

    def test_reject_tampered_external_execution_digest(self):
        self.bad(lambda v:v[3].update(v15_execution_sha256=h('other')))

    def test_reject_fake_reviewer_verified(self):
        self.bad(lambda v:v[3].update(reviewer_independence_unverified=False))

    def test_reject_external_source_not_frozen(self):
        self.bad(lambda v:v[1].update(frozen_before_predictions=False))

    def test_reject_false_production_authority(self):
        self.bad(lambda v:v[3].update(production_authorized=True))

    def test_reject_duplicate_json_property(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'duplicate.json';p.write_text('{"x":1,"x":2}')
            with self.assertRaises(ValueError):load_json(p)

    def test_reject_nonfinite_json(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'nan.json';p.write_text('{"num":NaN}')
            with self.assertRaises(ValueError):load_json(p)

    def test_order_invariance(self):
        a=report(self.s)
        copy=__import__('copy').deepcopy(self.s)
        copy[3]['records'].reverse()
        b=report(copy)
        self.assertEqual(a['per_arm_descriptive'],b['per_arm_descriptive'])
        self.assertEqual(a['grounded_system2_vs_baselines_descriptive'],
                         b['grounded_system2_vs_baselines_descriptive'])
        self.assertNotEqual(a['citation_inventory_sha256'],b['citation_inventory_sha256'])

    def test_claimed_family_not_independence(self):
        r=report(self.s)
        self.assertEqual(r['grounded_system2_vs_baselines_descriptive']['stop']
                         ['claimed_source_families_not_authenticated'],2)


if __name__=='__main__':unittest.main()
