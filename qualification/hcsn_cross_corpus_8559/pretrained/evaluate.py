"""Cold zero-shot pretrained Transformer evaluation on locked RSICD/UCM rows only."""
import argparse,hashlib,io,json,os,sys,time
from pathlib import Path

import numpy as np
from PIL import Image
import pyarrow.parquet as pq
import torch
from torch.nn.functional import normalize
from transformers import CLIPModel,CLIPTokenizerFast

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from confirm import shuffled
from hard_pairs import neighbors,eval_pairs
from prepare import words
from report import contrast
from score import metrics


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def raw_sources(rs,ucm,ids,which):
    if which=='rsicd':
        author={r['filename']:r['sentences'][0]['raw'] for r in json.loads((rs/'raw/original.json').read_text())['images']}
        paths=[rs/'raw/test.parquet']
    else:author=None;paths=sorted(ucm.glob('*.parquet'))
    want=set(ids.tolist());rows={}
    for path in paths:
        for batch in pq.ParquetFile(path).iter_batches(batch_size=24):
            for r in batch.to_pylist():
                key=Path(r['filename']).name if author is not None else r['file_name']
                if key in want:
                    assert key not in rows;rows[key]=(r['image']['bytes'],' '.join(words(author[key] if author is not None else r['caption_1'])))
    assert set(rows)==want
    return [rows[k] for k in ids]


def resize(p,cfg):
    n=cfg['size'];n=n['shortest_edge'] if isinstance(n,dict) else n
    w,h=p.size
    if min(w,h)!=n:
        dims=(n,int(n*h/w)) if w<=h else (int(n*w/h),n)
        p=p.resize(dims,Image.Resampling.BICUBIC)
    c=cfg['crop_size'];hh,ww=(c['height'],c['width']) if isinstance(c,dict) else (c,c)
    x=(p.width-ww)//2;y=(p.height-hh)//2;p=p.crop((x,y,x+ww,y+hh))
    buf=np.asarray(p,dtype=np.float32)/255
    return ((buf-np.asarray(cfg['image_mean'],np.float32))/np.asarray(cfg['image_std'],np.float32)).transpose(2,0,1)


def run(work,rs,ucm):
    torch.set_num_threads(1);start=time.perf_counter();cpu=time.process_time();dest=work/'pretrained';m=dest/'model'
    acquisition=json.loads((m/'receipt.json').read_text())
    for filename,(size,digest) in acquisition['files'].items():assert (m/filename).stat().st_size==size and sha(m/filename)==digest
    cfg=json.loads((m/'preprocessor_config.json').read_text());model=CLIPModel.from_pretrained(m,local_files_only=True).eval();tokenizer=CLIPTokenizerFast.from_pretrained(m,local_files_only=True)
    prep_time=time.perf_counter();setup_cpu=time.process_time()-cpu
    store=np.load(work/'input.npz');names=store['names'];pix=store['images'];groups=store['groups'];tokens=store['tokens'];split=store['split']
    frozen=json.loads((work/'seal.json').read_text());assert sha(work/'input.npz')==frozen['input']
    results={};embeds={};tm=0
    for gal,sc in [('rsicd',2),('ucm',3)]:
        ix=np.flatnonzero(split==sc);ids=names[ix];g=groups[ix,0]
        t0=time.perf_counter();raw=raw_sources(rs,ucm,ids,gal);caps=[r[1] for r in raw];assert len(set(caps))==len(np.unique(g))
        peer=neighbors(tokens[ix,0],g,ids);shuf=shuffled(g)
        t1=time.perf_counter();text=[];blue={}
        with torch.inference_mode():
            for i in range(0,len(raw),32):
                inputs=tokenizer(caps[i:i+32],padding=True,truncation=True,max_length=model.config.text_config.max_position_embeddings,return_tensors='pt')
                out=model.text_model(**inputs);text.append(normalize(model.text_projection(out.pooler_output),dim=-1).numpy())
            txt=np.concatenate(text);texttime=time.perf_counter()-t1
            for cond in ('cached32','native'):
                t2=time.perf_counter();image=[]
                for i in range(0,len(ids),8):
                    chunk=[]
                    for j in range(i,min(i+8,len(ids))):
                        if cond=='native':
                            with Image.open(io.BytesIO(raw[j][0])) as p:chunk.append(resize(p.convert('RGB'),cfg))
                        else:chunk.append(resize(Image.fromarray(pix[ix[j]]),cfg))
                    out=model.vision_model(pixel_values=torch.from_numpy(np.stack(chunk)));image.append(normalize(model.visual_projection(out.pooler_output),dim=-1).numpy())
                im=np.concatenate(image);it=time.perf_counter()-t2;st=time.perf_counter()
                sim=im@txt.T;values={'pair':metrics(sim,g),'shuffle':metrics(sim[shuf],g),'image_constant':metrics(np.broadcast_to(sim[:1],sim.shape),g),'text_constant':metrics(np.broadcast_to(sim[:,:1],sim.shape),g),'hard':eval_pairs(im,txt,peer)}
                selected={};paired={};pr=values['pair'][:,:,0].mean(1)
                for method in ('literal','smooth','sdpa','linear'):
                    deployments=[(r['seed'],r['selected']) for r in frozen['neural'] if r['arm']==method] if method!='linear' else [(0,0)]
                    x=[]
                    for seed,step in deployments:
                        with np.load(work/'cold'/f'{method}-{seed}-{step}.npz') as z:
                            assert np.array_equal(ids,z[gal+'_id']);x.append(z[gal+'_pair'][:,:,0].mean(1))
                    paired[method]=contrast(pr,np.mean(x,axis=0),g)
                name=gal+'_'+cond
                for k,v in values.items():embeds[name+'_'+k]=v.astype(np.float32)
                embeds[name+'_image']=im
                blue[cond]={'means':{k:v.mean((0,1)).tolist() for k,v in values.items()},'paired_clip_minus_reference':paired,'vision_wall_s':it,'scoring_wall_s':time.perf_counter()-st}
                print(gal,cond,round(blue[cond]['means']['pair'][0],5),round(it,2),flush=True)
        t3=time.perf_counter();results[gal]={'n':len(ids),'unique_primary':len(set(caps)),'load_roster_and_lexical_neighbors_wall_s':t1-t0,'text_wall_s':texttime,'elapsed_wall_s':t3-t0,'image_conditions':blue}
        embeds[gal+'_text']=txt;embeds[gal+'_group']=g;embeds[gal+'_id']=ids;embeds[gal+'_peers']=peer
    path=dest/'embeddings.npz';np.savez_compressed(path,**embeds)
    result=dict(reference=acquisition,parameters=sum(p.numel() for p in model.parameters()),input_sha256=frozen['input'],setup_wall_s=prep_time-start,setup_cpu_s=setup_cpu,compute_wall_s=time.perf_counter()-start,compute_cpu_s=time.process_time()-cpu,
                evaluation=results,embeddings_sha256=sha(path),threads=torch.get_num_threads(),torch=str(torch.__version__),prior_training_cost='not observed')
    (dest/'results.json').write_text(json.dumps(result,indent=2)+'\n');print('complete',result['compute_wall_s'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('work',type=Path);p.add_argument('rs',type=Path);p.add_argument('ucm',type=Path);a=p.parse_args();run(a.work,a.rs,a.ucm)
