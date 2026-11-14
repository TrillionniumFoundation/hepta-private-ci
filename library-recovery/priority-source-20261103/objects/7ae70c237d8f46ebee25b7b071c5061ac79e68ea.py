"""P1/P2 actual CPU training of a small HCSN-*inspired* recurrent surrogate.

Eight matched-in-parameter, matched-in-information, matched-in-SGD-step arms
vary only whether a recurrent gate uses ordinary sigmoid or a locally
value/slope matched Call/Risk/Margin nonlinear transform. This is NOT the
original HCSN source implementation, NOT a He-Xiong neural kernel, and fixed
nonlinear feature FLOPs/cycles are NOT equalized. This pilot is research only.
"""
from __future__ import annotations
import hashlib
import json
import math
import time
import resource
import numpy as np
import torch
from torch import nn
from scipy.special import expit,ndtr
from fair_ablation import ARMS
from synthetic_ablation_pilot import _raw, _ordinary

FEATURES=('call','risk','margin')
INPUT_DIM=6
HIDDEN_DIM=10


def _calibration():
    output=[]
    for i,name in enumerate(FEATURES):
        y,d=_ordinary([1.],i)
        v,g=_raw(name,[1.])
        a=float(d[0]/(y[0]*(1-y[0])*g[0]))
        b=float(math.log(y[0]/(1-y[0]))-a*v[0])
        output.append((a,b))
    return output

CALIBRATION=_calibration()


def gate(x,i,native):
    """The native transform is sigmoid calibrated at x=1 exactly to the
    value and first derivative of the i-th ordinary sigmoid control.
    """
    alpha=(.8,-.9,1.3)[i]
    beta=(-.3,.1,.2)[i]
    ordinary=torch.sigmoid(alpha*(x-1)+beta)
    if not native:
        return ordinary
    if i==0:
        gamma=.65
        raw=torch.expm1(x)+torch.expm1(-gamma*x)/gamma
    elif i==1:
        mu=-.2;sig=.7;T=.9;u=sig*math.sqrt(T)
        a=(-x-mu*T)/u;b=(-x+mu*T)/u
        raw=.5*torch.erfc(-a/math.sqrt(2)) + torch.exp(-2*mu*x/sig**2)*(.5*torch.erfc(-b/math.sqrt(2)))
    elif i==2:
        raw=torch.nn.functional.softplus(4*(x-.8))/4
    a,b=CALIBRATION[i]
    return torch.sigmoid(a*raw+b)


class RecurrentSurrogate(nn.Module):
    def __init__(self,arm:str,hidden:int=HIDDEN_DIM):
        super().__init__()
        if arm not in ARMS:
            raise ValueError('unknown arm')
        self.arm=arm
        self.input_layer=nn.Linear(INPUT_DIM,hidden)
        self.recurrent_layer=nn.Linear(hidden,hidden,bias=False)
        self.readout=nn.Linear(hidden,2)
        self.log_rate=nn.Parameter(torch.tensor(math.log(4.),dtype=torch.float32))
    def forward(self,series):
        h=torch.zeros((series.shape[0],self.input_layer.out_features),device=series.device)
        native=() if self.arm=='control' else tuple(self.arm.split('+'))
        for t in range(series.shape[1]):
            inp=series[:,t,:]
            u=self.input_layer(inp)+self.recurrent_layer(h)
            x=2.*torch.sigmoid(u)
            gates=[gate(x,i,name in native) for i,name in enumerate(FEATURES)]
            g=(gates[0]+gates[1]+gates[2])/3.
            dt=inp[:,-1:].clamp(0.001,4.)
            decay=torch.exp(-dt*torch.exp(self.log_rate))
            h=h*decay+(1-decay)*torch.tanh(u)*g
        return self.readout(h)


def make_dataset(length,n,seed,task='overwrite_reset'):
    """Deterministic event-level supervised data. No teacher leakage.

    All sequences are independently generated and end in QUERY. Targets are
    the most recent WRITE0/WRITE1 since last RESET, defaulting to zero.
    The irregular variant uses exponential inter-event times.
    """
    if task not in ('overwrite_reset','irregular_time','selective_copy','long_range','mqar','regeneration') or length<6 or n<1:
        raise ValueError('unsupported event task or size')
    rng=np.random.default_rng(seed)
    xs=np.zeros((n,length,INPUT_DIM),dtype=np.float32)
    ys=np.empty(n,dtype=np.int64)
    for i in range(n):
        if task=='regeneration':
            # A deliberately synthetic proxy for multiple state re-initialisations:
            # 3 exact RESET events at known positions; WRITE after the last reset
            # is guaranteed, and later distractor/overwrites remain possible.
            # This is NOT a stochastic hazard / physical renewal law or CTMC.
            memory=0
            resets={length//4,length//2,3*length//4}
            final_reset=max(resets)
            for t in range(length-1):
                if t in resets:
                    token=3
                    memory=0
                elif t==final_reset+1:
                    token=int(rng.choice((1,2)))
                    memory=token-1
                else:
                    token=int(rng.choice((0,1,2),p=(.64,.18,.18)))
                    if token in (1,2):memory=token-1
                xs[i,t,token]=1.
                xs[i,t,5]=float(min(4.,rng.exponential(.7)))
            xs[i,-1,4]=1.
            xs[i,-1,5]=float(min(4.,rng.exponential(.7)))
            ys[i]=memory
            continue
        if task=='mqar':
            # Two-key associative memory: each write carries (key,value),
            # last event queries a random key. No answers encoded in QUERY.
            memories=[0,0]
            for t in range(length-1):
                key=int(rng.integers(0,2))
                if rng.random()<.65:
                    value=int(rng.integers(0,2))
                    xs[i,t,0]=key
                    xs[i,t,1]=value
                    xs[i,t,2]=1. # WRITE tag
                    memories[key]=value
                else:
                    xs[i,t,4]=1. # distractor / no-write
                xs[i,t,5]=float(rng.uniform(.25,1.25))
            queried_key=int(rng.integers(0,2))
            xs[i,-1,0]=queried_key
            xs[i,-1,3]=1. # QUERY tag
            xs[i,-1,5]=float(rng.uniform(.25,1.25))
            ys[i]=memories[queried_key]
            continue
        if task in ('selective_copy','long_range'):
            marked_index=(int(rng.integers(0,length//2))
                          if task=='selective_copy' else int(rng.integers(0,2)))
            marked_value=int(rng.integers(0,2))
            for t in range(length-1):
                xs[i,t,1+marked_value if t==marked_index else 0]=1.
                xs[i,t,5]=float(rng.uniform(.25,1.25))
            xs[i,-1,4]=1.;xs[i,-1,5]=float(rng.uniform(.25,1.25))
            ys[i]=marked_value
            continue
        memory=0
        for t in range(length-1):
            token=int(rng.choice((0,1,2,3),p=(.35,.27,.27,.11)))
            xs[i,t,token]=1
            if token==1:memory=0
            if token==2:memory=1
            if token==3:memory=0
            xs[i,t,5]=float(min(4.,rng.exponential(.7)) if task=='irregular_time' else rng.uniform(.25,1.25))
        xs[i,-1,4]=1
        xs[i,-1,5]=float(rng.uniform(.25,1.25))
        ys[i]=memory
    return torch.from_numpy(xs),torch.from_numpy(ys)


def tensor_sha(t):
    return hashlib.sha256(t.detach().cpu().numpy().tobytes()).hexdigest()


def model_parameters_sha(m):
    h=hashlib.sha256()
    for p in m.parameters():h.update(p.detach().cpu().numpy().tobytes())
    return h.hexdigest()


def test_local_slope(eps=1e-4):
    # float64 isolates the calibration accuracy from fp32 rounding.
    errors=[]
    for i in range(3):
        x=torch.tensor(1.,dtype=torch.float64,requires_grad=True)
        a=gate(x,i,False)
        b=gate(x,i,True)
        ga=torch.autograd.grad(a,x,retain_graph=True)[0]
        gb=torch.autograd.grad(b,x)[0]
        errors.append({'mechanism':FEATURES[i],
                       'value_difference':float((a-b).abs().detach()),
                       'derivative_difference':float((ga-gb).abs().detach())})
    return errors


def run_pilot(seeds=(13,29),train_length=24,holdout_length=48,
              train_n=192,holdout_n=192,training_steps=32,batch_size=24,
              task='overwrite_reset'):
    if len(set(seeds))!=len(seeds) or training_steps<=0:
        raise ValueError('invalid run')
    torch.set_num_threads(1)
    # CPU; prohibit accidental data-dependent accelerator interpretation.
    rows=[]
    for seed in seeds:
        train_x,train_y=make_dataset(train_length,train_n,seed,task)
        test_x,test_y=make_dataset(holdout_length,holdout_n,seed+100000,task)
        # The exact same SGD mini-batch order and initial trainable weights
        # are reused across all arms within each seed.
        sampling=np.random.default_rng(seed+99000)
        indices=[torch.tensor(sampling.integers(0,train_n,batch_size),dtype=torch.long)
                 for _ in range(training_steps)]
        for arm in ARMS:
            torch.manual_seed(seed)
            model=RecurrentSurrogate(arm)
            initial=model_parameters_sha(model)
            optimizer=torch.optim.Adam(model.parameters(),lr=.011)
            begin=time.perf_counter()
            model.train()
            for idx in indices:
                optimizer.zero_grad(set_to_none=True)
                prediction=model(train_x[idx])
                loss=torch.nn.functional.cross_entropy(prediction,train_y[idx])
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(),5.)
                optimizer.step()
            train_s=time.perf_counter()-begin
            model.eval()
            with torch.no_grad():
                logits=model(test_x)
                quality=float((logits.argmax(-1)==test_y).float().mean().item())
                holdout_loss=float(nn.functional.cross_entropy(logits,test_y).item())
                mean_probability=float(torch.softmax(logits,dim=-1)[:,1].mean().item())
            rows.append({'seed':seed,'arm':arm,'initial_parameters_sha256':initial,
                         'parameter_count':sum(p.numel() for p in model.parameters()),
                         'train_set_sha256':tensor_sha(train_x)+':'+tensor_sha(train_y),
                         'holdout_set_sha256':tensor_sha(test_x)+':'+tensor_sha(test_y),
                         'train_tokens':training_steps*batch_size*train_length,
                         'training_steps':training_steps,
                         'training_wall_seconds':round(train_s,5),
                         'holdout_accuracy':quality,'holdout_cross_entropy':holdout_loss,
                         'prediction_mean_prob_one':mean_probability,
                         'train_n':train_n,'holdout_n':holdout_n})
    mismatches=[]
    for seed in seeds:
        cohort=[r for r in rows if r['seed']==seed]
        for field in ('initial_parameters_sha256','parameter_count','train_set_sha256',
                      'holdout_set_sha256','training_steps','train_tokens'):
            if len({x[field] for x in cohort})!=1:
                mismatches.append(f'{seed}: {field} not equal')
    return {'scope':'small CPU-trained HCSN-inspired surrogate, NOT original HCSN',
            'task':task,'train_length':train_length,'holdout_length':holdout_length,
            'seeds':list(seeds),'local_value_slope_matching':test_local_slope(),
            'rows':rows,'matched_parameter_data_step_constraints':not mismatches,
            'design_problems':mismatches,
            'full_training_flops_equal':False,'energy_measured':False,
            'source_HCSN_implementation_proven':False,
            'production_evidence_accepted':False}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--steps',type=int,default=32)
    parser.add_argument('--task',choices=('overwrite_reset','irregular_time','selective_copy','long_range','mqar','regeneration'),default='overwrite_reset')
    parser.add_argument('--seeds',nargs='+',type=int,default=[13,29])
    parser.add_argument('--out',default='reports/p1_p2_recurrent_pilot.json')
    args=parser.parse_args()
    d=run_pilot(seeds=args.seeds,training_steps=args.steps,task=args.task)
    from pathlib import Path
    Path(args.out).parent.mkdir(parents=True,exist_ok=True)
    Path(args.out).write_text(json.dumps(d,indent=2))
    print('saved',args.out,'arm rows',len(d['rows']),
          'elapsed training seconds',round(sum(x['training_wall_seconds'] for x in d['rows']),2))
    print('accuracies',{r['arm']:r['holdout_accuracy'] for r in d['rows'] if r['seed']==args.seeds[0]})
