"""Opt-in continuous task adapter; bounded semantic/recovery qualification only."""
import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from scipy.special import expit, ndtr
from ..digital_read_before_20261031 import data, deploy, task
from . import continuous_renewal as renewal

HERE = Path(__file__).resolve().parent
BASE = HERE.parent/'digital_read_before_20261031'
ROOT = HERE.parents[2]
CONTRACT = dict(schema='continuous-task-opt-in-v1', dynamic='continuous Brownian first passage',
                reset='continuous truncated Gaussian', normalized_reset_sd=.12,
                changed_from='finite projected folded-bin reset with interval-end recovery',
                head='unchanged archived 48x32x7', training='none', task_benefit_claim=False)


def read(path):
    path=Path(path);raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    with path.open('xb') as f:f.write(gzip.compress(raw,mtime=0) if path.suffix=='.gz' else raw)
    return sha(path)


def source_hashes():
    names=[HERE/'continuous_task_adapter.py',HERE/'continuous_task_protocol.json',HERE/'continuous_renewal.py']
    names += [BASE/(n+'.py') for n in ('task','data','deploy')]
    names += [BASE/'protocol.json',HERE.parent/'task_value_factorial_20261030/task.py',
              HERE.parent/'task_value_factorial_20261030/UPSTREAM_FILES.json']
    names += [ROOT/item['path'] for item in read(names[-1])['files']]
    return {str(p.relative_to(ROOT)):sha(p) for p in names}


class ContinuousPolicy(deploy.Policy):
    def __init__(self,artifact):
        if artifact.get('continuous_opt_in')!=CONTRACT:
            raise ValueError('explicit compatible continuous artifact opt-in required')
        super().__init__(artifact)
        if artifact['family']!='first_passage_bank':raise ValueError('FPT artifact required')
        self.physical=artifact['kernel']['physical']
        self.law(dict(last_symbol=0,last_reliability=.5)).validate()

    def law(self,state):
        p=self.physical
        return renewal.Law(boundary=p['boundary'],diffusion=p['diffusion'],
          drift=p['drift_bias']+p['gain']*state['last_symbol']*(2*state['last_reliability']-1),
          recovery_rate=p['recovery_rate'],reset_minus=p['reset_minus'],reset_plus=p['reset_plus'],
          reset_sd=CONTRACT['normalized_reset_sd']*p['boundary'])

    def predict_continuous(self,public,owner_state,cell,structured):
        law=self.law(owner_state);cell.validate(law)
        if cell.mode:
            rep=np.r_[np.zeros(10),float(cell.mode==-1),float(cell.mode==1)]
        else:
            calls=[ndtr((cell.voltage+law.drift*h-k*law.boundary)/(law.diffusion*np.sqrt(h)))
                   for h in (.25,.75,1.5) for k in (-.5,0.,.5)]
            rep=np.r_[calls,cell.voltage/law.boundary,0.,0.]
        x=np.r_[task.public_features(public,owner_state),rep]
        out=self.w2@np.tanh(self.w1@x+self.b1)+self.b2;p=float(expit(out[6]))
        q=out[:6].copy()
        if structured:q[[0,4,5]]=[0.,1-2*p,2*p-1]
        return dict(q=q.tolist(),belief=p,input=x.tolist())


def snapshot(owner,cell,rng,law,artifact_hash):
    return json.loads(json.dumps(dict(schema='continuous-task-checkpoint-v1',artifact_sha256=artifact_hash,
       public_sha256=hashlib.sha256(json.dumps(owner.public,sort_keys=True).encode()).hexdigest(),
       owner_state=owner.state,owner_receipts=owner.receipts,cell=renewal.checkpoint(cell,rng,law))))


def restore(payload,public,folder,adapter,artifact_hash):
    h=hashlib.sha256(json.dumps(public,sort_keys=True).encode()).hexdigest()
    if payload['schema']!='continuous-task-checkpoint-v1' or payload['artifact_sha256']!=artifact_hash or payload['public_sha256']!=h:
        raise ValueError('checkpoint owner/artifact identity mismatch')
    owner=task.Owner(public,folder,adapter)
    owner.state=copy.deepcopy(payload['owner_state']);owner.receipts=copy.deepcopy(payload['owner_receipts'])
    cell,rng,law=renewal.restore(payload['cell'])
    return owner,cell,rng,law


def stable(value):
    if isinstance(value,dict):return {k:stable(v) for k,v in value.items() if not k.endswith('_seconds')}
    if isinstance(value,list):return [stable(v) for v in value]
    return value


def episode(public,folder,adapter,policy,controller,seed,artifact_hash,start=None):
    owner=task.Owner(public,folder,adapter);cell=renewal.State();rng=np.random.default_rng(seed)
    if start is not None:owner,cell,rng,_=restore(start,public,folder,adapter,artifact_hash)
    checkpoints=[snapshot(owner,cell,rng,policy.law(owner.state),artifact_hash)];rows=[]
    while not owner.state['terminal']:
        before=copy.deepcopy(owner.state);oldcell=copy.deepcopy(cell);mask=task.legal(public,before)
        scores=policy.predict_continuous(public,before,cell,controller=='structured_value')
        action=task.fixed_action(before,mask,scores['belief']) if controller=='fixed' else int(np.argmax(np.where(mask,scores['q'],-np.inf)))
        events=[];wall,cpu=time.perf_counter(),time.process_time()
        if action not in (0,4,5):
            cell,events=renewal.advance(cell,public['duration'][before['tick']],policy.law(before),rng)
        receipt=owner.step(action)
        rows.append(dict(action=action,scores=scores,cell_before=copy.deepcopy(oldcell.__dict__),
             cell_after=copy.deepcopy(cell.__dict__),events=events,receipt=receipt,
             step_wall_seconds=time.perf_counter()-wall,step_cpu_seconds=time.process_time()-cpu))
        checkpoints.append(snapshot(owner,cell,rng,policy.law(owner.state),artifact_hash))
    return dict(rows=rows,final=checkpoints[-1],checkpoints=checkpoints)


def prepare(out):
    protocol=read(HERE/'continuous_task_protocol.json');out.mkdir(parents=True,exist_ok=False)
    models={};old={}
    for fit in protocol['fits']:
        path=BASE/f'checkpoints/fit_{fit}/first_passage_bank.json.gz';artifact=read(path)
        old[str(path.relative_to(ROOT))]=sha(path)
        artifact['continuous_opt_in']=copy.deepcopy(CONTRACT)
        artifact['continuous_source_artifact_sha256']=sha(path)
        modelpath=out/f'fit_{fit}_continuous_optin.json.gz';models[modelpath.name]=write(modelpath,artifact)
    freeze=dict(schema='continuous-task-source-freeze-v1',sources=source_hashes(),old_models=old,
       optin_artifacts=models,protocol=protocol,contract=CONTRACT,worlds_generated=False)
    write(out/'PREPARED_FREEZE.json',freeze)
    print(json.dumps(dict(prepared=str(out),models=len(models),worlds_generated=False)))


def run(prepared,published_commit):
    freeze=read(prepared/'PREPARED_FREEZE.json');protocol=freeze['protocol']
    if len(published_commit)!=40 or any(c not in '0123456789abcdef' for c in published_commit):
        raise ValueError('full published source commit required')
    if source_hashes()!=freeze['sources']:raise ValueError('source freeze mismatch')
    for name,h in freeze['old_models'].items():
        if sha(ROOT/name)!=h:raise ValueError('old artifact changed')
    for name,h in freeze['optin_artifacts'].items():
        if sha(prepared/name)!=h:raise ValueError('opt-in artifact changed')
    out=prepared/'qualification';out.mkdir(exist_ok=False)
    write(out/'STARTED.json',dict(published_source_commit=published_commit,freeze_sha256=sha(prepared/'PREPARED_FREEZE.json')))
    adapter=task.ContentAdapter();oldprotocol=read(BASE/'protocol.json')
    oldprotocol['confirmation_seed_base']=protocol['qualification_seed_base']
    all_rows=[];cohorts=[];checks=[];wall,cpu=time.perf_counter(),time.process_time()
    for fit in protocol['fits']:
        cohort=data.cohort(out/'worlds','iid',fit,protocol['worlds_per_fit'],oldprotocol);cohorts.append(cohort)
        artifact_path=prepared/f'fit_{fit}_continuous_optin.json.gz';artifact=read(artifact_path)
        policy=ContinuousPolicy(artifact);artifact_hash=sha(artifact_path)
        for wi,record in enumerate(cohort['records']):
            folder=Path(record['folder']);public=read(folder/'public.json')
            for controller in protocol['controllers']:
                seed=protocol['cell_seed_base']+fit*1000+wi
                start=time.perf_counter(),time.process_time()
                original=episode(public,folder,adapter,policy,controller,seed,artifact_hash)
                resumes=[]
                for boundary,payload in enumerate(original['checkpoints']):
                    replay=episode(public,folder,adapter,policy,controller,seed,artifact_hash,start=payload)
                    same=(stable(replay['rows'])==stable(original['rows'][boundary:]) and stable(replay['final'])==stable(original['final']))
                    resumes.append(dict(boundary=boundary,matched=same,replay=replay))
                    checks.append(same)
                label=read(folder/'evaluator.json')['label']
                outcome=task.evaluate_terminal(original['final']['owner_state'],label)
                all_rows.append(dict(fit=fit,world=record['id'],controller=controller,episode=original,
                    resumes=resumes,outcome=outcome,wall_seconds=time.perf_counter()-start[0],
                    cpu_seconds=time.process_time()-start[1]))
    integrity=dict(sources=source_hashes()==freeze['sources'],
      old_models=all(sha(ROOT/name)==h for name,h in freeze['old_models'].items()),
      optin_artifacts=all(sha(prepared/name)==h for name,h in freeze['optin_artifacts'].items()))
    result=dict(schema='continuous-task-qualification-v1',published_source_commit=published_commit,
      freeze_sha256=sha(prepared/'PREPARED_FREEZE.json'),contract=CONTRACT,cohorts=cohorts,episodes=all_rows,
      content_setup=adapter.setup,checks=dict(all_boundary_restores_match=all(checks),boundaries=len(checks),hashes_unchanged_after_execution=integrity),
      wall_seconds=time.perf_counter()-wall,cpu_seconds=time.process_time()-cpu)
    evidence=write(out/'RAW.json.gz',result)
    summary=dict(schema=result['schema'],episodes=len(all_rows),worlds=protocol['worlds_per_fit']*len(protocol['fits']),
      checks=result['checks'],actual_source_opens=sum(r['receipt']['source_opened'] is not None for e in all_rows for r in e['episode']['rows']),
      replay_source_opens=sum(r['receipt']['source_opened'] is not None for e in all_rows for replay in e['resumes'] for r in replay['replay']['rows']),
      events=sum(len(r['events']) for e in all_rows for r in e['episode']['rows']),
      pending_checkpoints=sum(c['owner_state']['pending'] is not None for e in all_rows for c in e['episode']['checkpoints']),
      refractory_checkpoints=sum(c['cell']['state']['mode']!=0 for e in all_rows for c in e['episode']['checkpoints']),
      raw_sha256=evidence,published_source_commit=published_commit,freeze_sha256=sha(prepared/'PREPARED_FREEZE.json'),
      wall_seconds=result['wall_seconds'],cpu_seconds=result['cpu_seconds'],claim='semantic adapter/recovery only; no task-benefit qualification')
    write(out/'SUMMARY.json',summary);print(json.dumps(summary,indent=2))
    if not all(checks) or not all(integrity.values()):raise RuntimeError('boundary replay/integrity failure retained')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['prepare','run']);p.add_argument('--prepared',type=Path,required=True)
    p.add_argument('--published-source-commit');a=p.parse_args()
    if a.stage=='prepare':prepare(a.prepared)
    else:run(a.prepared,a.published_source_commit or '')
