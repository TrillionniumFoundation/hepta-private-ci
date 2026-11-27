"""Run the prespecified frozen-model substitution in a CPU process."""
import argparse,hashlib,json,time,sys
from pathlib import Path
import numpy as np
import torch


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


class JointLookup(torch.nn.Module):
    def __init__(self,base,copies):
        super().__init__();self.base=base;self.copies=copies
        self.kappa=base.kappa;self.principal=base.principal;self.a0=base.a0
        self.f0=base.f0 if copies==1 else 1-(1-base.f0)**copies

    def lookup(self,x):
        original=self.base.lookup(x)
        if self.copies==1:return original
        equity,slope,annual,quarter,old_mean=original.unbind(-1)
        def bundle(q):
            # Finite table inputs stay in [0,1]. The geometric sum preserves tiny probabilities.
            s=1-q;term=torch.ones_like(s);total=term
            for _ in range(1,self.copies):
                term=term*s;total=total+term
            return q*total
        year=bundle(annual);hit=bundle(quarter)
        next_mean=(old_mean-.3*quarter)*(1-quarter).pow(self.copies-1)+.3*hit
        return torch.stack([equity,slope,year,hit,next_mean],dim=-1)


def main():
    cli=argparse.ArgumentParser();cli.add_argument('reference_dir',type=Path);cli.add_argument('objects_dir',type=Path);cli.add_argument('out',type=Path);args=cli.parse_args()
    sys.path.insert(0,str(args.reference_dir.resolve()));from model import Captioner
    from panel import Samples,score
    torch.set_num_threads(1);torch.set_num_interop_threads(1);cpu=torch.device('cpu');start=time.perf_counter()
    args.out.mkdir(exist_ok=True,parents=True);data=args.reference_dir/'data';manifest=json.loads((data/'manifest.json').read_text())
    assert sha(data/'manifest.json')=='ba7083f60f12be990ede3f9a60f04524aa81228989bf6384f1684f225c26dd1e'
    assert sha(args.reference_dir/'model.py')=='974c781f64662bc509e270d14e9eda35bfa113fcba115c8c83a4149678c33123'
    valid=Samples(data,'validation',manifest);assert len(valid.ids)==1000
    key=lambda i,p:hashlib.sha256(p+bytes(valid.ids[i])).digest()
    blocked=set(sorted(range(1000),key=lambda i:key(i,b'flickr-caption-prereg-128'))[:128]);assert len(blocked)==128
    ids=np.asarray(sorted(set(range(1000))-blocked,key=lambda i:key(i,b'hcsn-independent-microdomains-frozen-20261127'))[:256]);assert not blocked.intersection(ids)
    data_arrays={'ids':valid.ids[ids].copy()};per={};seals={17011:'2adbb5ada20af413a0755964e8400714935a9adf2a6a6eb3b345286c220e3e0b',24203:'5c842b33ff4ca43e6d0c1b9c48412aa01b72d856b488e520aae56301e43a7c8b',39827:'b3770234a6cbbb1718e9883425e73fc6fb2db7e56865717bb0b3b9fed0592339'}
    for seed,name in seals.items():
        path=args.objects_dir/name;assert sha(path)==name
        model=Captioner('hcsn',len(manifest['vocab'])).eval();model.load_state_dict(torch.load(path,map_location='cpu',weights_only=True))
        base=model.router.law;images,tokens=valid.batch(ids[:3],np.zeros(3,dtype=int),cpu)
        with torch.inference_mode():native=model(images,tokens[:,:-1])
        for n in [1,2,4]:
            model.router.law=JointLookup(base,n)
            if n==1:
                with torch.inference_mode():assert torch.equal(native,model(images,tokens[:,:-1]))
            a,c=score(model,valid,ids,cpu);shifted,cs=score(model,valid,ids,cpu,True);assert np.array_equal(c,cs)
            assert 'counts' not in data_arrays or np.array_equal(c,data_arrays['counts']);data_arrays['counts']=c
            name=f'{seed}_{n}';data_arrays[name+'_correct']=a;data_arrays[name+'_shifted']=shifted
            per[name]={'nll':float(a.sum()/c.sum()),'conditioning_gain':float((shifted-a).sum()/c.sum())}
            print('cell',name,per[name],flush=True)
    assert len(per)==9;rng=np.random.default_rng(20261127191);ix=rng.integers(256,size=(5000,256));counts=data_arrays['counts'];summary={}
    for n in [1,2,4]:
        loss=np.mean([data_arrays[f'{s}_{n}_correct'] for s in seals],axis=0)
        base=np.mean([data_arrays[f'{s}_1_correct'] for s in seals],axis=0)
        shifted=np.mean([data_arrays[f'{s}_{n}_shifted'] for s in seals],axis=0)
        diff=loss-base
        summary[n]={'nll':float(loss.sum()/counts.sum()),'conditioning_gain':float((shifted-loss).sum()/counts.sum()),'minus_n1':float(diff.sum()/counts.sum()),'paired_image_95':np.quantile(diff[ix].sum(1)/counts[ix].sum(1),[.025,.975]).tolist()}
    raw=args.out/'per_image.npz';np.savez_compressed(raw,**data_arrays)
    record={'source':sha(Path(__file__)),'scope':'previously used Flickr validation corpus, 256 images excluded from the original 128-image selection subset; frozen weights','weights':seals,'images':256,'captions':1280,'tokens':int(counts.sum()),'torch':str(torch.__version__),'threads':1,'device':'cpu','elapsed_seconds':time.perf_counter()-start,'array_sha256':sha(raw),'per_model':per,'summary':summary}
    (args.out/'frozen_results.json').write_text(json.dumps(record,sort_keys=True,indent=2)+'\n');print('complete',summary,flush=True)


if __name__=='__main__':main()
