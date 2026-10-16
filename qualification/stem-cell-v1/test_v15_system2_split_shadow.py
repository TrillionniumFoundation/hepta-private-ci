"""Adversarial deterministic and synthetic fixture tests. NO real model execution."""
import copy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from v15_system2_split_shadow import (
    PREFIX, ARMS, SPLIT_ARMS, sha_obj, load_json, plan_control,
    review_control, review_split, validate_control_study,
    validate_control_execution, validate_split_study,
)


def h(s):
    return sha256(s.encode('utf8')).hexdigest()


def node(nid, quality, actions=()):
    return {'id': nid, 'request_sha256':h('q1' if nid=='root' else 'q2' if nid=='start' else 'state-'+nid),
            'stop_quality_bps': quality, 'actions': list(actions)}


def action(aid, kind, cpu, tokens, *edges):
    return {'id': aid, 'kind': kind, 'cpu_ms': cpu, 'tokens': tokens,
            'outcomes': [{'node':nid, 'p_bps':p} for nid,p in edges]}


def control_study():
    return {
        'schema':PREFIX+'.control-study',
        'frozen_before_execution':True, 'source_only':True,
        'production_authorized':False,
        'objective_sha256':h('objective-v1'),
        'model':{'stem_sha256':h('stem'), 'reader_sha256':h('reader'),
                 'tokenizer_sha256':h('tok'), 'runtime_sha256':h('runtime')},
        'scope':{'principal':'p-user-1','purpose':'shadow-v15',
                 'generation':3, 'authority_epoch':5},
        'prices':{'correct_reward_micro':100_000,
                  'cpu_ms_price_micro':100, 'token_price_micro':100},
        'limits':{'extra_cpu_ms':20,'extra_tokens':20,
                  'max_total_cpu_ms':1000,'max_total_tokens':2000,'max_depth':3},
        'cases':[
            {'id':'q1','family':'f1','window':'historical','input_sha256':h('q1'),
             'root':'root','nodes':[
                node('root',7000,[
                    action('a','retrieve',4,3,('mid',10_000)),
                    action('b','verify',5,4,('alt',10_000))]),
                node('mid',7400,[action('d','continue',2,2,('good',10_000))]),
                node('alt',8800), node('good',9900)]},
            {'id':'q2','family':'f2','window':'future-1','input_sha256':h('q2'),
             'root':'start','nodes':[
                node('start',9900,[action('check','verify',5,4,('worse',10_000))]),
                node('worse',9800)]}
        ]
    }


def control_outputs(study, sealed):
    visits={
        ('q1','stop'):(['root'],[]),
        ('q1','fixed_one'):(['root','mid'],['a']),
        ('q1','greedy_one'):(['root','alt'],['b']),
        ('q1','ndu_shadow'):(['root','mid','good'],['a','d']),
        ('q2','stop'):(['start'],[]),
        ('q2','fixed_one'):(['start','worse'],['check']),
        ('q2','greedy_one'):(['start','worse'],['check']),
        ('q2','ndu_shadow'):(['start'],[]),
    }
    case_lookup={c['id']:c for c in study['cases']}
    rows=[]
    for cid in ('q1','q2'):
        for arm in ARMS:
            v,a=visits[cid,arm]
            rows.append({'case_id':cid,'arm':arm,
                         'input_sha256':case_lookup[cid]['input_sha256'],
                         'reader_sha256':study['model']['reader_sha256'],
                         'answer_sha256':h(cid+'-frozen-terminal-'+v[-1]),
                         'terminal_request_sha256':next(n['request_sha256'] for n in
                              case_lookup[cid]['nodes'] if n['id']==v[-1]),
                         'visited_nodes':v,'actions_taken':a,
                         'cpu_ms':10+5*len(a),'tokens':20+11*len(a),
                         'citations_entailed_claimed':False})
    return {'schema':PREFIX+'.execution',
            'study_sha256':sha_obj(study),
            'policy_sha256':sha_obj(sealed),
            'model_execution_source':'external_original_required',
            'sealed_before_adjudication':True,
            'production_authorized':False,'records':rows}


def control_judgments(study, execution):
    return {'schema':PREFIX+'.adjudication',
            'study_sha256':sha_obj(study),
            'execution_sha256':sha_obj(execution),
            'reviewer_id':'fixture-not-independent',
            'independence_unverified':True,
            'results':[
                {'case_id':r['case_id'],'arm':r['arm'],
                 'answer_sha256':r['answer_sha256'],
                 'correct':r['case_id']=='q1' and r['arm']=='ndu_shadow',
                 'citations_entailed':False}
                for r in execution['records']
            ]}


def split_study(n=4):
    cases=[]
    for i in range(n):
        cohort='old' if i<n//2 else 'future'
        window='old' if cohort=='old' else ('future-1' if i%2 else 'future-2')
        cases.append({'id':f's{i}','family':f'independent-root-{i}',
                      'window':window,'cohort':cohort,'input_sha256':h(f'input-{i}')})
    return {'schema':PREFIX+'.split-study','source_only':True,
            'frozen_before_predictions':True,'production_authorized':False,
            'objective_sha256':h('obj'),'stem_sha256':h('stem'),
            'parent_head_sha256':h('parent'),'split_head_sha256':h('child'),
            'cost_profile':{'correct_reward_micro':100_000,
                'cpu_ms_price_micro':10, 'token_price_micro':5,
                'extra_training_micro':100, 'extra_migration_micro':100,
                'extra_evaluation_micro':100},
            'max_old_regressions':0, 'cases':cases}


def split_outputs(study):
    rows=[]
    for c in study['cases']:
        for arm in SPLIT_ARMS:
            rows.append({'case_id':c['id'],'arm':arm,'input_sha256':c['input_sha256'],
                         'head_sha256':study['parent_head_sha256' if arm=='parent'
                                                     else 'split_head_sha256'],
                         'answer_sha256':h(c['id']+arm),
                         'cpu_ms':10,'tokens':20})
    return {'schema':PREFIX+'.split-predictions','study_sha256':sha_obj(study),
            'source':'external_original_required',
            'sealed_before_adjudication':True,'production_authorized':False,
            'records':rows}


def split_judgments(study,pred):
    c={x['id']:x for x in study['cases']}
    return {'schema':PREFIX+'.split-adjudication',
            'study_sha256':sha_obj(study),
            'predictions_sha256':sha_obj(pred),
            'reviewer_id':'synthetic-judge','independence_unverified':True,
            'results':[
                {'case_id':r['case_id'],'arm':r['arm'],
                 'answer_sha256':r['answer_sha256'],
                 'correct':c[r['case_id']]['cohort']=='old' or r['arm']=='split'}
                for r in pred['records']]}


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.study=control_study()
        self.policy=plan_control(self.study)
        self.execution=control_outputs(self.study,self.policy)
        self.adjudication=control_judgments(self.study,self.execution)

    def assertBadStudy(self,mutator):
        v=copy.deepcopy(self.study);mutator(v)
        with self.assertRaises(ValueError):
            plan_control(v)

    def assertBadExecution(self,mutator):
        v=copy.deepcopy(self.execution);mutator(v)
        with self.assertRaises(ValueError):
            validate_control_execution(self.study,self.policy,v)

    def assertBadJudgment(self,mutator):
        v=copy.deepcopy(self.adjudication);mutator(v)
        with self.assertRaises(ValueError):
            review_control(self.study,self.policy,self.execution,v)

    def test_optimal_two_hop_branch_and_early_stop(self):
        p={x['case_id']:x['policies'] for x in self.policy['cases']}
        self.assertEqual(p['q1']['stop'],{'root':'stop'})
        self.assertEqual(p['q1']['fixed_one'],{'root':'a','mid':'stop'})
        self.assertEqual(p['q1']['greedy_one'],{'root':'b','alt':'stop'})
        self.assertEqual(p['q1']['ndu_shadow'],{'root':'a','mid':'d','good':'stop'})
        self.assertEqual(p['q2']['ndu_shadow'],{'start':'stop'})

    def test_truthful_report_never_authorizes(self):
        r=review_control(self.study,self.policy,self.execution,self.adjudication)
        self.assertEqual(r['per_arm']['ndu_shadow']['correct'],1)
        self.assertEqual(r['ndu_paired_deltas']['stop']['ndu_only_correct'],1)
        for flag in ('net_task_gain_qualified','system2_activation_authorized',
                     'independent_outcome_authenticated','production_authorized',
                     'general_fbsde_solution_verified'):
            self.assertFalse(r[flag])
        self.assertEqual(r['decision'],'HOLD_NO_GO')

    def test_order_invariance(self):
        v=copy.deepcopy(self.execution);v['records'].reverse()
        jud=control_judgments(self.study,v)
        a=review_control(self.study,self.policy,self.execution,self.adjudication)
        b=review_control(self.study,self.policy,v,jud)
        self.assertEqual(a['per_arm'],b['per_arm'])
        self.assertEqual(a['ndu_paired_deltas'],b['ndu_paired_deltas'])
        self.assertNotEqual(a['execution_sha256'],b['execution_sha256'])

    def test_no_planner_label_access(self):
        self.assertBadStudy(lambda s:s['cases'][0].update(correct=True))
    def test_reject_gold_target_in_nodes(self):
        self.assertBadStudy(lambda s:s['cases'][0]['nodes'][0].update(actual_outcome='success'))
    def test_reject_false_frozen_flag(self):
        self.assertBadStudy(lambda s:s.update(frozen_before_execution=False))
    def test_reject_fake_prod_permission(self):
        self.assertBadStudy(lambda s:s.update(production_authorized=True))
    def test_reject_inexact_model_sha(self):
        self.assertBadStudy(lambda s:s['model'].update(reader_sha256='abc'))
    def test_reject_broken_generation(self):
        self.assertBadStudy(lambda s:s['scope'].update(generation=0))
    def test_reject_bool_as_budget(self):
        self.assertBadStudy(lambda s:s['limits'].update(extra_cpu_ms=True))
    def test_reject_negative_price(self):
        self.assertBadStudy(lambda s:s['prices'].update(cpu_ms_price_micro=-1))
    def test_reject_nonfinite_float_quality(self):
        self.assertBadStudy(lambda s:s['cases'][0]['nodes'][0].update(stop_quality_bps=float('nan')))
    def test_reject_duplicate_case(self):
        self.assertBadStudy(lambda s:s['cases'].append(copy.deepcopy(s['cases'][0])))
    def test_reject_duplicate_node(self):
        self.assertBadStudy(lambda s:s['cases'][0]['nodes'].append(copy.deepcopy(s['cases'][0]['nodes'][-1])))
    def test_reject_broken_probabilities(self):
        self.assertBadStudy(lambda s:s['cases'][0]['nodes'][0]['actions'][0]['outcomes'][0].update(p_bps=9999))
    def test_reject_cycle(self):
        self.assertBadStudy(lambda s:s['cases'][0]['nodes'][-1]['actions'].append(action('loop','continue',1,0,('root',10000))))
    def test_reject_ambiguous_merge(self):
        self.assertBadStudy(lambda s:s['cases'][0]['nodes'][0]['actions'][1]['outcomes'][0].update(node='mid'))
    def test_reject_unreachable_node(self):
        self.assertBadStudy(lambda s:s['cases'][0]['nodes'].append(node('orphan',9000)))
    def test_reject_excess_depth(self):
        self.assertBadStudy(lambda s:s['limits'].update(max_depth=1))
    def test_reject_free_action(self):
        self.assertBadStudy(lambda s:s['cases'][0]['nodes'][0]['actions'][0].update(cpu_ms=0,tokens=0))
    def test_reject_invalid_negative_action_token(self):
        self.assertBadStudy(lambda s:s['cases'][0]['nodes'][0]['actions'][0].update(tokens=-1))
    def test_reject_duplicated_edge(self):
        self.assertBadStudy(lambda s:s['cases'][0]['nodes'][0]['actions'][0]['outcomes'].append({'node':'mid','p_bps':100}))
    def test_reject_changed_sealed_policy(self):
        p=copy.deepcopy(self.policy);p['cases'][0]['policies']['ndu_shadow']['root']='stop'
        with self.assertRaises(ValueError):
            validate_control_execution(self.study,p,self.execution)
    def test_reject_wrong_digest(self):
        self.assertBadExecution(lambda e:e.update(policy_sha256=h('foreign')))
    def test_reject_outcome_claim_in_execution(self):
        self.assertBadExecution(lambda e:e['records'][0].update(correct=True))
    def test_reject_missing_model_result(self):
        self.assertBadExecution(lambda e:e['records'].pop())
    def test_reject_duplicate_prediction(self):
        self.assertBadExecution(lambda e:e['records'].__setitem__(-1,copy.deepcopy(e['records'][0])))
    def test_reject_model_replacement(self):
        self.assertBadExecution(lambda e:e['records'][0].update(reader_sha256=h('new-reader')))
    def test_reject_reused_state_request(self):
        self.assertBadStudy(lambda s:s['cases'][0]['nodes'][1].update(
            request_sha256=s['cases'][0]['nodes'][0]['request_sha256']))
    def test_reject_wrong_terminal_input(self):
        self.assertBadExecution(lambda e:e['records'][3].update(terminal_request_sha256=h('fake')))
    def test_reject_total_physical_budget_overrun(self):
        self.assertBadExecution(lambda e:e['records'][3].update(cpu_ms=1001))
    def test_reject_changed_input(self):
        self.assertBadExecution(lambda e:e['records'][0].update(input_sha256=h('new-input')))
    def test_reject_wrong_start(self):
        self.assertBadExecution(lambda e:e['records'][0].update(visited_nodes=['mid']))
    def test_reject_fake_action_choice(self):
        self.assertBadExecution(lambda e:e['records'][3].update(actions_taken=['b','d']))
    def test_reject_shortened_ndu_path(self):
        self.assertBadExecution(lambda e:e['records'][3].update(visited_nodes=['root','mid'],actions_taken=['a']))
    def test_reject_impossible_state_transition(self):
        self.assertBadExecution(lambda e:e['records'][3].update(visited_nodes=['root','alt','good']))
    def test_reject_observed_bool_cpu(self):
        self.assertBadExecution(lambda e:e['records'][0].update(cpu_ms=True))
    def test_reject_fake_execution_status(self):
        self.assertBadExecution(lambda e:e.update(production_authorized=True))
    def test_reject_changed_answer_for_review(self):
        self.assertBadJudgment(lambda j:j['results'][0].update(answer_sha256=h('tamper')))
    def test_same_root_terminal_different_answer_rejected(self):
        def mutate(e):
            row = next(r for r in e['records'] if
                       r['case_id']=='q2' and r['arm']=='ndu_shadow')
            row['answer_sha256']=h('invented-NDU-gain-with-identical-request')
        self.assertBadExecution(mutate)

    def test_same_nonroot_terminal_different_answer_rejected(self):
        def mutate(e):
            row = next(r for r in e['records'] if
                       r['case_id']=='q2' and r['arm']=='greedy_one')
            row['answer_sha256']=h('invented-greedy-gain-with-identical-request')
        self.assertBadExecution(mutate)

    def test_same_terminal_forged_citation_claim_rejected(self):
        def mutate(e):
            row = next(r for r in e['records'] if
                       r['case_id']=='q2' and r['arm']=='ndu_shadow')
            row['citations_entailed_claimed']=True
        self.assertBadExecution(mutate)

    def test_same_terminal_contradictory_correctness_rejected(self):
        def mutate(j):
            row = next(r for r in j['results'] if
                       r['case_id']=='q2' and r['arm']=='ndu_shadow')
            row['correct']=True
        self.assertBadJudgment(mutate)

    def test_same_terminal_contradictory_entailment_rejected(self):
        def mutate(j):
            row = next(r for r in j['results'] if
                       r['case_id']=='q2' and r['arm']=='ndu_shadow')
            row['citations_entailed']=True
        self.assertBadJudgment(mutate)

    def test_same_node_action_must_not_change_observed_successor(self):
        # Two policies may execute the same predeclared action at root. The
        # current V15 profile has no stochastic environment seed/observation
        # contract, so contradictory claimed successors must be denied.
        study = control_study()
        first = study['cases'][0]
        first['nodes'].append(node('other',5500))
        branch = first['nodes'][0]['actions'][0]
        branch['outcomes'] = [{'node':'mid','p_bps':9500},
                              {'node':'other','p_bps':500}]
        policy = plan_control(study)
        self.assertEqual(policy['cases'][0]['policies']['ndu_shadow']['root'],'a')
        execution = control_outputs(study,policy)
        target = next(r for r in execution['records'] if
                      r['case_id']=='q1' and r['arm']=='fixed_one')
        target['visited_nodes']=['root','other']
        target['terminal_request_sha256']=h('state-other')
        target['answer_sha256']=h('q1-frozen-terminal-other')
        with self.assertRaisesRegex(ValueError,'conflicting successors'):
            validate_control_execution(study,policy,execution)

    def test_changed_answer_only_on_changed_terminal(self):
        report=review_control(self.study,self.policy,
                              self.execution,self.adjudication)
        for result in report['ndu_paired_deltas'].values():
            self.assertEqual(result['unchanged_terminal_quality_delta'],0)
            self.assertLessEqual(result['changed_answer_cases'],
                                 result['changed_terminal_cases'])

    def test_reject_changed_adjudication_lineage(self):
        self.assertBadJudgment(lambda j:j.update(execution_sha256=h('tamper')))
    def test_reject_fake_reviewer_authority(self):
        self.assertBadJudgment(lambda j:j.update(independence_unverified=False))
    def test_reject_missing_judgment(self):
        self.assertBadJudgment(lambda j:j['results'].pop())
    def test_reject_bool_wrongly_string(self):
        self.assertBadJudgment(lambda j:j['results'][0].update(correct='true'))
    def test_frozen_budget_blocks_continue(self):
        v=copy.deepcopy(self.study)
        v['limits']['extra_cpu_ms']=0
        v['limits']['extra_tokens']=0
        p=plan_control(v)
        self.assertTrue(all(set(item['policies']['ndu_shadow'].values())=={'stop'}
                            for item in p['cases']))
    def test_price_sensitivity(self):
        v=copy.deepcopy(self.study)
        v['prices']['cpu_ms_price_micro']=100_000
        p=plan_control(v)
        self.assertEqual(p['cases'][0]['policies']['ndu_shadow']['root'],'stop')
    def test_sha_determinism(self):
        self.assertEqual(sha_obj(self.study),sha_obj(json.loads(json.dumps(self.study))))
    def test_duplicate_json_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'dup.json';p.write_text('{"a":1,"a":2}')
            with self.assertRaises(ValueError):
                load_json(p)
    def test_nonfinite_json_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'nan.json';p.write_text('{"a":NaN}')
            with self.assertRaises(ValueError):
                load_json(p)
    def test_actual_study_output_seal_digest(self):
        self.assertEqual(self.policy['study_sha256'],sha_obj(self.study))
        self.assertEqual(self.execution['policy_sha256'],sha_obj(self.policy))


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.study=split_study()
        self.pred=split_outputs(self.study)
        self.adj=split_judgments(self.study,self.pred)
    def assertBadStudy(self,change):
        s=copy.deepcopy(self.study);change(s)
        with self.assertRaises(ValueError):
            validate_split_study(s)
    def assertBadPred(self,change):
        p=copy.deepcopy(self.pred);change(p)
        with self.assertRaises(ValueError):
            review_split(self.study,p,self.adj)
    def assertBadAdj(self,change):
        a=copy.deepcopy(self.adj);change(a)
        with self.assertRaises(ValueError):
            review_split(self.study,self.pred,a)
    def test_split_gain_not_authorization(self):
        r=review_split(self.study,self.pred,self.adj)
        self.assertTrue(r['numeric_gain_gate'])
        self.assertFalse(r['sample_window_gate'])
        self.assertFalse(r['cell_split_authorized'])
        self.assertFalse(r['model_promotion_authorized'])
        self.assertEqual(r['decision'],'HOLD_NO_GO')
    def test_200_claimed_source_groups_do_not_authenticate_real_sources(self):
        s=split_study(200)
        pred=split_outputs(s);adj=split_judgments(s,pred)
        r=review_split(s,pred,adj)
        self.assertTrue(r['numeric_gain_gate'])
        self.assertTrue(r['sample_window_gate'])
        self.assertFalse(r['independent_source_family_authenticated'])
        self.assertFalse(r['cell_split_authorized'])
    def test_old_regression_prevents_gate(self):
        adj=copy.deepcopy(self.adj)
        for row in adj['results']:
            if row['case_id']=='s0' and row['arm']=='split':
                row['correct']=False
        r=review_split(self.study,self.pred,adj)
        self.assertEqual(r['old_parent_correct_to_split_wrong'],1)
        self.assertFalse(r['numeric_gain_gate'])
    def test_split_cost_can_kill_gain(self):
        s=copy.deepcopy(self.study)
        s['cost_profile']['extra_training_micro']=10_000_000
        p=split_outputs(s);a=split_judgments(s,p)
        r=review_split(s,p,a)
        self.assertFalse(r['numeric_gain_gate'])
    def test_reject_duplicate_cohort(self):
        self.assertBadStudy(lambda s:s['cases'][1].update(id='s0'))
    def test_reject_data_leakage(self):
        self.assertBadStudy(lambda s:s['cases'][0].update(correct=True))
    def test_reject_old_future_family_overlap(self):
        self.assertBadStudy(lambda s:s['cases'][2].update(family=s['cases'][0]['family']))
    def test_reject_missing_future(self):
        self.assertBadStudy(lambda s:[c.update(cohort='old') for c in s['cases']])
    def test_reject_synthetic_authorization(self):
        self.assertBadStudy(lambda s:s.update(production_authorized=True))
    def test_reject_inconsistent_split_digest(self):
        self.assertBadPred(lambda p:p['records'][1].update(head_sha256=h('wrong')))
    def test_reject_unsealed_prediction(self):
        self.assertBadPred(lambda p:p.update(sealed_before_adjudication=False))
    def test_reject_changed_source(self):
        self.assertBadPred(lambda p:p['records'][0].update(input_sha256=h('wrong')))
    def test_reject_missing_split_candidate(self):
        self.assertBadPred(lambda p:p['records'].pop())
    def test_reject_duplicate_split_arm(self):
        self.assertBadPred(lambda p:p['records'].__setitem__(-1,copy.deepcopy(p['records'][0])))
    def test_reject_split_boolean_tokens(self):
        self.assertBadPred(lambda p:p['records'][0].update(tokens=True))
    def test_reject_review_changed_answer(self):
        self.assertBadAdj(lambda a:a['results'][0].update(answer_sha256=h('tampered')))
    def test_reject_review_tamper(self):
        self.assertBadAdj(lambda a:a.update(predictions_sha256=h('changed')))
    def test_reject_review_missing(self):
        self.assertBadAdj(lambda a:a['results'].pop())
    def test_reject_fake_independent_reviewer(self):
        self.assertBadAdj(lambda a:a.update(independence_unverified=False))
    def test_reject_review_extra_fields(self):
        self.assertBadAdj(lambda a:a['results'][0].update(production_authorized=True))


if __name__=='__main__':
    unittest.main()
