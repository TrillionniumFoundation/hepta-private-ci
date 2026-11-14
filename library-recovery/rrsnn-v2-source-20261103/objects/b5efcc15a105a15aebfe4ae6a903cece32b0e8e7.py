"""Predeclared strict-initial diagnostic with separate results and the frozen ledger."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import time

for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
if hasattr(os, 'sched_setaffinity') and 8 in os.sched_getaffinity(0):
    os.sched_setaffinity(0, {8})

import numpy as np
import torch

from ...evaluate import evaluate, load_scenarios, load_oracles, load_policy
from ...aggregate_results import PairedBootstrap, compare, describe, paired_indices, retention
from .factory import use_shared_initial_factory, OriginalRollout
from .. import sampled_policy
from .audit_initial import run_audit

ROOT = Path(__file__).resolve().parent
MAIN = ROOT.parents[1]
SEEDS = (101,211,307,401,503)
CANDIDATE = 'rr_density_sampled'
REFERENCE = 'ctrnn_matched_cpu'
SOURCE_PATHS = ['evaluate.py','aggregate_results.py','policy.py','density_model.py',
                'audit/sampled_policy.py','audit/exact_rollout.py',
                'audit/strict_initial_counterfactual/run.py',
                'audit/strict_initial_counterfactual/factory.py',
                'audit/strict_initial_counterfactual/audit_initial.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    if path.suffix == '.gz':
        with gzip.open(path,'rt',encoding='utf-8') as handle:
            return json.load(handle)
    return json.loads(path.read_text())


def source_hashes():
    result = {name:sha(MAIN/name) for name in SOURCE_PATHS}
    result['../rrsnn_experiments/resource_env.py'] = sha(MAIN.parent/'rrsnn_experiments/resource_env.py')
    return result


def declare():
    target = ROOT/'protocol.json'
    if target.exists():
        protocol = read(target)
        verify_protocol(protocol)
        return protocol
    if (MAIN/'results/selection.json').exists():
        raise RuntimeError('First declaration must precede the main selection/holdout opening')
    artifacts = {}
    for run in (CANDIDATE,REFERENCE):
        artifacts[run] = {}
        for seed in SEEDS:
            folder = MAIN/'results'/run/f'seed_{seed}'
            receipt = read(folder/'training.json')
            checksum = sha(folder/'model.pt')
            if checksum != receipt['checkpoint_sha256'] or receipt['holdout_opened_by_training']:
                raise ValueError('Unqualified training artifact')
            artifacts[run][str(seed)] = {'checkpoint_sha256':checksum,
                                         'training_receipt_sha256':sha(folder/'training.json')}
    protocol = {
        'schema':'rrsnn.strict-initial-counterfactual-protocol.v1',
        'declared_utc':datetime.now(timezone.utc).isoformat(),
        'main_selection_existed_at_declaration':False,
        'holdout_metrics_read_before_declaration':False,
        'status':'Separate prospective diagnostic; frozen primary protocol/results are unchanged.',
        'candidate':CANDIDATE,'comparator':REFERENCE,'training_seeds':list(SEEDS),
        'dataset':'paired','value_groups':128,'conditions':['A0','A2','B0','B2'],
        'episodes_per_replay':512,'candidate_replays_per_seed':4,'deterministic_reference_replays':1,
        'seed_rule':'940000 + training_seed + 10007*repeat',
        'initialization':'Call the original reset-law initializer for 128 groups, then copy each entire actual state to its four conditions. Subsequent draws are ordinary fresh sampler draws, not common-noise coupling.',
        'initial_fields':['indices','physical_evidence','context','drift','boundary','time','total_counts','has_observed','initial_resource_if_present'],
        'no_invented_trace':'The primary sampled density controller has no persistent exponential spike-trace buffer. Its counts and deterministic context are copied. A coupled trace-feedback model is a different experiment.',
        'shared_actual_initial_state_before_first_observation':True,
        'shared_noise_after_initialization':False,
        'sampling_uncertainty':'Intervals condition on the four fixed replays. Initial group draws are shared across conditions. Additional unlimited-path uncertainty is not separately estimated.',
        'bootstrap':'10000 paired crossed seed-by-value-group draws; keep all four conditions in each group. Average fixed replays before utility contrasts; compute negative-transfer indicators per actual replay before averaging.',
        'bootstrap_seed':930201,'fixed_comparator_not_selected_from_holdout':True,
        'actor_information':'Use the frozen root evaluate ledger. Actor receives observations/dt/mask only; oracle Q enters the unchanged evaluator only after action selection.',
        'gate':'All declared artifacts remain byte-identical, initialization audit passed, and the main validation-only selection lock binds these checkpoints before any paired evaluation.',
        'data_files':{name:sha(MAIN/'data'/name) for name in
                      ('paired_scenarios.json','paired_oracle.npz')},
        'artifacts':artifacts,'source_sha256':source_hashes(),
        'output_root':'audit/strict_initial_counterfactual/',
        'real_future_window':False,
        'no_main_paired_outputs_overwritten':True,
    }
    target.write_text(json.dumps(protocol,indent=2)+'\n')
    return protocol


def verify_protocol(protocol):
    if protocol['source_sha256'] != source_hashes():
        raise ValueError('Declared source hashes changed')
    for name, checksum in protocol['data_files'].items():
        if sha(MAIN/'data'/name) != checksum:
            raise ValueError('Declared paired task changed')
    for run, seeds in protocol['artifacts'].items():
        for seed, expected in seeds.items():
            folder = MAIN/'results'/run/f'seed_{seed}'
            if sha(folder/'model.pt') != expected['checkpoint_sha256'] or sha(folder/'training.json') != expected['training_receipt_sha256']:
                raise ValueError('Declared model/training receipt changed')


def gate(protocol):
    verify_protocol(protocol)
    audit = read(ROOT/'initialization_audit.json')
    if not audit['all_passed'] or audit['uses_holdout_scenarios_or_metrics']:
        raise ValueError('Independent initialization-law audit did not pass')
    if audit['factory_sha256'] != sha(ROOT/'factory.py'):
        raise ValueError('Audited factory changed')
    selection_path = MAIN/'results/selection.json'
    if not selection_path.exists():
        raise RuntimeError('Main validation-only selection lock is not yet available; no holdout was opened')
    selection = read(selection_path)
    if selection['holdout_metrics_used_for_selection'] or selection['evaluation_source_sha256'] != sha(MAIN/'evaluate.py'):
        raise ValueError('Invalid main selection lock')
    for run,seeds in protocol['artifacts'].items():
        for seed,expected in seeds.items():
            if selection['checkpoints'][run][seed] != expected['checkpoint_sha256']:
                raise ValueError('Main selection differs from declared checkpoint')
    return sha(selection_path)


def result_path(run,seed,repeat):
    return ROOT/'results'/run/f'seed_{seed}'/f'paired_rep{repeat}.json.gz'


def expected_header(protocol, selection_sha, run, seed, repeat):
    return {'schema':'rrsnn.strict-initial-evaluation.v1','run_name':run,'seed':seed,
            'dataset':'paired','repeat':repeat,'random_seed':940000+seed+10007*repeat,
            'checkpoint_sha256':protocol['artifacts'][run][str(seed)]['checkpoint_sha256'],
            'selection_sha256':selection_sha,'protocol_sha256':sha(ROOT/'protocol.json'),
            'scenario_sha256':protocol['data_files']['paired_scenarios.json'],
            'strict_initial_candidate':run==CANDIDATE,'real_future_window':False}


def checked_read(path, header):
    payload = read(path)
    if any(payload.get(k) != v for k,v in header.items()):
        raise ValueError('Evaluation identity/replay/seed/provenance mismatch')
    return payload


def execute():
    protocol = declare();selection_sha = gate(protocol)
    torch.set_num_threads(1)
    scenarios = load_scenarios('paired')
    # Validate the unchanged four-condition design before creating the factory.
    indices = paired_indices([vars(s) for s in scenarios])
    if indices.shape != (128,4):
        raise ValueError('Unexpected paired group dimensions')
    oracles = load_oracles('paired',scenarios)
    for run in (CANDIDATE,REFERENCE):
        for seed in SEEDS:
            path = MAIN/'results'/run/f'seed_{seed}'/'model.pt'
            model,_ = load_policy(path)
            for repeat in range(4 if run==CANDIDATE else 1):
                header = expected_header(protocol,selection_sha,run,seed,repeat)
                output = result_path(run,seed,repeat)
                if output.exists():
                    checked_read(output,header);continue
                begin = time.perf_counter()
                if run==CANDIDATE:
                    with use_shared_initial_factory() as instances:
                        result = evaluate(model,scenarios,oracles,mode='ctmc',
                                          seed=header['random_seed'],keep_trace=True)
                        if len(instances)!=1:raise AssertionError('Unexpected sampler instance count')
                        initial = instances[0].strict_initial_receipt
                    if sampled_policy.SampledDensityRollout is not OriginalRollout:
                        raise AssertionError('Process-local patch was not restored')
                    trace_count = np.bincount([x['batch'] for x in result['real_spike_times']],minlength=512)
                    if not np.array_equal(trace_count,np.asarray(result['episode_internal_count'],dtype=np.int64)):
                        raise AssertionError('Recorded actual spikes and episode counts disagree')
                else:
                    result = evaluate(model,scenarios,oracles,mode='density',
                                      seed=header['random_seed'],keep_trace=True)
                    initial = {'deterministic_reference':True,'mode':'unchanged root policy initializer'}
                payload = {**header,'initialization':initial,'evaluation':result,
                           'diagnostic_wall_seconds':time.perf_counter()-begin}
                output.parent.mkdir(parents=True,exist_ok=True)
                temporary = output.with_suffix('.gz.tmp')
                with gzip.open(temporary,'wt',encoding='utf-8') as handle:
                    json.dump(payload,handle,allow_nan=False)
                temporary.replace(output)
                print(json.dumps({'completed':run,'seed':seed,'repeat':repeat,
                                  'seconds':payload['diagnostic_wall_seconds']}),flush=True)
    aggregate()


def load_arrays(run,protocol,selection_sha,scenarios):
    repeats = 4 if run==CANDIDATE else 1
    rows=[];files=[]
    for seed in SEEDS:
        seed_rows=[]
        for repeat in range(repeats):
            path=result_path(run,seed,repeat)
            payload=checked_read(path,expected_header(protocol,selection_sha,run,seed,repeat))
            e=payload['evaluation']
            if e['episodes']!=512 or not e['ledger_conservation'] or e['budget_violations']:
                raise ValueError('Episode ledger invariant failed')
            if run==CANDIDATE:
                initial=payload['initialization']
                if not all(initial['within_group_bitwise_equal'].values()) or e['mode']!='ctmc':
                    raise ValueError('Strict initial or actual CTMC condition failed')
            # Keep only the compact episode arrays, not all spike dictionaries.
            seed_rows.append({k:v for k,v in e.items() if k.startswith('episode_')})
            files.append({'path':str(path.relative_to(ROOT)),'sha256':sha(path)})
        rows.append(seed_rows)
    fields={'utility':'episode_utility','oracle':'episode_oracle',
            'normalized_utility':'episode_normalized_utility','budget_spent':'episode_budget_spent',
            'internal_count':'episode_internal_count'}
    arrays={k:np.asarray([[r[v] for r in row] for row in rows],dtype=float) for k,v in fields.items()}
    if any(a.shape!=(5,repeats,512) or not np.isfinite(a).all() for a in arrays.values()):
        raise ValueError('Unexpected seed/replay/episode array shape')
    oracle=arrays['oracle'];utility=arrays['utility']
    if not np.allclose(oracle,oracle[0,0],rtol=0,atol=1e-12) or np.max(utility-oracle)>1e-8:
        raise ValueError('Mismatched oracle or utility beyond optimum')
    ratio=np.divide(utility,oracle,out=np.ones_like(utility),where=oracle>1e-12)
    if not np.allclose(ratio,arrays['normalized_utility'],rtol=0,atol=1e-12):
        raise ValueError('Normalized utility mismatch')
    masks=np.asarray([[r['episode_live_final'] for r in row] for row in rows])
    kept=retention(np.array([s['values'] for s in scenarios]),masks)
    actual=np.asarray([[r['episode_retained_value'] for r in row] for row in rows])
    if not np.allclose(kept['retained_value'],actual,rtol=0,atol=1e-10):
        raise ValueError('Terminal retention mismatch')
    arrays.update(kept);arrays['regret']=oracle-utility
    return {'arrays':arrays,'replays':repeats,'modes':['strict-initial-real-ctmc' if run==CANDIDATE else 'unchanged-deterministic-reference'],
            'files':files,'unique_zero_oracle_episodes':int(np.sum(oracle[0,0]<=1e-12))}


def aggregate():
    protocol=declare();selection_sha=gate(protocol)
    scenarios=read(MAIN/'data/paired_scenarios.json');index=paired_indices(scenarios)
    candidate=load_arrays(CANDIDATE,protocol,selection_sha,scenarios)
    reference=load_arrays(REFERENCE,protocol,selection_sha,scenarios)
    if not np.array_equal(candidate['arrays']['oracle'][:,0],reference['arrays']['oracle'][:,0]):
        raise ValueError('Candidate/reference oracle differs')
    bootstrap=PairedBootstrap(5,128,draws=10000,seed=930201)
    result={'schema':'rrsnn.strict-initial-counterfactual-result.v1','all_completed':True,
            'protocol':protocol,'protocol_sha256':sha(ROOT/'protocol.json'),
            'main_selection_sha256':selection_sha,
            'candidate':describe(candidate,index),'reference':describe(reference,index),
            'paired_comparison':compare(candidate,reference,bootstrap,index),
            'input_files':candidate['files']+reference['files'],
            'same_actual_preobservation_initial_state':True,'common_noise_after_initialization':False,
            'real_future_window':False,'main_protocol_or_results_modified':False,
            'inference_limits':['Prospective diagnostic separate from the frozen primary matrix.',
                'Actual initial states are identical within group; observation-driven controls and subsequent random paths may differ.',
                'Intervals condition on four fixed replays; this is a synthetic task, not a real future window.',
                'Budget legality is enforced by the shared frozen environment mask, not attributed to the candidate.']}
    (ROOT/'aggregate.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'all_completed':True,'utility_contrast':result['paired_comparison']['contrasts_candidate_minus_reference']['utility'],
                      'normalized_utility_contrast':result['paired_comparison']['contrasts_candidate_minus_reference']['normalized_utility'],
                      'negative_transfer':result['paired_comparison']['negative_transfer_episode_fraction']}),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--declare',action='store_true')
    parser.add_argument('--audit-initial',action='store_true');parser.add_argument('--run',action='store_true')
    parser.add_argument('--aggregate',action='store_true');args=parser.parse_args()
    if args.declare:
        p=declare();print(json.dumps({'declared':True,'utc':p['declared_utc'],'protocol_sha256':sha(ROOT/'protocol.json')}))
    elif args.audit_initial:
        declare();r=run_audit();print(json.dumps({'audit_passed':r['all_passed'],'checks':len(r['checks'])}))
    elif args.run:execute()
    elif args.aggregate:aggregate()
    else:parser.error('Choose --declare, --audit-initial, --run or --aggregate')
