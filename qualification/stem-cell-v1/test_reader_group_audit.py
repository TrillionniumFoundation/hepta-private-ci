"""Actual trained Reader panels, fail-closed identities and paired groups."""
import copy
import unittest
from unittest.mock import patch
from conditioned_panel_study import build_panel,train_panel,ARMS
from test_conditioned_panel_study import ToyEncoder,ToyQuery,POLICY
from reader_group_audit import audit_reader_groups
from next_round_matrix import _digest

class ReaderGroupAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tr,cls.ev,cls.labels=build_panel('a'*64,train_groups=2,eval_groups=2)
        cls.obs,_=train_panel(cls.tr,cls.ev,evidence_encoder=ToyEncoder(),
                   query_encoder=ToyQuery(),checkpoint_sha256='a'*64,
                   steps=12,policy=POLICY)
    def audit(self, obs=None, labels=None, **kwargs):
        obs=self.obs if obs is None else obs
        labels=self.labels if labels is None else labels
        return audit_reader_groups(obs, labels,expected_observation_id=self.obs['observation_id'],
                                   expected_labels_sha256=_digest(labels),**kwargs)
    def test_all_controls_same_task_denominator_and_group_ledger(self):
        report=self.audit()
        self.assertEqual(report['common_questions'],16)
        self.assertEqual(set(report['comparisons']),set(ARMS)-{'conditioned'})
        for comparison in report['comparisons'].values():
            for g in comparison['groups']:
                self.assertEqual(g['questions'],8)
                self.assertEqual(sum(g[k] for k in ('conditioned_recovered','conditioned_lost','both_correct','both_wrong')),8)
        self.assertFalse(report['statistical_superiority_established'])
    def test_external_label_changes_recompute_but_never_train(self):
        other={k:1-v for k,v in self.labels.items()}
        with patch('conditional_evidence.fit_reader',side_effect=AssertionError('must not retrain')):
            b=self.audit(labels=other)
        self.assertNotEqual(self.audit()['external_labels_sha256'],b['external_labels_sha256'])
    def test_resealed_row_reorder_rejected(self):
        bad=copy.deepcopy(self.obs)
        bad['predictions']['no_query'].reverse()
        bad['observation_id']=_digest({k:v for k,v in bad.items() if k!='observation_id'})
        with self.assertRaises(ValueError):audit_reader_groups(bad,self.labels,
            expected_observation_id=bad['observation_id'],expected_labels_sha256=_digest(self.labels))
    def test_missing_label_rejected(self):
        bad=dict(self.labels);bad.pop(next(iter(bad)))
        with self.assertRaises(ValueError):self.audit(labels=bad)
    def test_invalid_allowances_not_accepted(self):
        for x in (True,-0.1,1.1,float('nan'),float('inf')):
            with self.subTest(x=x),self.assertRaises(ValueError):self.audit(max_group_accuracy_drop=x)
    def test_repeated_questions_do_not_inflate_independent_groups(self):
        r=self.audit()
        self.assertEqual(r['independent_group_count_not_attested'],2)
        self.assertTrue(r['repeated_question_rows_not_independent_samples'])
    def test_ablation_undetermined_accuracy_remains_null(self):
        self.assertIsNone(self.audit()['original_ablation_sensitivity']['actual_missing_premise_answer_accuracy'])
    def test_wrong_seal_rejected(self):
        with self.assertRaises(ValueError):audit_reader_groups(self.obs,self.labels,
            expected_observation_id='0'*64,expected_labels_sha256=_digest(self.labels))
if __name__=='__main__':unittest.main()
