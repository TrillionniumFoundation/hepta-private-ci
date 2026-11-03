"""Joint inference checkpoint for CoupledSpikePolicy, never the old sampler state.

The saved spike trace, pending initial score and PCG64 are required state. Model
parameters are separate. This is a Python single-owner, committed-boundary
research wrapper; it makes no production, durability or training-resume claim.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from ...coupled.model import CoupledSpikePolicy, CoupledState
from ...hepta.joint_checkpoint import (
    Scenario, validate_scenario, initial_ledger, commit_ledger, canonical, weights_sha,
)
from rrsnn_experiments.resource_env import exogenous, state_features, legal_actions, next_deadlines, EPS

MAIN = Path(__file__).resolve().parents[2]
SCHEMA = 'rrsnn.coupled-spike-ledger-checkpoint.v1'
DOMAIN = SCHEMA.encode()+b'\0'
STATE_FIELDS = {'indices','trace','context','drift','boundary','time','total_counts','observed','pending_initial_score'}
SOURCE_NAMES = ['audit/coupled_checkpoint/checkpoint.py','coupled/model.py','density_model.py',
                'policy.py','hepta/joint_checkpoint.py','../rrsnn_experiments/resource_env.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_model(path):
    blob = torch.load(path,map_location='cpu',weights_only=True)
    meta = blob['metadata']
    model = CoupledSpikePolicy(input_size=meta['input_size'],hidden_size=meta['hidden_size'],
        grid_size=meta['grid_size'],refractory_phases=meta['refractory_phases'],trace_tau=meta['trace_tau'])
    model.load_state_dict(blob['state_dict'],strict=True)
    model.eval()
    return model,blob


def profile(model):
    result = {name:getattr(model,name) for name in
              ('input_size','hidden_size','trace_tau','fixed_boundary','drift_scale','kick_scale')}
    result['operator'] = {name:getattr(model.operator,name) for name in
                         ('grid_size','refractory_phases','state_size','lower_bound','sigma','refractory','reset','method')}
    result['dtype'] = str(next(model.parameters()).dtype)
    return result


def state_record(state):
    if set(vars(state)) != STATE_FIELDS:
        raise ValueError('Coupled state fields changed; checkpoint profile must be reviewed')
    return {name:value.detach().cpu().tolist() if torch.is_tensor(value) else value.tolist()
            for name,value in vars(state).items()}


class CoupledJointRollout:
    def __init__(self,model,artifact,scenario,seed=992101):
        validate_scenario(scenario)
        parameter=next(model.parameters())
        if parameter.dtype!=torch.float32 or parameter.device.type!='cpu':
            raise ValueError('This inference checkpoint profile is float32 CPU')
        self.model=model.eval();self.artifact=Path(artifact).resolve()
        self.scenario=scenario;self.times=scenario.events();self.next_index=0
        self.rng=np.random.default_rng(seed)
        self.state=model.initial_state(1,self.rng)
        self.ledger=initial_ledger(scenario);self.committed=[];self.in_event=False

    @torch.no_grad()
    def advance(self,index):
        if self.in_event or type(index) is not int or index!=self.next_index or index>=len(self.times):
            raise ValueError('Duplicate/stale tick, incomplete event, or terminal episode')
        self.in_event=True
        now=self.times[index]
        available,_,_=exogenous(self.scenario,now,self.ledger['budget'])
        x=state_features(self.scenario,now,self.ledger['live'],available)
        state,out=self.model.step(self.state,torch.from_numpy(x[None,:]),now-float(self.state.time[0]),
                                 self.rng,record_spikes=True,record_path=True)
        action=None
        if index<len(self.times)-1:
            valid,due=legal_actions(self.scenario,now,self.ledger['live'],available)
            action=int(out['logits'][0].masked_fill(~torch.from_numpy(valid),-1e9).argmax()) if due.any() else 0
        ledger,checked=commit_ledger(self.scenario,self.ledger,index,action)
        if not np.array_equal(x,checked):raise AssertionError('Observation mismatch')
        row={'event_index':index,'time':now,'action':action,'observation':x.tolist(),
             'latent':out['latent'][0].tolist(),'interval_counts':out['actual_counts'][0].tolist(),
             'spikes':out['spike_times'],'trace_after_interval':out['path_record']['trace_after_interval'].tolist(),
             'trace_after_observation':state.trace.tolist(),'ledger_after':ledger}
        self.state=state;self.ledger=ledger;self.committed.append(row);self.next_index+=1;self.in_event=False
        return row

    def binding(self):
        return {'model_artifact_sha256':sha(self.artifact),'model_weights_sha256':weights_sha(self.model),
                'model_profile':profile(self.model),'source_sha256':{p:sha(MAIN/p) for p in SOURCE_NAMES},
                'numpy_version':np.__version__,'torch_version':str(torch.__version__)}

    def deadline_queue(self):
        now=self.times[self.next_index-1]
        deadlines=next_deadlines(self.scenario,now if self.next_index==len(self.times) else now+4*EPS)
        return [{'item':i,'value':self.scenario.values[i],'next_deadline':float(deadlines[i])}
                for i in range(4) if self.ledger['live']>>i&1]

    def checkpoint(self):
        if self.in_event or self.next_index==0:raise ValueError('Only fully committed inference events can be saved')
        rng=json.loads(json.dumps(self.rng.bit_generator.state))
        for name in ('state','inc'):rng['state'][name]=str(rng['state'][name])
        payload={'schema':SCHEMA,'phase':'after_committed_inference_event','binding':self.binding(),
                 'scenario':asdict(self.scenario),'event_schedule':self.times,'next_event_index':self.next_index,
                 'execution_state':state_record(self.state),'rng':rng,'ledger':self.ledger,
                 'deadline_queue':self.deadline_queue(),'committed_events':self.committed}
        payload=json.loads(canonical(payload))
        return {'schema':SCHEMA,'payload':payload,'payload_sha256':hashlib.sha256(DOMAIN+canonical(payload)).hexdigest(),
                'authority':'none','official_owner_receipt':None,'production_activation_allowed':False}

    @classmethod
    @torch.no_grad()
    def restore(cls,envelope,model,artifact,expected_sha256):
        required={'schema','payload','payload_sha256','authority','official_owner_receipt','production_activation_allowed'}
        if set(envelope)!=required:raise ValueError('Unknown envelope fields')
        p=envelope['payload'];digest=hashlib.sha256(DOMAIN+canonical(p)).hexdigest()
        if (envelope['schema']!=SCHEMA or p['schema']!=SCHEMA or digest!=envelope['payload_sha256']
            or digest!=expected_sha256 or envelope['authority']!='none'
            or envelope['official_owner_receipt'] is not None or envelope['production_activation_allowed'] is not False):
            raise ValueError('Integrity/expected-digest/non-authorizing envelope mismatch')
        if p['phase']!='after_committed_inference_event':raise ValueError('Mid-event/training recovery unsupported')
        raw=dict(p['scenario']);raw['values']=tuple(raw['values']);raw['deadlines']=tuple(raw['deadlines'])
        restored=cls(model,artifact,Scenario(**raw),seed=0)
        if restored.binding()!=p['binding']:raise ValueError('Wrong model, code, runtime or operator profile')
        frontier=p['next_event_index']
        if type(frontier) is not int or not 1<=frontier<=len(restored.times):raise ValueError('Invalid event frontier')
        if p['event_schedule']!=list(restored.times) or len(p['committed_events'])!=frontier:
            raise ValueError('Event schedule/history mismatch')
        ledger=initial_ledger(restored.scenario);h=model.hidden_size
        count=np.zeros((1,h),dtype=np.int64);trace=np.zeros((1,h),dtype=np.float64)
        context=torch.zeros((1,h),dtype=torch.float32);last=0.
        for index,row in enumerate(p['committed_events']):
            if row['event_index']!=index or row['time']!=restored.times[index]:raise ValueError('History order mismatch')
            ledger,obs=commit_ledger(restored.scenario,ledger,index,row['action'])
            if ledger!=row['ledger_after'] or obs.tolist()!=row['observation']:raise ValueError('Ledger/observation replay mismatch')
            now=row['time'];decayed=trace*np.exp(-(now-last)/model.trace_tau)
            immediate=np.zeros((1,h),dtype=np.int64);all_counts=np.zeros((1,h),dtype=np.int64)
            for event in row['spikes']:
                c=event['component']
                if event['batch']!=0 or type(c) is not int or not 0<=c<h or not last<=event['time']<=now:
                    raise ValueError('Invalid spike identity/clock')
                all_counts[0,c]+=1
                if event['cause']=='ctmc_threshold':
                    decayed[0,c]+=np.exp(-(now-event['time'])/model.trace_tau)
                elif event['cause']=='ctmc_observation_remap' and event['time']==now:
                    immediate[0,c]+=1
                else:raise ValueError('Invalid spike cause')
            before=np.asarray(row['trace_after_interval'],dtype=np.float64)
            after=np.asarray(row['trace_after_observation'],dtype=np.float64)
            if before.shape!=(1,h) or after.shape!=(1,h) or not np.isfinite(before).all() or (before<0).any():
                raise ValueError('Invalid spike trace shape/value')
            # Stored absolute spike times can lose a final rounding bit from
            # original interval-local times. Controls use the exact saved trace.
            if not np.allclose(before,decayed,rtol=0,atol=2e-12) or not np.array_equal(after,before+immediate):
                raise ValueError('Spike trace does not reconstruct from actual events')
            if (immediate>1).any() or all_counts[0].tolist()!=row['interval_counts']:
                raise ValueError('Actual spike counts mismatch')
            controls=model.controls(torch.from_numpy(obs[None,:]),before,context)
            context=controls['context'];trace=after;count+=all_counts;last=now
        if ledger!=p['ledger']:raise ValueError('Budget/reward ledger mismatch')
        restored.ledger=ledger;restored.next_index=frontier
        if restored.deadline_queue()!=p['deadline_queue']:raise ValueError('Deadline queue mismatch')
        e=p['execution_state']
        if set(e)!=STATE_FIELDS:raise ValueError('Incomplete coupled physical state')
        indices=np.asarray(e['indices'])
        if indices.shape!=(1,h) or indices.dtype.kind not in 'iu' or (indices<0).any() or (indices>=model.operator.state_size).any():
            raise ValueError('Invalid CTMC indices')
        if e['trace']!=trace.tolist() or e['total_counts']!=count.tolist():raise ValueError('Saved trace/counts do not match past events')
        if e['time']!=[last] or e['observed']!=[True] or e['pending_initial_score']!=[0.0]:
            raise ValueError('Clock/observation/pending-initial-score mismatch')
        held={}
        for name in ('context','drift','boundary'):
            actual=np.asarray(e[name],dtype=np.float32)
            if actual.shape!=(1,h) or not np.isfinite(actual).all() or not np.array_equal(actual,controls[name].numpy()):
                raise ValueError('Saved learned controls do not match trace-conditioned replay')
            held[name]=torch.from_numpy(actual.copy())
        restored.state=CoupledState(indices.astype(np.int64),trace.copy(),held['context'],held['drift'],held['boundary'],
            np.array([last],dtype=np.float64),count.copy(),np.ones(1,dtype=bool),torch.zeros(1,dtype=torch.float64))
        rng=json.loads(json.dumps(p['rng']))
        if (set(rng)!={'bit_generator','state','has_uint32','uinteger'} or rng['bit_generator']!='PCG64'
            or set(rng['state'])!={'state','inc'} or type(rng['has_uint32']) is not int
            or rng['has_uint32'] not in (0,1) or type(rng['uinteger']) is not int or not 0<=rng['uinteger']<2**32):
            raise ValueError('Invalid RNG profile')
        for name in ('state','inc'):
            word=rng['state'][name]
            if not isinstance(word,str) or not word.isdecimal() or str(int(word))!=word or not 0<=int(word)<2**128:
                raise ValueError('Invalid canonical PCG64 integer')
            rng['state'][name]=int(word)
        if rng['state']['inc']%2!=1:raise ValueError('Invalid PCG64 increment')
        restored.rng.bit_generator.state=rng
        restored.committed=json.loads(canonical(p['committed_events']))
        return restored
