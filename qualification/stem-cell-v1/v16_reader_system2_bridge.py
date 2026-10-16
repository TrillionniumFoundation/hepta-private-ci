"""Source-first V14 Reader -> V15 cost-bound System2 evidence bridge.

This is a RESEARCH-ONLY, DENY_ALL verifier. It cannot authenticate source/model,
forecast pre-registration, original inference or the independent evaluator.
No score, bootstrap interval or record in this module grants FinalUse or Cell Split.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from fractions import Fraction
from hashlib import sha256
import json
import random

import v14_reader_sufficiency_gate as v14
import v15_system2_split_shadow as v15

SCHEMA = 'hepta.stem.v16.reader-system2-bridge.v1'
BOOTSTRAP_DRAWS = 1024
COMPARATORS = ('stop', 'fixed_one', 'greedy_one')


def require(value, message):
    if not value:
        raise ValueError(message)


def source_first_bridge(v14_plan, v15_study):
    """Validate frozen source-only inputs; NEVER inspect predictions or gold."""
    v14.check_plan(v14_plan)
    v15.validate_control_study(v15_study)
    require(v14_plan['objective_sha256'] == v15_study['objective_sha256'],
            'objective mismatch')
    c = v14_plan['models']['candidate']
    m = v15_study['model']
    require(c['weights_sha256'] == m['reader_sha256']
            and c['tokenizer_sha256'] == m['tokenizer_sha256']
            and c['runtime_sha256'] == m['runtime_sha256'],
            'Reader/tokenizer/runtime mismatch')
    src = {c['id']: c for c in v14_plan['cases']}
    require(len(src) == len(v15_study['cases']), 'case-roster mismatch')
    bindings = []
    for case in v15_study['cases']:
        cid = case['id']
        require(cid in src, 'foreign System2 case')
        original = src[cid]
        require(original['family'] == case['family']
                and original['window'] == case['window'],
                'changed source group or time window')
        # Only evaluate incremental System2 from *exactly* the V14 sufficient
        # evidence request. We do not confuse it with its retrieved/lesioned arm.
        sufficient_request = original['arms']['sufficient']['request_sha256']
        require(case['input_sha256'] == sufficient_request,
                'System2 root is not the frozen sufficient-evidence request')
        require(next(n for n in case['nodes'] if n['id'] == case['root'])
                    ['request_sha256'] == sufficient_request,
                'changed System2 root request')
        bindings.append({'case_id': cid, 'family': case['family'],
                         'window': case['window'],
                         'question_sha256': original['question_sha256'],
                         'root_request_sha256': sufficient_request,
                         'root_forecast_bps': next(n for n in case['nodes']
                                if n['id'] == case['root'])['stop_quality_bps']})
    return {
        'schema': SCHEMA+'.source-first-seal',
        'v14_plan_sha256': v15.sha_obj(v14_plan),
        'v15_study_sha256': v15.sha_obj(v15_study),
        'bindings': bindings,
        'source_only': True,
        'labels_seen': False,
        'model_host_authenticated': False,
        'independent_evaluator_authenticated': False,
        'production_authorized': False,
        'decision': 'HOLD_NO_GO',
    }


def _floor_rank(sorted_values, numerator, denominator):
    index = min(len(sorted_values)-1, max(0, (len(sorted_values)-1)*numerator//denominator))
    return sorted_values[index]


def _bootstrapped_cluster_mean(groups, seed):
    """Paired, family-clustered; case-weighted, never pretend cases are roots."""
    require(bool(groups), 'missing source-family groups')
    keys = sorted(groups)
    n = len(keys)
    rng = random.Random(seed)
    boot = []
    for _ in range(BOOTSTRAP_DRAWS):
        net, cases = 0, 0
        for _ in range(n):
            value = groups[keys[rng.randrange(n)]]
            net += value['net_micro']
            cases += value['cases']
        boot.append(Fraction(net, cases))
    boot.sort()
    return [str(_floor_rank(boot, 25, 1000)),
            str(_floor_rank(boot, 975, 1000))]


def _per_family_statistics(v15_study, outputs, scores, arm, reference):
    family = {c['id']: c['family'] for c in v15_study['cases']}
    price = v15_study['prices']
    group = defaultdict(lambda: {'cases':0, 'net_micro':0,
                                  'correct_delta':0, 'cpu_ms_delta':0,
                                  'token_delta':0})
    for cid in family:
        a = outputs[cid,arm]
        b = outputs[cid,reference]
        correct_diff = (int(scores[cid,arm]['correct']) -
                        int(scores[cid,reference]['correct']))
        cpu_diff = a['cpu_ms']-b['cpu_ms']
        token_diff = a['tokens']-b['tokens']
        g = group[family[cid]]
        g['cases'] += 1
        g['correct_delta'] += correct_diff
        g['cpu_ms_delta'] += cpu_diff
        g['token_delta'] += token_diff
        g['net_micro'] += (correct_diff*price['correct_reward_micro']
                          - cpu_diff*price['cpu_ms_price_micro']
                          - token_diff*price['token_price_micro'])
    return group


def review_bridge(v14_plan, v14_predictions, v14_adjudication,
                  v15_study, v15_policy, v15_execution, v15_adjudication,
                  prelabel_seal):
    # Fail closed before touching outcomes if the source-first seal changed.
    require(prelabel_seal == source_first_bridge(v14_plan, v15_study),
            'prelabel source-first bridge mismatch')
    # Both original V14 and V15 validators enforce a complete, immutable,
    # separately adjudicated model-result census and full policy replay.
    v14_outputs, v14_scores = v14.check_adjudication(
        v14_plan, v14_predictions, v14_adjudication)
    v15_outputs = v15.validate_control_execution(
        v15_study, v15_policy, v15_execution)
    v15_review = v15.review_control(
        v15_study, v15_policy, v15_execution, v15_adjudication)
    v15_scores = {(r['case_id'],r['arm']):r
                  for r in v15_adjudication['results']}
    require(len(v15_scores) == len(v15_outputs), 'duplicate V15 outcome')
    brier_total, baseline_total = 0, 0
    bins = [{'cases':0, 'correct':0, 'forecast_sum_bps':0} for _ in range(4)]
    sufficient = {'candidate_correct':0, 'reference_correct':0,
                  'candidate_entailed':0, 'candidate_abstained':0,
                  'candidate_retrieved_correct':0,
                  'candidate_lesion_correct':0,
                  'candidate_none_correct':0}
    for binding in prelabel_seal['bindings']:
        cid = binding['case_id']
        original = v14_outputs[cid,'candidate','sufficient']
        judged = v14_scores[cid,'candidate','sufficient']
        stop = v15_outputs[cid,'stop']
        stop_judgment = v15_scores[cid,'stop']
        require(original['request_sha256'] == stop['terminal_request_sha256']
                and original['answer_sha256'] == stop['answer_sha256'],
                'stop was not an exact frozen V14 sufficient-answer replay')
        require(judged['correct'] == stop_judgment['correct']
                and judged['citations_entailed'] == stop_judgment['citations_entailed'],
                'same answer received contradictory external adjudication')
        sufficient['candidate_correct'] += int(judged['correct'])
        sufficient['reference_correct'] += int(
            v14_scores[cid,'reference','sufficient']['correct'])
        sufficient['candidate_entailed'] += int(judged['citations_entailed'])
        sufficient['candidate_abstained'] += int(original['abstained'])
        for name,arm in [('candidate_retrieved_correct','retrieved'),
                         ('candidate_lesion_correct','lesion'),
                         ('candidate_none_correct','none')]:
            sufficient[name] += int(v14_scores[cid,'candidate',arm]['correct'])
        q = binding['root_forecast_bps']
        y = 10000*int(judged['correct'])
        brier_total += (q-y)**2
        baseline_total += (5000-y)**2
        cal = bins[min(3,q//2500)]
        cal['cases'] += 1
        cal['correct'] += int(judged['correct'])
        cal['forecast_sum_bps'] += q
    comparisons = {}
    for ref in COMPARATORS:
        groups = _per_family_statistics(v15_study,v15_outputs,v15_scores,'ndu_shadow',ref)
        count = sum(v['cases'] for v in groups.values())
        total = sum(v['net_micro'] for v in groups.values())
        root_count = len(groups)
        bootstrap_seed = int(sha256((v15.sha_obj(prelabel_seal)+'/'+ref)
                         .encode('ascii')).hexdigest()[:16],16)
        leave_one_out = [Fraction(total - v['net_micro'],count-v['cases'])
            for v in groups.values() if count>v['cases']]
        comparisons[ref] = {
            'paired_cases':count,
            'claimed_independent_families_not_authenticated':root_count,
            'net_micro_delta':total,
            'net_micro_delta_per_case':str(Fraction(total,count)),
            'correct_delta':sum(v['correct_delta'] for v in groups.values()),
            'cpu_ms_delta':sum(v['cpu_ms_delta'] for v in groups.values()),
            'token_delta':sum(v['token_delta'] for v in groups.values()),
            'paired_family_bootstrap_95_per_case_micro':
                _bootstrapped_cluster_mean(groups,bootstrap_seed),
            'min_leave_one_family_out_per_case_micro':
                str(min(leave_one_out)) if leave_one_out else None,
        }
    return {
        'schema': SCHEMA+'.research-report',
        'prelabel_seal_sha256':v15.sha_obj(prelabel_seal),
        'v14_predictions_sha256':v15.sha_obj(v14_predictions),
        'v14_adjudication_sha256':v15.sha_obj(v14_adjudication),
        'v15_execution_sha256':v15.sha_obj(v15_execution),
        'v15_adjudication_sha256':v15.sha_obj(v15_adjudication),
        'case_count':len(prelabel_seal['bindings']),
        'sufficient_reader_descriptive':sufficient,
        'root_forecast_brier_total_bps_squared':brier_total,
        'untrained_half_probability_brier_total_bps_squared':baseline_total,
        'root_forecast_calibration_quartiles':bins,
        'system2_vs_baselines_descriptive':comparisons,
        'source_families_claimed_not_authenticated':len({b['family'] for b in prelabel_seal['bindings']}),
        'v14_original_reader_authenticated':False,
        'v15_original_reader_authenticated':False,
        'independent_review_authenticated':False,
        'prospective_evaluation_verified':False,
        'frozen_forecast_calibration_qualified':False,
        'system2_net_utility_gain_qualified':False,
        'cell_split_authorized':False,
        'production_authorized':False,
        'decision':'HOLD_NO_GO',
    }


def review_split_robustness(study, predictions, adjudication):
    """Add source/window sensitivity without authorizing V15 Split candidates."""
    v15_report = v15.review_split(study,predictions,adjudication)
    lookup = {r['case_id']:r['correct'] for r in adjudication['results'] if r['arm']=='split'}
    parents = {r['case_id']:r['correct'] for r in adjudication['results'] if r['arm']=='parent'}
    cases = study['cases']
    windows = defaultdict(lambda:{'cases':0,'parent_correct':0,'split_correct':0,
                                  'claimed_family_ids':set()})
    per_family = defaultdict(lambda:{'n':0,'old_correct_delta':0,'future_correct_delta':0})
    for c in cases:
        cid=c['id']
        d=int(lookup[cid])-int(parents[cid])
        pf=per_family[c['family']]
        pf['n'] += 1
        pf[c['cohort']+'_correct_delta'] += d
        if c['cohort']=='future':
            w=windows[c['window']]
            w['cases']+=1
            w['parent_correct']+=int(parents[cid])
            w['split_correct']+=int(lookup[cid])
            w['claimed_family_ids'].add(c['family'])
    window_summary={w:{'cases':v['cases'],
                       'claimed_families_not_authenticated':len(v['claimed_family_ids']),
                       'correct_delta':v['split_correct']-v['parent_correct']}
                    for w,v in sorted(windows.items())}
    future_gain_every_window=bool(window_summary) and all(
        x['correct_delta']>0 for x in window_summary.values())
    old_regressed_families=sum(1 for v in per_family.values() if v['old_correct_delta']<0)
    result={
        'schema':SCHEMA+'.split-robustness',
        'underlying_v15_report_sha256':v15.sha_obj(v15_report),
        'per_future_window_descriptive':window_summary,
        'future_gain_every_claimed_window':future_gain_every_window,
        'old_task_regressed_claimed_families':old_regressed_families,
        'numeric_gain_gate_from_v15':v15_report['numeric_gain_gate'],
        'sample_window_gate_from_v15':v15_report['sample_window_gate'],
        'authentic_model_execution_verified':False,
        'independent_family_identity_verified':False,
        'cell_split_authorized':False,
        'production_authorized':False,
        'decision':'HOLD_NO_GO',
    }
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    a=commands.add_parser('plan')
    a.add_argument('--v14-plan',required=True)
    a.add_argument('--v15-study',required=True)
    b=commands.add_parser('review')
    for name in ('v14-plan','v14-predictions','v14-adjudication',
                 'v15-study','v15-policy','v15-execution','v15-adjudication',
                 'prelabel-seal'):
        b.add_argument('--'+name,required=True)
    c=commands.add_parser('split')
    for name in ('study','predictions','adjudication'):
        c.add_argument('--'+name,required=True)
    args=parser.parse_args()
    load=v15.load_json
    if args.command=='plan':
        result=source_first_bridge(load(args.v14_plan),load(args.v15_study))
    elif args.command=='review':
        result=review_bridge(load(args.v14_plan),load(args.v14_predictions),
          load(args.v14_adjudication),load(args.v15_study),load(args.v15_policy),
          load(args.v15_execution),load(args.v15_adjudication),load(args.prelabel_seal))
    else:
        result=review_split_robustness(load(args.study),load(args.predictions),
                                       load(args.adjudication))
    print(json.dumps(result,sort_keys=True,indent=2,allow_nan=False))


if __name__=='__main__':
    main()
