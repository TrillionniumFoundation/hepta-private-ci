"""Offline, post-hoc controls. Run with numpy; no model imports or network calls."""
import hashlib
import json
from pathlib import Path
import numpy as np

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent / 'caption-run-audit-539d-20261024T2256Z/artifact'
CONSUMED = {}
def read(path):
    data = path.read_bytes()
    CONSUMED[str(path.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
    return data

def save(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')

def nll(z, y):
    return float(np.mean(np.logaddexp(0, z) - y*z))

def fit(x, y, penalty):
    a = np.column_stack([np.ones(len(x)), x]); w = np.zeros(2)
    def objective(v): return nll(a@v, y) + penalty*v[1]**2/2
    for _ in range(100):
        p = 1/(1+np.exp(-np.clip(a@w,-700,700)))
        g = a.T@(p-y)/len(y) + np.array([0,penalty*w[1]])
        h = (a.T*(p*(1-p)))@a/len(y) + np.diag([1e-12,penalty+1e-12])
        step = np.linalg.solve(h,g)
        if np.linalg.norm(g) < 1e-10: break
        rate=1.
        while rate > 2**-30 and objective(w-rate*step) > objective(w)-1e-4*rate*float(g@step): rate/=2
        w-=rate*step
    return w

def load_rows(split):
    rows=[json.loads(s) for s in read(ROOT/'cohorts'/f'{split}.jsonl').splitlines()]
    assert len({r['row_id'] for r in rows}) == len(rows)
    for r in rows:
        assert r['split']==split and r['image_id'] in index and r['source_caption_image_id'] in index
        assert r['label']==int(r['image_id']==r['source_caption_image_id'])
    for block in {r['pair_block_id'] for r in rows}:
        b=[r for r in rows if r['pair_block_id']==block]
        assert len(b)==4 and len({r['image_id'] for r in b})==2
    return rows

def scores(rows):
    t=text[[index[r['source_caption_image_id']] for r in rows]]
    i=image[[index[r['image_id']] for r in rows]]
    return np.sum(t*i,axis=1), np.array([r['label'] for r in rows])

def metrics(s,y,z=None):
    pos=s[y==1]; neg=s[y==0]
    out={'auroc':float(np.mean((pos[:,None]>neg)+.5*(pos[:,None]==neg)))}
    pred=s>=0 if z is None else z>=0
    out.update(balanced_accuracy=float((np.mean(pred[y==1])+np.mean(~pred[y==0]))/2), positive_recall=float(np.mean(pred[y==1])),correct=int(np.sum(pred==y)))
    if z is not None:
        p=1/(1+np.exp(-np.clip(z,-700,700))); accepted=np.maximum(p,1-p)>=.7
        out.update(nll=nll(z,y),coverage=float(accepted.mean()),selective_risk=float(np.mean(pred[accepted]!=y[accepted])) if accepted.any() else None)
    return out

def retrieval(rows, within_block=False):
    ids=sorted({r['image_id'] for r in rows}); ranks=[[],[]]
    block_map={r['image_id']:r['pair_block_id'] for r in rows}
    for direction in range(2):
        for ident in ids:
            candidates=[i for i in ids if not within_block or block_map[i]==block_map[ident]]
            left,right=(text,image) if direction==0 else (image,text)
            s=right[[index[i] for i in candidates]]@left[index[ident]]
            own=s[candidates.index(ident)]
            ranks[direction].append(1+np.sum(s>own)+.5*(np.sum(s==own)-1))
    return {d:{'top1':float(np.mean(np.array(r)<=1)),'top5':float(np.mean(np.array(r)<=5)),'mrr':float(np.mean(1/np.array(r))),'queries':len(r),'candidate_count':2 if within_block else len(ids)} for d,r in zip(['text_to_image','image_to_text'],ranks)}

if __name__=='__main__':
    manifest=json.loads(read(ROOT/'bank/manifest.json'))
    digest=hashlib.sha256(read(ROOT/'bank/features.npz')).hexdigest()
    assert digest==manifest['features_sha256']=='d40179b7be10e921b6881b813c4670e791637b1ab365530d1eea7545ba013bb1'
    assert manifest['authority']=='DENY_ALL' and not manifest['production_activation_allowed']
    bank=np.load(ROOT/'bank/features.npz',allow_pickle=False)
    ids=manifest['image_ids']; assert len(ids)==len(set(ids))==384
    index={v:i for i,v in enumerate(ids)}
    arrays=[]
    for key in ['text','image']:
        a=bank[key].astype(np.float64); assert a.shape==(384,768) and np.isfinite(a).all()
        norm=np.linalg.norm(a,axis=1); assert np.all(norm>0)
        arrays.append(a/norm[:,None])
    text,image=arrays
    rows={s:load_rows(s) for s in ['train','dev','calibration']}
    s,y=scores(rows['train']); mean=float(s.mean()); std=float(s.std()); assert std>0
    dev,dy=scores(rows['dev']); cal,cy=scores(rows['calibration'])
    candidates=[]
    for penalty in [0,.0001,.001,.01,.1,1]:
        w=fit((s-mean)/std,y,penalty)
        candidates.append({'penalty':penalty,'weights':w.tolist(),'dev_nll':nll(w[0]+w[1]*(dev-mean)/std,dy)})
    selected=min(candidates,key=lambda v:v['dev_nll']); w=np.array(selected['weights'])
    temperatures=[{'temperature':t,'calibration_nll':nll((w[0]+w[1]*(cal-mean)/std)/t,cy)} for t in [.25,.5,.75,1,1.5,2,3,4,8]]
    temperature=min(temperatures,key=lambda v:v['calibration_nll'])['temperature']
    fitting={'posthoc':True,'train_mean':mean,'train_std':std,'candidates':candidates,'selected':selected,'temperatures':temperatures,'temperature':temperature,'fit_input_sha256':dict(CONSUMED),'protocol_sha256':hashlib.sha256((OUT/'PROTOCOL.md').read_bytes()).hexdigest()}
    save('frozen-fit.json',fitting)  # Test JSONL has not been opened above this line.
    rows['test']=load_rows('test')
    sets=[{r[k] for r in rr for k in ['image_id','source_caption_image_id']} for rr in rows.values()]
    for i,a in enumerate(sets):
        for b in sets[i+1:]: assert not a&b
    s,y=scores(rows['test']); z=(w[0]+w[1]*(s-mean)/std)/temperature
    comparisons={}; order={r['row_id']:i for i,r in enumerate(rows['test'])}
    blocks=np.array([r['pair_block_id'] for r in rows['test']]); ub=sorted(set(blocks))
    for mode in ['gated','linear']:
        path=ROOT/f'results/text_image-{mode}-test/predictions.npz'; read(path)
        original=np.load(path,allow_pickle=False); permutation=[order[str(r)] for r in original['source_ids']]
        assert np.array_equal(y[permutation],original['labels'])
        diff=(original['prediction']==original['labels']).astype(float)-((z[permutation]>=0)==y[permutation])
        b=blocks[permutation]; bd=np.array([diff[b==v].mean() for v in ub])
        rng=np.random.default_rng(20261022); boot=bd[rng.integers(len(bd),size=(2000,len(bd)))].mean(axis=1)
        comparisons[mode]={'head_minus_cosine_accuracy':float(diff.mean()),'block_bootstrap_95_percentile':np.quantile(boot,[.025,.975]).tolist(),'head_metrics':metrics(original['probabilities'][:,1],original['labels'],np.log(np.clip(original['probabilities'][:,1],1e-15,1))/np.ones(len(y))-np.log(np.clip(original['probabilities'][:,0],1e-15,1)))}
    save('results.json',{'posthoc_not_acceptance':True,'authority':'DENY_ALL','production_activation_allowed':False,'source':'539d1d5e73f7c26ec170165e610b8570858b1e59','artifact_id':12579262528,'test_rows':len(y),'zero_shot_cosine_threshold_zero_diagnostic':metrics(s,y),'calibrated_cosine':metrics(s,y,z),'retrieval_two_candidate':retrieval(rows['test'],True),'retrieval_all_test_candidates':retrieval(rows['test']),'comparisons':comparisons,'inputs_sha256':CONSUMED})
    save('test-predictions.json',[{'row_id':r['row_id'],'cosine':float(c),'logit':float(v)} for r,c,v in zip(rows['test'],s,z)])
    print((OUT/'results.json').read_text())
