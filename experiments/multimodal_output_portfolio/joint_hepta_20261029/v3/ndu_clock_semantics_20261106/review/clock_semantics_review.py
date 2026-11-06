"""Independent bounded review of the frozen clock audit; no imported target evaluator.

Uses the retained NDU-JAC implementation on manually authored graphs, direct
terminal-law formulas for the existing 81 cells, and two explicit scope witnesses.
No LLM forward, task tool, random sample, or new primary grid cell is executed.
"""
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal as D, localcontext
from fractions import Fraction as F
import hashlib
import importlib.util
from itertools import product
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
TARGET = Path('/workspace/scratch/e5ecafe4ccc8/next_root_work/ndu_clock_semantics_20261106')
CORE = Path('/workspace/scratch/e5ecafe4ccc8/hepta-research/experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/ndu_jac/core.py')
OUT = Path('/workspace/scratch/e5ecafe4ccc8/next_root_review')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes():
    paths = [TARGET/name for name in ['__init__.py', 'semantics.py', 'study.py', 'protocol.json', 'freeze.json', 'THEORY.md', 'evidence/run-01/result.json']]+[CORE]
    return {str(path):digest(path) for path in paths}


def import_retained_core():
    spec=importlib.util.spec_from_file_location('retained_ndu_core_clock_review', CORE)
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module


def monetary_ce(lottery, eta):
    """Direct, unshifted terminal exponential moment; no target helper is used."""
    return -sum(probability*(-eta*payoff).exp() for probability,payoff in lottery).ln()/eta


def physical_law(graph, policy):
    """Keep declared fee/payment times and the legally delivered X observation.

    Naming the administrative 'resolve' state is not a physical observation.
    Cash flows are immediate in the retained core, so the reward 1 is placed in
    its revealed terminal state, not on the initiating transition.
    """
    transcripts=[]
    def walk(state,time,probability,cashflows,observations):
        for outcome in graph[state][policy[state]]:
            cash=F(str(outcome.reward))-F(str(outcome.cost))-F(str(outcome.adjustment_cost))
            flows=cashflows+([(time,cash)] if cash else [])
            finish=time+F(str(outcome.duration))
            probability2=probability*F(str(outcome.probability))
            obs=observations+([(finish,int(outcome.next_state=='one'))] if outcome.next_state in ('zero','one') else [])
            if outcome.next_state is None:
                transcripts.append((probability2,tuple(flows),tuple(obs),finish))
            else:
                walk(outcome.next_state,finish,probability2,flows,obs)
    walk('root',F(0),F(1),[],[])
    return sorted(transcripts)


def clock_sets(graph):
    clocks={s:set() for s in graph}
    def walk(state,time):
        if time in clocks[state]:return
        clocks[state].add(time)
        for law in graph[state].values():
            for o in law:
                if o.next_state is not None:walk(o.next_state,time+F(str(o.duration)))
    walk('root',F(0))
    return {s:sorted(str(t) for t in times) for s,times in clocks.items()}


def main():
    before=source_hashes()
    frozen=json.loads((TARGET/'freeze.json').read_text())
    protocol=json.loads((TARGET/'protocol.json').read_text())
    retained=json.loads((TARGET/'evidence/run-01/result.json').read_text())
    checks=[]
    def check(name,value):
        checks.append({'name':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    check('frozen_python_and_protocol_hashes_match',all(digest(TARGET/name)==sha for name,sha in frozen['sha256'].items()))
    check('original_run_bound_to_same_source',retained['source_sha256']==frozen['sha256'])
    check('original_run_bound_to_freeze',retained['freeze_sha256']==digest(TARGET/'freeze.json'))
    check('original_protocol_retained',retained['protocol']==protocol)
    check('registered_safe_and_fee_match_current_builder_defaults',D(protocol['safe_reward_at_time_zero'])==D('.16') and D(protocol['probe_launch_charge'])==D('.01'))

    core=import_retained_core()
    O=core.Outcome
    # Handwritten independent graphs. No pair/backward/terminal_law/exhaustive
    # or other function from the new semantics.py module is imported or called.
    coarse={
        'root':{'STOP':(O(1.0,reward=.16),),
                'probe':(O(.5,cost=.01,duration=1.0,next_state='zero'),
                         O(.5,cost=.01,duration=1.0,next_state='one'))},
        'zero':{'STOP':(O(1.0,reward=0.0),)},
        'one':{'STOP':(O(1.0,reward=1.0),)},
    }
    refined={
        'root':{'STOP':(O(1.0,reward=.16),),
                'probe':(O(1.0,cost=.01,duration=1.0,next_state='resolve'),)},
        'resolve':{'forced':(O(.5,next_state='zero'),O(.5,next_state='one'))},
        'zero':{'STOP':(O(1.0,reward=0.0),)},
        'one':{'STOP':(O(1.0,reward=1.0),)},
    }
    legacy=[]
    for name,graph in [('coarse',coarse),('refined',refined)]:
        answer=core.optimal_policy(graph,'root',eta=2.0,rho=math.log(2.0))
        probe_policy={s:{a:float(a==('probe' if s=='root' else next(iter(actions)))) for a in actions} for s,actions in graph.items()}
        evaluation=core.evaluate(graph,'root',probe_policy,eta=2.0,rho=math.log(2.0))
        legacy.append({'representation':name,'probe_value':answer['action_values']['root']['probe'],'forced_probe_policy_value':evaluation['value'],'optimal_value':answer['value'],'root_policy':answer['policy']['root'],'clock_sets':clock_sets(graph)})
        check(name+'_policy_evaluator_agrees_with_optimal_Q_for_probe',abs(evaluation['value']-answer['action_values']['root']['probe'])<1e-15)
    check('retained_core_coarse_probe_value',abs(legacy[0]['probe_value']-.17994274652086124)<1e-15)
    check('retained_core_refined_probe_value',abs(legacy[1]['probe_value']-.1315547923792432)<1e-15)
    check('retained_core_root_action_flip',legacy[0]['root_policy']['probe']==1.0 and legacy[1]['root_policy']['STOP']==1.0)
    physical={}
    for root_action in ['STOP','probe']:
        policies=[]
        for graph in [coarse,refined]:
            policy={s:next(iter(actions)) for s,actions in graph.items()}
            policy['root']=root_action
            policies.append(policy)
        first=physical_law(coarse,policies[0]); second=physical_law(refined,policies[1])
        check('complete_timed_cashflows_and_X_observations_match_'+root_action,first==second)
        physical[root_action]=[{'probability':str(p),'cashflows':[[str(t),str(c)] for t,c in flows],'observations':[[str(t),x] for t,x in obs],'terminal_time':str(t)} for p,flows,obs,t in first]
    check('manual_pair_has_unique_clock_per_reachable_named_state',all(len(times)==1 for row in legacy for times in row['clock_sets'].values()))

    lottery_graph={'root':{'zero':(O(1.0,reward=0.0),),'one':(O(1.0,reward=1.0),)}}
    outside=core.evaluate(lottery_graph,'root',{'root':{'zero':.5,'one':.5}},eta=2.0,rho=math.log(2.0))['value']
    check('retained_core_random_actions_mixed_outside_CE',outside==.5)
    rows=[]
    with localcontext() as context:
        context.prec=135
        tol=D(protocol['equality_tolerance'])
        half=D('.5'); safe=D(protocol['safe_reward_at_time_zero']); fee=D(protocol['probe_launch_charge'])
        inside=monetary_ce([(half,D(0)),(half,D(1))],D(2))
        check('random_action_trajectory_CE_differs_from_retained_core',abs(inside-D('0.28310958475848640648675265754993606832058353577594844828526939635271017115646814593317038461184285060429250676'))<tol and inside<D(str(outside)))
        expected_keys=set(product(map(D,protocol['eta_values']),map(D,protocol['gamma_values']),map(D,protocol['success_probabilities']),protocol['durations']))
        actual_keys=[(D(r['eta']),D(r['gamma']),D(r['p']),r['duration']) for r in retained['rows']]
        check('exactly_existing_81_grid_cells_no_omission_duplicate_or_extension',len(actual_keys)==len(expected_keys)==81 and set(actual_keys)==expected_keys)
        flips=[]
        for row in retained['rows']:
            eta,gamma,p,d=D(row['eta']),D(row['gamma']),D(row['p']),row['duration']
            discount=gamma**d
            # Direct closed forms from the physical payoff, independent of the
            # new module's graph building, Bellman recursion, or enumeration.
            trajectory=-fee-((1-p)+p*(-eta*discount).exp()).ln()/eta
            fixed_refined=-fee-discount*((1-p)+p*(-eta).exp()).ln()/eta
            transported_refined=-fee-discount*((1-p)+p*(-eta*discount).exp()).ln()/(eta*discount)
            expected={
              'coarse':{'transport_probe_value':trajectory,'fixed_local_probe_value':trajectory,'transport_value':max(safe,trajectory),'strong_value':max(safe,trajectory),'fixed_local_value':max(safe,trajectory)},
              'refined':{'transport_probe_value':transported_refined,'fixed_local_probe_value':fixed_refined,'transport_value':max(safe,trajectory),'strong_value':max(safe,trajectory),'fixed_local_value':max(safe,fixed_refined)},
            }
            cell=f'eta={eta},gamma={gamma},p={p},duration={d}'
            max_error=max(abs(D(row[k][field])-value) for k,values in expected.items() for field,value in values.items())
            check('independent_closed_form_all_values_'+cell,max_error<tol)
            choices={'coarse':'probe' if trajectory>safe else 'STOP','refined':'probe' if fixed_refined>safe else 'STOP'}
            check('independent_root_choices_'+cell,all(row[k]['fixed_local_choice']==choices[k] and row[k]['transport_choice']==('probe' if trajectory>safe else 'STOP') and row[k]['strong_choice']==('probe' if trajectory>safe else 'STOP') for k in ['coarse','refined']))
            if choices['coarse']!=choices['refined']:flips.append({'eta':str(eta),'gamma':str(gamma),'p':str(p),'duration':d})
            expected_physical=sorted([(p,-fee+discount,D(d)),(1-p,-fee,D(d))])
            recorded_physical=sorted(tuple(map(D,event)) for event in row['same_physical_terminal_law'])
            check('independent_terminal_payoff_time_law_'+cell,expected_physical==recorded_physical)
            rows.append({'cell':cell,'maximum_decimal_discrepancy':str(max_error),'trajectory_probe':str(trajectory),'fixed_refined_probe':str(fixed_refined)})
        check('two_fixed_local_flips_reproduced',len(flips)==retained['fixed_local_action_flip_cells']==2)
        check('zero_matched_strong_baseline_difference_claim_agrees_with_closed_form',retained['matched_strong_baseline_difference_cells']==0)
        count=81*6+27+2+2+1
        check('518_original_checks_have_correct_declared_accounting',count==retained['check_count']==len(retained['checks'])==518)
        # The separate random-duration example already in the original study.
        random_duration_direct=monetary_ce([(D('.08'),D('-.01')),(D('.32'),D('.49')),(D('.48'),D('-.01')),(D('.12'),D('.24'))],D(2))
        check('existing_random_duration_probe_matches_direct_moment',abs(random_duration_direct-D(retained['details']['random_duration']['probe_value']))<tol)
        # Scope witness only: one merged node is reached at t=0 and t=1.
        # A state-only policy cannot choose safe now and lottery later.
        safe2=D('.35')
        by_time={}
        for actions in product(['safe','risk'],repeat=2):
            payoff_law=[]
            for t,action in enumerate(actions):
                if action=='safe':payoff_law.append((half,(half**t)*safe2))
                else:payoff_law.extend([(D('.25'),D(0)),(D('.25'),half**t)])
            by_time['/'.join(actions)]=monetary_ce(payoff_law,D(2))
        stationary=max(by_time['safe/safe'],by_time['risk/risk'])
        adaptive=max(by_time.values())
        check('unique_clock_precondition_matters_for_policy_enumeration',by_time['safe/risk']==adaptive and adaptive>stationary)
        clock_scope={'classification':'out_of_contract_analytic_scope_witness; not a new grid cell','eta':'2','gamma':'.5','safe_reward':'.35','arrival_clocks_at_same_named_state':[0,1],
                     'policy_values':{k:str(v) for k,v in by_time.items()},'best_state_only':str(stationary),'best_clock_conditioned':str(adaptive)}
        # Scope witness only: an unobserved payment X is perfectly correlated
        # with later Y=X and is not encoded in the child observable history.
        # Marginal continuation CE cannot be factored out of the joint moment.
        actual_hidden=monetary_ce([(half,D(0)),(half,D(2))],D(2))
        invalid_factorization=2*inside
        check('hidden_past_cashflow_requires_additional_conditional_sufficiency',abs(actual_hidden-invalid_factorization)>D('.1'))
        hidden_scope={'classification':'assumption witness, not a claim about the registered fully observed graphs','X':'Bernoulli(1/2)','Y':'X','duration':0,'eta':2,
                     'actual_CE_of_X_plus_Y':str(actual_hidden),'incorrect_sum_of_marginal_CEs':str(invalid_factorization),
                     'needed_condition':'r and d are measurable in child history, or future payoff is conditionally independent of their omitted components given child history'}
    after=source_hashes()
    check('reviewed_sources_and_evidence_not_modified',before==after)
    report={'schema':'ndu.clock-semantics.independent-internal-review.v1','created_at_utc':datetime.now(timezone.utc).isoformat(),'reviewer':'/root/frozen_llm','author_of_reviewed_unit':False,
        'review_scope':'Existing 81 cells, existing random-duration and random-action checks, retained-core handbuilt representative, plus explicit assumption witnesses outside the primary grid',
        'imports_target_semantics':False,'calls_target_graph_or_computation_functions':False,'model_calls':0,'real_task_tool_calls':0,'new_random_samples':0,'primary_grid_expanded':False,
        'source_sha256':before,'checks':checks,'check_count':len(checks),'all_checks_pass':all(x['passed'] for x in checks),
        'retained_core_reproduction':legacy,'physical_transcript_reconstruction':physical,
        'action_randomization':{'retained_outside_CE':outside,'terminal_inside_CE':str(inside)},
        'independent_closed_form_rows':rows,'reproduced_fixed_local_flips':flips,
        'unique_clock_policy_scope_witness':clock_scope,'unobserved_cashflow_assumption_witness':hidden_scope,
        'findings':[
          {'severity':'required_theory_scope_clarification','finding':'Bellman factorization needs observed/child-history-measurable interim cash flows and duration, or the corresponding conditional sufficiency. Full observable history alone does not cover omitted hidden cash flows correlated with future payoff. Registered examples satisfy the needed condition.'},
          {'severity':'scope_boundary_not_current_result_failure','finding':'exhaustive uses policy[state], whereas backward uses state and elapsed time. Its documented unique-clock precondition is necessary, not an automatic property of validate. All registered graph families satisfy it.'},
          {'severity':'configuration_coupling_not_current_result_failure','finding':'study.py invokes pair(p,duration) without passing the safe/launch protocol fields. The frozen values equal the builder defaults; future protocol changes must not silently leave defaults unchanged.'},
          {'severity':'evidence_scope','finding':'Equal terminal payoff/time alone is insufficient for general adaptive-policy process equivalence. The explicit forced-wait pair does preserve timed cashflows, observation timing, and opportunities, as independently reconstructed for both root choices.'}],
        'disposition':'PASS_REGISTERED_SEMANTIC_RESULT; clarify conditional sufficiency before any broader Bellman claim; no new RL advantage',
        'external_review':False,'formal_outward_rounding_claimed':False}
    destination=OUT/'clock_semantics_review.json'
    with destination.open('x') as stream:json.dump(report,stream,indent=2);stream.write('\n')
    print(json.dumps({'all_checks_pass':report['all_checks_pass'],'checks':len(checks),'legacy_reproduction':legacy,'flips':flips,'action_randomization':report['action_randomization'],'scope_witness':clock_scope,'hidden_cashflow':hidden_scope,'disposition':report['disposition']},indent=2))


if __name__=='__main__':main()
