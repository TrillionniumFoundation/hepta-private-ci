"""Evaluate all held WikiText targets and check exact hierarchical word decoding."""
import argparse
from hashlib import sha256
from pathlib import Path
import json,math,sys,time
import numpy as np
import torch
import torch.nn.functional as F
from stream_wiki import State,log_probs

HERE=Path(__file__).resolve().parent
WEIGHTS={'hx':'ae4204b23201b3b517517811b737da97ac155800fb525eb0e13eb535d670a2ce',
         'sdpa':'a28db196e6039eae047f7d4d0cbd09a2f9c4757c739b48b3b58de6e056b5136e'}
SOURCE={'model.py':'3c2b414b304c00d931c131c736f1e5c11fcf9e491d464669198780af8e08a2cd',
        'closed_form.py':'f16fd8f2bc5c402cb60d3742ac6673132bb35fc4de3211d9839df6153a7ac047'}
WINDOWS=(128,256,512,1024,2048)


def load(root):
    for name,expected in SOURCE.items():assert sha256((root/'src'/name).read_bytes()).hexdigest()==expected
    sys.path.insert(0,str(root/'src'))
    from model import LanguageModel
    a=np.load(root/'test.npy');assert sha256(a.tobytes()).hexdigest()=='66a09df53e4ff74fcf7984bc98b0db3bba8623c475a46aad72b39ac065464651'
    models={};reports={}
    for k,val in WEIGHTS.items():
        p=root/'results'/f'{k}-887-best.pt'
        assert sha256(p.read_bytes()).hexdigest()==val
        reports[k]=json.loads((root/'results'/f'{k}-887.json').read_text())
        assert reports[k]['model_sha256']==val
        m=LanguageModel(33278,k)
        m.load_state_dict(torch.load(p,map_location='cpu',weights_only=True))
        models[k]=m.to('cuda').eval()
    return torch.from_numpy(a).long().to('cuda'),models,reports


def check_head(m,z):
    h=z[:4].contiguous()
    calc=log_probs(m.head,h).cpu()
    head=m.head
    first=head.root(h).to(torch.float64).log_softmax(-1)
    values=[first[:,:head.direct]]
    for g in range(head.groups):
        n=min(head.width,head.vocab-head.direct-g*head.width)
        raw=head.rank(F.gelu(h+head.condition.weight[g]))+head.prior.weight[g]
        values.append(first[:,g+head.direct:g+head.direct+1]+raw[:,:n].double().log_softmax(-1))
    reference=torch.cat(values,1).cpu()
    err=float((calc-reference).abs().max())
    mass=float((calc.double().exp().sum(1)-1.).abs().max())
    assert err<1e-4 and mass<1e-5 and torch.equal(reference.argmax(1),calc.argmax(1))
    return dict(complete_word_scores=calc.numel(),max_logp_difference=err,max_normalization_error=mass)


def main(root):
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    a,models,prior=load(root)
    device=torch.cuda.get_device_name(0)
    assert bool(torch.version.hip and torch.cuda.is_available())
    dot=float(torch.dot(torch.arange(8,device='cuda').float(),torch.arange(8,device='cuda').float()))
    assert dot==140.
    metrics=dict(torch=str(torch.__version__),hip=torch.version.hip,device=device,dot=dot,weights=WEIGHTS,rows=[],head_check={})
    totals={};valid_counts=None
    N=len(a)-1
    with torch.inference_mode():
        for kind,net in models.items():
            for W in WINDOWS:
                n=(N+W-1)//W
                x=F.pad(a[:-1],(0,W*n-N)).view(n,W)
                y=F.pad(a[1:],(0,W*n-N),value=-1).view(n,W)
                lossvals=[];refdiff=altdiff=0.
                start=time.perf_counter()
                for i in range(0,n,max(1,8192//W)):
                    ix=x[i:i+max(1,8192//W)];t=y[i:i+len(ix)]
                    source=State(net,kind,len(ix),W)
                    encoded=source.append(ix)
                    if W==128:
                        ref=net.encode(ix);refdiff=max(refdiff,float((ref-encoded).abs().max()))
                    if i==0:
                        separate=State(net,kind,1,W)
                        seq=ix[:1];parts=[]
                        for frag in seq[:,:W-8].split(97,dim=1):parts.append(separate.append(frag))
                        for q in seq[:,W-8:].split(1,dim=1):parts.append(separate.append(q))
                        altdiff=float((torch.cat(parts,1)-encoded[:1]).abs().max())
                        if W==128:metrics['head_check'][kind]=check_head(net,encoded[0,:4])
                    yp=t.reshape(-1);ok=yp>=0;hidden=encoded.flatten(0,1)
                    cacheloss=net.head(hidden[ok],yp[ok])
                    lossvals.append(cacheloss.cpu().numpy())
                losses=np.concatenate(lossvals);assert len(losses)==N
                # Keep raw total NLL and count for every original 128-target macroblock.
                pad=(-N)%128;blocks=np.pad(losses.astype(np.float64),(0,pad)).reshape(-1,128).sum(1)
                counts=np.minimum(128,np.maximum(0,N-np.arange(len(blocks))*128));valid_counts=counts
                key=kind+'_'+str(W);totals[key]=blocks
                nll=float(blocks.sum()/N)
                if W==128:assert abs(nll-prior[kind]['test']['nll'])<1e-5
                assert altdiff<2e-4 and refdiff<2e-4
                row=dict(kind=kind,window=W,targets=N,nll=nll,ppl=math.exp(nll),
                         strict_hidden_max_error=refdiff if W==128 else None,alternate_chunking_max_error=altdiff,
                         source_reference_nll=prior[kind]['test']['nll'],wall_seconds=time.perf_counter()-start)
                metrics['rows'].append(row);print(json.dumps(row),flush=True)
    totals['counts']=valid_counts
    raw=HERE/'WikiText_blocks.npz';np.savez_compressed(raw,**totals)
    metrics['raw_sha256']=sha256(raw.read_bytes()).hexdigest()
    bucket=4096//128;g=(len(valid_counts)+bucket-1)//bucket;pad=g*bucket-len(valid_counts)
    den=np.pad(valid_counts,(0,pad)).reshape(-1,bucket).sum(1)
    pick=np.random.default_rng(88412).integers(0,g,(5000,g));metrics['block_bootstrap']={}
    for kind in ('hx','sdpa'):
        for W in WINDOWS[1:]:
            dif=totals[kind+'_'+str(W)]-totals[kind+'_128']
            num=np.pad(dif,(0,pad)).reshape(-1,bucket).sum(1)
            boot=num[pick].sum(1)/den[pick].sum(1)
            metrics['block_bootstrap'][kind+'_'+str(W)]=[float(num.sum()/N),*np.quantile(boot,[.025,.975]).tolist()]
    (HERE/'wikitext_scores.json').write_text(json.dumps(metrics,indent=2)+'\n')
if __name__=='__main__':main(Path(sys.argv[1]))
