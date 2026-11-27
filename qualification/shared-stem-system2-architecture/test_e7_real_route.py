"""Source/label/proposal tamper controls using FAKE cases; no real model rerun."""
from __future__ import annotations

from copy import deepcopy
import json
import unittest

from e7_archive import (ARMS, HEADS, REVISIONS, THRESHOLDS,
                        canonical,decode,digest,physical_rows)
from e7_route_seal import seal, routing_prob
from e7_independent_score import score


def mock_reports():
    reports={'granite97':{},'mmbert_small':{}}
    labels={}
    for i in range(128):
        y=i%2
        gr=(.63 if y else .37) if i%3==0 else (.93 if y else .07)
        mm=.83 if y else .17
        if i%16==0:
            gr=.94  # one intentionally incorrect high-confidence base
        if i%8==0:
            mm=.94  # same deliberately bad comparison site
        cid=f'case-{i:03d}'
        group=f'{i+100:064x}'
        input_sha=f'{i+1000:064x}'
        labels[cid]={'case_id':cid,'group_id':group,'joint_input_digest':input_sha,'label':y}
        for model,p in [('granite97',gr),('mmbert_small',mm)]:
            reports[model][cid]={
                'case_id':cid,'group_id':group,'joint_input_digest':input_sha,
                'split':'new_holdout','input_tokens':25,
                'probs':{'frozen_gate':.5,'learned_gate':p,'trained_linear':p},
                'head_ns':{head:250+ i%10 for head in HEADS},
                'encoder_forward_ns':10_000+(100 if model=='mmbert_small' else 0)+i}
    return reports,labels


def full_synthetic_archive():
    """Contract fixture, never accepted as genuine SHA-pinned real ZIP."""
    reports,_=mock_reports()
    data={'current-source.sha':b'c'*40+b'\n'}
    seals=[]
    for model,(revision,pooling) in REVISIONS.items():
        records=list(reports[model].values())
        for i in range(64):
            r=deepcopy(records[i])
            r['case_id']=f'test-{i}-{model}'
            r['split']='test'
            records.append(r)
        raw=canonical({'schema':'hepta.p0.compact.physical-trial.v1','model_id':model,
                       'revision':revision,'pooling':pooling,'authority':'DENY_ALL',
                       'production_accepted':False,'p0_accepted':False,'p1_accepted':False,
                       'model_weights_executed_locally':True,
                       'chronological_future_verified':False,
                       'matched_full_lifecycle_cost':False,
                       'authenticity_independently_verified':False,
                       'actual_encoder_forward_count':352,'q24_feature_dimension':384,
                       'source_sha256':'a'*64,'source_only_future_sha256':'b'*64,
                       'future_predictions':records})
        h=digest(raw)
        seals.append(f'{h}  {model}.report.json')
        data[model+'.report.json']=raw
        data[model+'.stdout.log']=canonical({'report_sha256':h})
    data['pre-score-seals.sha256']=('\n'.join(seals)+'\n').encode()
    return data


class PhysicalRoute(unittest.TestCase):
    def setUp(self):
        self.reports,self.labels=mock_reports()
        self.proposal=seal(self.reports)

    def test_fixed_registered_five_arms_and_absence_of_labels(self):
        self.assertEqual(set(self.proposal['arms']),set(ARMS))
        self.assertEqual(len(self.proposal['cases']),128)
        self.assertTrue(all('label' not in row and 'truth' not in row for row in self.proposal['cases']))
        self.assertIs(self.proposal['source_labels_read_by_proposer'],False)
        self.assertEqual(self.proposal['real_new_model_forwards'],0)
        self.assertIs(self.proposal['production_accepted'],False)

    def test_deep_independent_round_trip_with_fake_sources(self):
        review=score(decode(canonical(self.proposal)),self.labels,self.reports)
        self.assertEqual(review['observed_distinct_original_groups'],128)
        self.assertEqual(review['arms']['granite_only']['n'],128)
        self.assertEqual(review['arms']['mmbert_only']['n'],128)
        self.assertIs(review['actual_future_time_outcomes_scored'],False)
        self.assertIs(review['online_system2_win_established'],False)
        self.assertIs(review['production_accepted'],False)

    def test_base_cost_is_exact_archived_proxy(self):
        review=score(self.proposal,self.labels,self.reports)
        base=sum(x['encoder_forward_ns']+x['head_ns']['learned_gate']
                 for x in self.reports['granite97'].values())
        self.assertEqual(review['arms']['granite_only']['archived_per_case_wall_proxy_ns_sum'],base)
        self.assertEqual(review['arms']['granite_only']['hypothetical_total_model_calls'],128)
        self.assertEqual(review['arms']['mmbert_only']['hypothetical_total_model_calls'],128)
        self.assertEqual(review['arms']['granite_only']['hypothetical_secondary_model_calls'],0)

    def test_routed_second_call_paid_only_if_low_confidence(self):
        review=score(self.proposal,self.labels,self.reports)
        for arm,threshold in THRESHOLDS.items():
            expected=sum(max(x['probs']['learned_gate'],1-x['probs']['learned_gate'])<threshold
                         for x in self.reports['granite97'].values())
            self.assertEqual(review['arms'][arm]['hypothetical_secondary_model_calls'],expected)
            self.assertEqual(review['arms'][arm]['hypothetical_total_model_calls'],128+expected)

    def test_archived_real_report_schema_parser_on_synthetic_structure(self):
        parsed=physical_rows(full_synthetic_archive())
        self.assertEqual(set(parsed),set(self.reports))
        self.assertEqual(set(parsed['granite97']),set(self.reports['granite97']))

    def test_reject_missing_report_or_fake_identity(self):
        for op in ('missing','reported-pretrained-false','unknown-row-field'):
            raw=full_synthetic_archive()
            if op=='missing':
                del raw['mmbert_small.report.json']
            else:
                p=json.loads(raw['granite97.report.json'])
                if op=='reported-pretrained-false':
                    p['model_weights_executed_locally']=False
                else:
                    p['future_predictions'][0]['label']=1
                raw['granite97.report.json']=canonical(p)
                h=digest(raw['granite97.report.json'])
                raw['pre-score-seals.sha256']+=('  '+h).encode()
                raw['granite97.stdout.log']=canonical({'report_sha256':h})
            with self.subTest(op=op),self.assertRaises((ValueError,KeyError)):
                physical_rows(raw)

    def test_label_injection_into_proposal_rejected(self):
        tam=deepcopy(self.proposal)
        tam['cases'][0]['label']=1
        with self.assertRaises(ValueError):
            score(tam,self.labels,self.reports)

    def test_forged_route_on_high_confidence_rejected(self):
        tam=deepcopy(self.proposal)
        row=tam['cases'][1]
        row['routing']['gate_conf_075']['probability']=row['mmbert_prob']
        row['routing']['gate_conf_075']['secondary_used']=True
        with self.assertRaises(ValueError):
            score(tam,self.labels,self.reports)

    def test_scoring_fails_on_changed_original_model_probability(self):
        tam=deepcopy(self.proposal)
        tam['cases'][0]['granite_prob']=.321
        with self.assertRaises(ValueError):
            score(tam,self.labels,self.reports)

    def test_scoring_fails_on_forged_cheaper_meters(self):
        tam=deepcopy(self.proposal)
        tam['cases'][0]['granite_encoder_forward_ns']=1
        with self.assertRaises(ValueError):
            score(tam,self.labels,self.reports)

    def test_missing_or_duplicated_group_fails_closed(self):
        for op in ('missing','dupgroup'):
            tam=deepcopy(self.proposal)
            if op=='missing':
                tam['cases'].pop()
            else:
                tam['cases'][0]['group_id']=tam['cases'][1]['group_id']
            with self.subTest(op=op),self.assertRaises(ValueError):
                score(tam,self.labels,self.reports)

    def test_score_requires_independent_original_truth(self):
        for op in ('wronglabel','missing', 'extra'):
            lab=deepcopy(self.labels)
            if op=='wronglabel':
                lab['case-000']['label']=2
            elif op=='missing':
                lab.pop('case-000')
            else:
                lab['extra']={'label':0,'group_id':'no','joint_input_digest':'no'}
            with self.subTest(op=op),self.assertRaises(ValueError):
                score(self.proposal,lab,self.reports)

    def test_claim_promotion_and_tuned_policy_fails_closed(self):
        for field,new in [('production_accepted',True),('source_labels_read_by_proposer',True),
                          ('actual_matched_online_routing_measured',True),
                          ('policy_thresholds',{'gate_conf_075':.01})]:
            tam=deepcopy(self.proposal)
            tam[field]=new
            with self.subTest(field=field),self.assertRaises(ValueError):
                score(tam,self.labels,self.reports)

    def test_duplicate_json_object_key_and_nan_payload_rejected(self):
        for x in (b'{"a":1,"a":2}',b'{"p":NaN}',b'{"p":Infinity}'):
            with self.subTest(x=x),self.assertRaises(ValueError):
                decode(x)

    def test_threshold_is_strict_and_fixed(self):
        self.assertEqual(routing_prob('gate_conf_075',.75,.10),(.75,False))
        self.assertEqual(routing_prob('gate_conf_075',.74,.10),(.10,True))
        self.assertEqual(routing_prob('granite_only',.74,.10),(.74,False))
        with self.assertRaises(ValueError):
            routing_prob('optimize_threshold_with_labels',.7,.2)


if __name__=='__main__':
    unittest.main()
