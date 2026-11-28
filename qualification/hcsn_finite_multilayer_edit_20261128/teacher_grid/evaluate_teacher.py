"""Blindly reproduce four new/retained speech panels, including 14 unpermuted GRID folder controls."""
import argparse
import hashlib
import json
import sys
import time
from functools import lru_cache
from pathlib import Path
import numpy as np
from scipy.special import softmax
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from confirm import npzd,predict,sha,time_pair
from fit_teacher import ARMS


SEEDS=(271,577,911)
ARCHS=('literal','smooth')
RUNGS=(3,15,60)
EXTERNAL=('keep','source_teacher','previous_lm')


def read(p):return json.loads(p.read_text())


def signature(a):
    stored={};inputs={};root=Path(__file__).resolve().parent
    for arch in ARCHS:
        for seed in SEEDS:
            tag=f'{arch}_{seed}';d=a.src/tag;t=a.fits/tag
            common={f:sha(d/f) for f in ('parent.npz','parent.json','ridge_3.npz','ridge.json','lm_joint_3.npz','lm_joint.json')}
            if arch=='smooth':common['smooth.npz']=sha(d/'smooth.npz')
            stored[tag]={'common':common,'methods':{}}
            for arm in ARMS:
                h=read(t/(arm+'.json'));r={'fit':sha(t/(arm+'.json')),'setup':sha(t/(arm+'_setup.json'))}
                for b in RUNGS:
                    f=f'{arm}_{b}.npz';assert sha(t/f)==h['picks'][str(b)]['sha256'];r[f]=sha(t/f)
                if arm.startswith('alpha') or arm=='crisp':r['geometry']=sha(t/(arm+'_geometry.json'))
                stored[tag]['methods'][arm]=r
    for path in (a.law,a.old/'old_test.npz',a.aux/'aux.npz',a.aux/'A2.npz',a.aux/'B2.npz',a.aux/'sources.json',
                 a.grid/'GRID.npz',a.grid/'grid.json',a.grid/'segments.tsv',a.aux/'clips.tsv'):
        inputs[path.name]=sha(path)
    local={f.name:sha(f) for f in root.glob('*.py')}
    for file in ('sensitivity.py','model.py','fit_model.py','confirm.py','receiver.py'):
        local['parent_source/'+file]=sha(root.parent/file)
    return dict(states=stored,source=inputs,code=local,protocol={p:sha(root/p) for p in ('PROTOCOL.md','NAMED_EDITORS.md','GRID_ALIGNMENT.md')})


def panel_data(a):
    return {key:npzd(path) for key,path in {'old':a.old/'old_test.npz','A2':a.aux/'A2.npz','B2':a.aux/'B2.npz','GRID':a.grid/'GRID.npz'}.items()}


def cold(a):
    a.work.mkdir(parents=True,exist_ok=True);f=a.work/'seal.json';value=signature(a)
    if a.mode=='seal':
        if f.exists():raise FileExistsError(f)
        f.write_text(json.dumps(value,sort_keys=True,indent=1)+'\n');return
    assert read(f)==value
    sets=panel_data(a)
    for seed in SEEDS:
        for arch in ARCHS:
            tag=f'{arch}_{seed}';d=a.src/tag;t=a.fits/tag;out=a.work/tag;out.mkdir(exist_ok=True)
            times={};logits={}
            for method in (*EXTERNAL,*ARMS):
                for b in ((0,) if method in EXTERNAL else RUNGS):
                    clock=time_pair();common=npzd(d/'parent.npz');m=[common['encoder'],common['W']];corr=None
                    if method=='source_teacher':corr=npzd(d/'ridge_3.npz')
                    elif method=='previous_lm' or method in ARMS:
                        fit=npzd(d/'lm_joint_3.npz' if method=='previous_lm' else t/f'{method}_{b}.npz')
                        m=[fit['sender'],fit['receiver']]
                    law=npzd(a.law if arch=='literal' else d/'smooth.npz')
                    id=f'{method}_{b}'
                    for k,cohort in sets.items():
                        logits[id+'_'+k]=predict(cohort['x'].astype('float64'),common,m,law,corr)
                        if k=='B2':times[id]={'through_panels':(time_pair()-clock).tolist()}
                    times[id]['all']=(time_pair()-clock).tolist()
            np.savez_compressed(out/'logits.npz',**logits);(out/'time.json').write_text(json.dumps(times,indent=1)+'\n')
            print('cold',tag,flush=True)
    (a.work/'complete.json').write_text(json.dumps({str(p.relative_to(a.work)):sha(p) for p in sorted(a.work.rglob('*')) if p.is_file() and p.name!='complete.json'},indent=1)+'\n')


def score(a):
    cc=read(a.work/'complete.json')
    assert all(sha(a.work/p)==digest for p,digest in cc.items())
    sets=panel_data(a);table={};cs={};old_kl={};options={};grid=read(a.grid/'grid.json');x0=sets['GRID']
    ids=np.isin(x0['speaker'],grid['matched_direct_folders'])
    sets['GRID_same_folder']={k:x[ids] for k,x in x0.items()}
    aux_prep=read(a.aux/'sources.json')['total_s']
    for seed in SEEDS:
        for arch in ARCHS:
            tag=f'{arch}_{seed}';d=a.src/tag;t=a.fits/tag;g=a.work/tag
            cold=npzd(g/'logits.npz');times=read(g/'time.json');parent=read(d/'parent.json')
            generic=read(d/'ridge.json')['finished']['wall'];source_lm=read(d/'lm_joint.json')['picks']['3']['wall_upper']
            for arm in (*EXTERNAL,*ARMS):
                fit=read(t/(arm+'.json')) if arm in ARMS else None
                geom=read(t/(arm+'_geometry.json'))['wall'] if (t/(arm+'_geometry.json')).exists() else 0.
                for b in RUNGS:
                    ident=f'{arm}_{b if fit else 0}';key=(arch,seed,arm,b);search=fit['picks'][str(b)]['wall_upper'] if fit else 0.
                    setup=read(t/(arm+'_setup.json'))['setup']['wall'] if fit else 0.
                    teacher=generic if arm in ('source_teacher',*ARMS) else source_lm if arm=='previous_lm' else 0.
                    timing=times[ident];ready=search+setup+teacher+timing['through_panels'][1]
                    total=ready+parent['parent_fit']['wall']+parent['study_prep']['wall']+read(a.old/'data.json')['wall_seconds']+aux_prep
                    xs=softmax(cold[ident+'_old'],-1);const=softmax(cold['keep_0_old'],-1)
                    old_kl[key]=float((const*np.log(const/xs)).sum(1).mean())
                    cs[key]=dict(teacher_fit=teacher,projection=geom,actual_budget_search=search,setup=setup,from_available_inputs=ready,
                        from_raw_primary=total,from_raw_including_grid=total+grid['wall_s']+timing['all'][1]-timing['through_panels'][1],
                        projected_search_amortization={str(n):max(search-geom,0)+geom/n for n in (1,10,100)})
                    options[key]=fit['picks'][str(b)] if fit else None
                    for h,cohort in sets.items():
                        z=cold[ident+'_GRID'][ids] if h=='GRID_same_folder' else cold[ident+'_'+h]
                        s=cohort['speaker'];ok=z.argmax(1)==cohort['y']
                        table[key+(h,)]=np.array([ok[s==v].mean() for v in np.unique(s)])
    @lru_cache(None)
    def draw(n):return np.random.default_rng(9748559).integers(n,size=(10000,n),dtype=np.int32)
    def compare(arr,ref):
        d=(arr-ref).mean(0);seed=(arr-ref).mean(1)
        return dict(mean=float(d.mean()),seeds=seed.tolist(),ci=np.quantile(d[draw(len(d))].mean(1),[.025,.975]).tolist())
    out=[];idx={}
    for arch in ARCHS:
        for arm in (*EXTERNAL,*ARMS):
            for b in RUNGS:
                def vals(method,k,budget=b):return np.array([table[arch,s,method,budget,k] for s in SEEDS])
                perf={k:vals(arm,k) for k in sets}
                pair={k:{m:compare(v,vals(m,k)) for m in ('keep','source_teacher','previous_lm','teacher_bp','teacher_lm','frozen_aux','crisp','alpha')} for k,v in perf.items()}
                retained=min(pair['old']['keep']['seeds'])>=-.02-1e-12
                learned=all(min(pair[k]['keep']['seeds'])>=.02-1e-12 and pair[k]['keep']['ci'][0]>0 for k in ('A2','B2'))
                matches=all(pair[k]['source_teacher']['ci'][0]>=-.02 for k in ('A2','B2'))
                cross=min(pair['GRID']['keep']['seeds'])>=.02-1e-12 and pair['GRID']['keep']['ci'][0]>0
                keys=[(arch,s,arm,b) for s in SEEDS]
                row=dict(arch=arch,arm=arm,budget=b,accuracy={k:v.mean(1).tolist() for k,v in perf.items()},
                    average={k:float(v.mean()) for k,v in perf.items()},contrasts=pair,retained=bool(retained),learned=bool(learned),matches_teacher=bool(matches),
                    primary_gate=bool(retained and learned and matches),cross_domain_gate=bool(cross),robust_gate=bool(retained and learned and matches and cross),
                    old_kl=[old_kl[k] for k in keys],times=[cs[k] for k in keys],choices=[options[k] for k in keys])
                out.append(row);idx[(arch,arm,b)]=row
    front=[]
    for arch in ARCHS:
        for arm in ('teacher_lm','alpha','alpha_exact','crisp','receiver_teacher'):
            chosen=next((idx[arch,arm,b] for b in RUNGS if idx[arch,arm,b]['primary_gate']),None)
            bp=next((idx[arch,'teacher_bp',b] for b in RUNGS if idx[arch,'teacher_bp',b]['primary_gate']),None)
            f=dict(arch=arch,arm=arm,first_local=chosen['budget'] if chosen else None,first_reverse=bp['budget'] if bp else None)
            if chosen and bp:
                m=chosen['budget'];n=bp['budget'];quality={}
                for h in ('A2','B2','GRID'):
                    a1=np.stack([table[arch,s,arm,m,h] for s in SEEDS]);a2=np.stack([table[arch,s,'teacher_bp',n,h] for s in SEEDS]);quality[h]=compare(a1,a2)
                ratios={k:float(np.median([x[k] for x in chosen['times']])/np.median([x[k] for x in bp['times']])) for k in ('from_available_inputs','from_raw_primary','from_raw_including_grid')}
                f.update(paired=quality,ratio=ratios,speed_gate=bool(ratios['from_raw_primary']<=.8 and min(quality[h]['ci'][0] for h in ('A2','B2'))>=-.02))
            else:f.update(speed_gate=False,reason='at least one native method failed the compound quality rule')
            front.append(f)
    (a.work/'results.json').write_text(json.dumps({'rows':out,'frontiers':front,'speakers':{k:len(set(v['speaker'])) for k,v in sets.items()}},indent=1,allow_nan=False)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('seal','cold','score'))
    for k in ('src','fits','old','aux','grid','law','work'):p.add_argument(k,type=Path)
    a=p.parse_args();(score if a.mode=='score' else cold)(a)
