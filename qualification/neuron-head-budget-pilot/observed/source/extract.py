"""Restore-dependent, fixed encoder only; no head fitting or scoring."""
import hashlib,json,os,resource,shutil,tempfile,time
from pathlib import Path
import numpy as np
import torch
from sentence_transformers import SentenceTransformer
P=Path(__file__).resolve().parent;O=P.parent/'cell-head-calibration-research'
H=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(x,msg):
 if not x:raise ValueError(msg)
def write(name,x):
 with (P/name).open('x') as f:json.dump(x,f,indent=2)
expected='b73cb06a5e441d07e0c38f0bb02350ee798f6e4cd30c70b51abc2163157faf1c'
require(H(P/'protocol.json')==expected,'protocol drift')
require(H(P/'rows.json')=='2017a6ba9d4d986c72490ab62c0b7ad57da382a47aa9fa3b2ed44cac3b85b308','selected manifest drift')
require(H(P/'preparation-receipt.json')=='e6317885c59fa590a8558e6491fa978831b3060ebcc6ff0b28f47fbe5ebfbe7b','frozen preparation drift')
receipt=json.loads((P/'preparation-receipt.json').read_text())
require(H(P/'selected-local-only.json')==receipt['selected_local_sha256'],'rows drift')
require(not (P/'features.npz').exists(),'never overwrite features')
rows=json.loads((P/'selected-local-only.json').read_text());original=json.loads((O/'extraction.json').read_text())['snapshot_inventory']
source=P.parent/'shared-model-cache'/'harrier-oss-v1-270m'/'31de22b673913c7d658c0f03f792d77c2dcf8ebd'
def inventory(p):return {f.relative_to(p).as_posix():H(f) for f in sorted(p.rglob('*')) if f.is_file()}
require(inventory(source)==original,'source snapshot differs from original experiment')
torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.use_deterministic_algorithms(True)
start=time.monotonic();arrays={};stats={}
with tempfile.TemporaryDirectory(prefix='harrier-head-budget-') as tmp:
 runtime=Path(tmp)/'model';shutil.copytree(source,runtime)
 model=SentenceTransformer(str(runtime),device='cpu',trust_remote_code=False,local_files_only=True,model_kwargs={'torch_dtype':torch.float32})
 model.max_seq_length=256;model.eval()
 require(model[1].pooling_mode_lasttoken and not model[1].pooling_mode_mean_tokens,'pooling mode')
 require(all(p.dtype==torch.float32 for p in model.parameters()),'model dtype')
 for split in ['train','test']:
  ts=time.monotonic();batches=[];lengths=[]
  for offset in range(0,len(rows[split]),8):
   texts=[r['text'] for r in rows[split][offset:offset+8]]
   lengths.extend(len(model.tokenizer(t,add_special_tokens=True,truncation=False)['input_ids']) for t in texts)
   if split=='train' and offset==0:
    tokens=model.tokenize(texts)
    with torch.inference_mode():
     f=model[0]({k:v.clone() for k,v in tokens.items()});a=f['attention_mask'];ix=(a*torch.arange(a.shape[1])).max(dim=1).values
     manual=torch.nn.functional.normalize(f['token_embeddings'][torch.arange(len(texts)),ix],p=2,dim=1)
     native=model({k:v.clone() for k,v in tokens.items()})['sentence_embedding']
    parity=float((manual-native).abs().max());require(parity<=1e-6,'pooling parity')
   z=model.encode(texts,prompt='',batch_size=8,convert_to_numpy=True,show_progress_bar=False,normalize_embeddings=True)
   batches.append(z)
   require(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss<3.5*1024*1024,'RSS budget exceeded')
   require(time.monotonic()-start<1800,'time budget exceeded')
  z=np.concatenate(batches);require(z.shape==(len(rows[split]),640) and z.dtype==np.float32 and np.isfinite(z).all(),'features invalid')
  require(np.max(np.abs(np.linalg.norm(z,axis=1)-1))<1e-5,'feature norms invalid')
  arrays[split]=z;stats[split]={'rows':len(z),'raw_tokens':sum(lengths),'max_tokens':max(lengths),'truncated':sum(l>256 for l in lengths),'seconds':time.monotonic()-ts,'tensor_sha256':hashlib.sha256(z.tobytes()).hexdigest()}
  require(inventory(source)==original and inventory(runtime)==original,'snapshot drift')
  print(json.dumps({'completed_split':split,**stats[split]}),flush=True)
 del model
np.savez_compressed(P/'features.npz',**arrays)
write('extraction.json',{'protocol_sha256':expected,'driver_sha256':H(__file__),'features_sha256':H(P/'features.npz'),'preparation_receipt_sha256':H(P/'preparation-receipt.json'),'splits':stats,'native_pooling_parity_max_abs':parity,'snapshot_inventory':original,'total_seconds':time.monotonic()-start,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
