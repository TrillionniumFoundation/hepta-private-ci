"""Synthetic 4-scale source-group pairing and forgery tests; no real teacher/labels."""
import copy
import json
import unittest
from pathlib import Path
import tempfile
import p5_cluster_replay as c


def fixtures():
    rows=[]; groups=[]
    correct_levels=[[4,3,2,2],[4,4,2,2],[4,4,3,2],[4,4,3,2]]
    for i,scale in enumerate((64,256,1024,4096)):
        tid=f'trial-{scale}'
        rows.append({
            'trial_id':tid,'arm':'shared_sparse','seed':41,
            'source_sha256':'a'*64,'held_label_sha256':'b'*64,
            'evaluator_sha256':'c'*64,'stem_sha256':'d'*64,
            'logical_cells':scale,'active_cells':8,'reasoning_depth':2,
            'train_rows':128,'compute_budget_ns':1000000,
            'correct':sum(correct_levels[i]),'total':16,
            'training_cpu_ns':2000+scale,'inference_cpu_ns':1000+scale,
            'encoder_forwards':16,'peak_rss_bytes':1000000+scale,
            'independent_source_groups':4,'physical_work_observed':True,
            'independent_score_receipt':True,
        })
        for j in range(4):
            groups.append({'trial_id':tid,'source_group_id':f'group-{j}',
                           'source_group_sha256':str(j+1)*64,
                           'correct':correct_levels[i][j],
                           'total':4,'label_owner_scored':True})
    source={'schema':'hepta.stem-cell-one-axis-scale.v1','authority_posture':'DENY_ALL',
            'production_accepted':False,'teacher_equivalence_certified':False,
            'rows':rows}
    raw=(json.dumps(source,sort_keys=True,separators=(',',':'))+'\n').encode()
    groupdoc={'schema':c.SCHEMA,'source_manifest_sha256':c.sha(raw),
              'authority_posture':'DENY_ALL',
              'model_or_teacher_equivalence_certified':False,
              'production_accepted':False,'rows':groups}
    return source,raw,groupdoc


class TestP5ClusterReplay(unittest.TestCase):
    def setUp(self):
        self.source,self.raw,self.group=fixtures()

    def test_all_four_scales_match_exact_source_groups(self):
        x=c.replay(self.source,self.raw,self.group)
        self.assertEqual(x['registered_complete_sweeps'],1)
        self.assertEqual(x['original_trials_accounted'],4)
        r=x['paired_sweep_reviews'][0]
        self.assertEqual(r['scale_levels'],[64,256,1024,4096])
        self.assertEqual(r['paired_group_correct_deltas'],[0,0,0,0])
        self.assertEqual(r['exact_group_signflip_p_descriptive_only'],1)
        self.assertIs(r['statistical_gain_claim_admitted'],False)
        self.assertIs(x['teacher_or_10t_100t_equivalence_established'],False)

    def test_true_source_level_sign_flip_is_descriptive(self):
        self.assertEqual(c.exact_signflip([1,1,1,1]),.125)
        self.assertEqual(c.exact_signflip([0,0,0,0]),1.)
        self.assertIsNone(c.exact_signflip([1]))
        self.assertIsNone(c.exact_signflip([1]*13))

    def test_missing_source_group_cannot_be_imputed(self):
        side=copy.deepcopy(self.group);side['rows'].pop()
        with self.assertRaises(c.ClusterDenied):c.replay(self.source,self.raw,side)

    def test_duplicate_group_in_same_trial_is_denied(self):
        side=copy.deepcopy(self.group);side['rows'].append(copy.deepcopy(side['rows'][0]))
        with self.assertRaises(c.ClusterDenied):c.replay(self.source,self.raw,side)

    def test_reallocated_group_scores_are_not_independent_issuer_attestation(self):
        side=copy.deepcopy(self.group)
        side['rows'][0]['correct']-=1;side['rows'][1]['correct']+=1
        # Same aggregate correct but moved between groups; arithmetic alone
        # cannot authenticate publisher truth. Pairing remains descriptive.
        x=c.replay(self.source,self.raw,side)
        self.assertFalse(x['outcome_receipts_independently_authenticated'])
        side['rows'][0]['correct']-=1
        with self.assertRaises(c.ClusterDenied):c.replay(self.source,self.raw,side)

    def test_changed_original_group_identity_between_scales_denied(self):
        for field,value in [('source_group_id','tampered-group'),
                            ('source_group_sha256','e'*64),('total',5)]:
            side=copy.deepcopy(self.group);side['rows'][7][field]=value
            with self.subTest(field=field),self.assertRaises(c.ClusterDenied):
                c.replay(self.source,self.raw,side)

    def test_wrong_source_manifest_or_false_authority_denied(self):
        for key,val in [('source_manifest_sha256','f'*64),('production_accepted',True),
                        ('authority_posture','ALLOW'),('model_or_teacher_equivalence_certified',True)]:
            side=copy.deepcopy(self.group);side[key]=val
            with self.subTest(key=key),self.assertRaises(c.ClusterDenied):
                c.replay(self.source,self.raw,side)

    def test_changed_label_issuer_or_missing_field_denied(self):
        for key,val in [('label_owner_scored',False),('correct',True),
                        ('source_group_sha256','invalid'),('trial_id','unregistered')]:
            side=copy.deepcopy(self.group);side['rows'][0][key]=val
            with self.subTest(key=key),self.assertRaises(c.ClusterDenied):
                c.replay(self.source,self.raw,side)
        side=copy.deepcopy(self.group);del side['rows'][0]['source_group_id']
        with self.assertRaises(c.ClusterDenied):c.replay(self.source,self.raw,side)

    def test_source_only_row_does_not_count_as_new_future_group(self):
        x=c.replay(self.source,self.raw,self.group)
        for flag in ('outcome_receipts_independently_authenticated',
                     'independent_cluster_sampling_established',
                     'new_real_pretrained_forward_executed',
                     'teacher_or_10t_100t_equivalence_established','production_accepted'):
            self.assertFalse(x[flag])

    def test_strict_json_duplicate_nonfinite_and_write_once(self):
        for raw in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":Infinity}'):
            with self.assertRaises(c.ClusterDenied):c.parse(raw)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'report.json'
            report=c.replay(self.source,self.raw,self.group)
            digest=c.emit_once(path,report)
            self.assertEqual(digest,c.sha(path.read_bytes()))
            with self.assertRaises(FileExistsError):c.emit_once(path,report)


if __name__ == '__main__':
    unittest.main()
