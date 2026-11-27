"""Certify exact rational rank of observed physical feedback keys in historical trained HCSNs."""
import functools,hashlib,json,sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import torch
from torch.nn import functional as F
P=Path(__file__).resolve().parent
sys.path.insert(0,str(P.parent/'specialization'));sys.path.insert(1,str(P.parent))
import exact
import experiment as core
PRIME=2**61-1
@functools.lru_cache(maxsize=262144)
def residue(f):
    num,den=float(f).as_integer_ratio()
    return (num*pow(den,-1,PRIME))%PRIME
def modular_pivots(matrix):
    basis={};rows=[];cols=[];product=1
    for i,row in enumerate(matrix):
        v=[residue(float(x)) for x in row]
        for k,normalized in sorted(basis.items()):
            if v[k]:
                multiple=v[k];v=[(u-multiple*b)%PRIME for u,b in zip(v,normalized)]
        pivot=next((j for j,x in enumerate(v) if x),None)
        if pivot is None:continue
        rows.append(i);cols.append(pivot);val=v[pivot];product=product*val%PRIME
        inv=pow(val,-1,PRIME);basis[pivot]=[a*inv%PRIME for a in v]
        if len(basis)==matrix.shape[1]:break
    # Online elimination uses independent pivots indexed by columns, with no row reorder in this record.
    # With rows in selection order and columns in pivot order, determinant is the pivot product.
    if len(rows)==matrix.shape[1]:
        inversions=sum(a>b for i,a in enumerate(cols) for b in cols[i+1:])
        determinant=product*(-1 if inversions%2 else 1)%PRIME
    else:determinant=None
    return rows,cols,determinant
@torch.no_grad()
def designs(m,x):
    inputs=[];prior=[];step_ix=[]
    for batch in x.split(24):
        prev=m.reset_absolute.new_zeros(len(batch),32);u=[];bs=[];steps=[]
        for t,(_,control,_,_,_,_,boundary,due) in enumerate(exact.boundary_updates(m,batch)):
            if due:
                delivered=(prev-m.boundary_reference) if t else prev
                u.append(F.pad(control,(0,1),value=1.));bs.append(delivered.to(control));steps.append(t)
            prev=boundary
        inputs.append(torch.stack(u,1));prior.append(torch.stack(bs,1));step_ix=steps
    u=torch.cat(inputs);b=torch.cat(prior)
    return {'first_input':u[:,0].numpy(),'all_input':u.flatten(0,1).numpy(),
            'sender_joint':torch.cat((u,b[:,:,:16]),2).flatten(0,1).numpy(),'receiver_recurrent':b.flatten(0,1).numpy()},np.array(step_ix)
def main():
    torch.set_num_threads(1);results=P/'results';results.mkdir(exist_ok=True)
    summary=[]
    for seed in core.DIGESTS:
        a=SimpleNamespace(seed=seed,input=P.parent/'input',parents=Path('/tmp/hcsn-audit-c889/nobp'))
        m,c,orig=core.read_parent(a);x,_,ids=core.loads(a,'train',c)['ar'];ds,steps=designs(m,x)
        destination=results/str(seed);destination.mkdir(exist_ok=True)
        raw=destination/'matrices.npz';np.savez_compressed(raw,source_ids=ids,steps=steps,**ds)
        rows={}
        for name,data in ds.items():
            assert data.dtype==np.float32
            indices,cols,det=modular_pivots(data);s=np.linalg.svd(data.astype(np.float64),compute_uv=False);n,p=data.shape
            row_ids=[str(ids[i if name=='first_input' else i//len(steps)]) for i in indices]
            ticks=[0 if name=='first_input' else int(steps[i%len(steps)]) for i in indices]
            rows[name]=dict(shape=[n,p],source_ids=row_ids,ticks=ticks,retained_row_indices=indices,column_pivots=cols,
                minor_sha256=hashlib.sha256(data[indices].astype('<f4').tobytes()).hexdigest(),det_mod_prime=det,
                rank_mod_prime=len(indices),certified_full_rational_rank=len(indices)==p and det!=0,
                singular_values=s.tolist(),condition=float(s[0]/s[-1]),standard_numerical_rank=int(np.linalg.matrix_rank(data.astype(np.float64))),
                by_relative_cutoff={str(tol):int((s>tol*s[0]).sum()) for tol in (1e-2,1e-4,1e-6,1e-8)},
                min_frozen_raw_preactivation_row_rms_per_unit_frobenius=float(s[-1]/np.sqrt(n)))
        doc=dict(seed=seed,prime=PRIME,source_parent=orig,data_sha256=core.sha(raw.read_bytes()),observed=rows,
                 measurement='actual consumed FP32 design, field certificate applies to ideal real affine recombination')
        core.write(destination/'audit.json',doc);summary.append(doc)
    core.write(results/'results.json',dict(rows=summary,prime=PRIME,protocol=core.sha((P/'PROTOCOL.md').read_bytes())))
    for row in summary:print(row['seed'],[(k,v['rank_mod_prime'],v['shape'][1],v['condition'],v['by_relative_cutoff']['0.01']) for k,v in row['observed'].items()],flush=True)
if __name__=='__main__':main()
