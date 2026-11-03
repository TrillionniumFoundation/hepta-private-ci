"""P1: actual equal-trainable-parameter CPU ridge pilot, NOT HCSN evidence.

Null-problem on independently generated 1D function. All arms observe exactly
same x, data, train set, holdout and ridge solver; native features locally
match the value AND slope of ordinary sigmoid gates at x=1. Native feature
preprocessing is costlier; this pilot MUST NOT qualify equal compute budget.
"""
from __future__ import annotations
import hashlib
import json
import numpy as np
from scipy.special import ndtr,expit
from fair_ablation import ARMS
from factorial_evidence import estimate_mechanisms


def _raw(name,x):
    x=np.asarray(x,dtype=np.float64)
    if name=='call':
        gamma=.65
        return np.expm1(x)+np.expm1(-gamma*x)/gamma, np.exp(x)-np.exp(-gamma*x)
    if name=='risk':
        mu=-.2; sig=.7; T=.9; u=sig*np.sqrt(T)
        a=(-x-mu*T)/u
        b=(-x+mu*T)/u
        h=np.exp(-2*mu*x/sig**2)
        value=ndtr(a)+h*ndtr(b)
        dens=lambda z:np.exp(-z*z/2)/np.sqrt(2*np.pi)
        derivative=-dens(a)/u+h*(-2*mu/sig**2*ndtr(b)-dens(b)/u)
        return value,derivative
    if name=='margin':
        value=np.logaddexp(0.,4*(x-.8))/4
        return value,expit(4*(x-.8))
    raise ValueError('invalid mechanism')


def _ordinary(x,i):
    alpha=[.8,-.9,1.3][i]
    bias=[-.3,.1,.2][i]
    y=expit(alpha*(np.asarray(x)-1)+bias)
    return y,alpha*y*(1-y)


def design(x,arm):
    x=np.asarray(x,dtype=np.float64)
    activated=set() if arm=='control' else set(arm.split('+'))
    vectors=[np.ones_like(x),x]
    for i,name in enumerate(('call','risk','margin')):
        base,_=_ordinary(x,i)
        if name not in activated:
            vectors.append(base)
            continue
        reference,ref_grad=_ordinary(np.asarray([1.]),i)
        raw,grad=_raw(name,np.asarray([1.]))
        if abs(grad[0])<1e-12:
            raise ArithmeticError('zero slope at matching anchor')
        warped,_=_raw(name,x)
        feat=reference[0]+(warped-raw[0])*ref_grad[0]/grad[0]
        vectors.append(feat)
    return np.stack(vectors,axis=-1)


def local_value_and_slope(arm,dx=1e-5):
    x0=design([1.],arm)[0]
    derivative=(design([1.+dx],arm)[0]-design([1.-dx],arm)[0])/(2*dx)
    return x0,derivative


def _hash_array(x):
    x=np.asarray(x,dtype='<f8')
    return hashlib.sha256(x.tobytes()).hexdigest()


def run_pilot(seeds=(11,23,37,41,59),train_size=192,holdout_size=1024):
    if len(set(seeds))!=len(seeds):raise ValueError('duplicate seed')
    rows=[]
    summaries=[]
    for seed in seeds:
        rng=np.random.default_rng(seed)
        train_x=rng.uniform(.05,2.4,size=train_size)
        holdout_x=rng.uniform(.05,2.4,size=holdout_size)
        target=lambda z:expit(1.8*(z-1.))+.15*np.sin(5*z)
        train_y=target(train_x)+rng.normal(0,.06,size=train_size)
        test_y=target(holdout_x)
        x0,grad0=local_value_and_slope('control')
        for arm in ARMS:
            feat=design(train_x,arm)
            test_feat=design(holdout_x,arm)
            weights=np.linalg.solve(feat.T@feat+np.eye(5)*.0001,feat.T@train_y)
            pred=test_feat@weights
            mse=float(np.mean((pred-test_y)**2))
            if not np.isfinite(mse):raise ArithmeticError('nonfinite MSE')
            local,grad=local_value_and_slope(arm)
            # This metadata verifies only trainable ridge dimensions and
            # linear readout FLOPs, NOT full feature/transformation cost.
            rows.append({'seed':seed,'arm':arm,
                         'train_set_sha256':_hash_array(np.stack((train_x,train_y),axis=1)),
                         'holdout_set_sha256':_hash_array(np.stack((holdout_x,test_y),axis=1)),
                         'information_sha256':_hash_array(train_x),
                         'encoder_sha256':hashlib.sha256(b'NO_ENCODER/synthetic_pilot').hexdigest(),
                         'parameter_count':5,
                         'local_slope_norm':float(np.linalg.norm(grad)),
                         'train_tokens':train_size,
                         'train_flops':float(5*5*train_size+5**3),
                         'hyperparameter_search_trials':1,
                         'quality':1/(1+mse),
                         'inference_flops':float(5*holdout_size*2),
                         'training_joules':None,
                         'peak_rss_bytes':None,
                         'pilot_mse':mse,
                         'local_value_max_abs_delta':float(np.max(np.abs(local-x0))),
                         'local_derivative_max_abs_delta':float(np.max(np.abs(grad-grad0)))})
        summaries.append({'seed':seed,'train_points':train_size,'holdout_points':holdout_size})
    analysis=estimate_mechanisms(
        rows,seeds,exploratory_unmeasured_physical=True)
    if not analysis['valid_exploratory_design']:
        raise AssertionError(f'pilot design invalid: {analysis["problems"]}')
    return {'scope':'ACTUAL CPU ridge readout fitted on synthetic 1D null task, NOT HCSN',
            'model_trainable_parameters':5,'study_seeds':list(seeds),
            'equal_slope_check_max':max(r['local_derivative_max_abs_delta'] for r in rows),
            'equal_anchor_value_check_max':max(r['local_value_max_abs_delta'] for r in rows),
            'quality_by_arm':{arm:sum(r['quality'] for r in rows if r['arm']==arm)/len(seeds)
                              for arm in ARMS},
            'mse_by_arm':{arm:sum(r['pilot_mse'] for r in rows if r['arm']==arm)/len(seeds)
                          for arm in ARMS},
            'exploratory_factorial':analysis,
            'full_feature_training_compute_matched':False,
            'feature_cost_measured':False,
            'energy_measured':False,
            'production_evidence_accepted':False}

if __name__=='__main__':
    print(json.dumps(run_pilot(),indent=2))
