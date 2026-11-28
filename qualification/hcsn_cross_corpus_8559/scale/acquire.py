from pathlib import Path
import hashlib, json, os, time, urllib.request as u, urllib.parse, concurrent.futures
import sys
base=Path(sys.argv[1]);base.mkdir(parents=True,exist_ok=True)
sets={'nwpu':('caglarmert/NWPU-captions','80bbaf1ef145c7279b1e2de933689c8add174606',['data/test-00000-of-00001.parquet','data/train-00000-of-00002.parquet','data/train-00001-of-00002.parquet','data/validation-00000-of-00001.parquet']),'sydney':('isaaccorley/Sydney-Captions','4b357e804147b78f6daf2deaed77260c53441bb5',['Sydney_captions.zip'])}
def request(o):
 b,(slug,rev,files)=o
 remote=json.load(u.urlopen(f'https://huggingface.co/api/datasets/{slug}/tree/{rev}/'+('data' if b=='nwpu' else '')+'?expand=true',timeout=20))
 manifest={f['path']:f for f in remote}
 (base/b).mkdir(exist_ok=True);(base/b/'remote.json').write_text(json.dumps(manifest,indent=2))
 for f in files:
  meta=manifest[f];expected=meta['lfs']['oid'];target=base/b/Path(f).name
  if target.exists() and target.stat().st_size==meta['size']:continue
  for attempt in range(4):
   try:
    req=u.Request(f'https://huggingface.co/datasets/{slug}/resolve/{rev}/{f}?download=true',headers={'User-Agent':'HCSN cross-corpus research'})
    h=hashlib.sha256()
    with u.urlopen(req,timeout=40) as response, target.with_suffix('.partial').open('wb') as out:
     while data:=response.read(512*1024): h.update(data);out.write(data)
    if h.hexdigest()!=expected:raise ValueError((h.hexdigest(),expected))
    os.replace(target.with_suffix('.partial'),target);print(b,f,meta['size'],h.hexdigest(),flush=True);break
   except Exception as e: print(b,'retry',attempt,type(e).__name__,str(e)[:120],flush=True);time.sleep(3*(attempt+1))
  else: raise RuntimeError(f)
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(request,sets.items()))
