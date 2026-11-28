"""Prepare real frozen HCSN features, with a full native panel and compact cloud panel."""
from pathlib import Path
import hashlib,json,io,base64,lzma
import numpy as np

base=Path.home()/'.local/share/hepta-research';old=base/'hcsn-rls-edit-1140569/run'
out=base/'hcsn-9de7-device-edit';out.mkdir(exist_ok=True)
sha=lambda b:hashlib.sha256(b).hexdigest()
primary=json.loads((old/'development_seal.json').read_text());assert sha((old/'development_seal.json').read_bytes())=='deea9b35799c5cdc1a9c2c787be6494f4a098d07ef60060567b18383351b5eba'
p=old/'137';assert sha((p/'basis.npz').read_bytes())==primary['parents']['137']['archive_sha256']
assert sha((p/'held.npz').read_bytes())==json.loads((p/'held.json').read_text())['archive_sha256']
with np.load(p/'basis.npz',allow_pickle=False) as b,np.load(p/'held.npz',allow_pickle=False) as h:
 data={k:b[k] for k in b.files};data.update({k:h[k] for k in ('held','held_y','held_ids')})
y=data['train_y'];ids=data['train_ids'];eligible=np.flatnonzero(y//6>=6);eligible=eligible[np.argsort(ids[eligible],kind='stable')]
i=np.random.default_rng(912731).choice(eligible,size=128,replace=False);i=i[np.argsort(ids[i],kind='stable')]
data['anchors']=np.vstack((data['text'],data['train'][i]))
def choose(part,small):
 labels=data[part+'_y'];names=data[part+'_ids']
 # Full order is stage first, stable clip ID within the stage, as for the original fitter.
 if not small:
  if part=='train':
   return np.concatenate([s[np.argsort(names[s],kind='stable')] for j in range(3) for s in [np.flatnonzero(labels//6==j)]])
  return np.arange(len(labels))
 limit=6 if part=='train' else 2
 sel=[]
 for lab in range(18 if part=='train' else 72):
  found=np.flatnonzero(labels==lab)
  key=lambda i:hashlib.sha256((part+str(names[i])).encode()).digest()
  sel.extend(sorted(found,key=key)[:limit])
 return np.array(sorted(sel,key=lambda i:(labels[i]//6,names[i])))
info={}
for small in (False,True):
 name='compact' if small else 'native';dtype=np.float16 if small else np.float32
 fields={k:data[k].astype(dtype) for k in ('W0','text','anchors')};info[name]={}
 for part in ('train','dev','held'):
  i=choose(part,small);fields[part]=data[part][i].astype(dtype);fields[part+'_y']=data[part+'_y'][i].astype('int16')
  info[name][part]={'n':len(i),'id_hash':sha('\n'.join(data[part+'_ids'][i]).encode())}
 buf=io.BytesIO();np.savez(buf,**fields);bytes_=buf.getvalue();(out/(name+'.npz')).write_bytes(bytes_);info[name]['sha256']=sha(bytes_)
 if small:
  source=(base/'hcsn-9de7-device-head.py').read_text().replace('PACKED=None','PACKED='+repr(base64.b85encode(lzma.compress(bytes_,preset=9)).decode())).replace('EXPECTED=None','EXPECTED='+repr(sha(bytes_)))
  assert len(source.encode())<=262144
  (out/'cloud.py').write_text(source);info[name]['cloud_sha256']=sha(source.encode());info[name]['cloud_bytes']=len(source.encode())
(out/'inputs.json').write_text(json.dumps(info,indent=2)+'\n');print(json.dumps(info))
