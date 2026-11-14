"""Small train-only integration audit of frozen-ledger streaming and paths."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
import torch
from ..evaluate import load_scenarios
from .model import CoupledSpikePolicy
from .evaluate import evaluate_coupled,validate_identity,MODE,sha,ROOT,MAIN


def main():
    torch.set_num_threads(1);torch.manual_seed(710401)
    model=CoupledSpikePolicy();scenarios=load_scenarios('train')[:4]
    result,adapter=evaluate_coupled(model,scenarios,seed=710402,keep_trace=True,
        return_adapter=True,record_observations=True)
    repeated=evaluate_coupled(model,scenarios,seed=710402,keep_trace=True)
    for field in ('episode_utility','episode_budget_spent','episode_live_final',
                  'episode_internal_count','real_spike_times','traces'):
        assert result[field]==repeated[field],field
    x=torch.stack([row['x'] for row in adapter.observations],dim=1)
    dt=torch.stack([row['dt'] for row in adapter.observations],dim=1)
    masks=torch.stack([row['event_mask'] for row in adapter.observations],dim=1)
    with torch.no_grad():
        forward=model(x,dt,masks,rng=np.random.default_rng(710402),record_spikes=True)
    assert forward['spike_times']==result['real_spike_times']
    np.testing.assert_array_equal(forward['state'].indices,adapter.final_state.indices)
    np.testing.assert_array_equal(forward['state'].trace,adapter.final_state.trace)
    np.testing.assert_array_equal(forward['state'].total_counts,adapter.final_state.total_counts)
    logits=torch.stack(adapter.outputs,dim=1)
    assert torch.equal(logits,forward['logits'])
    assert result['state_storage']['numeric_bytes_per_sequence']==305
    header={'schema':'rrsnn.coupled-evaluation.v1','milestone':'fixed_updates','seed':101,
        'run_name':'rr_coupled_full_path_fixed_updates','variant':'rr_coupled_full_path',
        'dataset':'paired','repeat':0,'random_seed':940101,'checkpoint_sha256':'test-model',
        'selection_sha256':'test-selection','mode':MODE,'evaluator_sha256':sha(ROOT/'evaluate.py'),
        'frozen_ledger_evaluator_sha256':sha(MAIN/'evaluate.py')}
    validate_identity(header,'fixed_updates',101,'paired',0,'test-model','test-selection')
    try:
        validate_identity(header,'fixed_updates',101,'paired',1,'test-model','test-selection')
        raise AssertionError('Copied repeat0 accepted as repeat1')
    except ValueError:pass
    report={'schema':'rrsnn.coupled-evaluator-audit.v1','passed':True,
        'data':'First4 training scenarios only; no holdout file read',
        'identical_seed_reproduces_actions_ledger_utility_and_spike_times':True,
        'full_forward_replay_of_closed_loop_observation_tape_matches_streaming':True,
        'same_weights_same_complete_spike_path':True,'actual_spikes':len(result['real_spike_times']),
        'copied_replay_identity_rejected':True,
        'action_trace_counts':[len(row) for row in result['traces']],
        'ledger_conservation':result['ledger_conservation'],'state_storage':result['state_storage'],
        'semantic_scope':'Actual closed-loop sampled spike policy with frozen ledger; supervised training remains external-teacher NLL.',
        'source_sha256':{name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                         for name in ('model.py','evaluate.py','validate_evaluator.py')},
        'frozen_ledger_sha256':hashlib.sha256((Path(__file__).parent.parent/'evaluate.py').read_bytes()).hexdigest()}
    target=Path(__file__).parent/'results'/'evaluator_validation.json'
    target.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
