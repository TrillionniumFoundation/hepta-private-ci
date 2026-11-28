"""Directly perturb the directed price/boundary paths in sealed real-data encoders."""
import argparse,hashlib,json,time
from pathlib import Path

import numpy as np
import torch

from confirm import shuffled
from fit import read_inputs
from network import Encoder
from report import contrast
from score import score_embeddings

CONDITIONS=('factual','sham','zero_wire','permute_wire','no_E','no_L','no_prices')


def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


@torch.inference_mode()
def enc(net,pix,tok,rows,condition,other=None):
    raw=[];im=[];tx=[]
    for m in net.mix:m.kind=condition if condition in ('no_E','no_L','no_prices') else 'literal'
    def collect(mod,args,out):
        n=len(out[1])//2;raw.append(torch.stack([out[1][:n],out[1][n:]],1).clone())
    h=net.mix[0].register_forward_hook(collect) if condition=='factual' else None
    try:
        for ix in np.array_split(np.arange(len(rows)),(len(rows)+63)//64):
            hook=None
            if condition in ('zero_wire','permute_wire','sham'):
                def sub(mod,args):
                    original=args[0]
                    if condition=='zero_wire':return (torch.zeros_like(original),)
                    x=other[ix];return (torch.cat([x[:,0],x[:,1]],0),)
                hook=net.mix[1].wire.register_forward_pre_hook(sub)
            try:
                a,b=net(pix[rows[ix]],tok[rows[ix],0]);im.append(a.numpy());tx.append(b.numpy())
            finally:
                if hook:hook.remove()
    finally:
        if h:h.remove()
    return np.concatenate(im),np.concatenate(tx),torch.cat(raw,0) if raw else None


def run(work,law):
    torch.set_num_threads(1);t0=time.perf_counter();c0=time.process_time()
    spec=json.loads((work/'seal.json').read_text());assert digest(work/'input.npz')==spec['input']
    pix,tok,groups,split,vocab=read_inputs(work/'input.npz');data=np.load(work/'input.npz')
    records={};scores={};arrays={}
    for gal,sc in [('rsicd',2),('ucm',3)]:
        ix=np.flatnonzero(split==sc);g=groups[ix,0];mapping=shuffled(g)
        records[gal]={};scores[gal]={}
        for desc in (r for r in spec['neural'] if r['arm']=='literal'):
            seed,step=desc['seed'],desc['selected'];p=work/'fits'/f'literal-{seed}'/f'{step}.pt'
            assert digest(p)==next(r['sha256'] for r in desc['rungs'] if r['step']==step)
            net=Encoder('literal',seed,vocab,law).eval();net.load_state_dict(torch.load(p,weights_only=True,map_location='cpu'))
            base=np.load(work/'cold'/f'literal-{seed}-{step}.npz');assert np.array_equal(base[gal+'_id'],data['names'][ix])
            records[gal][seed]={};factual=None
            for name in CONDITIONS:
                marks=None if factual is None else factual[2][mapping] if name=='permute_wire' else factual[2]
                im,tx,actual=enc(net,pix,tok,ix,name,marks)
                if name=='factual':
                    factual=(im,tx,actual)
                    assert np.array_equal(im,base[gal+'_image']) and np.array_equal(tx,base[gal+'_text'])
                if name=='sham':
                    assert np.array_equal(im,factual[0]) and np.array_equal(tx,factual[1])
                v=score_embeddings(im,tx,g);single=v[:,:,0].mean(1)
                arrays[f'{gal}_{seed}_{name}']=v
                diffs=[np.linalg.norm(im-factual[0],axis=1),np.linalg.norm(tx-factual[1],axis=1)]
                scores[gal].setdefault(name,[]).append(single)
                records[gal][seed][name]={'means_i2t':v[:,0].mean(0).tolist(),'means_t2i':v[:,1].mean(0).tolist(),
                                          'concordance':float(single.mean()),'mean_embedding_l2':[float(x.mean()) for x in diffs],'max_embedding_l2':[float(x.max()) for x in diffs]}
            print(gal,seed,{k:round(v['concordance'],5) for k,v in records[gal][seed].items()},flush=True)
        arrays[gal+'_id']=data['names'][ix];arrays[gal+'_group']=g;arrays[gal+'_derangement']=mapping
    result={}
    for gal,sc in [('rsicd',2),('ucm',3)]:
        g=groups[split==sc,0];avg={k:np.mean(x,axis=0) for k,x in scores[gal].items()};base=avg['factual']
        result[gal]={k:contrast(base,x,g) for k,x in avg.items() if k!='factual'}
    path=work/'interventions.npz';np.savez_compressed(path,**arrays)
    out=dict(by_seed=records,factual_minus_intervention=result,wire_task_contribution=all(result['ucm'][k]['caption_cluster_ci95'][0]>0 for k in ('zero_wire','permute_wire')),
             evidence_sha256=digest(path),elapsed_wall_s=time.perf_counter()-t0,elapsed_cpu_s=time.process_time()-c0)
    (work/'interventions.json').write_text(json.dumps(out,indent=2)+'\n')
    print('complete',out['wire_task_contribution'],out['elapsed_wall_s'],flush=True)


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('work',type=Path);a.add_argument('law',type=Path);p=a.parse_args();run(p.work,p.law)
