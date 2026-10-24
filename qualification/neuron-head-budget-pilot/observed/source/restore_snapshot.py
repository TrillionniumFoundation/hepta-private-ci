import hashlib,json,urllib.request,time
from pathlib import Path
P=Path(__file__).resolve().parent;S=P.parent/'shared-model-cache'/'harrier-oss-v1-270m'/'31de22b673913c7d658c0f03f792d77c2dcf8ebd'
meta=json.loads((P.parent/'cell-head-calibration-research/extraction.json').read_text())
S.mkdir(parents=True,exist_ok=True)
for name,expected in meta['snapshot_inventory'].items():
 target=S/name;target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists():
  if hashlib.sha256(target.read_bytes()).hexdigest()!=expected:raise ValueError('existing mismatch '+name)
  continue
 url='https://huggingface.co/microsoft/harrier-oss-v1-270m/resolve/31de22b673913c7d658c0f03f792d77c2dcf8ebd/'+name
 part=target.with_name(target.name+'.partial');h=hashlib.sha256();n=0
 with urllib.request.urlopen(url,timeout=180) as response,part.open('xb') as out:
  while chunk:=response.read(1024*1024):out.write(chunk);h.update(chunk);n+=len(chunk)
 if h.hexdigest()!=expected:raise ValueError('download mismatch '+name)
 part.rename(target);print(json.dumps({'file':name,'bytes':n,'sha256':h.hexdigest(),'verified':True}),flush=True)
print('SNAPSHOT VERIFIED',S,flush=True)
