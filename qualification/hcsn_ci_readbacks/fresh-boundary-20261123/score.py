"""Join frozen actions to the later camera labels and verify source-level scores with the original evaluators."""
import argparse
import hashlib
import json
import time
from pathlib import Path
import numpy as np
from qualification.hcsn_blocker_followup import metrics
from qualification.hcsn_intervention_value import run

HERE=Path(__file__).resolve().parent
read=lambda path:json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def avg(x):return float(np.mean(x))
def score(out):
    started=time.perf_counter()
    seal=read(out/'action-seal.json'); camera=read(out/'camera-receipt.json')
    assert sha(out/'action-seal.json')==camera['action_seal'] and sha(out/'camera.npz')==camera['output_sha256']
    assert all(sha(out/k)==v for k,v in seal['files'].items())
    rule=read(HERE/'protocol.json');assert sha(HERE/'protocol.json')==seal['protocol_sha256']
    rows=read(out/'roster.json')
    group=np.array([r['group'] for r in rows])
    source=np.array([r['recording'] for r in rows])
    ids=np.array([r['query_id'] for r in rows])
    y=np.array([r['label'] for r in rows])
    with np.load(out/'free.npz',allow_pickle=False) as f:free=f['scores'];gallery=f['gallery_audio']
    with np.load(out/'camera.npz',allow_pickle=False) as f:
        assert np.array_equal(f['query_id'],ids)
        paid=f['probability']
    with np.load(out/'qvalues.npz',allow_pickle=False) as f:qt={k:f[k] for k in f.files}
    dt=np.full((48,6),.48)
    data=dict(scores=free,read_scores=paid,target=y,group=group,source=source,query_id=ids,dt=dt)
    hits=np.stack((free.argmax(-1)==y[:,None],paid.argmax(-1)==y[:,None]),axis=-1)
    t=np.arange(6).astype(float)*.48
    rewards=hits.astype(float)-np.array([0.,.30])
    value=np.exp(-.2*t[None,:,None])*rewards+.4*np.expm1(-.2*t[None,:,None])/.2
    labels=sorted(set(group))
    def means(v):return np.asarray([np.mean(v[group==g]) for g in labels])
    frozen=read(out/'actions.json');scores={};vs={}
    free0=means(value[:,0,0]);paid0=means(value[:,0,1])
    for key,row in frozen.items():
        e=np.array(row['end']);a=np.array(row['action'])
        assert len(a)==48 and ((0<=e)&(e<6)).all() and np.isin(a,(0,1)).all()
        val=value[np.arange(48),e,a];hit=hits[np.arange(48),e,a]
        g=means(val);vs[key]=g
        saves=(a==1)&(hits[np.arange(48),e,1])&(~hits[np.arange(48),e,0])
        harms=(a==1)&(~hits[np.arange(48),e,1])&(hits[np.arange(48),e,0])
        vfree=g-free0;vpaid=g-paid0
        score={'utility':avg(g),'accuracy':avg(means(hit)),'purchases':int(a.sum()),'waits':int((e>0).sum()),
               'rescues_at_exit':int(saves.sum()),'harms_at_exit':int(harms.sum()),'wait_seconds_mean':avg(t[e]),
               'gain_vs_free':avg(vfree),'gain_vs_paid':avg(vpaid),'worst_vs_free':float(vfree.min()),
               'p_vs_free_paid':[metrics.sign_p(vfree),metrics.sign_p(vpaid)],
               'source_utility':dict(zip(labels,g.tolist()))}
        if key in qt:
            original=run.score(qt[key],data,True)
            assert original['exit_prefix']==e.tolist() and original['terminal_action']==a.tolist()
            assert np.allclose(original['episode_utility'],val,rtol=0,atol=1e-12)
        elif key not in ('free','paid'):
            original=metrics.evaluate(data,a.astype(bool))
            assert all(abs(original[k]-score[n])<1e-12 for k,n in [('utility','utility'),('r1','accuracy'),('worst_delta_free','worst_vs_free')])
            score['original_first_prefix_adoption']=original['adopt']
        scores[key]=score
    primary={}
    for how in ('keep','bp'):
        mean={m:np.mean([vs[f'read-{m}-{how}-{s}'] for s in rule['seeds']],axis=0) for m in rule['architectures']}
        qvi=mean['qvi'];contrasts=[qvi-mean[m] for m in ('fixed','learned')]
        p=[metrics.sign_p(row) for row in contrasts]
        minimum=float(min(qvi-free0));deltas=list(map(avg,contrasts))
        primary[how]={'source_macro':{m:avg(v) for m,v in mean.items()},'qvi_minus_fixed_learned':deltas,
          'p_vs_fixed_learned':p,'qvi_worst_vs_free':minimum,
          'paired_source_differences':{label:[float(row[i]) for row in contrasts] for i,label in enumerate(labels)},
          'passes_predeclared_superiority':bool(min(deltas)>=.03-1e-12 and min(p)<=.025 and max(p)<=.05 and minimum>=-.05-1e-12)}
    immediate=value[:,0,:].max(axis=-1);hindsight=value.reshape(48,12).max(axis=1)
    increment=hindsight-immediate;groups=means(increment)
    opportunity={'first_prefix_oracle':avg(means(immediate)),'any_prefix_oracle':avg(means(hindsight)),
                 'waiting_gain':avg(groups),'helped_queries':int((increment>1e-12).sum()),
                 'helped_sources':int((groups>1e-12).sum()),'passes_old_opportunity_gate':bool(avg(groups)>=.015 and (groups>1e-12).sum()>=2),
                 'anytime_upper_p_vs_free':metrics.sign_p(means(hindsight)-free0),'source_gains':dict(zip(labels,groups.tolist()))}
    m=free[:,0,1]*2-1; cell=(m>=0)&(np.abs(m)<=.65)&(gallery[:,0,1]<.5)
    real=hits[:,0,1].astype(int)-hits[:,0,0].astype(int)
    subgroup={'n':int(cell.sum()),'sources':len(set(group[cell])),'rescues':int(np.sum(real[cell]==1)),
              'harms':int(np.sum(real[cell]==-1)),'net_per_purchase':avg(real[cell]-.30) if cell.any() else None}
    report={'protocol_sha256':seal['protocol_sha256'],'pre_camera_action_seal':camera['action_seal'],'sources':len(labels),
       'queries':len(rows),'policies':len(frozen),'all_original_evaluators_match':True,'primary':primary,'scores':scores,
       'opportunity':opportunity,'prior_audio_subgroup':subgroup,'scoring_wall_seconds':time.perf_counter()-started}
    (out/'result.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'primary':primary['bp']['qvi_minus_fixed_learned'],'free':scores['free']['utility'],'paid':scores['paid']['utility'],
                      'opportunity':opportunity['waiting_gain'],'subgroup':subgroup},ensure_ascii=False))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('out',type=Path)
    score(p.parse_args().out)
