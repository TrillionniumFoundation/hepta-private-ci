"""Extract shared CLIP global embeddings and fixed projections of true hidden tokens."""
import argparse, gc, hashlib, json, os, time
from pathlib import Path
import numpy as np
from PIL import Image
from tokenizers import Tokenizer
import onnx
import onnxruntime as ort
ROOT=Path(__file__).resolve().parent
NODES={'vision':('/vision_model/encoder/layers.11/Add_1_output_0',768),'text':('/text_model/final_layer_norm/Add_1_output_0',512)}
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  while data:=f.read(1024*1024):h.update(data)
 return h.hexdigest()
def graph(cache,mod):
 dest=cache/(mod+'_hidden.onnx')
 if dest.exists():return dest
 base=cache/(mod+'_model_quantized.onnx');m=onnx.load(base)
 name,d=NODES[mod]
 assert sum(name in n.output for n in m.graph.node)==1
 m.graph.output.append(onnx.helper.make_tensor_value_info(name,onnx.TensorProto.FLOAT,['batch','length',d]))
 tmp=dest.with_suffix('.onnx.tmp');onnx.save(m,tmp);os.replace(tmp,dest);return dest
def image(path,config):
 with Image.open(path) as im:
  im=im.convert('RGB');w,h=im.size
  if w<=h:new=(224,224*h//w)
  else:new=(224*w//h,224)
  im=im.resize(new,Image.Resampling.BICUBIC);i=(new[0]-224)//2;j=(new[1]-224)//2
  arr=np.asarray(im.crop((i,j,i+224,j+224)),np.float32)/255
 return ((arr-np.array(config['image_mean'],np.float32))/np.array(config['image_std'],np.float32)).transpose(2,0,1)
def segments(z,mod,length,proj):
 if mod=='vision':
  p=z[1:].reshape(7,7,-1); seq=np.stack([p[:3,:3].mean((0,1)),p[:3,3:].mean((0,1)),p[3:,:3].mean((0,1)),p[3:,3:].mean((0,1))])
 else:
  tokens=z[1:max(2,length-1)];seq=np.stack([t.mean(0) if len(t) else tokens[-1] for t in np.array_split(tokens,4)])
 return (seq@proj).astype(np.float32)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('mod',choices=['vision','text']);ap.add_argument('--threads',type=int,default=1);ap.add_argument('--batch',type=int,default=4);ap.add_argument('--splits',nargs='+',default=['train','val','test']);args=ap.parse_args()
 start=time.perf_counter();c=ROOT/'cache';out=ROOT/'features';out.mkdir(exist_ok=True)
 roster=json.loads((c/'selected.json').read_text());cfg=json.loads((c/'preprocessor_config.json').read_text())
 dest=graph(c,args.mod);gc.collect()
 opt=ort.SessionOptions();opt.intra_op_num_threads=args.threads;opt.inter_op_num_threads=1;opt.enable_cpu_mem_arena=False;opt.enable_mem_pattern=False
 session=ort.InferenceSession(str(dest),opt,providers=['CPUExecutionProvider']);tokenizer=Tokenizer.from_file(str(c/'tokenizer.json'))
 rng=np.random.default_rng(11881 if args.mod=='vision' else 77411);dim=NODES[args.mod][1]
 proj=rng.normal(0,1/np.sqrt(dim),(dim,32)).astype(np.float32)
 for sp in args.splits:
  records=roster[sp];items=[(i,r['file']) for i,r in enumerate(records)] if args.mod=='vision' else [(i,t) for i,r in enumerate(records) for t in r['captions']]
  part=out/f'{args.mod}-{sp}';part.mkdir(exist_ok=True)
  clock=time.perf_counter()
  for lo in range(0,len(items),args.batch):
   p=part/f'{lo:06d}.npz';batch=items[lo:lo+args.batch]
   if p.exists():continue
   if args.mod=='vision':
    paths=[c/'images'/v for i,v in batch]
    if not all(x.is_file() for x in paths):raise FileNotFoundError(next(str(x) for x in paths if not x.is_file()))
    data={'pixel_values':np.stack([image(x,cfg) for x in paths])};lengths=[50]*len(paths)
   else:
    ids=[tokenizer.encode(v).ids for i,v in batch]
    ids=[x if len(x)<=77 else x[:76]+[49407] for x in ids];lengths=list(map(len,ids))
    padded=np.full((len(ids),max(lengths)),49407,np.int64)
    for k,x in enumerate(ids):padded[k,:len(x)]=x
    data={'input_ids':padded}
   emb,hidden=session.run(None,data)
   seq=np.stack([segments(z,args.mod,l,proj) for z,l in zip(hidden,lengths)])
   assert np.isfinite(emb).all() and np.isfinite(seq).all()
   with p.with_suffix('.tmp').open('wb') as f:np.savez_compressed(f,global_embedding=emb.astype(np.float32),tokens=seq,index=[i for i,v in batch])
   os.replace(p.with_suffix('.tmp'),p)
  with (out/f'{args.mod}-{sp}.npz').open('wb') as f:
   chunks=sorted(part.glob('*.npz'));vals={k:[] for k in ('global_embedding','tokens','index')}
   for p in chunks:
    with np.load(p) as d:
     for k in vals:vals[k].append(d[k])
   assert sum(len(x) for x in vals['index'])==len(items)
   np.savez_compressed(f,**{k:np.concatenate(v) for k,v in vals.items()})
  info={'source_sha256':digest(c/(args.mod+'_model_quantized.onnx')),'enriched_graph':digest(dest),'manifest_sha256':digest(c/'selected.json'),'batch':args.batch,'threads':args.threads,'providers':session.get_providers(),'ort':ort.__version__,'n':len(items),'elapsed_this_invocation':time.perf_counter()-clock,'process_elapsed_this_invocation':time.perf_counter()-start,'sha256':digest(out/f'{args.mod}-{sp}.npz')}
  (out/f'{args.mod}-{sp}.json').write_text(json.dumps(info,indent=2));print(sp,info,flush=True)
if __name__=='__main__':main()
