"""Synthetic adversarial mechanism tests, not pretrained execution evidence."""
import copy
import hashlib
import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path

from independent_audit import (
    EvidenceError, SOURCE_SHA, MODEL_ID, MODEL_REV, LIMIT_NS,
    closed_form, hash_file, read_evidence, score_failure, score_predictions,
)


def make_case(i):
    return {"case_id": f"test:v2:{i}", "formula": ["or", ["and", 0, 1], ["and", 2, 3]],
            "target_intents": [0, 1, 2, 3], "utterance_ids": [f"test:{i}:{j}" for j in range(4)]}


def test_document():
    probability = .4*.7 + .9*.3 - (.4*.7)*(.9*.3)
    cases = [make_case(i) for i in range(192)]
    hashes = {c['case_id']:hashlib.sha256(c['case_id'].encode()).hexdigest() for c in cases}
    belief = {c['case_id']:{'leaf_probabilities':[.4,.7,.9,.3],
                            'public_input_sha256':hashes[c['case_id']]} for c in cases}
    truth = {c['case_id']:False for c in cases}
    rows = {}
    for name,lat in [('exact_formula',1000),('fbsde_tree',2500)]:
        rows[name] = [{"case_id":c['case_id'],"probability":probability,
                       "public_input_sha256":hashes[c['case_id']],
                       "text":"No, the stated condition is not satisfied.",
                       "cpu_ns":lat,"scenario_nodes":31 if name=='fbsde_tree' else 0,
                       "bsde_interface_residual":0.0 if name=='fbsde_tree' else None}
                      for c in cases]
    brier=probability**2
    return {
        "real-study/public-cases.json": {'test':cases},
        "real-study/belief-inputs.json":belief,
        "real-study/private-test-truths.json":truth,
        "real-study/exact_formula-predictions.json":rows['exact_formula'],
        "real-study/fbsde_tree-predictions.json":rows['fbsde_tree'],
        "real-study/physical-summary.json": {'model':MODEL_ID,'revision':MODEL_REV,'source_sha':SOURCE_SHA,
                                              'real_weights_executed':True,'production_promotion_permitted':False},
        "real-study/design.json":{'question_profile':'independent_targets_v2','real_future_windows':False},
        "real-study/comparison.json":{'equal_compute_superiority_claimed':False,
             'full_lifecycle_resource_gate_passed':False,
             'inference_cpu_ns':{'exact_formula':192000,'fbsde_tree':480000},
             'metrics':{name:{'count':192,'decoded_exact_accuracy':1.0,'binary_brier':brier} for name in rows}},
    }


def failure_document():
    ids=['a'*64,'b'*64]
    def attempt(i):
        over=i==1
        return {'id':f'val:{i}', 'arm':'ndu_bsde', 'view':i, 'head_sha256':'a'*64,
          'attempt_sha256':ids[i], 'previous_sha256':ids[i-1] if i else None,
          'cpu_ns':LIMIT_NS+1 if over else 50000000,'limit_ns':LIMIT_NS,
          'phase_cpu_ns':{'encoder_cpu_ns':LIMIT_NS+1 if over else 50000000,
                          'head_cpu_ns':0,'receipt_cpu_ns':0,'text_cpu_ns':0},
          'prediction_returned':not over,'status':'budget_exceeded' if over else 'returned'}
    a=[attempt(0),attempt(1)]
    return {'acquisition-study/plan.json':{'backend':'mmbert','cohort':'banking_v1','prediction_cpu_limit_ns':LIMIT_NS},
            'acquisition-study/failure.json':{'schema':'hepta.acquisition.failure.v1','error_type':'ViewBudgetExceeded',
               'budget_relaxed':False,'run_complete':False,'scientific_pass':False,
               'split':'validation','last_attempt_sha256':ids[-1],'attempts_in_split':2},
            'cpu-tail-replay/original-clock-audit.json':{'budget':{'budget_unchanged_ns':LIMIT_NS,
                'failures':[copy.deepcopy(a[-1])|{'dominant_measured_phase':'encoder_cpu_ns'}],
                'journals':{'validation':{'attempts':2,'last_attempt_sha256':ids[-1]}}}},
            'acquisition-study/validation-view-attempts.jsonl': '\n'.join(json.dumps(x) for x in a)+'\n'}


def pack(path, members):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for key,val in members.items():
            content = val if isinstance(val,str) else json.dumps(val,allow_nan=False)
            z.writestr(key,content)


class FormulaTests(unittest.TestCase):
    def test_probability(self):
        s=set()
        self.assertAlmostEqual(closed_form(['or',['and',0,1],['and',2,3]],[.4,.7,.9,.3],s),.4744)
        self.assertEqual(s,{0,1,2,3})
    def test_repeated_leaf_forbidden(self):
        with self.assertRaises(EvidenceError):
            closed_form(['and',0,0],[.4],set())
    def test_unknown_gate_forbidden(self):
        with self.assertRaises(EvidenceError):
            closed_form(['xor',0,1],[.4,.5],set())


class RealRawStructureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'test.zip'
        self.doc=test_document()

    def score(self):
        pack(self.path,self.doc)
        with zipfile.ZipFile(self.path) as z:
            return score_predictions(z,'independent_targets_v2')

    def reject(self, change):
        change(self.doc)
        with self.assertRaises(EvidenceError): self.score()

    def test_complete_fixture_no_authority(self):
        data=self.score()
        self.assertEqual(data['exact_formula']['correct'],192)
        self.assertEqual(data['finite_tree_bsde']['correct'],192)
        self.assertEqual(data['incremental_bsde_task_success_gain'],0)
        self.assertGreater(data['incremental_bsde_cpu_ns'],0)
        self.assertFalse(data['production_accepted'])
    def test_altered_bsde_probability(self):
        self.reject(lambda x:x['real-study/fbsde_tree-predictions.json'][3].update(probability=.8))
    def test_altered_class_label(self):
        self.reject(lambda x:x['real-study/fbsde_tree-predictions.json'][0].update(text='Yes, the stated condition is satisfied.'))
    def test_changed_input_binding(self):
        self.reject(lambda x:x['real-study/exact_formula-predictions.json'][0].update(public_input_sha256='0'*64))
    def test_duplicate_answer(self):
        self.reject(lambda x:x['real-study/fbsde_tree-predictions.json'][1].update(case_id='test:v2:0'))
    def test_broken_truth_coverage(self):
        self.reject(lambda x:x['real-study/private-test-truths.json'].pop('test:v2:0'))
    def test_tampered_cpu(self):
        self.reject(lambda x:x['real-study/exact_formula-predictions.json'][0].update(cpu_ns=1))
    def test_changed_solver_node_count(self):
        self.reject(lambda x:x['real-study/fbsde_tree-predictions.json'][0].update(scenario_nodes=0))
    def test_changed_interface(self):
        self.reject(lambda x:x['real-study/fbsde_tree-predictions.json'][0].update(bsde_interface_residual=.01))
    def test_fake_physical_claim(self):
        self.reject(lambda x:x['real-study/physical-summary.json'].update(real_weights_executed=False))
    def test_fake_future_claim(self):
        self.reject(lambda x:x['real-study/design.json'].update(real_future_windows=True))
    def test_fake_lifecycle_acceptance(self):
        self.reject(lambda x:x['real-study/comparison.json'].update(full_lifecycle_resource_gate_passed=True))
    def test_archive_outer_hash_seal(self):
        self.score()
        with read_evidence(self.path,hash_file(self.path)) as z:
            self.assertEqual(len(z.namelist()),8)
        with self.assertRaises(EvidenceError):read_evidence(self.path,'0'*64)


class FailureBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'test.zip'
        self.doc=failure_document()

    def score(self):
        pack(self.path,self.doc)
        with zipfile.ZipFile(self.path) as z:
            return score_failure(z,'mmbert','banking_v1')

    def reject(self,change):
        change(self.doc)
        with self.assertRaises(EvidenceError):self.score()

    def test_real_budget_exhaustion_stays_failed(self):
        x=self.score()
        self.assertFalse(x['trial_completed'])
        self.assertEqual(x['excess_cpu_ns'],1)
    def test_altered_budget(self):
        self.reject(lambda x:x['acquisition-study/plan.json'].update(prediction_cpu_limit_ns=300000000))
    def test_changed_failure_type(self):
        self.reject(lambda x:x['acquisition-study/failure.json'].update(error_type='Succeeded'))
    def test_missing_attempts(self):
        self.reject(lambda x:x.__setitem__('acquisition-study/validation-view-attempts.jsonl',
                                           x['acquisition-study/validation-view-attempts.jsonl'].splitlines()[0]+'\n'))
    def test_changed_terminal_digest(self):
        self.reject(lambda x:x['acquisition-study/failure.json'].update(last_attempt_sha256='c'*64))
    def test_chained_previous_mismatch(self):
        def mutate(d):
            key='acquisition-study/validation-view-attempts.jsonl'
            rows=[json.loads(y) for y in d[key].splitlines()]
            rows[1]['previous_sha256']='z'*64
            d[key]='\n'.join(json.dumps(y) for y in rows)+'\n'
        self.reject(mutate)
    def test_prior_exceeded_budget_silently(self):
        def mutate(d):
            key='acquisition-study/validation-view-attempts.jsonl'
            rows=[json.loads(y) for y in d[key].splitlines()]
            rows[0]['cpu_ns']=LIMIT_NS+2
            rows[0]['phase_cpu_ns']['encoder_cpu_ns']=LIMIT_NS+2
            d[key]='\n'.join(json.dumps(y) for y in rows)+'\n'
        self.reject(mutate)


if __name__=='__main__':unittest.main()
