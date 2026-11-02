"""Compare vectorized feedback branches with independent scalar execution."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np
import torch
from experiments.hcsn_v12_followup_20261101.control import feedback_rollout as target
from experiments.hcsn_v9_followup_20261101.mechanisms import campaign as v9
from . import scalar_reference


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(out):
    torch.set_num_threads(1)
    repo=Path(__file__).resolve().parents[4]
    source=sha(target.__file__)
    meta={'created_unix':time.time(),'target_sha256':source,'scalar_reference_sha256':sha(scalar_reference.__file__),
          'checker_sha256':sha(__file__),'samples_per_case':8,'family_count':3,'profile_count':3,'prefix_count':5}
    with out.with_name(out.stem+'_FREEZE.json').open('x') as stream:json.dump(meta,stream,indent=2);stream.write('\n')
    cp=torch.load(v9.V8/'fit_81101/models.pt',weights_only=False,map_location='cpu')
    cores={'analytic':v9.FittedAnalytic('original',1.), **{f:v9.load_core(cp,f) for f in ('gru','ssm')}}
    physics=v9.Physics(-.7,.45,.7,.2)
    config=v9.old.Config()
    matrix=v9.old.transition_matrix(5)
    uniform=[.2]*5
    prefixes=[(v9.old.Observation(0.,.7,0.,uniform,False),0,3),
              (v9.old.Observation(0.,.7,0.,uniform,False),5,2),
              (v9.old.Observation(1.5,.7,.1,[0.,0.,1.,0.,0.],True),10,2),
              (v9.old.Observation(2.7,.45,0.,[0.,0.,0.,1.,0.],True),18,1),
              (v9.old.Observation(0.,.7,0.,uniform,False),19,3)]
    qfit=json.loads((repo/'experiments/hcsn_v9_followup_20261101/mechanisms/results/development001/SERVICE_FIT.json').read_text())['forecast']
    profiles={'fitted':qfit,'all_fail':[0.]*21,'all_success':[1.]*21}
    roots=['STOP','WAIT','READ']
    cases=[]
    failures=[]
    for name,core in cores.items():
        for pi,(obs,tick,budget) in enumerate(prefixes):
            for qi,(profile,q) in enumerate(profiles.items()):
                pool,start,pool_hash=target.model_pool(obs,physics,matrix,config,120130+pi*10+qi,8)
                actual=target.branch_rewards(core,obs,tick,budget,physics,matrix,config,q,pool,start,roots)
                reference=[[scalar_reference.run(core,obs,tick,budget,physics,matrix,config,q,pool,start,i,root)
                            for i in range(8)] for root in roots]
                expected_units=[[v['units'] for v in group] for group in reference]
                expected_correct=[[v['correct'] for v in group] for group in reference]
                expected_reads=[[v['reads'] for v in group] for group in reference]
                digest=hashlib.sha256()
                flat=[v for group in reference for v in group]
                for frame in range(config.ticks-tick):
                    states=[v['states'][frame] for v in flat]
                    for key,dtype in [('action',np.int64),('budget',np.int64),('pending',np.int64),
                                      ('x',np.float64),('time',np.float64),('remaining',np.float64),('content',np.float64)]:
                        digest.update(np.asarray([v[key] for v in states],dtype=dtype).tobytes())
                checks={'integer_rewards_equal':actual['reward_units']==expected_units,
                        'correct_counts_equal':actual['correct_counts']==expected_correct,
                        'READ_counts_equal':actual['read_counts']==expected_reads,
                        'all_feedback_states_equal':actual['feedback_trace_sha256']==digest.hexdigest()}
                case={'family':name,'prefix':pi,'profile':profile,'pool_sha256':pool_hash,'checks':checks}
                cases.append(case)
                if not all(checks.values()):
                    failures.append({**case,'actual_units':actual['reward_units'],'expected_units':expected_units})
    unchanged=sha(target.__file__)==source
    result={'status':'passed' if not failures and unchanged else 'failed','cases':len(cases),
            'paired_branch_samples':len(cases)*8*3,'cases_checked':cases,'failed_case_count':len(failures),
            'failure_examples':failures[:10],'source_unchanged':unchanged,'target_sha256':source,
            'scope':'original scalar light policy and output head vs vectorized branch; full state/action trace digest'}
    with out.open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({'status':result['status'],'cases':len(cases),'failed_cases':len(failures),'source_unchanged':unchanged}))
    if result['status']!='passed':raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    check(parser.parse_args().out)
