"""Independent integer reward bounds and two-pool Hoeffding gate contracts."""
import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
from unittest.mock import patch
from experiments.hcsn_v12_followup_20261101.control import feedback_rollout as target


def run(out):
    source=hashlib.sha256(Path(target.__file__).read_bytes()).hexdigest()
    checks=0
    def require(condition,label):
        nonlocal checks
        checks+=1
        if not condition:raise AssertionError(label)
    for r in range(5):
        for b in range(4):
            bound=Fraction(r,4)+Fraction(b,25)
            values=[25*c-4*reads for c in range(r+1) for reads in range(b+1)]
            for a in values:
                for z in values:
                    require(abs(Fraction(z-a,100))<=bound,'full-fee paired range')
            require(Fraction(max(values)-min(values),100)==bound,'tight symmetric magnitude')
    config=target.v9.old.Config()
    obs=target.v9.old.Observation(0.,.7,0.,[.2]*5,False)
    physics=target.v9.Physics(-.7,.45,.7,.2)
    matrix=target.v9.old.transition_matrix(5)
    alpha=.05/(12*11*20)
    results=[]
    for name,validation_units,keep in [('pass',46,False),('fallback',-4,False),('selection_keeps',46,True)]:
        used=[];branches=[]
        def pool(observation,law,transition,cfg,seed,size):
            used.append(seed)
            return {'seed':seed},0,'pool-'+str(seed)
        def rewards(core,observation,tick,budget,law,transition,cfg,q,pool,start,roots):
            branches.append((pool['seed'],list(roots)))
            if pool['seed']==11:
                units=[0 if keep or a!='READ' else 46 for a in roots]
            else:
                units=[0,validation_units]
            return {'reward_units':[[v]*512 for v in units], 'feedback_trace_sha256':'stub'}
        with patch.object(target.v9,'choose',return_value=('WAIT',{})),patch.object(target,'model_pool',side_effect=pool),patch.object(target,'branch_rewards',side_effect=rewards):
            action,detail=target.choose(None,obs,0,3,physics,matrix,config,[11,13],[.5]*21,512,alpha)
        require(detail['candidate_action']==('WAIT' if keep else 'READ'),'selection fixed candidate')
        require(action==('READ' if name=='pass' else 'WAIT'),'conservative chosen action')
        require(detail['fallback']==(name!='pass'),'fallback contract')
        require(used==([11] if keep else [11,13]),'independent pool namespace and skip when not needed')
        if not keep:
            require(branches[1]==(13,['WAIT','READ']),'pool2 tests only selected action')
            require(detail['paired_difference_units']==[validation_units]*512,'exact paired integer differences')
            require(detail['mean_difference']==validation_units/100,'integer mean conversion')
            require(abs(detail['bound']-1.12)<1e-15,'all future fees included')
            implied_alpha=math.exp(-512*detail['radius']**2/(2*detail['bound']**2))
            require(abs(implied_alpha/alpha-1)<1e-12,'one-sided Hoeffding inversion')
            require(detail['lcb']==detail['mean_difference']-detail['radius'],'LCB arithmetic')
        results.append({'case':name,'action':action,'fallback':detail['fallback'],'used_seeds':used,
                        'lcb':detail.get('lcb'),'radius':detail.get('radius')})
    def bad_rewards(core,observation,tick,budget,law,transition,cfg,q,pool,start,roots):
        return {'reward_units':[[0]*512,[130]*512] if pool['seed']==13 else [[0]*512,[0]*512,[46]*512]}
    rejected=False
    with patch.object(target.v9,'choose',return_value=('WAIT',{})),patch.object(target,'model_pool',side_effect=pool),patch.object(target,'branch_rewards',side_effect=bad_rewards):
        try:target.choose(None,obs,0,3,physics,matrix,config,[11,13],[.5]*21,512,alpha)
        except ArithmeticError:rejected=True
    require(rejected,'out-of-range reward rejected')
    require(hashlib.sha256(Path(target.__file__).read_bytes()).hexdigest()==source,'source unchanged')
    result={'status':'passed','checks':checks,'target_sha256':source,'gate_cases':results,
            'global_max_tests':2640,'global_delta':.05,'per_test_alpha':alpha,
            'uniform_bound':1.12,'first_prefix_radius':1.12*math.sqrt(2*math.log(1/alpha)/512),
            'scope':'independent bounded-reward enumeration and isolated gate fixtures; not a statistical coverage experiment',
            'limits':['requires independent model futures conditional on fixed prefix and pool1-selected action',
                      'familywise bound covers declared model-local tests, not true-world model error or total task superiority']}
    with out.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({'status':'passed','checks':checks,'first_prefix_radius':result['first_prefix_radius']}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    run(parser.parse_args().out)
