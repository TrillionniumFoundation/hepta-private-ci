"""Limited frozen-model replay of six Monte Carlo planner forwards.

This calls the same planner with recorded public inputs and frozen seeds. It is
not a second independent planner implementation. Actual hidden task paths are not
passed into the planner. Table/mixture arithmetic is audited separately.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time
import torch
from experiments.hcsn_v10_followup_20261101.control import mpc
from experiments.hcsn_v9_followup_20261101.mechanisms import campaign as v9


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(run_dir,out):
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    p=json.loads((run_dir/'PLAN.json').read_text())
    complete=json.loads((run_dir/'COMPLETE.json').read_text())
    if sha(run_dir/'runs.jsonl.gz')!=complete['raw_sha256']:
        raise ValueError('Raw hash mismatch')
    repo=Path(__file__).resolve().parents[4]
    for section in ('source_sha256','assets_sha256'):
        for path,expected in p[section].items():
            if sha(repo/path)!=expected:raise ValueError('Frozen identity mismatch')
    meta={'created_unix':time.time(),'source_sha256':sha(__file__),'planner_sha256':sha(mpc.__file__),
          'raw_sha256':sha(run_dir/'runs.jsonl.gz'),'worlds_sha256':sha(run_dir/'worlds.jsonl.gz'),
          'cases':'condition world0 tick0; analytic91103 GRU81101 SSM81101',
          'absolute_tolerance':1e-12,'same_implementation_replay':True}
    with out.with_name(out.stem+'_FREEZE.json').open('x') as stream:json.dump(meta,stream,indent=2);stream.write('\n')
    with gzip.open(run_dir/'worlds.jsonl.gz','rt') as stream:
        worlds={(v['condition'],v['index']):v for v in map(json.loads,stream)}
    targets=[]
    with gzip.open(run_dir/'runs.jsonl.gz','rt') as stream:
        for row in map(json.loads,stream):
            if row['index']==0 and row['controller']=='multi_read_mpc' and ((row['family']=='analytic' and row['fit_seed']=='91103') or
                (row['family'] in ('gru','ssm') and row['fit_seed']=='81101')):targets.append(row)
    if len(targets)!=6:raise ValueError('Target inventory mismatch')
    assets=repo/'experiments/hcsn_v9_followup_20261101/mechanisms/results/development001'
    q=json.loads((assets/'SERVICE_FIT.json').read_text())['forecast']
    scale=json.loads((assets/'ANALYTIC_FITS.json').read_text())['91103']['original']['selected_scale']
    cp=torch.load(v9.V8/'fit_81101/models.pt',weights_only=False,map_location='cpu')
    rows=[]
    for record in targets:
        core=v9.FittedAnalytic('original',scale) if record['family']=='analytic' else v9.load_core(cp,record['family'])
        public=record['trace'][0]['observation']
        config=v9.old.Config(**{**p['config'],'condition':record['condition']})
        world=worlds[(record['condition'],0)]
        physics=v9.Physics(**world['episode']['calibration']['estimated'])
        action,detail=mpc.choose(core,v9.old.Observation(**public),0,config.budget,physics,
            v9.old.transition_matrix(config.classes),config,world['policy_seeds'][0],q,p['MPC_samples'])
        old=record['trace'][0]
        checks={'action_equal':action==old['action'],'base_correct_equal':detail['base_correct']=={int(k):v for k,v in old['detail']['base_correct'].items()},
            'read_correct_equal':detail['read_correct']==old['detail']['read_correct'],
            'selected_schedule_equal':detail['selected_arrivals']==old['detail']['selected_arrivals'],
            'candidate_schedules_equal':[v['arrivals'] for v in detail['candidates']]==[tuple(v['arrivals']) for v in old['detail']['candidates']]}
        error=max(abs(a['score']-b['score']) for a,b in zip(detail['candidates'],old['detail']['candidates']))
        checks['all_scores_within_tolerance']=error<=1e-12
        checks['selected_score_within_tolerance']=abs(detail['selected_score']-old['detail']['selected_score'])<=1e-12
        if not all(checks.values()):raise ArithmeticError('MC forward replay mismatch')
        rows.append({'condition':record['condition'],'family':record['family'],'fit_seed':record['fit_seed'],
                     'checks':checks,'maximum_score_error':error,'candidates':len(detail['candidates']),
                     'packet_evaluations':detail['packet_evaluations']})
    result={'status':'passed','replayed_decisions':6,'rows':rows,'tolerance':1e-12,
            'scope':'same implementation six-decision MC-forward replay, not independent planner or entire-run neural replay'}
    with out.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({'status':'passed','replayed_decisions':6,'max_score_error':max(v['maximum_score_error'] for v in rows)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();run(args.run,args.out)
