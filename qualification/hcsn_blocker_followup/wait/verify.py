"""Independent HAPT raw sensor, classifier, decision and value replay after confirmation."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
import numpy as np
import torch
from qualification.hcsn_intervention_value.policy import representation,features,fold_ids
from qualification.hcsn_intervention_value.verify_policy import nuisance_replay,context,head


def read(p):return json.loads(p.read_text())
def same(x,y):np.testing.assert_allclose(x,y,rtol=1e-8,atol=2e-9)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def samples(archive,subjects):
    ends={7:(1,0),8:(0,1),9:(0,2),10:(2,0),11:(1,2),12:(2,1)}; out={}; events={}
    with zipfile.ZipFile(archive) as z:
        for e,subject,act,b,_ in np.loadtxt(z.open('RawData/labels.txt'),dtype=int):
            if subject in subjects and act in ends:events.setdefault((e,subject),[]).append((act,b))
        for (e,sub),ev in events.items():
            arr=[np.loadtxt(z.open(f'RawData/{s}_exp{e:02d}_user{sub:02d}.txt')) for s in ('acc','gyro')]
            for act,b in ev:
                if b<24 or b+120>len(arr[0]): continue
                subject,goal=ends[act];target=tuple(v for v in range(3) if v!=subject).index(goal)
                uid=f'subject-{sub:02d}/trial-{e:02d}/sample-{b}'; channels=[]
                for a in arr:
                    rows=[];baseline=a[b-24:b].mean(0)
                    for t in range(6):
                        x=a[b-24+24*t:b+24*t]; past=a[b-24:b+24*t]; delta=np.diff(x,axis=0)
                        rows.append(np.r_[np.mean(x,axis=0),np.std(x,axis=0),x[23]-x[0],x[23],x.mean(0)-baseline,
                            np.sum(x[16:]-x[:8],axis=0)/8,np.sqrt(np.sum(delta*delta,axis=0)/23),np.mean(past,axis=0),past.max(0)-past.min(0)])
                    channels.append(rows)
                out[uid]=(int(sub),subject,target,np.asarray(channels))
    return out


def replay_class(train,valid,alltrain,leaveout):
    g,post,gold,m=train;gv,pv,_,v=valid; ans=[]
    for i in range(2):
        x=np.concatenate([m[:,j] for j in range(i+1)],-1);y=np.concatenate([v[:,j] for j in range(i+1)],-1);pred=np.empty(y.shape[:2])
        for src in np.unique(gv) if leaveout else (None,):
            for pose in range(3):
                tr=np.where((post==pose)&(g!=src))[0];test=np.where((pv==pose)&((gv==src) if leaveout else np.ones(len(pv),bool)))[0];gy=gold[tr]
                w=np.array([1/(g[tr]==s).sum() for s in g[tr]]);w/=w.sum();b=float(w@gy)
                for t in range(6):
                    value=x[tr,t]; center=w@value;sd=np.sqrt(w@(value-center)**2).clip(1e-6);a=(value-center)/sd;d=a.shape[-1]
                    coef=np.linalg.lstsq(np.vstack((a*np.sqrt(w[:,None]),np.sqrt(.1)*np.eye(d))),np.r_[(gy-b)*np.sqrt(w),np.zeros(d)],rcond=None)[0]
                    pred[test,t]=(((y[test,t]-center)/sd)@coef+b).clip(.001,.999)
        ans.append(np.stack((1-pred,pred),-1))
    return ans


def independent_value(z,t,a):
    times=np.array(t);actions=np.array(a); i=np.arange(len(t));hits=np.where(actions==1,z['read_scores'][i,times].argmax(1),z['scores'][i,times].argmax(1))==z['target'];
    u=[]
    for ti,ac,h in zip(times,actions,hits):
        # One-step Bellman accumulation instead of the closed return used to score.
        val=float(h)-.30*ac;disc=np.exp(-.2*.48)
        for _ in range(ti):val=disc*val-2*(1-disc)
        u.append(val)
    return np.array(u),hits


def evaluate_decision(z,r):
    v,h=independent_value(z,r['prefix'],r['action']);same(r['u'],v);same(r['hit'],h);groups=z['group'];
    for g in np.unique(groups):same(r['by_group'][g],v[groups==g].mean());same(r['r1_by_group'][g],h[groups==g].mean())
    same(r['utility'],np.mean(list(r['by_group'].values())));same(r['r1'],np.mean(list(r['r1_by_group'].values())))


def verify(archive,out):
    import time
    start=time.monotonic();roster=read(out/'roster.json');seal=read(out/'fit_seal.json');conf=read(out/'confirmation.json');w=read(out/'weights.json');dev=read(out/'development.json')
    assert sha(archive)==roster['archive_sha']==seal['raw_archive_sha'] and conf['fit_seal']==sha(out/'fit_seal.json') and conf['shard_sha']==sha(out/'test.npz')
    for k,h in seal['files'].items():assert sha(out/k)==h
    splits={}; raw={}; evaluations=0;model_evals=0; heads=0;max_prob=0.;max_coef=0.
    for name,ids in roster['subjects'].items():
        with np.load(out/(name+'.npz'),allow_pickle=False) as f:splits[name]=z={k:f[k] for k in f.files}
        source=samples(archive,set(ids));assert set(source)==set(z['query_id']);rows=[source[k] for k in z['query_id']];g,p,y,ch=[np.asarray(v) for v in zip(*rows)];raw[name]=(g,p,y,ch);assert np.array_equal(z['target'],y) and np.array_equal(z['posture'],p);same(z['x'][:,:,:27],ch[:,0]);same(z['dt'],.48)
    for name,z in splits.items():
        free,paid=replay_class(raw['train'],raw[name],True,name=='train');same(free,z['scores']);same(paid,z['read_scores']);max_prob=max(max_prob,np.max(abs(free-z['scores'])),np.max(abs(paid-z['read_scores'])))
        obs=conf['summary'] if name=='test' else dev[name]; threshold,limit=w['simple']['threshold']; exp_t=[]
        for q in free:
            t=0
            while t<limit and max(q[t])<threshold:t+=1
            exp_t.append(t)
        same(exp_t,obs['primary']['prefix']);same(obs['primary']['action'],0);evaluate_decision(z,obs['primary']);evaluations+=len(exp_t)
        for key,r in obs['fixed_exits'].items():
            a,t=map(int,key.split('-'));same(r['prefix'],t);same(r['action'],a);evaluate_decision(z,r);evaluations+=len(z['target'])
        mat=np.stack([np.stack([np.array(obs['fixed_exits'][f'{a}-{t}']['u']) for a in (0,1)],axis=-1) for t in range(6)],axis=1);op=obs['opportunity']
        macro=lambda v:np.mean([v[z['group']==j].mean() for j in np.unique(z['group'])]);same(op['free_wait_over_immediate'],macro(mat[:,:,0].max(1)-mat[:,0,0]));same(op['joint_wait_over_best_immediate'],macro(mat.max((1,2))-mat[:,0].max(1)));same(op['paid_over_free_future'],macro(mat.max((1,2))-mat[:,:,0].max(1)))
    z=splits['train'];context0=context(z);mu=np.array(w['mu']);sd=np.array(w['sd']);inputs={n:dict(zt=torch.as_tensor((context(v)-mu)/sd),clock=torch.from_numpy(v['dt'])) for n,v in splits.items()}
    for av in ('read','noread'):
        paid=av=='read';targets,_,_=nuisance_replay(z,context0,fold_ids(z),paid)
        for k,m in w['models'].items():
            mode,seed,suffix=k.split('-');
            if suffix!=av:continue
            mod=representation(mode,int(seed),len(mu));fun=features(mod,mode,paid);theta=mod.initial_edit_vector() if mod else torch.zeros(0,dtype=torch.float64)
            with torch.no_grad(): ht=fun(theta,inputs['train']).numpy(); coef=head(ht,targets,z['group']);same(coef,m['head']);max_coef=max(max_coef,abs(coef-np.array(m['head'])).max());heads+=1
            for n,recs in [('dev',dev['models']),('test',conf['models'])]:
                with torch.no_grad(): q=fun(theta,inputs[n]).numpy()@coef[:-1]+coef[-1]
                if not paid:q[:,:,1]=-np.inf
                q[:,-1,2]=-np.inf;act=q.argmax(-1); chosen=recs[k]['chosen'];ts=np.array([next(i for i,a in enumerate(seq) if a!=2) for seq in act]);same(ts,chosen['prefix']);same(act[np.arange(len(ts)),ts],chosen['action']);evaluate_decision(splits[n],chosen);model_evals+=len(ts)
    return dict(passed=True,raw_to_score_max_abs=float(max_prob),raw_events=len(raw['train'][0])+len(raw['dev'][0])+len(raw['test'][0]),linear_heads_rebuilt=heads,
        maximum_head_abs=float(max_coef),threshold_and_fixed_episode_checks=evaluations,model_episode_checks=model_evals,wall_seconds=time.monotonic()-start,
        scope='Raw sensor segments, all source-held-out and final sensor classifier scores, actual prefix traces and discounted utility, hindsight opportunities and independent source-exclusive stopping target/normal-equation readouts. Physical feature kernel shared.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('archive',type=Path);p.add_argument('out',type=Path);args=p.parse_args();torch.set_num_threads(1);r=verify(args.archive,args.out)
    with (args.out/'verification.json').open('x') as f: json.dump(r,f,allow_nan=False);f.write('\n')
    print(json.dumps(r))
