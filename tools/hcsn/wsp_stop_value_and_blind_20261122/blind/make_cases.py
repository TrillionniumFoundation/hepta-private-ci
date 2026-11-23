"""Create five opaque model copies, expose support only, and reserve complete task worlds."""
import hashlib,json,secrets,sys
from pathlib import Path
import numpy as np

root=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=False)
sys.path.insert(0,str(root/"pinned"))
from study_io import gen_items,context
from data_contract import head
import value_graph as vg
p=json.loads((root/'pinned/PROTOCOL_FROZEN.json').read_text())
ctx=context(p)
seed=secrets.randbits(128) if len(sys.argv)<4 else int(sys.argv[3])
r=np.random.default_rng(seed)
cases={}
faults=['swap2','neg1','down','two','keep'];r.shuffle(faults)
for fit,fault in zip(p['fit_ids'],faults):
    base,worlds=gen_items(p, root/'inputs',fit)
    uid=r.bytes(5).hex()
    shape=base['network']
    perm=r.permutation(48); signs=r.choice((-1.,1.),48)
    W=np.array(shape['w1'])[perm]*signs[:,None]; b=np.array(shape['b1'])[perm]*signs
    Y=np.array(shape['w2'])[:,perm]*signs[None,:]; c=np.array(shape['b2'])
    hW,hb,hY,hc=(v.copy() for v in (W,b,Y,c))
    labels={}
    if fault=='swap2':
        i,j=r.choice(48,2,replace=False);Y[:,[i,j]]=Y[:,[j,i]];labels=dict(i=int(i),j=int(j))
    if fault=='neg1':
        i=int(r.integers(48));W[i]*=-1;b[i]*=-1;labels=dict(i=i)
    if fault=='down':
        i=int(r.integers(48));k=int(r.integers(4));Y[k,i]+=.37;labels=dict(i=i,k=k)
    if fault=='two':
        i,j=map(int,r.choice(48,2,replace=False));k=int(r.integers(4));Y[k,i]+=.31;Y[k,j]-=.27;labels=dict(i=i,j=j,k=k)
    # Use complete worlds 0..11 for support; 16 and 25 are never revealed.
    rows=[]
    for w in worlds[:12]:
        X,_=vg.semantic_inputs(ctx,w['graph']['public'],ctx.NumpyPolicy(base),w['graph']['states'],lambda:None)
        rows.append(X)
    A=np.vstack(rows);A=A[r.choice(len(A),32,replace=False)]
    target=np.tanh(A@hW.T+hb)@hY.T+hc
    method=dict(input=A,reference_logits=target,W1=W,b1=b,W2=Y,b2=c)
    name=uid+'.npz';np.savez(out/name,**method)
    cases[uid]=dict(fit=fit,fault=fault,indices=labels,perm=perm.tolist(),signs=signs.tolist(),
                    file_sha256=hashlib.sha256((out/name).read_bytes()).hexdigest())
(out.parent/'protocol.json').write_text(json.dumps(dict(seed=seed,cases=cases,holdout_worlds=[16,25],
    target='original four preactivations after hidden-unit wrapping; report actual parameter support, forward recovery, full hard-policy expected utility',
    generation_code=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),indent=2))
