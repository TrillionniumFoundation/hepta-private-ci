"""Post-hoc *mechanism* probe for frozen Hepta NDU policy, not an outcome study.

Reads only the recorded reference-free checkpoint features, recorded local
covariance action penalties, frozen train-fitted policy, and PRNG seeds. No test
labels enter inference, and no generated token is rerun. Frozen pilot metrics
and dev-selected risk weight 0 are not changed.
"""
import argparse
import json
from pathlib import Path
import torch
from policies import Policies, _conservative_distribution


def project_action(policy, features, local_penalty, risk_weight, seed, include_covariance):
    if risk_weight < 0 or not torch.isfinite(torch.tensor(risk_weight)):
        raise ValueError('risk_weight must be nonnegative and finite')
    state = torch.as_tensor(features, dtype=torch.float32)
    penalty = torch.as_tensor(local_penalty, dtype=torch.float32)
    if state.shape != (24,) or not torch.isfinite(state).all() or penalty.shape != (6,) or not torch.isfinite(penalty).all() or torch.any(penalty < -1e-5):
        raise ValueError('bad recorded inference features or covariance penalties')
    with torch.no_grad():
        output = policy.models['ndu'](((state - policy.mean) / policy.scale).unsqueeze(0))
        quality, _, risk = policy._estimates(output, 'ndu', policy.prior.unsqueeze(0))
        local = penalty.clamp_min(0) if include_covariance else 0
        scores = quality[0].clamp(0, 1) - risk_weight * (risk[0] + policy.config['covariance_strength'] * local)
        logits = .25 * output['actor'][0] + scores / policy.config['temperature']
        prob = _conservative_distribution(logits, policy.prior, policy.config['kl_bound'])
        generator = torch.Generator().manual_seed(int(seed))
        selected = int(torch.multinomial(prob, 1, generator=generator))
    return prob, selected


def probe(policy, episodes, weights=(0, .5, 1, 2, 5)):
    decisions=[]
    distinct_seeds=set()
    for episode in episodes:
        if episode.get('method') != 'ndu':
            continue
        for step in episode.get('controls', []):
            if not step.get('checkpoint_changed'):
                continue
            extra=step['extra']
            metadata=extra['policy']
            state=extra['observed_features']
            penalty=metadata['local_disagreement_penalty']
            seed=metadata['seed']
            observed=metadata['action_probs']
            p0,a0=project_action(policy, state, penalty, 0, seed, True)
            maximum=max(abs(float(v)-float(u)) for v,u in zip(p0, observed))
            if maximum>2e-6 or a0 != step['action']:
                raise ValueError(f"original frozen action/probability differs at {episode['task_id']} step {step['step']}")
            tested={}
            for weight in weights:
                with_p, with_action = project_action(policy,state,penalty,weight,seed,True)
                without_p, without_action = project_action(policy,state,penalty,weight,seed,False)
                tv = float(torch.sum(torch.abs(with_p - without_p))/2)
                tv_from_base = float(torch.sum(torch.abs(with_p - p0))/2)
                tested[str(weight)]={'covariance_tv':tv,'risk_from_zero_tv':tv_from_base,
                    'action_switch_due_covariance': int(with_action!=without_action),
                    'action_switch_from_zero':int(with_action!=a0),
                    'expected_local_penalty_with_covariance':float(torch.dot(with_p,torch.tensor(penalty))),
                    'expected_local_penalty_without_covariance':float(torch.dot(without_p,torch.tensor(penalty))),
                    'probabilities_with_covariance':with_p.tolist(),
                    'probabilities_without_covariance':without_p.tolist()}
            decisions.append({'task_id':episode['task_id'],'step':step['step'],'methods':tested})
            distinct_seeds.add(seed)
    if not decisions:
        raise ValueError('no real NDU checkpoints in supplied episodes')
    result={'schema':'hepta.ndu.posthoc-risk-counterfactual.v1','classification':'mechanism_only_not_outcome_evidence',
      'frozen_pilot_unchanged':True,'risk_selection_of_original_pilot':0.0,'reference_labels_used':False,
      'original_NDU_checkpoints_replayed':len(decisions),'distinct_logged_seeds':len(distinct_seeds),
      'weights':{},'per_checkpoint':decisions}
    for weight in weights:
        group=[row['methods'][str(weight)] for row in decisions]
        result['weights'][str(weight)]={
          'mean_covariance_total_variation':sum(r['covariance_tv'] for r in group)/len(group),
          'covariance_nonzero_effect_checkpoints':sum(r['covariance_tv']>1e-8 for r in group),
          'covariance_changed_actions':sum(r['action_switch_due_covariance'] for r in group),
          'mean_risk_from_original_total_variation':sum(r['risk_from_zero_tv'] for r in group)/len(group),
          'risk_changed_actions_from_original':sum(r['action_switch_from_zero'] for r in group),
          'mean_expected_cov_penalty_with':sum(r['expected_local_penalty_with_covariance'] for r in group)/len(group),
          'mean_expected_cov_penalty_without':sum(r['expected_local_penalty_without_covariance'] for r in group)/len(group)}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy',required=True,type=Path)
    parser.add_argument('--episodes',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    policy=Policies.load(args.policy)
    episodes=[json.loads(line) for line in args.episodes.read_text().splitlines() if line.strip()]
    result=probe(policy,episodes)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('per_checkpoint',)},indent=2))


if __name__=='__main__':main()
