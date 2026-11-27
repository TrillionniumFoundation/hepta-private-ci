from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import hashlib,json,os,time,sys,urllib.parse
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parent; C=ROOT/'cache';C.mkdir(exist_ok=True)
def download(url,path):
 if path.exists():return
 for a in range(4):
  temp=path.with_name('.'+path.name+'.tmp')
  try:
   with urlopen(Request(url,headers={'User-Agent':'Hepta research COCO benchmark'}),timeout=60) as f,temp.open('wb') as out:
    while chunk:=f.read(1048576):out.write(chunk)
    if f.headers.get('Content-Length') and out.tell()!=int(f.headers['Content-Length']):raise ValueError('incomplete')
   temp.replace(path);return
  except Exception as e:
   if a==3:raise
   time.sleep(1+a)
def j(p):return json.loads(p.read_bytes())
def digest(b):return hashlib.sha256(b).hexdigest()
hf='https://huggingface.co'
m=jpath=C/'model-id.json'
pinned_rev='6b7c523703ae26e39be4b03774966f8571c7f523'
download(hf+'/api/models/Xenova/clip-vit-base-patch32/revision/'+pinned_rev,m)
rev=j(m)['sha'];assert rev==pinned_rev;print('model',rev,flush=True)
model_paths=['onnx/vision_model_quantized.onnx','onnx/text_model_quantized.onnx','tokenizer.json','preprocessor_config.json']
def setup(it):
 base,p=it;download(base,C/p);return p
setups=[(hf+'/Xenova/clip-vit-base-patch32/resolve/'+rev+'/'+s,Path(s).name) for s in model_paths]
ann='https://storage.googleapis.com/sfr-vision-language-research/datasets/coco_karpathy_'
setups += [(ann+s+'.json',s+'.json') for s in ['train','val','test']]
with ThreadPoolExecutor(7) as ex:
 for f in as_completed([ex.submit(setup,it) for it in setups]):
  print('ready',f.result(),flush=True)
if (C/'selected.json').is_file():
 records=j(C/'selected.json')
else:
 records={}; seen=set()
 for sp,n in [('train',1024),('val',192),('test',384)]:
  rows=j(C/(sp+'.json'));d={}
  for row in rows:
   name=row['image'].split('/')[-1]; caps=row['caption'];caps=[caps] if isinstance(caps,str) else caps
   r=d.setdefault(name,{'file':name,'path':row['image'],'captions':[]})
   for cap in caps:
    if cap not in r['captions'] and len(r['captions'])<5:r['captions'].append(cap)
  selected=sorted(d,key=lambda k:digest(('hepta-hcsn-coco-20261127-v1:'+k).encode()))[:n]
  assert not (seen&set(selected)) and len(selected)==n
  seen.update(selected); records[sp]=[d[k] for k in selected]
 (C/'selected.json').write_text(json.dumps(records,ensure_ascii=False))
(C/'images').mkdir(exist_ok=True)
def one(rec):
 p=C/'images'/rec['file'];url='https://s3.amazonaws.com/images.cocodataset.org/'+rec['path']
 download(url,p)
 with p.open('rb') as f:assert f.read(2)==b'\xff\xd8'
 return rec['file'],digest(p.read_bytes()),p.stat().st_size
roster=[];errors=[]
with ThreadPoolExecutor(8) as ex:
 futures={ex.submit(one,r):r['file'] for rows in records.values() for r in rows}
 for f in as_completed(futures):
  try:roster.append(f.result())
  except Exception as e:errors.append([futures[f],str(e)])
  if (len(roster)+len(errors))%128==0:print('jpeg',len(roster),len(errors),flush=True)
p=ROOT/'source_receipt.json';p.write_text(json.dumps({'revision':rev,'files':{f:[(C/f).stat().st_size,digest((C/f).read_bytes())] for _,f in setups},'jpeg':sorted(roster),'errors':errors,'ordered_splits':{k:digest('\n'.join(r['file'] for r in vv).encode()) for k,vv in records.items()}},indent=1))
assert not errors,errors[:3]
