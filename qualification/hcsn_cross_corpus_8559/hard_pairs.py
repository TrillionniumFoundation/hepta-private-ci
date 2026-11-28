"""Score new and frozen programs against purely lexical hard negatives."""
import argparse,json
from pathlib import Path
import numpy as np
from scipy import sparse
from report import contrast


def neighbors(tokens,groups,ids):
    n=len(tokens);v=int(tokens.max())+1
    idx=[];wt=[]
    for i,seq in enumerate(tokens):
        w=np.unique(seq[seq>1]);idx.extend(w.tolist());wt.extend([i]*len(w))
    bag=sparse.csr_matrix((np.ones(len(idx),dtype=np.float32),(wt,idx)),shape=(n,v))
    count=np.asarray(bag.sum(1)).ravel()
    overlap=(bag@bag.T).toarray();jac=overlap/np.maximum(count[:,None]+count[None,:]-overlap,1)
    # Deterministic lexical name order within an overlap tier.
    order=np.argsort(ids,kind='stable');peers=[]
    for i in range(n):
        allow=order[groups[order]!=groups[i]]
        rank=np.argsort(-jac[i,allow],kind='stable');peers.append(allow[rank[:25]])
    return np.stack(peers)


def eval_pairs(im,txt,peers):
    # Use a common float32 accumulation order for both true and peer dotted scores.
    d=np.einsum('ij,ij->i',im,txt,optimize=False);res=[]
    for a,b in ((im,txt),(txt,im)):
        fake=np.einsum('id,ijd->ij',a,b[peers],optimize=False)
        hit=((d[:,None]>fake)+.5*(d[:,None]==fake)).mean(1)
        r1=(d>=fake.max(1))/(1+(d[:,None]==fake).sum(1))
        res.append(np.stack([hit,r1],1))
    return np.stack(res,1)


def run(work):
    seal=json.loads((work/'seal.json').read_text())
    d=np.load(work/'input.npz');out={};rawvalues={}
    for name,split in [('rsicd',2),('ucm',3)]:
        ix=np.flatnonzero(d['split']==split);group=d['groups'][ix,0];peer=neighbors(d['tokens'][ix,0],group,d['names'][ix])
        vals={}
        for method in ['linear','literal','smooth','sdpa']:
            trials=[(r['seed'],r['selected']) for r in seal['neural'] if r['arm']==method] if method!='linear' else [(0,0)]
            arrays=[]
            for seed,step in trials:
                with np.load(work/'cold'/f'{method}-{seed}-{step}.npz') as z:
                    assert np.array_equal(z[name+'_group'],group)
                    arrays.append(eval_pairs(z[name+'_image'],z[name+'_text'],peer))
            vals[method]=np.mean(arrays,axis=0);rawvalues[name+'_'+method]=vals[method]
        rawvalues[name+'_peers']=peer;rawvalues[name+'_groups']=group
        out[name]={'means':{a:r.mean((0,1)).tolist() for a,r in vals.items()},'contrasts':{a:contrast(vals['literal'][:,:,0].mean(1),vals[a][:,:,0].mean(1),group) for a in ('linear','smooth','sdpa')}}
    np.savez_compressed(work/'hard.npz',**rawvalues);(work/'hard.json').write_text(json.dumps(out,indent=2)+'\n');print(out)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('work',type=Path);run(p.parse_args().work)
