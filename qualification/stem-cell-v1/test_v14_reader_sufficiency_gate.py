"""V14 negative/adversarial contract fixtures only; NO pretrained Reader calls."""
import copy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import v14_reader_sufficiency_gate as v


def h(s): return sha256(s.encode()).hexdigest()


def sample():
    plan = dict(schema=v.SCHEMA+'.plan',source_only=True,
                frozen_before_predictions=True,production_authorized=False,
                objective_sha256=h('fixed task success criterion'),max_output_tokens=24,
                models={reader:dict(weights_sha256=h(reader+' weights'),
                    tokenizer_sha256=h(reader+' tokenizer'),
                    runtime_sha256=h(reader+' runtime')) for reader in v.READERS},
                cases=[])
    for i in (1,2):
        arms={}
        for arm in v.ARMS:
            evidence = {'none':[], 'retrieved':['e1'],
                        'sufficient':['e1','e2'], 'lesion':['e1']}[arm]
            arms[arm]=dict(request_sha256=h(f'actual prompt bytes {i}:{arm}'),
                           evidence_ids=evidence)
        plan['cases'].append(dict(id=f'question-{i}',family=f'family-{i}',
                          window='historical',question_sha256=h(f'question-{i}'),
                          arms=arms))
    predictions = dict(schema=v.SCHEMA+'.predictions',plan_sha256=v.sha_obj(plan),
                       model_output_source='external_original_required',
                       production_authorized=False,records=[])
    labels = dict(schema=v.SCHEMA+'.adjudication',plan_sha256=v.sha_obj(plan),
                  predictions_sha256='',reviewer_id='unverified-reviewer',
                  reviewer_independence_unverified=True,results=[])
    for case in plan['cases']:
        for reader in v.READERS:
            for arm in v.ARMS:
                answer=h(f'original answer {case["id"]}/{reader}/{arm}')
                cited=case['arms'][arm]['evidence_ids'][:1]
                predictions['records'].append(dict(case_id=case['id'], reader=reader,
                    arm=arm, request_sha256=case['arms'][arm]['request_sha256'],
                    model_sha256=plan['models'][reader]['weights_sha256'],
                    answer_sha256=answer,cited_evidence_ids=cited,
                    input_tokens=21,output_tokens=3,cpu_ms=20,wall_ms=13,
                    abstained=False))
                success = (reader=='reference' and arm=='sufficient') or (
                    reader=='candidate' and arm=='sufficient' and case['id']=='question-1')
                labels['results'].append(dict(case_id=case['id'],reader=reader,
                     arm=arm,answer_sha256=answer,correct=success,
                     citations_entailed=bool(cited and success)))
    labels['predictions_sha256']=v.sha_obj(predictions)
    return plan,predictions,labels


class V14Contracts(unittest.TestCase):
    def setUp(self): self.plan,self.pred,self.labels=sample()
    def review(self): return v.report(self.plan,self.pred,self.labels)
    def predict(self): return v.check_predictions(self.plan,self.pred)
    def reject_plan(self, f):
        f(self.plan)
        with self.assertRaises(ValueError):self.predict()
    def reject_pred(self, f):
        f(self.pred)
        with self.assertRaises(ValueError):self.predict()
    def reject_review(self, f):
        f(self.labels)
        with self.assertRaises(ValueError):self.review()
    def test_healthy_fixture_never_selects_model(self):
        report=self.review()
        self.assertEqual(report['decision'],'HOLD_NO_GO')
        self.assertFalse(report['stem_winner_verified'])
        self.assertFalse(report['independent_human_attestation_verified'])
        self.assertEqual(report['diagnostics']['reader_capacity_candidate'],1)
        self.assertEqual(report['diagnostics']['retrieval_or_evidence_selection'],1)
        self.assertEqual(report['diagnostics']['lesion_sensitive'],1)
    def test_schema_rejects_gold_leak(self):
        self.reject_plan(lambda p:p['cases'][0].update(answer='gold'))
    def test_not_frozen_before_pred(self):
        self.reject_plan(lambda p:p.update(frozen_before_predictions=False))
    def test_cannot_announce_production(self):
        self.reject_plan(lambda p:p.update(production_authorized=True))
    def test_no_raw_prediction_gold(self):
        self.reject_pred(lambda p:p['records'][0].update(publisher_answer='secret'))
    def test_must_keep_all_four_arms(self):
        self.reject_plan(lambda p:p['cases'][0]['arms'].pop('none'))
    def test_none_cannot_contain_evidence(self):
        self.reject_plan(lambda p:p['cases'][0]['arms']['none']['evidence_ids'].append('e2'))
    def test_lesion_must_delete_source(self):
        self.reject_plan(lambda p:p['cases'][0]['arms']['lesion'].update(
            evidence_ids=['e1','e2']))
    def test_lesion_cannot_add_foreign_source(self):
        self.reject_plan(lambda p:p['cases'][0]['arms']['lesion'].update(
            evidence_ids=['wrong']))
    def test_changed_arm_requires_changed_original_input(self):
        self.reject_plan(lambda p:p['cases'][0]['arms']['lesion'].update(
            request_sha256=p['cases'][0]['arms']['sufficient']['request_sha256']))
    def test_missing_prediction(self):
        self.reject_pred(lambda p:p['records'].pop())
    def test_duplicate_prediction(self):
        self.reject_pred(lambda p:p['records'].__setitem__(1,copy.deepcopy(p['records'][0])))
    def test_wrong_reader(self):
        self.reject_pred(lambda p:p['records'][0].update(reader='fake_reader'))
    def test_wrong_model_checkpoint(self):
        self.reject_pred(lambda p:p['records'][0].update(model_sha256=h('other')))
    def test_wrong_original_request(self):
        self.reject_pred(lambda p:p['records'][0].update(request_sha256=h('other')))
    def test_citation_not_in_original_input(self):
        self.reject_pred(lambda p:p['records'][0].update(cited_evidence_ids=['fabricated']))
    def test_cpu_bool_is_not_integer(self):
        self.reject_pred(lambda p:p['records'][0].update(cpu_ms=True))
    def test_output_exceeds_budget(self):
        self.reject_pred(lambda p:p['records'][0].update(output_tokens=100000))
    def test_predicted_outcome_untrusted(self):
        self.reject_pred(lambda p:p.update(model_output_source='trusted-human-eval'))
    def test_adjudication_missing_response(self):
        self.reject_review(lambda a:a['results'].pop())
    def test_adjudication_cannot_change_answer(self):
        self.reject_review(lambda a:a['results'][0].update(answer_sha256=h('altered')))
    def test_adjudication_cannot_assert_independence(self):
        self.reject_review(lambda a:a.update(reviewer_independence_unverified=False))
    def test_adjudication_wrong_model_output_sha(self):
        self.reject_review(lambda a:a.update(predictions_sha256=h('fake')))
    def test_duplicate_question(self):
        self.reject_plan(lambda p:p['cases'][1].update(id='question-1'))
    def test_fail_if_model_same_as_reference(self):
        self.reject_plan(lambda p:p['models']['reference'].update(
            weights_sha256=p['models']['candidate']['weights_sha256']))
    def test_strict_json_duplicate_keys_and_nan(self):
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/'a.json'
            for payload in ('{"a":1,"a":2}', '{"a":NaN}'):
                file.write_text(payload)
                with self.assertRaises(ValueError):v.load_json(file)
    def test_command_line_contract(self):
        with tempfile.TemporaryDirectory() as d:
            args=[]
            for name, data in [('plan',self.plan),('predictions',self.pred),
                               ('adjudication',self.labels)]:
                file=Path(d)/(name+'.json')
                file.write_text(json.dumps(data))
                args.extend(('--'+name,str(file)))
            output=subprocess.run([sys.executable,str(Path(v.__file__)),*args],
                      text=True,capture_output=True,check=True)
            self.assertEqual(json.loads(output.stdout)['decision'],'HOLD_NO_GO')
    def test_input_order_does_not_change_report(self):
        orig=self.review()
        self.pred['records'].reverse()
        self.labels['predictions_sha256']=v.sha_obj(self.pred)
        self.labels['results'].reverse()
        next_=self.review()
        self.assertEqual(orig['per_reader_arm'],next_['per_reader_arm'])
        self.assertEqual(orig['diagnostics'],next_['diagnostics'])

if __name__=='__main__':unittest.main()
