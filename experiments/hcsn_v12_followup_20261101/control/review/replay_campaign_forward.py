"""Six coverage-selected real-campaign feedback forwards, same implementation."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time
import torch
from experiments.hcsn_v12_followup_20261101.control import campaign


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(folder,out):
    torch.set_num_threads(1)
    p=campaign.read_plan(folder)
    complete=json.loads((folder/'COMPLETE.json').read_text())
    if sha(folder/'runs.jsonl.gz')!=complete['raw_sha256']:raise ValueError('Main raw hash')
    with gzip.open(folder/'worlds.jsonl.gz','rt') as stream:
        worlds={(v['condition'],v['index']):v for v in map(json.loads,stream)}
    with gzip.open(folder/'runs.jsonl.gz','rt') as stream:
        records=[v for v in map(json.loads,stream) if v['index']==0 and v['controller']=='feedback_rollout'
                 and ((v['family']=='analytic' and v['fit_seed']=='91103') or (v['family'] in ('gru','ssm') and v['fit_seed']=='81101'))]
    if len(records)!=6:raise ValueError('Coverage replay inventory')
    selected=[]
    for r in records:
        validating=[v for v in r['trace'] if 'validation' in v['detail']]
        selected.append((r,validating[0] if validating else r['trace'][0]))
    freeze={'created_unix':time.time(),'source_sha256':sha(__file__),'target_sha256':sha(campaign.feedback.__file__),
            'raw_sha256':sha(folder/'runs.jsonl.gz'),'worlds_sha256':sha(folder/'worlds.jsonl.gz'),
            'selection_rule':'world0 each condition; analytic91103/GRU81101/SSM81101; first validation decision else tick0; no reward/LCB selection',
            'cases':[{'condition':r['condition'],'family':r['family'],'fit_seed':r['fit_seed'],'tick':t['tick'],
                      'enters_validation':'validation' in t['detail']} for r,t in selected],
            'scope':'same-implementation frozen-prefix forward replay, not second independent planner'}
    with out.with_name(out.stem+'_FREEZE.json').open('x') as stream:json.dump(freeze,stream,indent=2);stream.write('\n')
    q=json.loads((campaign.V9/'SERVICE_FIT.json').read_text())['forecast']
    scale=json.loads((campaign.V9/'ANALYTIC_FITS.json').read_text())['91103']['original']['selected_scale']
    ckpt=torch.load(campaign.prior.v9.V8/'fit_81101/models.pt',weights_only=False,map_location='cpu')
    result=[]
    for r,t in selected:
        world=worlds[(r['condition'],0)]
        core=campaign.prior.v9.FittedAnalytic('original',scale) if r['family']=='analytic' else campaign.prior.v9.load_core(ckpt,r['family'])
        obs=campaign.prior.v9.old.Observation(**t['observation'])
        physics=campaign.prior.v9.Physics(**world['episode']['calibration']['estimated'])
        config=campaign.prior.v9.old.Config(**{**p['config'],'condition':r['condition']})
        budget=t['budget_after']+(t['action']=='READ')
        action,detail=campaign.feedback.choose(core,obs,t['tick'],budget,physics,
            campaign.prior.v9.old.transition_matrix(config.classes),config,world['policy_seeds'][t['tick']],
            q,p['selection_pool_size'],p['alpha_per_test'])
        if action!=t['action'] or detail!=t['detail']:raise ArithmeticError('Exact campaign forward mismatch')
        result.append({'condition':r['condition'],'family':r['family'],'fit_seed':r['fit_seed'],'tick':t['tick'],
                       'validation_exercised':'validation' in detail,'action_equal':True,'all_detail_fields_equal':True})
    with out.open('x') as stream:json.dump({'status':'passed','decisions':6,'cases':result,
        'scope':freeze['scope'],'exact_detail_comparison':True},stream,indent=2);stream.write('\n')
    print(json.dumps({'status':'passed','decisions':6,'validation_decisions':sum(v['validation_exercised'] for v in result)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();run(args.run,args.out)
