import hashlib, io, json, math, time, zipfile, collections
from fractions import Fraction as F
import numpy as np
from pathlib import Path
z=zipfile.ZipFile('/mnt/data/r20-original.zip')
assert hashlib.sha256(Path('/mnt/data/r20-original.zip').read_bytes()).hexdigest()=='20e456f7f6a655afee7cf44882c0937457a7cc84abfbff5fcc9e21922c3c2d77'
def load(p):return json.loads(z.read(p))
def sq(lo,hi):return (F(0) if lo<=0<=hi else min(lo**2,hi**2),max(lo**2,hi**2))
def cr(lo,hi,c):
    pts=[lo,hi]+[F(j) for j in (-1,1) if lo<=j<=hi]
    y=[c*t/(1+t*t) for t in pts];return min(y),max(y)
def ce(v,w,r,lower):
    d=(r*(v-w)/2)**2
    correction=max(F(0),d/2-d*d/12) if lower else d/2
    return (v+w)/2+correction/r
def bounds(box, signed):
    a,A,b,B=box
    prod=[x*y for x in (a,A) for y in (b,B)]
    p0,p1=min(prod),max(prod)
    v0,v1=a-B,A-b
    s0,s1=sq(v0,v1);q0,q1=cr(a,A,F(1,25));j0,j1=cr(v0,v1,F(1,8) if signed else F(0))
    dl,dh=s0/4+q0+j0,s1/4+q1+j1
    result=[]
    for lower in (True,False):
        idx=0 if lower else 1
        groups=[]
        for x in (-1,1):
            for initial in (0,1):
                inner=[]
                for u in (-1,1):
                    first=initial ^ int(u==1)
                    terms=[]
                    for w in (-1,1):
                        second=first ^ int(w==1)
                        plo,phi=(p0-1,p1-1) if x==1 else (1-p1,1-p0)
                        shift=F(w,10)-1
                        terms.append(sq(plo+dl+shift,phi+dh+shift)[idx]+F(second,50))
                    inner.append(F(first,20)+F(9,10)*ce(*terms,F(1+first,2),lower))
                groups.append(ce(*inner,F(1+initial,2),lower))
        result.append(F(9,40)*sum(groups)+(sq(a,A)[idx]+sq(b,B)[idx])/4)
    return tuple(result)
def children(box):
    a,A,b,B=box
    if A-a>=B-b:
        m=(a+A)/2;return ((a,m,b,B),(m,A,b,B))
    m=(b+B)/2;return ((a,A,b,m),(a,A,m,B))
summary={}
for arm,signed,label in [('signed',True,'NEW'),('control',False,'CONTROL')]:
    t=time.perf_counter(); c=load('evidence/CERT_'+label+'.json'); raw=z.read('evidence/FRONTIER_'+label+'.jsonl'); assert hashlib.sha256(raw).hexdigest()==c['frontier_sha256']; rows=[json.loads(line) for line in raw.splitlines()]; assert len(rows)==c['frontier_count']; duplicate_ids={str(k):v for k,v in collections.Counter(r['id'] for r in rows).items() if v>1}; frontier={tuple(map(F,r['box'])):F(r['lower']) for r in rows}; assert len(frontier)==len(rows)
    a,b=F(c['candidate_a']),F(c['candidate_b']); lo,hi=bounds((a,a,b,b),signed); assert lo==F(c['candidate_cost_lower']) and hi==F(c['candidate_cost_rigorous_upper']); assert hi<F(9,4)
    # Reconstruct the binary partition independently, no heap or original verifier.
    todo=[(F(-3),F(3),F(-3),F(3))]; seen=set(); split=pruned=0; count=0
    while todo:
        box=todo.pop(); count+=1; lower,_=bounds(box,signed)
        if box in frontier:
            assert lower==frontier[box] and lower<hi
            seen.add(box)
        elif lower>=hi:pruned+=1
        else:
            split+=1; assert split<=c['bnb_node_cap']; todo.extend(children(box))
    assert seen==set(frontier) and split==c['nodes_split']; assert count==2*split+1
    lower=min(lo,min(frontier.values()));gap=max(F(0),hi-lower)
    assert lower==F(c['global_cost_lower']) and gap==F(c['global_regret_upper']) and (gap<=F(c['threshold']))==c['passes_frozen_global_threshold']
    summary[arm]={'frontier_rows':len(rows),'duplicate_ids':duplicate_ids,'split':split,'pruned':pruned,'partition_nodes':count,'global_lower':float(lower),'candidate_upper':float(hi),'gap':float(gap),'seconds':time.perf_counter()-t}
    print(arm,summary[arm],flush=True)
# Independently calculate exact conservative individual regret at every sealed final weight.
done=load('runs/COMPLETE.json'); assert len(done['entries'])==80
counts=collections.defaultdict(lambda:[0,0]); worst={}; checkpoint_rows=0
for ent in done['entries']:
    spec=ent['spec']; name=ent['name']; folder='runs/'+name+'/'
    rpt=load(folder+'REPORT.json'); seal=load(folder+'FIT_SEAL.json'); assert hashlib.sha256(z.read(folder+'REPORT.json')).hexdigest()==ent['report_sha']; assert hashlib.sha256(z.read(folder+'CHECKPOINTS.npz')).hexdigest()==seal['checkpoints']
    with np.load(io.BytesIO(z.read(folder+'WEIGHTS.npz')),allow_pickle=False) as f: theta=f['theta'].copy()
    assert hashlib.sha256(theta.tobytes()).hexdigest()==seal['weights']==rpt['weights_sha']
    with np.load(io.BytesIO(z.read(folder+'CHECKPOINTS.npz')),allow_pickle=False) as f: checkpoint_rows+=len(f['theta'])
    signed=spec['arm']=='signed'; c=load('evidence/CERT_'+('NEW' if signed else 'CONTROL')+'.json'); a,b=map(lambda x:F.from_float(float(x)),theta); _,hi=bounds((a,a,b,b),signed); gap=max(F(0),hi-F(c['global_cost_lower'])); k=(spec['arm'],spec['method']); counts[k][0]+=int(gap<=F(1,100));counts[k][1]+=1;worst[k]=max(worst.get(k,F(0)),gap)
summary['individual']=[{'arm':k[0],'method':k[1],'pass':v[0],'total':v[1],'max_gap':float(worst[k])} for k,v in sorted(counts.items())]; summary['checkpoint_rows_observed']=checkpoint_rows; summary['python']=__import__('sys').version;summary['numpy']=np.__version__;summary['scope']='independent rational global interval and 80 endpoint gap arithmetic only; no original verifier, optimizer, model/AD checkpoint replay or tamper tests'
print(json.dumps(summary,indent=2),flush=True)
Path('/mnt/data/hcsn_r20_independent/receipt.json').write_text(json.dumps(summary,indent=2)+'\n')
