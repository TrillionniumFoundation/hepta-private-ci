"""V15 source-first cost-bound System2 and Cell Split qualification, SHADOW_ONLY.

This executable models a *finite, precommitted, additive-cost special case* of
recursive utility. It is NOT an FBSDE solver, pretrained execution, trusted
original-model receipt, independent evaluator, split executor or FinalUse owner.

Planner never sees post-execution answers or labels. Reviewer validates exactly
bound physical-result *claims* and produces descriptive reports only; arbitrary
JSON and its SHA are not proof of original inference or source independence.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re

PREFIX = 'hepta.stem.v15.system2-split.v1'
ARMS = ('stop', 'fixed_one', 'greedy_one', 'ndu_shadow')
SPLIT_ARMS = ('parent', 'split')
ACTIONS = ('retrieve', 'verify', 'branch', 'continue')
HASH = re.compile(r'^[0-9a-f]{64}$')
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_CASES = 4096
MAX_NODES = 48
MAX_DEPTH = 8
MAX_BUDGET = 16_384
MIN_FAMILIES = 200


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def exact(value, keys, name):
    require(type(value) is dict and set(value) == set(keys), name + ' shape')


def sha_obj(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                 ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def hex_sha(value):
    return type(value) is str and HASH.fullmatch(value) is not None


def bounded_id(value, name='ID'):
    require(type(value) is str and 1 <= len(value) <= 128
            and all(32 <= ord(c) <= 126 for c in value), name)


def unsigned(value, maximum=10_000_000):
    return type(value) is int and 0 <= value <= maximum


def load_json(path):
    p = Path(path)
    require(p.is_file() and p.stat().st_size <= MAX_JSON_BYTES, 'missing/oversized input')
    def unique(pairs):
        obj = {}
        for k, v in pairs:
            require(k not in obj, 'duplicate JSON property')
            obj[k] = v
        return obj
    def invalid_constant(value):
        raise ValueError('nonfinite number: ' + value)
    return json.loads(p.read_bytes(), object_pairs_hook=unique,
                      parse_constant=invalid_constant)


def validate_control_study(study):
    """No post-label fields are admitted, even as additional JSON keys."""
    exact(study, ('schema','frozen_before_execution','source_only',
           'production_authorized','objective_sha256','model', 'scope',
           'prices', 'limits', 'cases'), 'control study')
    require(study['schema'] == PREFIX + '.control-study'
            and study['frozen_before_execution'] is True
            and study['source_only'] is True
            and study['production_authorized'] is False, 'unsafe study status')
    require(hex_sha(study['objective_sha256']), 'objective SHA')
    exact(study['model'], ('stem_sha256','reader_sha256','tokenizer_sha256',
                          'runtime_sha256'), 'model')
    require(all(hex_sha(s) for s in study['model'].values()), 'unbound model')
    exact(study['scope'], ('principal','purpose','generation','authority_epoch'), 'scope')
    bounded_id(study['scope']['principal'])
    bounded_id(study['scope']['purpose'])
    require(unsigned(study['scope']['generation'])
            and study['scope']['generation'] > 0
            and unsigned(study['scope']['authority_epoch'])
            and study['scope']['authority_epoch'] > 0, 'scope generation/epoch')
    exact(study['prices'], ('correct_reward_micro','cpu_ms_price_micro',
                            'token_price_micro'), 'prices')
    require(unsigned(study['prices']['correct_reward_micro'], 100_000_000)
            and study['prices']['correct_reward_micro'] > 0
            and unsigned(study['prices']['cpu_ms_price_micro'], 100_000)
            and unsigned(study['prices']['token_price_micro'], 100_000), 'cost profile')
    exact(study['limits'], ('extra_cpu_ms','extra_tokens','max_total_cpu_ms',
                            'max_total_tokens','max_depth'), 'limits')
    require(unsigned(study['limits']['extra_cpu_ms'], MAX_BUDGET)
            and unsigned(study['limits']['extra_tokens'], MAX_BUDGET)
            and unsigned(study['limits']['max_total_cpu_ms'], 10_000_000)
            and unsigned(study['limits']['max_total_tokens'], 10_000_000)
            and study['limits']['max_total_cpu_ms'] > 0
            and study['limits']['max_total_tokens'] > 0
            and type(study['limits']['max_depth']) is int
            and 1 <= study['limits']['max_depth'] <= MAX_DEPTH, 'limits')
    cases = study['cases']
    require(type(cases) is list and 1 <= len(cases) <= MAX_CASES, 'case census')
    case_ids = set()
    for case in cases:
        exact(case, ('id','family','window','input_sha256','root','nodes'), 'case')
        for field in ('id','family','window','root'):
            bounded_id(case[field], field)
        require(case['id'] not in case_ids, 'duplicate case')
        case_ids.add(case['id'])
        require(hex_sha(case['input_sha256']), 'input SHA')
        nodes = case['nodes']
        require(type(nodes) is list and 1 <= len(nodes) <= MAX_NODES, 'node census')
        lookup = {}
        for node in nodes:
            exact(node, ('id','request_sha256','stop_quality_bps','actions'), 'node')
            bounded_id(node['id'], 'node ID')
            require(hex_sha(node['request_sha256']), 'state-conditioned request SHA')
            require(node['id'] not in lookup, 'duplicate node')
            require(unsigned(node['stop_quality_bps'], 10_000), 'stop quality')
            actions = node['actions']
            require(type(actions) is list and len(actions) <= 4, 'action count')
            seen_actions = set()
            for action in actions:
                exact(action, ('id','kind','cpu_ms','tokens','outcomes'), 'action')
                bounded_id(action['id'], 'action ID')
                require(action['id'] not in seen_actions, 'duplicate action')
                seen_actions.add(action['id'])
                require(action['kind'] in ACTIONS, 'action kind')
                require(unsigned(action['cpu_ms'], MAX_BUDGET)
                        and unsigned(action['tokens'], MAX_BUDGET)
                        and action['cpu_ms'] + action['tokens'] > 0, 'action work')
                outcomes = action['outcomes']
                require(type(outcomes) is list and 1 <= len(outcomes) <= 8,
                        'outcome count')
                children = set()
                total = 0
                for edge in outcomes:
                    exact(edge, ('node','p_bps'), 'edge')
                    bounded_id(edge['node'], 'edge node')
                    require(edge['node'] not in children, 'duplicate edge')
                    children.add(edge['node'])
                    require(type(edge['p_bps']) is int
                            and 1 <= edge['p_bps'] <= 10_000, 'edge probability')
                    total += edge['p_bps']
                require(total == 10_000, 'probabilities must sum to 10000')
            lookup[node['id']] = node
        require(case['root'] in lookup, 'missing root')
        require(lookup[case['root']]['request_sha256'] == case['input_sha256']
                and len({n['request_sha256'] for n in nodes}) == len(nodes),
                'root input/state change not source-bound')
        # Conservative tree, not an arbitrary graph: no hidden cycles, merges,
        # unreachable pre-labelled states or depth beyond the admitted horizon.
        incoming = defaultdict(int)
        for node in nodes:
            for action in node['actions']:
                for edge in action['outcomes']:
                    require(edge['node'] in lookup and edge['node'] != node['id'],
                            'foreign/self edge')
                    incoming[edge['node']] += 1
        require(incoming[case['root']] == 0, 'root has incoming edge')
        require(all(incoming[n] == 1 for n in lookup if n != case['root']),
                'non-tree node / missing parent')
        reached = set()
        def visit(node_id, depth):
            require(node_id not in reached, 'cyclic graph')
            require(depth <= study['limits']['max_depth'], 'excess depth')
            reached.add(node_id)
            for action in lookup[node_id]['actions']:
                for edge in action['outcomes']:
                    visit(edge['node'], depth + 1)
        # Common child through two alternative actions is intentionally
        # rejected by the unique-predecessor check above.
        visit(case['root'], 0)
        require(len(reached) == len(lookup), 'unreachable nodes')
    return True


def _case_policies(study, case):
    nodes = {n['id']:n for n in case['nodes']}
    prices = study['prices']
    cap_cpu = study['limits']['extra_cpu_ms']
    cap_tokens = study['limits']['extra_tokens']
    max_depth = study['limits']['max_depth']
    reward = prices['correct_reward_micro']
    def stop_value(node_id):
        return Fraction(nodes[node_id]['stop_quality_bps'] * reward, 10_000)
    def affordable(action, cpu, tokens):
        return action['cpu_ms'] <= cpu and action['tokens'] <= tokens
    def action_cost(a):
        return a['cpu_ms'] * prices['cpu_ms_price_micro'] + a['tokens'] * prices['token_price_micro']
    @lru_cache(maxsize=4096)
    def solve(node_id, cpu, tokens, depth):
        best = stop_value(node_id)
        choice = 'stop'
        if depth >= max_depth:
            return best, choice
        for action in sorted(nodes[node_id]['actions'], key=lambda a:a['id']):
            if not affordable(action, cpu, tokens):
                continue
            expected = sum((Fraction(e['p_bps'], 10_000) *
                   solve(e['node'], cpu - action['cpu_ms'],
                         tokens - action['tokens'], depth + 1)[0]
                   for e in action['outcomes']), Fraction(0)) - action_cost(action)
            # A tie stops, avoiding redundant speculative work.
            if expected > best:
                best, choice = expected, action['id']
        return best, choice
    def rollout(root_choice=None, *, mode='fixed'):
        policy = {}
        def walk(node_id, cpu, tokens, depth, forced=None):
            if forced is not None:
                choice = forced
            elif mode == 'ndu_shadow':
                choice = solve(node_id, cpu, tokens, depth)[1]
            else:
                choice = 'stop'
            policy[node_id] = choice
            if choice == 'stop':
                return
            action = next(a for a in nodes[node_id]['actions'] if a['id'] == choice)
            for edge in action['outcomes']:
                walk(edge['node'], cpu - action['cpu_ms'],
                     tokens - action['tokens'], depth + 1)
        walk(case['root'], cap_cpu, cap_tokens, 0, root_choice)
        return policy
    eligible = [a for a in nodes[case['root']]['actions']
                if affordable(a, cap_cpu, cap_tokens)]
    first = sorted(eligible, key=lambda a:a['id'])[0]['id'] if eligible else 'stop'
    # Greedy is a fixed one-action baseline that maximizes forecast post-action
    # stop correctness WITHOUT paying an estimated extra-work penalty.
    greedy = sorted(eligible, key=lambda a:(-
        sum(e['p_bps'] * nodes[e['node']]['stop_quality_bps'] for e in a['outcomes']),
        a['id']))[0]['id'] if eligible else 'stop'
    return {
        'stop':rollout('stop'),
        'fixed_one':rollout(first),
        'greedy_one':rollout(greedy),
        'ndu_shadow':rollout(mode='ndu_shadow')
    }


def plan_control(study):
    validate_control_study(study)
    return {
        'schema':PREFIX+'.policy-seal',
        'study_sha256':sha_obj(study),
        'algorithm':'finite-tree-additive-expectation-v1-not-general-FBSDE',
        'source_only':True,
        'labels_seen':False,
        'production_authorized':False,
        'cases':[
            {'case_id':c['id'],'policies':_case_policies(study,c)}
            for c in study['cases']
        ],
        'decision':'HOLD_NO_GO'
    }


def validate_control_execution(study, sealed, executed):
    # Recompute the whole policy from the source-only study, rather than
    # trusting self-declared selected actions, counters or digest strings.
    require(sealed == plan_control(study), 'policy seal mismatch')
    exact(executed, ('schema','study_sha256','policy_sha256',
                     'model_execution_source','sealed_before_adjudication',
                     'production_authorized','records'), 'executed')
    require(executed['schema'] == PREFIX+'.execution'
            and executed['study_sha256'] == sha_obj(study)
            and executed['policy_sha256'] == sha_obj(sealed)
            and executed['model_execution_source'] == 'external_original_required'
            and executed['sealed_before_adjudication'] is True
            and executed['production_authorized'] is False, 'unbound execution')
    records = executed['records']
    require(type(records) is list and len(records) == len(study['cases']) * len(ARMS),
            'incomplete execution census')
    cases = {c['id']:c for c in study['cases']}
    policies = {s['case_id']:s['policies'] for s in sealed['cases']}
    used = {}
    # An immutable terminal request names one deterministic Reader result per
    # case, regardless of the policy arm that reached it. A request digest is
    # not proof that the original call happened; this checks cross-arm claims.
    terminal_outputs = {}
    observed_transitions = {}
    for row in records:
        exact(row, ('case_id','arm','input_sha256','reader_sha256',
                    'answer_sha256','terminal_request_sha256',
                    'visited_nodes','actions_taken', 'cpu_ms','tokens','citations_entailed_claimed'), 'execution row')
        key = row['case_id'], row['arm']
        require(key not in used and key[0] in cases and key[1] in ARMS,
                'duplicate/unknown arm')
        case = cases[key[0]]
        require(row['input_sha256'] == case['input_sha256']
                and row['reader_sha256'] == study['model']['reader_sha256']
                and hex_sha(row['answer_sha256']), 'model/answer/input substitution')
        # Real physical units are mandatory in every arm; no zero-cost cache
        # assertion or dummy physical receipt is deduced from metadata.
        require(unsigned(row['cpu_ms'], 10_000_000)
                and unsigned(row['tokens'], 10_000_000)
                and type(row['citations_entailed_claimed']) is bool,
                'missing/invalid physical counters')
        visits, actions_taken = row['visited_nodes'], row['actions_taken']
        require(type(visits) is list and type(actions_taken) is list
                and 1 <= len(visits) <= MAX_DEPTH + 1
                and len(actions_taken) == len(visits) - 1,
                'trace lengths')
        nodes = {n['id']:n for n in case['nodes']}
        remaining_cpu, remaining_tok = (study['limits']['extra_cpu_ms'],
                                        study['limits']['extra_tokens'])
        require(visits[0] == case['root'], 'wrong starting state')
        require(row['terminal_request_sha256'] ==
                nodes[visits[-1]]['request_sha256'] if visits[-1] in nodes
                else False, 'terminal model input did not change with state')
        bound_policy = policies[key[0]][key[1]]
        for i, node_id in enumerate(visits):
            require(type(node_id) is str and node_id in nodes and node_id in bound_policy,
                    'foreign/unscheduled state')
            choice = bound_policy[node_id]
            if i == len(visits)-1:
                require(choice == 'stop', 'trace terminated without stop')
                break
            a_id = actions_taken[i]
            require(type(a_id) is str and a_id == choice and choice != 'stop',
                    'trace disobeyed sealed decision')
            matches = [a for a in nodes[node_id]['actions'] if a['id'] == a_id]
            require(len(matches) == 1, 'nonexistent action')
            action = matches[0]
            require(action['cpu_ms'] <= remaining_cpu
                    and action['tokens'] <= remaining_tok, 'forecast budget overspent')
            remaining_cpu -= action['cpu_ms']
            remaining_tok -= action['tokens']
            require(visits[i+1] in [e['node'] for e in action['outcomes']],
                    'impossible observed transition')
            # This source-only qualification declares deterministic observed
            # transitions. Unpinned stochastic environments need a *new* seed/
            # observation-bound schema; do not silently treat a different
            # successor as a policy benefit.
            transition_key = (key[0], node_id, a_id)
            successor = visits[i+1]
            if transition_key in observed_transitions:
                require(observed_transitions[transition_key] == successor,
                        'same source/action observed conflicting successors')
            else:
                observed_transitions[transition_key] = successor
        terminal_key = (key[0], row['terminal_request_sha256'])
        terminal_claim = (row['answer_sha256'],
                          row['citations_entailed_claimed'])
        if terminal_key in terminal_outputs:
            require(terminal_outputs[terminal_key] == terminal_claim,
                    'same terminal Reader request claimed conflicting outputs')
        else:
            terminal_outputs[terminal_key] = terminal_claim
        # The actually metered end-to-end spend is separate from modelled
        # incremental work; require a ceiling, but never pretend they match.
        require(row['cpu_ms'] <= study['limits']['max_total_cpu_ms']
                and row['tokens'] <= study['limits']['max_total_tokens'],
                'recorded total physical budget overspent')
        used[key] = row
    return used


def review_control(study, sealed, executed, adjudication):
    outputs = validate_control_execution(study, sealed, executed)
    exact(adjudication, ('schema','study_sha256','execution_sha256',
                         'reviewer_id','independence_unverified','results'),
                         'adjudication')
    require(adjudication['schema'] == PREFIX+'.adjudication'
            and adjudication['study_sha256'] == sha_obj(study)
            and adjudication['execution_sha256'] == sha_obj(executed)
            and adjudication['independence_unverified'] is True,
            'untrusted adjudication')
    bounded_id(adjudication['reviewer_id'], 'reviewer')
    results = adjudication['results']
    require(type(results) is list and len(results) == len(outputs),
            'incomplete judgment census')
    judged = {}
    for r in results:
        exact(r, ('case_id','arm','answer_sha256','correct','citations_entailed'),
              'adjudication row')
        key = r['case_id'],r['arm']
        require(key in outputs and key not in judged
                and r['answer_sha256'] == outputs[key]['answer_sha256']
                and type(r['correct']) is bool
                and type(r['citations_entailed']) is bool,
                'invalid/duplicated judgment')
        judged[key] = r
    # Cross-arm self-consistency: the same case + request + answer cannot
    # acquire different post-seal correctness or citation judgments merely
    # because the research policy label changed.
    terminal_judgments = {}
    for (cid, arm), score in judged.items():
        row = outputs[cid, arm]
        terminal_key = cid, row['terminal_request_sha256'], row['answer_sha256']
        assessed = score['correct'], score['citations_entailed']
        if terminal_key in terminal_judgments:
            require(terminal_judgments[terminal_key] == assessed,
                    'same terminal Reader answer received conflicting judgments')
        else:
            terminal_judgments[terminal_key] = assessed
    tally = {arm:dict(cases=0,correct=0,entailed=0,cpu_ms=0,tokens=0,
                     net_micro=0) for arm in ARMS}
    for (cid,arm),row in outputs.items():
        score = judged[cid,arm]
        t = tally[arm]
        t['cases'] += 1
        t['correct'] += int(score['correct'])
        t['entailed'] += int(score['citations_entailed'])
        t['cpu_ms'] += row['cpu_ms']
        t['tokens'] += row['tokens']
        t['net_micro'] += int(score['correct']) * study['prices']['correct_reward_micro'] \
            - row['cpu_ms'] * study['prices']['cpu_ms_price_micro'] \
            - row['tokens'] * study['prices']['token_price_micro']
    deltas = {}
    for ref in ARMS[:-1]:
        plus,minus = 0,0
        for c in study['cases']:
            cid=c['id']
            a=judged[cid,'ndu_shadow']['correct']
            b=judged[cid,ref]['correct']
            plus += int(a and not b)
            minus += int(b and not a)
        changed = [c['id'] for c in study['cases']
            if outputs[c['id'],'ndu_shadow']['terminal_request_sha256'] !=
               outputs[c['id'],ref]['terminal_request_sha256']]
        different_answers = [c['id'] for c in study['cases']
            if outputs[c['id'],'ndu_shadow']['answer_sha256'] !=
               outputs[c['id'],ref]['answer_sha256']]
        require(set(different_answers) <= set(changed),
                'changed answer without changed frozen Reader input')
        deltas[ref]={
            'ndu_only_correct':plus,
            'reference_only_correct':minus,
            'net_micro_delta':tally['ndu_shadow']['net_micro']-tally[ref]['net_micro'],
            'changed_terminal_cases':len(changed),
            'changed_answer_cases':len(different_answers),
            'unchanged_terminal_quality_delta':sum(
                 int(judged[c['id'],'ndu_shadow']['correct']) -
                 int(judged[c['id'],ref]['correct']) for c in study['cases']
                 if c['id'] not in changed),
        }
    return {
        'schema':PREFIX+'.control-review',
        'study_sha256':sha_obj(study),
        'policy_sha256':sha_obj(sealed),
        'execution_sha256':sha_obj(executed),
        'adjudication_sha256':sha_obj(adjudication),
        'per_arm':tally,
        'ndu_paired_deltas':deltas,
        'source_families_claimed_unverified':len({c['family'] for c in study['cases']}),
        'windows_claimed_unverified':sorted({c['window'] for c in study['cases']}),
        'general_fbsde_solution_verified':False,
        'reader_sufficiency_verified':False,
        'original_execution_authenticated':False,
        'independent_outcome_authenticated':False,
        'net_task_gain_qualified':False,
        'system2_activation_authorized':False,
        'production_authorized':False,
        'decision':'HOLD_NO_GO'
    }


def validate_split_study(study):
    exact(study, ('schema','source_only','frozen_before_predictions',
                  'production_authorized','objective_sha256','stem_sha256',
                  'parent_head_sha256','split_head_sha256','cost_profile',
                  'max_old_regressions','cases'), 'split study')
    require(study['schema']==PREFIX+'.split-study'
            and study['source_only'] is True
            and study['frozen_before_predictions'] is True
            and study['production_authorized'] is False, 'unsafe split study')
    require(all(hex_sha(study[k]) for k in (
        'objective_sha256','stem_sha256','parent_head_sha256','split_head_sha256'))
        and study['parent_head_sha256'] != study['split_head_sha256'],
        'split source/head identity')
    exact(study['cost_profile'], ('correct_reward_micro','cpu_ms_price_micro',
                                 'token_price_micro','extra_training_micro',
                                 'extra_migration_micro','extra_evaluation_micro'), 'cost')
    require(all(unsigned(v, 100_000_000) for v in study['cost_profile'].values())
            and study['cost_profile']['correct_reward_micro'] > 0, 'split prices')
    require(unsigned(study['max_old_regressions'], MAX_CASES), 'regression limit')
    cases=study['cases']
    require(type(cases) is list and 1 <= len(cases) <= MAX_CASES, 'split cases')
    seen=set()
    for c in cases:
        exact(c, ('id','family','window','cohort','input_sha256'), 'split case')
        for k in ('id','family','window'):
            bounded_id(c[k], k)
        require(c['id'] not in seen, 'split case duplicate')
        seen.add(c['id'])
        require(c['cohort'] in ('old','future') and hex_sha(c['input_sha256']),
                'split cohort/source')
    require({c['cohort'] for c in cases} == {'old','future'},
            'old/future required')
    old={c['family'] for c in cases if c['cohort']=='old'}
    new={c['family'] for c in cases if c['cohort']=='future'}
    require(not (old&new), 'family leakage across old and future')
    return True


def review_split(study, predictions, adjudication):
    validate_split_study(study)
    exact(predictions, ('schema','study_sha256','source','sealed_before_adjudication',
                        'production_authorized','records'), 'split predictions')
    require(predictions['schema']==PREFIX+'.split-predictions'
            and predictions['study_sha256']==sha_obj(study)
            and predictions['source']=='external_original_required'
            and predictions['sealed_before_adjudication'] is True
            and predictions['production_authorized'] is False,
            'unsafe split predictions')
    cases={c['id']:c for c in study['cases']}
    rows=predictions['records']
    require(type(rows) is list and len(rows)==len(cases)*2, 'split prediction census')
    results={}
    for row in rows:
        exact(row, ('case_id','arm','input_sha256','head_sha256',
                    'answer_sha256','cpu_ms','tokens'), 'split prediction row')
        key=row['case_id'],row['arm']
        require(key[0] in cases and key[1] in SPLIT_ARMS and key not in results,
                'duplicate/missing split output')
        require(row['input_sha256']==cases[key[0]]['input_sha256']
                and row['head_sha256']==study['parent_head_sha256' if key[1]=='parent'
                                                   else 'split_head_sha256']
                and hex_sha(row['answer_sha256'])
                and unsigned(row['cpu_ms']) and unsigned(row['tokens']),
                'split output substitution/cost')
        results[key]=row
    exact(adjudication, ('schema','study_sha256','predictions_sha256',
                         'reviewer_id','independence_unverified','results'),
                         'split adjudication')
    require(adjudication['schema']==PREFIX+'.split-adjudication'
            and adjudication['study_sha256']==sha_obj(study)
            and adjudication['predictions_sha256']==sha_obj(predictions)
            and adjudication['independence_unverified'] is True,
            'split adjudication lineage')
    bounded_id(adjudication['reviewer_id'], 'split reviewer')
    verdicts={}
    votes=adjudication['results']
    require(type(votes) is list and len(votes)==len(results), 'split judgment census')
    for row in votes:
        exact(row, ('case_id','arm','answer_sha256','correct'), 'split verdict')
        key=row['case_id'],row['arm']
        require(key in results and key not in verdicts
                and row['answer_sha256']==results[key]['answer_sha256']
                and type(row['correct']) is bool, 'split changed answer/duplicated verdict')
        verdicts[key]=row['correct']
    counts={cohort:{arm:0 for arm in SPLIT_ARMS} for cohort in ('old','future')}
    old_regressions=0
    for c in study['cases']:
        cid,cohort=c['id'],c['cohort']
        for arm in SPLIT_ARMS:
            counts[cohort][arm] += int(verdicts[cid,arm])
        if cohort=='old' and verdicts[cid,'parent'] and not verdicts[cid,'split']:
            old_regressions+=1
    prices=study['cost_profile']
    net={}
    for arm in SPLIT_ARMS:
        net[arm] = sum(int(verdicts[c['id'],arm])*prices['correct_reward_micro']
                   - results[c['id'],arm]['cpu_ms']*prices['cpu_ms_price_micro']
                   - results[c['id'],arm]['tokens']*prices['token_price_micro']
                   for c in study['cases'])
    net['split'] -= sum(prices[k] for k in (
        'extra_training_micro','extra_migration_micro','extra_evaluation_micro'))
    families={c['family'] for c in study['cases']}
    future_windows={c['window'] for c in study['cases'] if c['cohort']=='future'}
    improvement=(counts['future']['split']>counts['future']['parent']
        and old_regressions<=study['max_old_regressions']
        and counts['old']['split']>=counts['old']['parent']
        and net['split']>net['parent'])
    window_family_counts = {w:len({c['family'] for c in study['cases']
                   if c['cohort']=='future' and c['window']==w})
                   for w in future_windows}
    coverage=(len(families)>=MIN_FAMILIES and len({c['family'] for c in study['cases']
             if c['cohort']=='old'})>=50 and len({c['family'] for c in study['cases']
             if c['cohort']=='future'})>=100 and len(future_windows)>=2
             and all(v>=30 for v in window_family_counts.values()))
    return {
        'schema':PREFIX+'.split-review',
        'study_sha256':sha_obj(study),
        'predictions_sha256':sha_obj(predictions),
        'adjudication_sha256':sha_obj(adjudication),
        'cohort_correct':counts,
        'old_parent_correct_to_split_wrong':old_regressions,
        'net_micro':net,
        'source_families_claimed_unverified':len(families),
        'future_windows_claimed_unverified':sorted(future_windows),
        'per_future_window_claimed_family_count':window_family_counts,
        'numeric_gain_gate':improvement,
        'sample_window_gate':coverage,
        'independent_source_family_authenticated':False,
        'future_observer_authenticated':False,
        'real_model_execution_authenticated':False,
        'cell_split_authorized':False,
        'model_promotion_authorized':False,
        'production_authorized':False,
        'decision':'HOLD_NO_GO'
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    modes=p.add_subparsers(dest='mode',required=True)
    a=modes.add_parser('plan',help='Freeze deterministic four-arm policy seal')
    a.add_argument('--study',required=True)
    a=modes.add_parser('review',help='Review separately sealed original executions')
    a.add_argument('--study',required=True)
    a.add_argument('--policy',required=True)
    a.add_argument('--execution',required=True)
    a.add_argument('--adjudication',required=True)
    a=modes.add_parser('split',help='Review paired old/future split candidates')
    a.add_argument('--study',required=True)
    a.add_argument('--predictions',required=True)
    a.add_argument('--adjudication',required=True)
    a=p.parse_args()
    if a.mode=='plan':
        out=plan_control(load_json(a.study))
    elif a.mode=='review':
        out=review_control(load_json(a.study),load_json(a.policy),
                           load_json(a.execution),load_json(a.adjudication))
    else:
        out=review_split(load_json(a.study),load_json(a.predictions),
                         load_json(a.adjudication))
    print(json.dumps(out,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False))

if __name__=='__main__':
    main()
