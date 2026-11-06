"""Non-oracle confidence analysis of all existing frozen JAC banks; no new draws."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time
from ..ndu_jac.finite_study import build_problem
from ..ndu_jac.core import evaluate
from ..ndu_jac.policy_gate import guarded_update
from .confidence import structural_support, probability_boxes, certified_update


def run(evidence_path, protocol_path):
    protocol=json.loads(protocol_path.read_bytes())
    source=evidence_path.read_bytes()
    if hashlib.sha256(source).hexdigest()!=protocol['source_evidence_sha256']:
        raise ValueError('Historical bank evidence changed')
    banks=json.loads(source)['rows']
    if len(banks)!=protocol['families']:
        raise ValueError('Protocol family mismatch')
    truth,root,_=build_problem()
    support=structural_support(truth)
    rows=[]
    begin=time.perf_counter(),time.process_time()
    for bank in banks:
        box_begin=time.perf_counter(),time.process_time()
        counts=bank['sampling']['outcome_counts']
        if any(sum(c)!=protocol['samples_per_row'] for row in counts.values() for c in row.values()):
            raise ValueError('Sample count changed')
        boxes,meta=probability_boxes(support,counts,protocol['alpha'],protocol['families'])
        box_cost={'wall_seconds':time.perf_counter()-box_begin[0],
                  'cpu_seconds':time.process_time()-box_begin[1]}
        coverage=all(lo-1e-12<=atom.probability<=hi+1e-12
            for s,row in truth.items() for a,atoms in row.items()
            for atom,(lo,hi) in zip(atoms,boxes[s][a]))
        comparisons={}
        proposal=bank['policies'][protocol['proposal']]
        for name in protocol['baselines']:
            baseline=bank['policies'][name]
            fit_begin=time.perf_counter(),time.process_time()
            result=certified_update(support,root,baseline,proposal,boxes,
                eta=protocol['eta'],rho=protocol['rho'],fee=protocol['fee'])
            old=guarded_update(baseline,proposal,result['baseline_bounds']['q'],root,protocol['fee'])
            fitting={'wall_seconds':time.perf_counter()-fit_begin[0],
                     'cpu_seconds':time.process_time()-fit_begin[1]}
            # All oracle quantities are isolated to this validation block.
            actual=evaluate(truth,root,baseline,eta=protocol['eta'],rho=protocol['rho'])
            returned=evaluate(truth,root,result['policy'],eta=protocol['eta'],rho=protocol['rho'])
            proposed=evaluate(truth,root,proposal,eta=protocol['eta'],rho=protocol['rho'])
            qcoverage=all(lo-1e-12<=actual['action_values'][s][a]<=hi+1e-12
                for s,row in result['baseline_bounds']['q'].items() for a,(lo,hi) in row.items())
            tiltcov=all(lo<=actual['tilted_probabilities'][s][a][i]+1e-12
                for s,row in result['propagation']['tilted_mass_lower'].items()
                for a,vals in row.items() for i,lo in enumerate(vals))
            actual_gain=returned['value']-actual['value']
            comparisons[name]={
                'certificate':result,'old_root_only_gate_decision':old['decision'],
                'true_baseline_value':actual['value'],'true_proposal_value':proposed['value'],
                'true_returned_value':returned['value'],'true_returned_gain':actual_gain,
                'true_returned_gain_after_declared_fee':actual_gain-protocol['fee'],
                'simultaneous_Q_intervals_cover_in_this_bank':qcoverage,
                'tilted_mass_bounds_hold_in_this_bank':tiltcov,
                'returned_gain_after_fee_covers_lower':actual_gain-protocol['fee']>=result['returned_net_lower']-1e-12,
                'confidence_layer_fitting':fitting,
                'same_bank_dp_proposal_hurts_baseline':proposed['value']<actual['value']-1e-12}
        rows.append({'seed':bank['seed'],'split':bank['split'],'bank_sha256':bank['bank_sha256'],
            'probability_boxes':boxes,'confidence_metadata':meta,'box_construction_cost':box_cost,
            'model_coverage_in_this_bank':coverage,'comparisons':comparisons})
    summary={}
    for name in protocol['baselines']:
        items=[r['comparisons'][name] for r in rows]
        summary[name]={
            'adopted':sum(x['certificate']['decision']=='adopt' for x in items),
            'old_root_only_adopted':sum(x['old_root_only_gate_decision']=='adopt' for x in items),
            'positive_unpriced_gain_bound':sum(x['certificate']['proposed_gain_lower']>1e-12 for x in items),
            'mean_true_baseline':statistics.mean(x['true_baseline_value'] for x in items),
            'mean_true_returned':statistics.mean(x['true_returned_value'] for x in items),
            'mean_true_returned_gain_after_declared_fee':statistics.mean(x['true_returned_gain_after_declared_fee'] for x in items),
            'min_unpriced_gain_lower':min(x['certificate']['proposed_gain_lower'] for x in items),
            'max_unpriced_gain_lower':max(x['certificate']['proposed_gain_lower'] for x in items),
            'mean_safe_rows':statistics.mean(x['certificate']['safe_rows_changed'] for x in items),
            'unsafe_DP_replacements':sum(x['same_bank_dp_proposal_hurts_baseline'] for x in items),
            'mean_confidence_layer_wall_seconds':statistics.mean(x['confidence_layer_fitting']['wall_seconds'] for x in items),
            'mean_box_construction_wall_seconds':statistics.mean(r['box_construction_cost']['wall_seconds'] for r in rows)}
    return {'schema':'ndu-jac.learned-confidence-analysis.v1','protocol':protocol,
        'protocol_sha256':hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
        'state_count':len(support),'state_action_count':sum(map(len,support.values())),
        'new_observation_count':0,'retained_observations_per_bank':protocol['samples_per_row']*sum(map(len,support.values())),
        'row_count':len(rows),'summary':summary,'rows':rows,
        'all_observed_model_coverage':all(r['model_coverage_in_this_bank'] for r in rows),
        'all_observed_Q_and_tilt_coverage':all(x['simultaneous_Q_intervals_cover_in_this_bank'] and x['tilted_mass_bounds_hold_in_this_bank']
            for r in rows for x in r['comparisons'].values()),
        'all_observed_returned_gain_bounds':all(x['returned_gain_after_fee_covers_lower'] for r in rows for x in r['comparisons'].values()),
        'wall_seconds_before_serialization':time.perf_counter()-begin[0],
        'cpu_seconds_before_serialization':time.process_time()-begin[1],
        'source_sha256':{str(p.name):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [Path(__file__),Path(__file__).with_name('confidence.py'),Path(__file__).parents[1]/'ndu_jac/core.py',
             Path(__file__).parents[1]/'ndu_jac/finite_study.py',Path(__file__).parents[1]/'ndu_jac/policy_gate.py']},
        'cost_scope':'Existing acquisition and actor fitting are inherited, not free. New confidence computation measured; .01 is an inherited declared toy audit fee, not measured hardware or provider money. No lifecycle positivity claim.',
        'scope':'Classical known-support fixed-sample confidence sets; existing same-task banks; no independent tasks, no optional-stopping coverage, no near-information-cost theorem, no new RL superiority claim.'}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--protocol',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        raise SystemExit('Refuse to overwrite evidence')
    result=run(args.evidence,args.protocol)
    args.output.write_text(json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n')
    print(json.dumps({'summary':result['summary'],'coverage':result['all_observed_model_coverage'],
        'Q_and_tilt':result['all_observed_Q_and_tilt_coverage'],'gain':result['all_observed_returned_gain_bounds']},indent=2))
