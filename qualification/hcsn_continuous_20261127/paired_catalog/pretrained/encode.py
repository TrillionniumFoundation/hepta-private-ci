"""Reproducible official-model catalog inference with per-block resume and immutable product-identity checks."""
from pathlib import Path
import sys,os,json,hashlib,io,time,gc
import numpy as np
from PIL import Image
import pyarrow.parquet as pq
import torch
from assets import BASE,OUT,HS
sys.path.insert(0,str(OUT))
from model import build_model
from simple_tokenizer import SimpleTokenizer

def prep(blob):
    with Image.open(io.BytesIO(blob)) as p:
        im=p.convert('RGB');w,h=im.size
        size=(224,int(224*h/w)) if w<=h else (int(224*w/h),224)
        im=im.resize(size,Image.Resampling.BICUBIC);w,h=im.size
        left=int(round((w-224)/2));top=int(round((h-224)/2))
        pix=np.asarray(im.crop((left,top,left+224,top+224))).astype(np.float32)/255.
        return ((pix-np.array([.48145466,.4578275,.40821073],np.float32))/np.array([.26862954,.26130258,.27577711],np.float32)).transpose(2,0,1)
def text_ids(tokenizer,strings):
    z=np.zeros((len(strings),77),dtype=np.int64);start=tokenizer.encoder['<|startoftext|>'];end=tokenizer.encoder['<|endoftext|>']
    for i,s in enumerate(strings):
        t=[start,*tokenizer.encode(s)[:75],end];z[i,:len(t)]=t
    return z
def main():
    threads=int(os.environ.get('HCSN_CLIP_THREADS','1'));torch.set_num_threads(threads);torch.set_num_interop_threads(1)
    device=os.environ.get('HCSN_CLIP_DEVICE','cpu');start=time.monotonic()
    assert hashlib.file_digest((OUT/'ViT-B-32.pt').open('rb'),'sha256').hexdigest()==HS
    # Release the original archive as soon as upstream eager module has copied the parameters.
    jit=torch.jit.load(str(OUT/'ViT-B-32.pt'),map_location='cpu').eval();m=build_model(jit.state_dict());del jit;gc.collect()
    if device=='cpu':m.float()
    m=m.to(device).eval().requires_grad_(False)
    tok=SimpleTokenizer(str(OUT/'bpe_simple_vocab_16e6.txt.gz'))
    meta=json.loads((BASE/'source.json').read_bytes());q=np.load(BASE/'catalog.npz');ids=q['id'];out=BASE/'clip_features';out.mkdir(exist_ok=True)
    nn=sum(p.numel() for p in m.parameters())
    print('native',device,torch.__version__,threads,'parameters',nn,'load_s',time.monotonic()-start,flush=True)
    offset=0;bi=0;images=0;secs=0.
    with torch.inference_mode():
        for f in meta['shards']:
            path=BASE/Path(f['path']).name
            for chunk in pq.ParquetFile(path).iter_batches(batch_size=256,columns=['id','image','productDisplayName']):
                target=out/f'block{bi:04d}.npz'
                rec=chunk.to_pylist();idx=np.array([r['id'] for r in rec]);assert np.array_equal(idx,ids[offset:offset+len(rec)])
                if target.exists():
                    with np.load(target) as prev:assert np.array_equal(prev['id'],idx) and prev['image'].shape==(len(idx),512) and np.isfinite(prev['text']).all()
                    offset+=len(idx);bi+=1;continue
                t=time.monotonic();X=[];Y=[]
                for i in range(0,len(rec),12):
                    rows=rec[i:i+12]
                    x=torch.from_numpy(np.stack([prep(v['image']['bytes']) for v in rows])).to(device)
                    a=m.encode_image(x);a=a.float()/a.float().norm(dim=-1,keepdim=True).clamp_min(1e-8)
                    words=torch.from_numpy(text_ids(tok,[v['productDisplayName'] for v in rows])).to(device)
                    y=m.encode_text(words);y=y.float()/y.float().norm(dim=-1,keepdim=True).clamp_min(1e-8)
                    X.append(a.cpu().numpy().astype('float16'));Y.append(y.cpu().numpy().astype('float16'))
                elapsed=time.monotonic()-t;secs+=elapsed;images+=len(idx)
                tmp=target.with_suffix('.tmp.npz');np.savez_compressed(tmp,image=np.concatenate(X),text=np.concatenate(Y),id=idx,seconds=elapsed);tmp.replace(target)
                offset+=len(idx);bi+=1
                if bi%4==0 or bi==1:print('blocks',bi,'images',offset,'active_items_s',images/max(secs,1e-8),'elapsed_s',time.monotonic()-start,flush=True)
    assert offset==len(ids)
    receipts={p.name:hashlib.file_digest(p.open('rb'),'sha256').hexdigest() for p in sorted(out.glob('block*.npz'))}
    (out/'seal.json').write_text(json.dumps({'model_sha256':HS,'device':device,'parameters':nn,'threads':threads,'records':offset,'blocks':receipts,'torch':torch.__version__},indent=1))
if __name__=='__main__':main()
