"""Verify exclusive-port topology, freeze all fits and recover independent raw-gallery predictions."""
import argparse,hashlib,json,os,sys,time
from pathlib import Path

import numpy as np
import torch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from confirm import shuffled
from hard_pairs import neighbors,eval_pairs
from port import PortEncoder,ARMS,SEEDS
from report import contrast
from score import metrics
from train_port import sha,write

GALLERIES=('rsicd','ucm','rsitmd_r4','rsitmd_r8','nocaps')
MODES=('pair','visual_derange','image_clamp','text_clamp','both_clamp','hard')


def read(p):return json.loads(p.read_text())


def seal(source,out,law):
    if (out/'seal.json').exists():return
    assert not (out/'cold').exists()
    runs=[]
    for bits in (32,8):
        for arm in ARMS:
            for seed in SEEDS:
                b=out/'fits'/f'{arm}-{bits}-{seed}';rec=read(b/'selected.json')
                assert [x['step'] for x in rec['history']]==[128,512,2048]
                for x in rec['history']:assert sha(b/f"s{x['step']}.pt")==x['sha256']
                assert rec['selected']==max(rec['history'],key=lambda x:x['dev_concordance']);runs.append(rec)
    external=read(out/'RSITMD_ROSTER.json')
    assert sha(out/'rsitmd.npz')==external['array_sha256']
    natural=read(out/'NOCAPS_ROSTER.json');assert sha(out/'nocaps.npz')==natural['derived_sha256']
    with (out/'seal.json').open('x') as f:
        json.dump(dict(sealed_utc=time.time(),runs=runs,law=sha(law),source=sha(source/'input.npz'),target=external['array_sha256'],natural=natural['derived_sha256'],natural_roster=sha(out/'NOCAPS_ROSTER.json'),roster=sha(out/'RSITMD_ROSTER.json'),
                       sources={p.name:sha(p) for p in HERE.glob('*.py')}),f,indent=2)


def galleries(source,out):
    src=np.load(source/'input.npz');ext=np.load(out/'rsitmd.npz')
    for g,sc in [('rsicd',2),('ucm',3)]:
        ix=src['split']==sc
        yield g,src['images'][ix],src['tokens'][ix,0].astype(np.int64),src['names'][ix],src['groups'][ix,0]
    nat=np.load(out/'nocaps.npz')
    yield 'nocaps',nat['pixels'],nat['tokens'].astype(np.int64),nat['ids'],nat['groups']
    for r in (4,8):
        ix=ext[f'radius{r}']
        yield 'rsitmd_r'+str(r),ext['pixels'][ix],ext['tokens'][ix].astype(np.int64),ext['ids'][ix],ext['groups'][ix]


def take_wire(model,wires,rows):
    q=np.concatenate([wires[0][rows],wires[1][rows]])
    # Recreate an ordinary byte payload and reconstruct solely from dtype, dimensions and raw values.
    serialized=q.tobytes(order='C');q=np.frombuffer(serialized,dtype=q.dtype).reshape(q.shape).copy()
    return model.upper(model.decode(torch.from_numpy(q)))


def probe(model,pix,tok):
    result={}
    for clamp in (False,True):
        model.zero_grad();model.train()
        x=torch.from_numpy(pix[:4]).float().requires_grad_();t=torch.from_numpy(tok[:4]);b=model.lower(x,t);q=model.decode(model.serialize(b))
        if model.bits==8:q=q+(b-b.detach())
        if clamp:q=q*0+(model.lo+model.hi)*.5
        i,s=model.upper(q);obj=(i[:,0]+s[:,1]).sum()
        grad_pixel,grad_words=torch.autograd.grad(obj,(x,model.word.weight),allow_unused=False)
        result['clamped' if clamp else 'unclamped']={'pixel_l1':float(grad_pixel.abs().sum()),'word_table_l1':float(grad_words.abs().sum())}
    assert result['clamped']['pixel_l1']==0 and result['clamped']['word_table_l1']==0
    assert result['unclamped']['pixel_l1']>0 and result['unclamped']['word_table_l1']>0
    model.eval();return result


@torch.inference_mode()
def one_gallery(model,pix,tok,groups,ids,peers):
    chunks=np.array_split(np.arange(len(ids)),max(1,(len(ids)+63)//64))
    pred=[[],[]];wires=[[],[]];model.eval()
    for ix in chunks:
        x,t=torch.from_numpy(pix[ix]),torch.from_numpy(tok[ix]);a,z=model(x,t);b=model.lower(x,t);w=model.serialize(b);i,j=w.chunk(2,0)
        for dest,p in zip(pred,(a,z)):dest.append(p.numpy())
        for dest,p in zip(wires,(i,j)):dest.append(p.numpy())
    pred=[np.concatenate(v) for v in pred];wires=[np.concatenate(v) for v in wires]
    assert wires[0].nbytes*8//len(ids)==4*8*model.bits
    wire_stats=[]
    for w in wires:
        codes=w if w.dtype==np.uint8 else torch.round((torch.from_numpy(w)-model.lo)*255/(model.hi-model.lo)).clip(0,255).byte().numpy()
        prob=np.array([np.bincount(c,minlength=256) for c in codes.reshape(-1,8).T],dtype=np.float64)
        width=(prob>0).sum(1).tolist();prob/=prob.sum(1,keepdims=True)
        h=-(prob*np.log2(prob.clip(1e-300))).sum(1)
        wire_stats.append(dict(marginal_entropy_8bit_bins_per_group=h.tolist(),occupied_bins=width))
    center=getattr(model,'clamp_wire_code',128) if model.bits==8 else float((model.hi+model.lo)*.5);fixed=[np.full_like(w,center) for w in wires]
    perm=shuffled(groups);outputs={}
    for mode,values in [('pair',wires),('visual_derange',(wires[0][perm],wires[1])),('image_clamp',(fixed[0],wires[1])),('text_clamp',(wires[0],fixed[1])),('both_clamp',fixed)]:
        arrays=[[],[]]
        for ix in chunks:
            for arr,part in zip(arrays,take_wire(model,values,ix)):arr.append(part.numpy())
        arr=[np.concatenate(x) for x in arrays];outputs[mode]=arr
    max_error=max(float(np.max(np.abs(pred[i]-outputs['pair'][i]))) for i in (0,1));assert max_error<=2e-7
    variation=max(float(np.ptp(a,axis=0).max()) for a in outputs['both_clamp']);assert variation<=3e-6
    scores={mode:metrics(a@b.T,groups).astype(np.float32) for mode,(a,b) in outputs.items()}
    scores['hard']=eval_pairs(*outputs['pair'],peers).astype(np.float32)
    status={'wire_bits_per_example_per_tower':4*8*model.bits,'native_dtype':str(wires[0].dtype),'actual_serialized_bytes_per_example':wires[0][0].nbytes,
            'max_sham_replay_abs_error':max_error,'max_clamped_output_coordinate_range':variation,'marginal_occupancy':wire_stats}
    return scores,wires,pred,status


def confirm(source,out,law):
    s=read(out/'seal.json');assert s['source']==sha(source/'input.npz') and s['target']==sha(out/'rsitmd.npz') and sha(law)==s['law']
    assert s['natural']==sha(out/'nocaps.npz') and s['natural_roster']==sha(out/'NOCAPS_ROSTER.json')
    torch.set_num_threads(1);folder=out/'cold';folder.mkdir(exist_ok=True)
    gs=list(galleries(source,out));peers={g:neighbors(tok,grp,ids) if len(ids)>=27 else None for g,_,tok,ids,grp in gs}
    with np.load(source/'input.npz') as d:vocab=int(d['vocab'])
    for candidate in s['runs']:
        arm,bits,seed=candidate['arm'],candidate['bits'],candidate['seed'];key=f'{arm}-{bits}-{seed}';p=folder/(key+'.npz');rp=folder/(key+'.json')
        if rp.exists():
            assert sha(p)==read(rp)['sha256'];continue
        tic=time.perf_counter();cpu=time.process_time()
        chosen=candidate['selected'];fn=out/'fits'/key/f"s{chosen['step']}.pt";assert sha(fn)==chosen['sha256']
        net=PortEncoder(arm,bits,seed,vocab,law);net.load_state_dict(torch.load(fn,map_location='cpu',weights_only=True));arr={};status={}
        grad=probe(net,gs[0][1],gs[0][2])
        for g,pix,tok,ids,grp in gs:
            if peers[g] is None:
                status[g]={'n':len(ids),'scorable':False};continue
            vals,wire,pred,st=one_gallery(net,pix,tok,grp,ids,peers[g]);arr[g+'_id']=ids;arr[g+'_group']=grp
            for k,v in vals.items():arr[g+'_'+k]=v
            for sname,a,b in zip(('image','text'),wire,pred):arr[g+'_'+sname+'_wire']=a;arr[g+'_'+sname+'_embedding']=b
            status[g]=dict(n=len(ids),unique_primary=len(np.unique(grp)),scorable=True,means={k:v.mean((0,1),dtype=np.float64).tolist() for k,v in vals.items()},**st)
        with p.with_suffix('.part').open('wb') as f:np.savez_compressed(f,**arr)
        os.replace(p.with_suffix('.part'),p);write(rp,dict(arm=arm,bits=bits,seed=seed,source_selected_step=chosen['step'],probe=grad,galleries=status,sha256=sha(p),wall_s=time.perf_counter()-tic,cpu_s=time.process_time()-cpu))
        print('confirmed',key,{g:round(x['means']['pair'][0],5) for g,x in status.items() if x['scorable']},flush=True)


def summarize(out):
    seal_doc=read(out/'seal.json');report={};folder=out/'cold';gates={}
    for name in GALLERIES:
        stats={};all_seeds={};g=None
        for bits in (32,8):
            for arm in ARMS:
                key=f'{arm}-{bits}';values=[]
                for sd in SEEDS:
                    rec=read(folder/f'{key}-{sd}.json');st=rec['galleries'][name]
                    if not st['scorable']:continue
                    with np.load(folder/f'{key}-{sd}.npz') as z:
                        cur=z[name+'_group']
                        if g is None:g=cur
                        assert np.array_equal(g,cur)
                        values.append(np.stack([z[name+'_'+mode][:,:,0].mean(1,dtype=np.float64) for mode in MODES]))
                if values:
                    x=np.stack(values);all_seeds[key]=x
                    stats[key]={k:float(x[:,i].mean()) for i,k in enumerate(MODES)}
                    stats[key]['seed_pair']=x[:,0].mean(1).tolist()
        if g is None:report[name]={'scorable':False};continue
        diffs={};decisions={}
        for bits in (32,8):
            m=str(bits);signal=all_seeds['literal-'+m].mean(0)
            diffs[m]={a:contrast(signal[0],all_seeds[a+'-'+m].mean(0)[0],g) for a in ('smooth','attention')}
            decisions[m]={'specific_positive':len(g)>=50 and all(v['caption_cluster_ci95'][0]>0 for v in diffs[m].values()),
                         'quality_all_three':all(i>=.60 for i in stats['literal-'+m]['seed_pair']),
                         'derangement_chance_each_seed':bool(np.all(np.abs(all_seeds['literal-'+m][:,1].mean(1)-.5)<=.05))}
        report[name]=dict(n=len(g),unique_normalized_captions=len(np.unique(g)),metrics=stats,paired_literal_minus_baseline=diffs,gates=decisions)
    write(out/'results.json',dict(seal_sha256=sha(out/'seal.json'),metrics=report,probe_note='8-bit unclamped training probes use the registered STE, and eval physically transmits uint8 bytes. The FP32 port transmits float32 words.'))
    print('final',report['rsitmd_r4'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('out',type=Path);p.add_argument('law',type=Path);p.add_argument('mode',choices=('seal','confirm','report','finish'));a=p.parse_args()
    if a.mode in ('seal','finish'):seal(a.source,a.out,a.law)
    if a.mode in ('confirm','finish'):confirm(a.source,a.out,a.law)
    if a.mode in ('report','finish'):summarize(a.out)
