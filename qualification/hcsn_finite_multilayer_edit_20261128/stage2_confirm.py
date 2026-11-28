"""Freeze sequential-edit candidate hashes and independently recompute external logits and scores."""
import argparse
import hashlib
import json
import time
from pathlib import Path
import numpy as np
from confirm import npzd,predict,sha,time_pair

def validate_metadata(a):
    mods={};src={}
    for arch in ('literal','smooth'):
        for seed in (271,577,911):
            for kind in ('parent0','after1'):
                d=a.models/f'{arch}_{seed}_{kind}'
                names=['parent.json','parent.npz']
                for m in ['joint','lm_joint','bp','ridge']+(['wrong'] if arch=='literal' else []):
                    names.append(m+'.json');rec=json.loads((d/(m+'.json')).read_text())
                    for b in (3,15,60):
                        f=d/f'{m}_{b}.npz';assert sha(f)==rec['picks'][str(b)]['sha256'];names.append(f.name)
                for nm in names:mods[(d/nm).relative_to(a.models).as_posix()]=sha(d/nm)
    for f in (a.sc/'support.npz',a.sc/'development.npz',a.sc/'confirmation.npz',a.previous/'S.npz',a.prior/'old_test.npz',a.law):src[f.name]=sha(f)
    return dict(selected=mods,inputs=src,code={f.name:sha(f) for f in Path(__file__).parent.glob('*.py')},
                protocol=sha(Path(__file__).with_name('SEQUENTIAL_TRANSFER.md')))
def cold(a):
    f=a.work/'stage2_seal.json'
    wanted=validate_metadata(a)
    if a.mode=='seal':
        if f.exists():raise FileExistsError(f)
        f.write_text(json.dumps(wanted,indent=2,sort_keys=True)+'\n');return
    assert json.loads(f.read_text())==wanted
    sets={'new':a.sc/'confirmation.npz','old':a.prior/'old_test.npz','previous':a.previous/'S.npz'}
    target={}
    for name,p in sets.items():
        v=npzd(p)
        for field in ('y','record','speaker'):target[name+'_'+field]=v[field]
    np.savez_compressed(a.work/'targets.npz',**target)
    for arch in ('literal','smooth'):
        for seed in (271,577,911):
            for kind in ('parent0','after1'):
                d=a.models/f'{arch}_{seed}_{kind}';out={};ts={}
                methods=['keep','joint','lm_joint','bp','ridge']+(['wrong'] if arch=='literal' else [])
                for method in methods:
                    for b in ((0,) if method=='keep' else (3,15,60)):
                        t=time_pair();ident=f'{method}_{b}'
                        p=npzd(d/'parent.npz');m=[p['encoder'],p['W']]
                        table=npzd(a.law if arch=='literal' else a.stage1/f'{arch}_{seed}'/'smooth.npz')
                        corr=None
                        if method!='keep':
                            pars=npzd(d/(ident+'.npz'))
                            if method=='ridge':corr=pars
                            else:m=[pars['sender'],pars['receiver']]
                        for dom,path in sets.items():
                            with np.load(path) as v:x=v['x'].astype('float64')
                            out[ident+'_'+dom]=predict(x,p,m,table,corr)
                        ts[ident]=(time_pair()-t).tolist()
                name=f'{arch}_{seed}_{kind}'
                np.savez_compressed(a.work/(name+'.npz'),**out);(a.work/(name+'.json')).write_text(json.dumps(ts,indent=2)+'\n')
def score(a):
    obs=npzd(a.work/'targets.npz');seeds=[271,577,911];groups=('old','previous','new');arms=('keep','joint','lm_joint','bp','ridge','wrong');stats={};meta={}
    for arch in ('literal','smooth'):
        for seed in seeds:
            for start in ('parent0','after1'):
                name=f'{arch}_{seed}_{start}';arrays=npzd(a.work/(name+'.npz'));t=json.loads((a.work/(name+'.json')).read_text());par=a.models/name
                prep=json.loads((par/'parent.json').read_text())['setup']['wall'];s1=a.stage1/f'{arch}_{seed}'
                prev_cost=json.loads((s1/'lm_joint.json').read_text())['picks']['15']['wall_upper'] if start=='after1' else 0.
                parent_fit=json.loads((s1/'parent.json').read_text())['parent_fit']['wall']
                original_preparation=json.loads((a.prior/'data.json').read_text())['wall_seconds']
                new_preparation=json.loads((a.sc/'PREPARATION.json').read_text())['full_stream_and_preparation_wall']
                previous_prep=json.loads((a.previous/'preparation.json').read_text())['splits']['S']['wall']
                for m in arms:
                    if m=='wrong' and arch=='smooth':continue
                    picks=json.loads((par/(m+'.json')).read_text())['picks'] if m!='keep' else {}
                    for b in (3,15,60):
                        key=(arch,seed,start,m,b);ident=f'{m}_{0 if m=="keep" else b}'
                        fit=picks[str(b)]['wall_upper'] if m!='keep' else 0
                        meta[key]=dict(chosen=picks[str(b)]['selection'] if m!='keep' else None, fit_wall=fit,
                                       with_cached_inputs=prep+fit+t[ident][1],
                                       all_wall=parent_fit+original_preparation+prev_cost+new_preparation+previous_prep+prep+fit+t[ident][1])
                        for g in groups:
                            y=obs[g+'_y'];s=obs[g+'_speaker'];z=arrays[ident+'_'+g].argmax(1)==y
                            stats[key+(g,)]=np.array([z[s==sp].mean() for sp in np.unique(s)])
    def pair(v):
        d=v.mean(0);idx=np.random.default_rng(40031).integers(len(d),size=(10000,len(d)));return dict(mean=float(d.mean()),ci=np.quantile(d[idx].mean(1),[.025,.975]).tolist())
    out=[]
    for arch in ('literal','smooth'):
        for parent in ('parent0','after1'):
            for m in arms:
                if m=='wrong' and arch=='smooth':continue
                for b in (3,15,60):
                    def av(arm,g):return np.array([stats[(arch,s,parent,arm,b,g)] for s in seeds])
                    sc={g:av(m,g).mean(1) for g in groups};gain={g:av(m,g)-av('keep',g) for g in groups}
                    passed=(gain['new'].mean(1)>=.02-1.e-12)&(gain['old'].mean(1)>=-.02-1.e-12)&(gain['previous'].mean(1)>=-.02-1.e-12)
                    contrast={g:{q:pair(av(m,g)-av(q,g)) for q in ('keep','bp','ridge')} for g in groups}
                    out.append(dict(arch=arch,start=parent,method=m,budget=b,means={g:float(s.mean()) for g,s in sc.items()},seeds={g:s.tolist() for g,s in sc.items()},
                                    passes=int(passed.sum()),gate=bool(passed.all() and contrast['new']['keep']['ci'][0]>0),contrasts=contrast,
                                    costs=[meta[(arch,s,parent,m,b)] for s in seeds]))
    (a.work/'stage2_results.json').write_text(json.dumps(out,indent=2)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('seal','cold','score'))
    for n in ('models','stage1','sc','previous','prior','law','work'):p.add_argument(n,type=Path)
    a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True)
    if a.mode=='score':score(a)
    else:cold(a)
