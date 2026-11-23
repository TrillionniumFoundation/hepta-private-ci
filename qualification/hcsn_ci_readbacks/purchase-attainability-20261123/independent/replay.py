"""Independent read-only TRAIN/DEV receipt. No project modules, CLI solver, or TEST members."""
from pathlib import Path
from fractions import Fraction as F
from collections import defaultdict
from io import BytesIO
from zipfile import ZipFile
from hashlib import sha256,sha1
from math import comb
import json
import numpy as np
from scipy.special import expit
BASE=Path('trial/qualification')
R=BASE/'hcsn_ci_readbacks/purchase-attainability-20261123'
OUT=Path(__file__).parent
commit='0e744edcf0768f08618f1ca679ac4d7e3c7b8af3'
pins={'coordinate_witness.json':'9bbed0f4b7747c49d19a86865fc97fb19f9a3aa1','train_only_seal.json':'20696bd052593f9c2b15dab2a74c64e7ac194482','cell_mixture_bound.json':'23917598c1d2790b2b57fb66dd5a4d6ed5016d57','coordinate_witness_result.json':'a164a2bf522663bb00353b48528116d0758d2f48','train_only_result.json':'eb3ec60d28a739f237df72ab7fccb56eea2c7296','hcsn_intervention_value':'c69cb7dba3664dc19082be7dd8035f473cfe8572','hcsn_blocker_followup':'7ac4cd61151538ac5233809c4e74dd2b14435a75'}
sources={}
def h(b):return sha256(b).hexdigest()
def pinned(path,key):
    b=path.read_bytes()
    assert sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==pins[key]
    sources[str(path)]=h(b)
    return json.loads(b)
def loadfrom(phase,wanted):
    ev=BASE/phase/'evidence'
    catalog=pinned(ev/'archive_manifest.json',phase)['archives']
    result={}
    for arch,item in catalog.items():
        names=set(wanted)&item['files'].keys()
        if not names: continue
        with ZipFile(ev/arch) as z:
            for n in names:
                assert 'test' not in n
                raw=z.read(n)
                assert h(raw)==item['files'][n]['sha256']
                sources[phase+'/'+n]=h(raw)
                if n.endswith('.npz'):
                    with np.load(BytesIO(raw),allow_pickle=False) as arr: result[n]={k:arr[k] for k in arr.files}
                else: result[n]=json.loads(raw)
    assert set(result)==set(wanted)
    return result
front=loadfrom('hcsn_intervention_value',['primary/discovery/front_weights.json'])['primary/discovery/front_weights.json']
panels=('train','dev')
wanted=['outcomes/fit.json']+[f'media/{kind}/{s}.{suffix}' for s in panels for kind,suffix in [('roster','json'),('semantic','npz'),('features','npz')]]
raw=loadfrom('hcsn_blocker_followup',wanted)
head=raw['outcomes/fit.json']['full-svd-.1']
theta=list(map(lambda x:F(float(x)),[*head['beta'],head['bias']]))
docs={k:pinned(R/k,k) for k in pins if k.endswith('.json')}
def pos_sign(v):
    n=sum(x!=0 for x in v); positives=sum(x>0 for x in v)
    return F(sum(comb(n,x) for x in range(positives,n+1)),2**n)
def avg(v):return sum(v,F())/len(v)
def digits(x):return x if isinstance(x,str) else str(x)
price=F(3,10); records={}; cells={}
for s in panels:
    rd=raw[f'media/features/{s}.npz']; sd=raw[f'media/semantic/{s}.npz']
    reg={i['query_id']:(i['group'],i['label']) for i in raw[f'media/roster/{s}.json']}
    ids=rd['query_id'].tolist()
    assert len(set(ids))==len(ids)==len(reg) and set(rd['split'].tolist())=={s}
    assert all(reg[i]==(g,int(y)) for i,g,y in zip(ids,rd['group'],rd['label'],strict=True))
    hdr=front['final']['audio']; ref=front['reference']['audio']
    # Use the frozen linear audio frontend at physical prefix zero. The camera is
    # read only for the realized first-prefix outcome after decisions are constructed.
    a=rd['audio'][:,0,:]
    z=np.clip((a-hdr['center'])/hdr['scale'],-8,8)
    gf=np.clip((a-ref['center'])/ref['scale'],-8,8)
    gf0=np.asarray(ref['gallery'])[:,0,:]
    d=np.square(gf[:,None,:]-gf0[None,:,:]).mean(axis=-1)
    p=expit(2*(z@hdr['linear'][:-1]+hdr['linear'][-1]));g=expit(d[:,0]-d[:,1]);m=2*p-1;v=2*g-1
    q=np.linalg.qr(np.random.default_rng(420111).normal(size=(a.shape[1],8)))[0]
    feats=np.column_stack((m,np.abs(m),m**2,p>=.5,v,np.abs(v),np.abs(m-v),m*v,(p>=.5)!=(g>=.5),m*np.abs(m),z@q))
    x=np.clip((feats-head['mean'])/head['std'],-5,5);x=np.column_stack((x,np.ones(len(x))))
    coords=[[F(float(b)) for b in row] for row in x]
    gids=sorted(set(rd['group'].tolist()));grp=rd['group'].tolist()
    assert all(grp.count(k)==4 for k in gids)
    assert len(sd['query_id'])==len(ids) and set(sd['query_id'])==set(ids)
    ind={k:j for j,k in enumerate(sd['query_id'])}
    camera=sd['probability'][[ind[k] for k in ids],0].argmax(axis=-1)
    # Strict binary tie convention selects the first (piano) slot.
    free=np.stack((1-p,p),axis=1).argmax(axis=1)==rd['label'];paid=camera==rd['label']
    net=[F(int(c)-int(f))-price for f,c in zip(free,paid,strict=True)]
    cell=((p>=.5)*4+(np.abs(m)>.65)*2+((p>=.5)!=(g>=.5))).astype(int)
    cells[s]={group:[sum((net[i]/4 for i in range(len(ids)) if grp[i]==group and cell[i]==j),F()) for j in range(8)] for group in gids}
    for name,src in [('joint','coordinate_witness.json'),('train_only','train_only_seal.json')]:
        delta=list(map(F,docs[src]['delta']))
        assert len(delta)==19 and sum(map(abs,delta))<=1
        w=[t+d for t,d in zip(theta,delta,strict=True)]
        gap=[sum(c[k]*w[k] for k in range(19))-price for c in coords]
        decisions=[t>0 for t in gap]
        gr={g:[sum((net[i] if decisions[i] else F()) for i in range(len(ids)) if grp[i]==g)/4,
               sum((F() if decisions[i] else -net[i]) for i in range(len(ids)) if grp[i]==g)/4] for g in gids}
        diffs=list(zip(*gr.values())); buys=[k for k,b in zip(ids,decisions) if b]
        budget=sum(map(abs,delta)); below=min(map(abs,gap))
        positive=[pos_sign(side) for side in diffs];means=[avg(side) for side in diffs];worst=min(diffs[0])
        results=docs['coordinate_witness_result.json' if name=='joint' else 'train_only_result.json']['panels'][s]
        if name=='joint':
            assert buys==results['bought_queries'];expect=results['source_contrasts']; sig=results['one_sided_source_p']
            assert [F(results[k]) for k in ('gain_vs_free','gain_vs_paid','worst_vs_free')]==[*means,worst]
            assert abs(float(below)-results['min_score_margin'])<1e-12
            assert {g:list(map(F,ds)) for g,ds in expect.items()}==gr
        else:
            assert buys==results['bought_ids'];sig=results['one_sided_sign_p']
            assert all(abs(float(mean)-results[k])<1e-12 for mean,k in zip([*means,worst],('delta_free','delta_paid','worst_delta_free')))
            assert abs(float(below)-results['minimum_margin'])<1e-12
            for group,rv in results['sources'].items():
                assert all(abs(float(gr[group][j])-rv[k])<1e-12 for j,k in enumerate(('delta_free','delta_paid')))
        assert list(map(float,positive))==sig
        records.setdefault(name,{'l1':str(budget),'nonzero':sum(i!=0 for i in delta)})
        records[name][s]={'bought':buys,'input_queries':len(ids),'price_per_read':str(price),'total_price_paid':str(price*len(buys)),
                          'source_differences':{g:list(map(str,ds)) for g,ds in gr.items()},
                          'means':list(map(str,means)),'worst_vs_free':str(worst),'source_sign_p':list(map(str,positive)),
                          'minimum_abs_margin':float(below)}
        assert abs(budget-(F(9833757,10000000) if name=='joint' else F(9601562,10000000)))==0
# Build all inequalities independently from per-row returns with the convention A p <= b.
ineq={}
for s,g in cells.items():
    for group,coef in g.items():ineq[f'{s}/{group}']=([-c for c in coef]+[0],F(1,20))
    common_coef=[avg(list(c)) for c in zip(*g.values())]
    ineq[f'{s}/mean vs free']=([-c for c in common_coef]+[1],F())
    ineq[f'{s}/mean vs paid']=([-c for c in common_coef]+[1],-sum(common_coef))
for j in range(8):
    for mult,word,bound in ((1,'at most one',1),(-1,'at least zero',0)):
        ineq[f'cell {j} {word}']=([mult*int(j==k) for k in range(8)]+[0],F(bound))
cert=docs['cell_mixture_bound.json'];decision=list(map(F,[*cert['cell_probabilities'],cert['common_gain']]))
dual=defaultdict(F,{k:F(v) for k,v in cert['nonzero_dual_multipliers'].items()})
assert set(dual)<=ineq.keys() and min(dual.values())>0
slack={k:b-sum(c*x for c,x in zip(a,decision,strict=True)) for k,(a,b) in ineq.items()}
assert min(slack.values())>=0 and sum(slack[n]*dual[n] for n in ineq)==0
normal=[sum(dual[k]*a[i] for k,(a,b) in ineq.items()) for i in range(9)]
dualobj=sum(dual[k]*b for k,(a,b) in ineq.items())
assert normal==[0]*8+[1] and dualobj==decision[-1]==F(-487,10920)
receipt={'commit':commit,'opened_splits':panels,'input_sha256':dict(sorted(sources.items())),'replay':records,'lp':{'rows':len(ineq),'min_slack':str(min(slack.values())),'positive_dual_support':sum(x>0 for x in dual.values()),'primal':str(decision[-1]),'dual':str(dualobj),'stationarity':list(map(str,normal))},'independent_replay_source_sha256':h(Path(__file__).read_bytes())}
body=(json.dumps(receipt,sort_keys=True,indent=2)+'\n').encode()
(OUT/'receipt.json').write_bytes(body)
print(h(body))
for name,result in records.items():
 for s in panels:
  z=result[s];print(name,s, len(z['bought']),z['input_queries'],z['total_price_paid'],z['means'],z['worst_vs_free'],z['source_sign_p'],z['minimum_abs_margin'])
print(receipt['lp'])
