"""Final seed/parameter guards and arithmetic on actual two-pool forwards."""
import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
from unittest.mock import patch
import torch
from experiments.hcsn_v12_followup_20261101.control import feedback_rollout as target
from experiments.hcsn_v9_followup_20261101.mechanisms import campaign as v9


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(out):
    torch.set_num_threads(1)
    source=sha(target.__file__)
    with out.with_name(out.stem+'_FREEZE.json').open('x') as stream:
        json.dump({'source_sha256':source,'checker_sha256':sha(__file__),'pool_size':512},stream,indent=2);stream.write('\n')
    checks=0
    def require(condition,label):
        nonlocal checks
        checks+=1
        if not condition:raise AssertionError(label)
    cfg=v9.old.Config();matrix=v9.old.transition_matrix(5)
    obs=v9.old.Observation(0.,.7,0.,[.2]*5,False)
    physics=v9.Physics(-.7,.45,.7,.2)
    alpha=.05/(12*11*20)
    invalid=[([11,11],512,alpha),([11],512,alpha),([11,13,17],512,alpha),
             ([11,13],1,alpha),([11,13],0,alpha),([11,13],512,0.),
             ([11,13],512,1.),([11,13],512,-.1),([11,13],512,float('nan'))]
    for seeds,size,a in invalid:
        rejected=False
        with patch.object(target.v9,'choose',side_effect=AssertionError('Invalid argument reached baseline')):
            try:target.choose(None,obs,3,3,physics,matrix,cfg,seeds,[1.]*21,size,a)
            except ValueError:rejected=True
        require(rejected,'invalid gate arguments rejected')
    repo=Path(__file__).resolve().parents[4]
    cp=torch.load(v9.V8/'fit_81101/models.pt',weights_only=False,map_location='cpu')
    qfit=json.loads((repo/'experiments/hcsn_v9_followup_20261101/mechanisms/results/development001/SERVICE_FIT.json').read_text())['forecast']
    cores={'analytic':v9.FittedAnalytic('original',1.), **{f:v9.load_core(cp,f) for f in ('gru','ssm')}}
    cases=[]
    for ci,(name,core) in enumerate(cores.items()):
        for qi,(profile,q) in enumerate([('all_success',[1.]*21),('fitted',qfit)]):
            seeds=[121003+ci*100+qi*10,121007+ci*100+qi*10]
            action,detail=target.choose(core,obs,3,3,physics,matrix,cfg,seeds,q,512,alpha)
            future=[d for d in cfg.deadlines if d>3]
            for kind in ('selection','validation'):
                if kind not in detail:continue
                br=detail[kind]
                for units,correct,reads in zip(br['reward_units'],br['correct_counts'],br['read_counts']):
                    require(len(units)==len(correct)==len(reads)==512,'pool row inventory')
                    require(all(u==25*c-4*r for u,c,r in zip(units,correct,reads)),'exact reward units')
                    require(all(0<=c<=len(future) for c in correct) and all(0<=r<=3 for r in reads),'future output/READ bounds')
            means=[float(Fraction(sum(v),51200)) for v in detail['selection']['reward_units']]
            require(means==detail['selection_means'],'exact selection means')
            candidate=max(range(3),key=lambda i:(means[i],-i))
            require(detail['candidate_action']==detail['roots'][candidate],'pool1 candidate selection')
            if 'validation' in detail:
                br=detail['validation']
                differences=[b-a for a,b in zip(*br['reward_units'])]
                require(differences==detail['paired_difference_units'],'paired integer differences')
                expected=float(Fraction(sum(differences),51200))
                require(expected==detail['mean_difference'],'exact validation mean')
                bound=Fraction(len(future),4)+Fraction(3,25)
                require(all(abs(Fraction(v,100))<=bound for v in differences),'true full-fee reward range')
                require(abs(detail['bound']-float(bound))<1e-15,'recorded full-fee bound')
                require(detail['selection_pool_sha256']!=detail['validation_pool_sha256'],'distinct actual pools')
                implied_alpha=math.exp(-512*detail['radius']**2/(2*detail['bound']**2))
                require(abs(implied_alpha/alpha-1)<1e-12,'Hoeffding tail inversion')
                require(detail['lcb']==expected-detail['radius'],'LCB arithmetic')
                require(detail['fallback']==(detail['lcb']<=0),'strict conservative gate')
                require(action==(detail['candidate_action'] if detail['lcb']>0 else detail['baseline_action']),'actual gate action')
            cases.append({'family':name,'profile':profile,'action':action,'detail':detail})
    require(any('validation' in v['detail'] for v in cases),'actual second-pool branch exercised')
    require(sha(target.__file__)==source,'source unchanged')
    result={'status':'passed','checks':checks,'guard_cases':len(invalid),'actual_forward_cases':len(cases),
            'actual_second_pools':sum('validation' in v['detail'] for v in cases),'source_sha256':source,
            'cases':cases,'scope':'actual two-pool integer and gate arithmetic; not independent Monte Carlo coverage or task superiority'}
    with out.open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({k:result[k] for k in ('status','checks','guard_cases','actual_forward_cases','actual_second_pools')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    run(parser.parse_args().out)
