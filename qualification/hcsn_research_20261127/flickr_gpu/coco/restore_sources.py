"""Restore exact COCO paired arrays from the upstream SHA-bound source roster."""
from pathlib import Path
import concurrent.futures,hashlib,json,os,subprocess,sys,time,urllib.request
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'coco_restored';OUT.mkdir(exist_ok=True)
def digest(f):
 with f.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def fetch(url,dst,h,n):
 if dst.exists() and dst.stat().st_size==n and digest(dst)==h:return
 for attempt in range(3):
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'Hepta paired-image research replay'})
   with urllib.request.urlopen(req,timeout=35) as src,dst.with_suffix('.download').open('wb') as f:
    while b:=src.read(262144):f.write(b)
   t=dst.with_suffix('.download')
   assert t.stat().st_size==n and digest(t)==h,(dst.name,t.stat().st_size)
   t.replace(dst);return
  except Exception as e:
   with (OUT/'network.jsonl').open('a') as log:log.write(json.dumps([dst.name,attempt,type(e).__name__])+'\n')
   if attempt==2:raise
   time.sleep(1+attempt)
ref=json.loads((ROOT/'coco_source_receipt.json').read_text());manifest=json.loads((ROOT/'coco_input_manifest.json').read_text())
rec={};seen=set()
for sp,n in [('train',1024),('val',192),('test',384)]:
 f=sp+'.json';size,h=ref['files'][f];dest=OUT/f
 fetch('https://storage.googleapis.com/sfr-vision-language-research/datasets/coco_karpathy_'+f,dest,h,size)
 docs=json.loads(dest.read_bytes()); d={}
 for row in docs:
  name=row['image'].split('/')[-1]; caps=row['caption'];caps=[caps] if isinstance(caps,str) else caps
  record=d.setdefault(name,{'file':name,'path':row['image'],'captions':[]})
  for c in caps:
   if c not in record['captions'] and len(record['captions'])<5:record['captions'].append(c)
 choose=sorted(d,key=lambda k:hashlib.sha256(('hepta-hcsn-coco-20261127-v1:'+k).encode()).hexdigest())[:n]
 assert len(choose)==n and not seen.intersection(choose)
 assert hashlib.sha256('\n'.join(choose).encode()).hexdigest()==ref['ordered_splits'][sp]
 rec[sp]=[d[k] for k in choose];seen.update(choose); del docs,d
 print('roster',sp,len(choose),flush=True)
(OUT/'selected.json').write_text(json.dumps(rec,ensure_ascii=False))
hashes={n:(h,s) for n,h,s in ref['jpeg']};folder=OUT/'images';folder.mkdir(exist_ok=True)
def image(row):
 name=row['file']; assert Path(name).name==name and name in hashes
 fetch('https://s3.amazonaws.com/images.cocodataset.org/'+row['path'],folder/name,*hashes[name])
 return name
with concurrent.futures.ThreadPoolExecutor(3) as ex:
 for i,name in enumerate(ex.map(image,[z for sp in rec.values() for z in sp]),1):
  if i%128==0: print('verified',i,'images',flush=True)
env=dict(os.environ,PYTHONPATH=str(ROOT/'prepare_packages'),OPENBLAS_NUM_THREADS='1')
subprocess.run([sys.executable,str(ROOT/'coco_raw_prepare.py'),'--image-dir',str(folder),'--roster',str(OUT/'selected.json'),'--out',str(OUT/'inputs')],env=env,cwd=OUT,check=True)
new=json.loads((OUT/'inputs'/'manifest.json').read_text())
assert all(new[s]==manifest[s] for s in ('train','val','test','vocab_sha256')),(new,manifest)
(OUT/'verification.json').write_text(json.dumps({'images':len(seen),'canonical_content_hashes':{s:new[s] for s in ('train','val','test')},'verified_epoch':time.time()}))
print('verified all original raw arrays',flush=True)
