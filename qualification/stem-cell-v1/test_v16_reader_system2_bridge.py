"""Research-only V16 integration and adversarial synthetic-record tests.

All outputs, Reader identities, source IDs and judgments are synthetic fixtures.
GitHub CI imports the repository's actual V14/V15 modules; local test harness
may use only the isolated V14 development-compatibility module.
"""
import copy
from hashlib import sha256
import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

import v14_reader_sufficiency_gate as v14
import v15_system2_split_shadow as v15
from v16_reader_system2_bridge import (
    SCHEMA, COMPARATORS, _bootstrapped_cluster_mean,
    _per_family_statistics, source_first_bridge, review_bridge,
    review_split_robustness,
)
from test_v15_system2_split_shadow import (
    h, control_study, control_outputs, control_judgments,
    split_study, split_outputs, split_judgments,
)


def v14_plan(study):
    cases=[]
    for c in study['cases']:
        cid=c['id']
        cases.append({'id':cid, 'family':c['family'], 'window':c['window'],
            'question_sha256':h('question-original-'+cid),
            'arms':{
                'none':{'request_sha256':h(cid+'-no-evidence'), 'evidence_ids':[]},
                'retrieved':{'request_sha256':h(cid+'-ordinary-retrieval'),
                             'evidence_ids':['retrieved-'+cid]},
                'sufficient':{'request_sha256':c['input_sha256'],
                              'evidence_ids':['sufficient-'+cid,'critical-'+cid]},
                'lesion':{'request_sha256':h(cid+'-lesion-deleted-source'),
                          'evidence_ids':['sufficient-'+cid]},
            }})
    return {'schema':v14.SCHEMA+'.plan','source_only':True,
       'frozen_before_predictions':True, 'production_authorized':False,
       'objective_sha256':study['objective_sha256'],
       'max_output_tokens':64,
       'models':{
           'candidate':{'weights_sha256':study['model']['reader_sha256'],
                        'tokenizer_sha256':study['model']['tokenizer_sha256'],
                        'runtime_sha256':study['model']['runtime_sha256']},
           'reference':{'weights_sha256':h('strong-reference-reader'),
                        'tokenizer_sha256':h('reference-tok'),
                        'runtime_sha256':h('reference-runtime')}},
       'cases':cases}


def v14_outputs(plan, v15_executed):
    stop={r['case_id']:r for r in v15_executed['records'] if r['arm']=='stop'}
    records=[]
    for c in plan['cases']:
        cid=c['id']
        for reader in v14.READERS:
            for arm in v14.ARMS:
                digest=(stop[cid]['answer_sha256'] if reader=='candidate'
                        and arm=='sufficient' else h(cid+':'+reader+':'+arm))
                records.append({'case_id':cid,'reader':reader,'arm':arm,
                    'request_sha256':c['arms'][arm]['request_sha256'],
                    'model_sha256':plan['models'][reader]['weights_sha256'],
                    'answer_sha256':digest,
                    'cited_evidence_ids':c['arms'][arm]['evidence_ids'][:1],
                    'input_tokens':24,'output_tokens':5,'cpu_ms':11,
                    'wall_ms':9,'abstained':False})
    return {'schema':v14.SCHEMA+'.predictions',
            'plan_sha256':v15.sha_obj(plan),
            'model_output_source':'external_original_required',
            'records':records,'production_authorized':False}


def v14_judgments(plan,predictions,v15_judgment):
    answers={(r['case_id'],r['arm']):r for r in v15_judgment['results']}
    return {'schema':v14.SCHEMA+'.adjudication',
        'plan_sha256':v15.sha_obj(plan),
        'predictions_sha256':v15.sha_obj(predictions),
        'reviewer_id':'fixture-claimed-reviewer',
        'reviewer_independence_unverified':True,
        'results':[{'case_id':r['case_id'],'reader':r['reader'],
                    'arm':r['arm'],'answer_sha256':r['answer_sha256'],
                    'correct':(answers[r['case_id'],'stop']['correct']
                               if r['reader']=='candidate' and r['arm']=='sufficient'
                               else r['reader']=='reference' and r['arm']=='sufficient'),
                    'citations_entailed':(answers[r['case_id'],'stop']['citations_entailed']
                               if r['reader']=='candidate' and r['arm']=='sufficient'
                               else False)}
                   for r in predictions['records']]}


def fixture():
    study=control_study()
    plan=v15.plan_control(study)
    execution=control_outputs(study,plan)
    adjudication=control_judgments(study,execution)
    reader_plan=v14_plan(study)
    reader_results=v14_outputs(reader_plan,execution)
    reader_judgments=v14_judgments(reader_plan,reader_results,adjudication)
    seal=source_first_bridge(reader_plan,study)
    return [reader_plan,reader_results,reader_judgments,
            study,plan,execution,adjudication,seal]


def report(parts):return review_bridge(*parts)


class BridgeTests(unittest.TestCase):
    def setUp(self): self.parts=fixture()

    def invalid(self,index,mutator,*,recompute=False):
        parts=copy.deepcopy(self.parts)
        mutator(parts[index])
        if recompute:
            parts[7]=source_first_bridge(parts[0],parts[3])
        with self.assertRaises(ValueError):report(parts)

    def test_stable_source_first_seal(self):
        a=self.parts
        self.assertEqual(a[7],source_first_bridge(a[0],a[3]))
        self.assertFalse(a[7]['production_authorized'])
        self.assertFalse(a[7]['labels_seen'])
        self.assertEqual(len(a[7]['bindings']),2)

    def test_cross_model_same_source_same_answer_review(self):
        r=report(self.parts)
        self.assertEqual(r['case_count'],2)
        self.assertEqual(r['sufficient_reader_descriptive']['reference_correct'],2)
        self.assertEqual(r['sufficient_reader_descriptive']['candidate_correct'],0)
        self.assertEqual(r['source_families_claimed_not_authenticated'],2)
        self.assertEqual(set(r['system2_vs_baselines_descriptive']),set(COMPARATORS))
        self.assertGreater(r['root_forecast_brier_total_bps_squared'],
                           r['untrained_half_probability_brier_total_bps_squared'])
        for f in ('v14_original_reader_authenticated','v15_original_reader_authenticated',
                  'independent_review_authenticated','prospective_evaluation_verified',
                  'system2_net_utility_gain_qualified','cell_split_authorized',
                  'production_authorized'):
            self.assertFalse(r[f],f)
        self.assertEqual(r['decision'],'HOLD_NO_GO')

    def test_forecast_calibration_can_be_good_without_promotion(self):
        parts=copy.deepcopy(self.parts)
        for row in parts[6]['results']:
            if row['arm']=='stop' or (row['case_id']=='q2' and row['arm']=='ndu_shadow'):
                row['correct']=True
        parts[2]=v14_judgments(parts[0],parts[1],parts[6])
        r=report(parts)
        self.assertEqual(r['sufficient_reader_descriptive']['candidate_correct'],2)
        self.assertFalse(r['frozen_forecast_calibration_qualified'])
        self.assertFalse(r['system2_net_utility_gain_qualified'])

    def test_statistical_paired_net_matches_underlying_v15(self):
        r=report(self.parts)
        v15r=v15.review_control(*self.parts[3:7])
        for key in COMPARATORS:
            self.assertEqual(r['system2_vs_baselines_descriptive'][key]['net_micro_delta'],
                             v15r['ndu_paired_deltas'][key]['net_micro_delta'])

    def test_order_invariance_for_statistics(self):
        a=copy.deepcopy(self.parts)
        r=report(a)
        a[1]['records'].reverse()
        a[2]=v14_judgments(a[0],a[1],a[6])
        a[5]['records'].reverse()
        a[6]=control_judgments(a[3],a[5])
        # V14 suff score in fixture remains same as the reconstructed stop score.
        a[2]=v14_judgments(a[0],a[1],a[6])
        b=report(a)
        self.assertEqual(r['system2_vs_baselines_descriptive'],
                         b['system2_vs_baselines_descriptive'])
        self.assertEqual(r['root_forecast_calibration_quartiles'],
                         b['root_forecast_calibration_quartiles'])
        self.assertNotEqual(r['v14_predictions_sha256'],b['v14_predictions_sha256'])

    def test_one_claimed_family_does_not_count_as_two(self):
        a=copy.deepcopy(self.parts)
        a[0]['cases'][1]['family']='same-root'
        a[0]['cases'][0]['family']='same-root'
        for c in a[3]['cases']:c['family']='same-root'
        a[4]=v15.plan_control(a[3])
        a[5]=control_outputs(a[3],a[4])
        a[6]=control_judgments(a[3],a[5])
        a[1]=v14_outputs(a[0],a[5])
        a[2]=v14_judgments(a[0],a[1],a[6])
        a[7]=source_first_bridge(a[0],a[3])
        r=report(a)
        self.assertEqual(r['source_families_claimed_not_authenticated'],1)
        self.assertEqual(r['system2_vs_baselines_descriptive']['stop']
                          ['claimed_independent_families_not_authenticated'],1)
        self.assertIsNone(r['system2_vs_baselines_descriptive']['stop']
                          ['min_leave_one_family_out_per_case_micro'])

    def test_bootstrap_repeatable_and_case_weighted(self):
        groups={'fA':{'cases':9,'net_micro':900},'fB':{'cases':1,'net_micro':-1000}}
        a=_bootstrapped_cluster_mean(groups,123)
        self.assertEqual(a,_bootstrapped_cluster_mean(dict(reversed(list(groups.items()))),123))
        self.assertEqual(len(a),2)
        self.assertNotEqual(a[0],a[1])

    def test_bootstrap_reject_empty(self):
        with self.assertRaises(ValueError):_bootstrapped_cluster_mean({},456)

    def test_wrong_objective(self):
        self.invalid(0,lambda v:v.update(objective_sha256=h('mutated')))
    def test_wrong_candidate_weights(self):
        self.invalid(0,lambda v:v['models']['candidate'].update(weights_sha256=h('other')))
    def test_wrong_candidate_tokenizer(self):
        self.invalid(0,lambda v:v['models']['candidate'].update(tokenizer_sha256=h('other')))
    def test_wrong_candidate_runtime(self):
        self.invalid(0,lambda v:v['models']['candidate'].update(runtime_sha256=h('other')))
    def test_wrong_question_identity(self):
        self.invalid(0,lambda v:v['cases'][0].update(id='foreign'))
    def test_wrong_family(self):
        self.invalid(0,lambda v:v['cases'][0].update(family='foreign-family'))
    def test_wrong_window(self):
        self.invalid(0,lambda v:v['cases'][0].update(window='old-not-future'))
    def test_root_uses_retrieval_not_sufficient(self):
        self.invalid(0,lambda v:v['cases'][0]['arms']['sufficient']
                           .update(request_sha256=h('other-original-source')))
    def test_changed_study_includes_gold(self):
        self.invalid(3,lambda v:v['cases'][0].update(gold_answer=True))
    def test_unchanged_request_after_lesion(self):
        self.invalid(0,lambda v:v['cases'][0]['arms']['lesion'].update(
                   request_sha256=v['cases'][0]['arms']['sufficient']['request_sha256']))
    def test_false_frozen_flag(self):
        self.invalid(0,lambda v:v.update(frozen_before_predictions=False))
    def test_fake_production_study(self):
        self.invalid(3,lambda v:v.update(production_authorized=True))
    def test_replaced_prelabel_seal(self):
        self.invalid(7,lambda v:v.update(model_host_authenticated=True))
    def test_prelabel_seal_tamper(self):
        self.invalid(7,lambda v:v['bindings'][0].update(root_forecast_bps=9999))
    def test_missing_v14_reader_answer(self):
        self.invalid(1,lambda v:v['records'].pop())
    def test_v14_answer_tamper(self):
        self.invalid(1,lambda v:v['records'][0].update(answer_sha256=h('changed')))
    def test_v14_review_tamper(self):
        self.invalid(2,lambda v:v['results'][0].update(answer_sha256=h('changed')))
    def test_v14_reviewer_claims_verified(self):
        self.invalid(2,lambda v:v.update(reviewer_independence_unverified=False))
    def test_same_terminal_ndu_ghost_gain_denied_by_bridge(self):
        parts=copy.deepcopy(self.parts)
        for row in parts[5]['records']:
            if row['case_id']=='q2' and row['arm']=='ndu_shadow':
                row['answer_sha256']=h('ghost-positive-output')
        parts[6]=control_judgments(parts[3],parts[5])
        with self.assertRaisesRegex(ValueError,'same terminal Reader'):
            report(parts)

    def test_same_nonroot_terminal_duplicate_output_denied(self):
        parts=copy.deepcopy(self.parts)
        for row in parts[5]['records']:
            if row['case_id']=='q2' and row['arm']=='greedy_one':
                row['answer_sha256']=h('different-frozen-content')
        parts[6]=control_judgments(parts[3],parts[5])
        with self.assertRaisesRegex(ValueError,'same terminal Reader'):
            report(parts)

    def test_bridge_reports_only_true_terminal_changes(self):
        values=report(self.parts)['system2_vs_baselines_descriptive']
        self.assertEqual(values['stop']['unchanged_terminal_quality_delta'],0)
        self.assertEqual(values['stop']['changed_terminal_cases'],1)
        self.assertEqual(values['stop']['changed_answer_cases'],1)

    def test_v15_changed_policy(self):
        self.invalid(4,lambda v:v['cases'][0]['policies']['ndu_shadow'].update(root='stop'))
    def test_v15_model_output_tamper(self):
        self.invalid(5,lambda v:v['records'][0].update(answer_sha256=h('changed')))
    def test_v15_adjudication_tamper(self):
        self.invalid(6,lambda v:v['results'][0].update(answer_sha256=h('changed')))
    def test_v15_reviewer_fake_independence(self):
        self.invalid(6,lambda v:v.update(independence_unverified=False))
    def test_v15_stopped_answer_diff_from_v14_same_input(self):
        parts=copy.deepcopy(self.parts)
        for row in parts[5]['records']:
            if row['case_id']=='q1' and row['arm']=='stop':row['answer_sha256']=h('different-frozen-stop')
        parts[6]=control_judgments(parts[3],parts[5])
        with self.assertRaisesRegex(ValueError,'exact frozen V14'):
            report(parts)

    def test_same_answer_contradictory_judgment(self):
        parts=copy.deepcopy(self.parts)
        for row in parts[6]['results']:
            if row['case_id']=='q1' and row['arm']=='stop':row['correct']=True
        with self.assertRaisesRegex(ValueError,'contradictory external'):
            report(parts)

    def test_same_answer_contradictory_citations(self):
        parts=copy.deepcopy(self.parts)
        for row in parts[6]['results']:
            if row['case_id']=='q1' and row['arm']=='stop':row['citations_entailed']=True
        with self.assertRaisesRegex(ValueError,'contradictory external'):
            report(parts)

    def test_invalid_boolean_physical_counter(self):
        self.invalid(5,lambda v:v['records'][0].update(cpu_ms=True))

    def test_duplicate_record_cannot_inflate_significance(self):
        self.invalid(5,lambda v:v['records'].append(copy.deepcopy(v['records'][0])))

    def test_external_evaluator_not_trusted_from_hashes(self):
        r=report(self.parts)
        self.assertFalse(r['independent_review_authenticated'])
        self.assertFalse(r['v14_original_reader_authenticated'])
        self.assertFalse(r['prospective_evaluation_verified'])

    def test_source_only_plan_has_no_outcome_access(self):
        v14_plan,_,_,v15_study,*_=self.parts
        a=source_first_bridge(copy.deepcopy(v14_plan),copy.deepcopy(v15_study))
        self.assertEqual(a,self.parts[-1])
        self.assertNotIn('answer_sha256',str(a))

    def test_cli_create_and_review(self):
        with tempfile.TemporaryDirectory() as d:
            paths=[]
            for i,doc in enumerate(self.parts):
                p=Path(d)/f'{i}.json'
                p.write_text(json.dumps(doc),encoding='utf8')
                paths.append(p)
            script=str(Path(__file__).with_name('v16_reader_system2_bridge.py'))
            env=os.environ.copy()
            cmd=[sys.executable,script,'plan','--v14-plan',str(paths[0]),
                 '--v15-study',str(paths[3])]
            output=subprocess.run(cmd,env=env,text=True,capture_output=True,check=True)
            self.assertEqual(json.loads(output.stdout),self.parts[7])
            cmd=[sys.executable,script,'review',
                 '--v14-plan',str(paths[0]),'--v14-predictions',str(paths[1]),
                 '--v14-adjudication',str(paths[2]),'--v15-study',str(paths[3]),
                 '--v15-policy',str(paths[4]),'--v15-execution',str(paths[5]),
                 '--v15-adjudication',str(paths[6]),'--prelabel-seal',str(paths[7])]
            output=subprocess.run(cmd,env=env,text=True,capture_output=True,check=True)
            self.assertEqual(json.loads(output.stdout)['decision'],'HOLD_NO_GO')


class SplitRobustnessTests(unittest.TestCase):
    def setUp(self):
        self.study=split_study(200)
        self.predictions=split_outputs(self.study)
        self.judgments=split_judgments(self.study,self.predictions)

    def test_positive_two_future_windows_cannot_authorize(self):
        r=review_split_robustness(self.study,self.predictions,self.judgments)
        self.assertTrue(r['numeric_gain_gate_from_v15'])
        self.assertTrue(r['sample_window_gate_from_v15'])
        self.assertTrue(r['future_gain_every_claimed_window'])
        self.assertFalse(r['cell_split_authorized'])
        self.assertFalse(r['production_authorized'])
        self.assertEqual(r['decision'],'HOLD_NO_GO')

    def test_one_future_window_regression_masked_by_aggregate_gain(self):
        self.assertTrue(v15.review_split(self.study,self.predictions,self.judgments)
                        ['numeric_gain_gate'])
        j=copy.deepcopy(self.judgments)
        future_one_ids={c['id'] for c in self.study['cases']
                        if c['cohort']=='future' and c['window']=='future-1'}
        for row in j['results']:
            if row['case_id'] in future_one_ids and row['arm']=='split':row['correct']=False
        r=review_split_robustness(self.study,self.predictions,j)
        self.assertGreater(r['per_future_window_descriptive']['future-2']['correct_delta'],0)
        self.assertFalse(r['future_gain_every_claimed_window'])
        self.assertFalse(r['cell_split_authorized'])

    def test_count_old_regressed_families(self):
        j=copy.deepcopy(self.judgments)
        for row in j['results']:
            if row['case_id']=='s0' and row['arm']=='split':row['correct']=False
        r=review_split_robustness(self.study,self.predictions,j)
        self.assertEqual(r['old_task_regressed_claimed_families'],1)
        self.assertFalse(r['numeric_gain_gate_from_v15'])

    def test_bad_prediction_rejected(self):
        v=copy.deepcopy(self.predictions)
        v['records'][0]['head_sha256']=h('different-head')
        with self.assertRaises(ValueError):
            review_split_robustness(self.study,v,self.judgments)

    def test_missing_judgment_rejected(self):
        v=copy.deepcopy(self.judgments)
        v['results'].pop()
        with self.assertRaises(ValueError):
            review_split_robustness(self.study,self.predictions,v)

    def test_bad_cohort_rejected(self):
        s=copy.deepcopy(self.study)
        s['cases'][0]['cohort']='future'
        with self.assertRaises(ValueError):
            review_split_robustness(s,self.predictions,self.judgments)

    def test_split_cli(self):
        with tempfile.TemporaryDirectory() as d:
            docs=[self.study,self.predictions,self.judgments]
            paths=[]
            for i,obj in enumerate(docs):
                p=Path(d)/f'file-{i}.json'
                p.write_text(json.dumps(obj),encoding='utf8')
                paths.append(str(p))
            cmd=[sys.executable,str(Path(__file__).with_name('v16_reader_system2_bridge.py')),
                 'split','--study',paths[0],'--predictions',paths[1],
                 '--adjudication',paths[2]]
            p=subprocess.run(cmd,text=True,capture_output=True,check=True)
            self.assertEqual(json.loads(p.stdout)['decision'],'HOLD_NO_GO')


if __name__=='__main__':unittest.main()
