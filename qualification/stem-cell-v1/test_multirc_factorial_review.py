"""Frozen, label-free factorial summaries and their owner/stress seals."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from matrix_materials import file_sha256, strict_json
from matrix_runtime import write_json_exclusive
from multirc_factorial_review import (review_factorial, read_exact_factorial,
                                     main, _validate_report)
from multirc_query_factorial import SCHEMA
from next_round_matrix import _digest


FACTORS = ('abs_change_question_only', 'abs_change_answer_only',
           'abs_change_question_and_answer')


def original():
    rows = []
    for group in ('A', 'B'):
        for slot in (0, 1):
            rows.append(dict(source_group=group, question_slot=slot, task_id=f'{group}{slot}',
                positive_probability_original=.51,
                abs_change_question_only=.0001 if group == 'A' else .2,
                abs_change_answer_only=.0002 if group == 'A' else .3,
                abs_change_question_and_answer=.3))
    report = dict(schema=SCHEMA, source_observation_id='a'*64,
        source_panel_id='b'*64, source_snapshot_sha256='c'*64,
        trained_reader_weights_sha256='d'*64, related_blinded_stress_id='e'*64,
        passage_count=2, question_count=4, physical_encoder_calls=2,
        newly_computed_question_embeddings=8, conditioned_reader_calls=8,
        records=rows, insensitive_epsilon=.001,
        mean_absolute_positive_probability_change={
            f:sum(row[f] for row in rows)/len(rows) for f in FACTORS},
        insensitive_question_counts={
            f:sum(row[f]<=.001 for row in rows) for f in FACTORS},
        work_observation=dict(schema='hepta.execution-work-observation.v1',
            unknown_operators={}, stopped=None, phase_flops={'inference':3392}),
        work_separate_from_original_inference=True,
        cross_question_answer_combinations_have_no_valid_labels=True,
        counterfactual_accuracy=None, independent_question_understanding_established=False,
        statistical_superiority_established=False, native_or_production_authorized=False)
    report['factorial_id']=_digest(report)
    return report


def seal_factors(path, report, *, owner_seal, stress_seal):
    path.mkdir()
    write_json_exclusive(path/'factorial.json', report)
    receipt = dict(schema='hepta.multirc.blind-factorial-seal.v1',
        owner_prediction_seal=owner_seal, source_stress_seal=stress_seal,
        factorial_sha256=file_sha256(path/'factorial.json'),
        factorial_id=report['factorial_id'],
        externally_labeled_answers_used=False, weights_uploaded=False,
        production_authorized=False)
    receipt['seal_id']=_digest(receipt)
    write_json_exclusive(path/'COMMITTED.json', receipt)
    return receipt['seal_id']


class FactorialReviewTests(unittest.TestCase):
    def call_review(self, report=None, **kwargs):
        report=original() if report is None else report
        return review_factorial(report, expected_factorial_id=report['factorial_id'], **kwargs)

    def test_realistic_complete_report_grouping_without_counterfactual_accuracy(self):
        summary=self.call_review()
        self.assertEqual(summary['double_insensitive_question_count'],2)
        self.assertEqual((summary['passage_count'],summary['question_count']),(2,4))
        self.assertEqual(summary['separately_metered_inference_formula_work'],3392)
        self.assertIsNone(summary['answer_accuracy'])
        self.assertFalse(summary['question_understanding_established'])
        self.assertFalse(summary['interaction_sign_identifiable_from_absolute_changes'])
        self.assertEqual(summary['review_id'],_digest({k:v for k,v in summary.items() if k!='review_id'}))

    def test_signed_aggregate_tamper_even_with_new_digest_refused(self):
        for field in ('mean_absolute_positive_probability_change','insensitive_question_counts'):
            report=original()
            report[field]['abs_change_question_only'] = .1 if field.startswith('mean') else 0
            report['factorial_id']=_digest({k:v for k,v in report.items() if k!='factorial_id'})
            with self.subTest(field=field), self.assertRaisesRegex(ValueError,'aggregate'):
                self.call_review(report)

    def test_resealed_duplicate_source_slot_or_task_refused(self):
        for kind in ('slot','task','label'):
            report=original()
            if kind=='slot':report['records'][1]['question_slot']=0
            elif kind=='task':report['records'][1]['task_id']=report['records'][0]['task_id']
            else:report['records'][0]['label']=1
            report['factorial_id']=_digest({k:v for k,v in report.items() if k!='factorial_id'})
            with self.subTest(kind=kind), self.assertRaises(ValueError):self.call_review(report)

    def test_incomplete_physical_encoder_and_query_costs_refused(self):
        for field in ('physical_encoder_calls','newly_computed_question_embeddings',
                      'conditioned_reader_calls','passage_count','question_count'):
            report=original()
            report[field] += 1
            report['factorial_id']=_digest({k:v for k,v in report.items() if k!='factorial_id'})
            with self.subTest(field=field),self.assertRaises(ValueError):self.call_review(report)

    def test_unknown_and_failed_accounting_remains_incomplete(self):
        for mode in ('unknown','stopped','missing','fake_zero'):
            report=original()
            work=report['work_observation']
            if mode=='unknown':work['unknown_operators']={'aten.atan.default':1}
            elif mode=='stopped':work['stopped']='coverage_stop'
            elif mode=='missing':work['phase_flops']['inference']=None
            else:work['phase_flops']['inference']=False
            report['factorial_id']=_digest({k:v for k,v in report.items() if k!='factorial_id'})
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.call_review(report)

    def test_no_posthoc_epsilon_selection_even_if_valid(self):
        for val in (True,-.1,.1,.002,float('nan'),float('inf')):
            with self.subTest(epsilon=val),self.assertRaises(ValueError):self.call_review(epsilon=val)
        self.assertEqual(self.call_review(epsilon=.001),self.call_review())

    def test_original_threshold_and_scope_modifications_refused(self):
        for key,value in (('insensitive_epsilon',.005),('source_panel_id','not_sha'),
                          ('counterfactual_accuracy',1.),('statistical_superiority_established',True)):
            report=original()
            report[key]=value
            report['factorial_id']=_digest({k:v for k,v in report.items() if k!='factorial_id'})
            with self.subTest(key=key), self.assertRaises(ValueError):self.call_review(report)

    def test_unsealed_mutation_or_wrong_external_digest_refused(self):
        report=original()
        report['records'][0]['abs_change_answer_only']=.9
        with self.assertRaises(ValueError):
            review_factorial(report,expected_factorial_id=report['factorial_id'])
        with self.assertRaises(ValueError):
            review_factorial(original(),expected_factorial_id='0'*64)


class RealFactorialSealTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_multirc_query_factorial as fixtures
        cls.fixture=fixtures.QuestionAnswerFactorialTests
        cls.fixture.setUpClass()
        cls.report=cls.fixture(cls.fixture._testMethodName if hasattr(cls.fixture,'_testMethodName') else
                               'test_real_two_by_two_question_answer_factorial_replays_old_stress').audit()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.doClassCleanups()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.factorial=self.root/'factorial'
        self.factorial_seal=seal_factors(self.factorial,self.report,
            owner_seal=self.fixture.model_seal['seal_id'],
            stress_seal=self.fixture.stress_seal['seal_id'])

    def args(self, output):
        return ['review','--factorial-dir',str(self.factorial),
                '--expected-factorial-seal-id',self.factorial_seal,
                '--owner-dir',str(self.fixture.run_dir),
                '--expected-owner-seal-id',self.fixture.model_seal['seal_id'],
                '--stress-dir',str(self.fixture.stress_dir),
                '--expected-stress-seal-id',self.fixture.stress_seal['seal_id'],
                '--output',str(output)]

    def check_owner(self, **changes):
        values=dict(folder=self.factorial,expected_factorial_seal_id=self.factorial_seal,
                    owner_dir=self.fixture.run_dir,
                    expected_owner_seal_id=self.fixture.model_seal['seal_id'],
                    stress_dir=self.fixture.stress_dir,
                    expected_stress_seal_id=self.fixture.stress_seal['seal_id'])
        values.update(changes)
        return read_exact_factorial(**values)

    def test_actual_pytorch_trained_bank_and_original_stress_join(self):
        original_result=self.check_owner()
        self.assertEqual(original_result['factorial_id'],self.report['factorial_id'])
        review=review_factorial(original_result,expected_factorial_id=original_result['factorial_id'])
        self.assertEqual(review['question_count'],8)
        self.assertEqual(review['passage_count'],4)
        self.assertIsNone(review['answer_accuracy'])

    def test_real_cli_seals_analysis_without_loading_labels(self):
        dest=self.root/'review'
        with patch.object(sys,'argv',self.args(dest)):
            main()
        self.assertTrue((dest/'COMMITTED.json').exists())
        self.assertFalse((dest/'FAILED.json').exists())
        saved=strict_json(dest/'review.json')
        sealed=strict_json(dest/'COMMITTED.json')
        self.assertEqual(sealed['review_sha256'],file_sha256(dest/'review.json'))
        self.assertEqual(sealed['review_id'],saved['review_id'])
        self.assertFalse(sealed['external_labels_loaded'])
        self.assertNotIn('labels',str(dest/'review.json'))

    def test_original_artifact_bytes_or_external_owner_ref_reject(self):
        self.assertEqual(self.check_owner()['question_count'],8)
        self.factorial.joinpath('factorial.json').write_bytes(
            self.factorial.joinpath('factorial.json').read_bytes()+b' ')
        with self.assertRaises(ValueError):self.check_owner()
        failed=self.root/'failed'
        with patch.object(sys,'argv',self.args(failed)):
            with self.assertRaises(ValueError):main()
        self.assertTrue((failed/'FAILED.json').exists())
        self.assertFalse((failed/'COMMITTED.json').exists())

    def test_external_stress_and_owner_ids_reject_before_analysis(self):
        for param in ('expected_owner_seal_id','expected_stress_seal_id',
                      'expected_factorial_seal_id'):
            with self.subTest(param=param), self.assertRaises(ValueError):
                self.check_owner(**{param:'0'*64})

    def test_predictor_logits_are_not_validated_as_labels(self):
        self.assertIsNone(review_factorial(self.check_owner(),
            expected_factorial_id=self.report['factorial_id'])['answer_accuracy'])


if __name__=='__main__':
    unittest.main()
