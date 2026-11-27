"""Seal every comparable fit, then open both registered final galleries and compare paired product groups."""
from pathlib import Path
import json,hashlib,time,sys,os
import numpy as np
from common import ROOT,setup_data,load_model,gallery,score
from construct import encode
from matched import choose
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def sealing():
    selected=choose();items=[]
    for kind,models in selected.items():
        for m in models:
            nm=f"{kind}-w{m['width']}-r{m['ridge']}-s{m['seed']}"
            items.append({'family':kind,'name':nm,'file':f'fitted/{nm}.npz','weights':m['weights_sha256'],'score':m['development'],'fit_seconds':m['fit_validate_save_s']})
    for folder in ['neural_fitted','time_matched']:
        for kind in ['physical_bp','conventional']:
            for seed in [113,229,367]:
                name=f'{kind}-{seed}';r=json.loads((ROOT/folder/(name+'.json')).read_bytes())
                regular=(folder=='neural_fitted')
                v=next(m['metrics'] for m in r['development'] if m['step']==r['selected']) if regular else r['dev']
                items.append({'family':kind if regular else kind+'_matched','name':folder+'-'+name,'file':folder+'/'+name+'.pt','weights':r['sha256'] if regular else r['weights_sha256'],'score':v,'fit_seconds':r['complete_wall_s'] if regular else r['inside_complete_s']})
    assert len(items)==18
    for item in items:assert sha(ROOT/item['file'])==item['weights']
    strong=max(['linear','conventional'],key=lambda k:tuple(np.mean([i['score'][m] for i in items if i['family']==k]) for m in ['strict_R1','strict_R5']))
    obj={'data':sha(ROOT/'catalog.npz'),'pixels':sha(ROOT/'pixels32.npy'),'gray_hash':sha(ROOT/'gray_hash.npy'),'law':sha(ROOT/'law.npz'),'items':items,'selected_strong':strong,'direct_fit_choices':{k:[v[0]['width'],v[0]['ridge']] for k,v in selected.items()}}
    dest=HERE/'SEAL.json'
    if dest.exists():assert json.loads(dest.read_bytes())==obj
    else:dest.write_text(json.dumps(obj,indent=1))
    print('sealed',sha(dest),strong,flush=True)
def clustered(dif,groups,seed=35129):
    keys,index=np.unique(groups,return_inverse=True);sums=np.bincount(index,dif);n=np.bincount(index);rng=np.random.default_rng(seed)
    chunks=[]
    for i in range(30):
        draw=rng.integers(len(keys),size=(100,len(keys)));chunks.append(sums[draw].sum(1)/n[draw].sum(1))
    return {'delta':float(np.mean(dif)),'paired_group_95':np.quantile(np.concatenate(chunks),[.025,.975]).tolist(),'n_groups':len(keys)}
def verify():
    import torch
    from neural import fresh,predictions
    torch.set_num_threads(1);seal=json.loads((HERE/'SEAL.json').read_bytes());assert sha(ROOT/'catalog.npz')==seal['data']
    d,V=setup_data();ix=gallery(d,2);g=np.load(ROOT/'gray_hash.npy');old=set(g[d['split']!=2]);freshq=np.array([e not in old for e in g[ix]])
    q={'standard':np.arange(len(ix)),'gray_disjoint':np.flatnonzero(freshq)}
    with np.load(ROOT/'law.npz') as zz:z=dict(zz)
    out=ROOT/'catalog_confirmed';out.mkdir(exist_ok=True)
    tables={k:{} for k in q};r1={k:{} for k in q}
    for item in seal['items']:
        n=item['name'];p=ROOT/item['file'];assert sha(p)==item['weights'];fam=item['family']
        t=time.monotonic()
        if p.suffix=='.npz':
            models,_=load_model(p);I,T=encode(V,d,ix,models,fam,z)
        else:
            net,inp=fresh(fam.replace('_matched',''),d,V,'cpu');net.load_state_dict(torch.load(p,weights_only=True,map_location='cpu'))
            I,T=predictions(net,inp,ix)
        cold=time.monotonic()-t;vec={}
        for gal,sel in q.items():
            m,r=score(I[sel],T[sel],d,ix[sel]);tables[gal][n]={'family':fam,'metrics':m,'encode_s':cold,'directions':{a:{'R1':float((v[:,0]<=1).mean()),'R5':float((v[:,0]<=5).mean()),'R10':float((v[:,0]<=10).mean()),'title_R1':float((v[:,1]<=1).mean()),'group_R1':float((v[:,2]<=1).mean())} for a,v in r.items()}}
            for a,v in r.items():vec[gal+'_'+a]=v
            vec[gal+'_id']=d['id'][ix[sel]];vec[gal+'_group']=d['group'][ix[sel]]
            r1[gal].setdefault(fam,[]).append(np.mean([v[:,0]==1 for v in r.values()],axis=0))
        np.savez_compressed(out/(n+'.npz'),**vec)
    report={}
    for gal,rows in tables.items():
        fams={v['family'] for v in rows.values()}
        metrics={f:{k:float(np.mean([v['metrics'][k] for v in rows.values() if v['family']==f])) for k in ['strict_R1','strict_R5','strict_R10','title_R1']} for f in fams}
        av={f:np.mean(r1[gal][f],0) for f in fams}
        contr={f:clustered(av['literal']-av[f],d['group'][ix[q[gal]]]) for f in fams if f!='literal'}
        report[gal]={'size':len(q[gal]),'metrics':metrics,'per_model':rows,'literal_minus':contr,'pass_quality_gate_vs_selected_conventional':contr[seal['selected_strong']]['paired_group_95'][0]>=-.02}
    result={'sealed':sha(HERE/'SEAL.json'),'strong':seal['selected_strong'],'galleries':report}
    (HERE/'RESULTS.json').write_text(json.dumps(result,indent=1));print(report['standard']['metrics'],report['standard']['literal_minus'][seal['selected_strong']],flush=True)
if __name__=='__main__':
    if sys.argv[1]=='seal':sealing()
    elif sys.argv[1]=='score':verify()
