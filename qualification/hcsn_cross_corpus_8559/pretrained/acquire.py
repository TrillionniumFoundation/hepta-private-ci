"""Acquire the pinned model release and check every downloaded file against the model publisher."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib,json,os,time
from pathlib import Path
import urllib.request as u

MODEL='openai/clip-vit-base-patch32'
REV='3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268'
FILES=['config.json','merges.txt','preprocessor_config.json','pytorch_model.bin','special_tokens_map.json','tokenizer.json','tokenizer_config.json','vocab.json']


def run(dest):
    start=time.perf_counter();cpu=time.process_time();dest.mkdir(parents=True,exist_ok=True)
    url=f'https://huggingface.co/api/models/{MODEL}/tree/{REV}?expand=true'
    metadata={x['path']:x for x in json.load(u.urlopen(url,timeout=40))}
    def grab(name):
        x=metadata[name];out=dest/name
        for attempt in range(3):
            if out.exists() and out.stat().st_size==x['size']:
                data=out.read_bytes()
                if x.get('lfs') and hashlib.sha256(data).hexdigest()==x['lfs']['oid']:return name,(x['size'],hashlib.sha256(data).hexdigest())
                if hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==x['oid']:return name,(x['size'],hashlib.sha256(data).hexdigest())
            try:
                h=hashlib.sha256();g=hashlib.sha1(b'blob '+str(x['size']).encode()+b'\0');tmp=out.with_suffix('.partial')
                req=u.Request(f'https://huggingface.co/{MODEL}/resolve/{REV}/{name}?download=true&retry={attempt}',headers={'User-Agent':'HCSN frozen encoder research'})
                with u.urlopen(req,timeout=90) as response,tmp.open('wb') as f:
                    while chunk:=response.read(1<<20):
                        h.update(chunk);g.update(chunk);f.write(chunk)
                if tmp.stat().st_size!=x['size'] or (h.hexdigest()!=x['lfs']['oid'] if x.get('lfs') else g.hexdigest()!=x['oid']):raise ValueError(name)
                os.replace(tmp,out);return name,(x['size'],h.hexdigest())
            except (OSError,ValueError) as e:print('retry',name,attempt,str(e)[:100],flush=True);time.sleep(1+attempt)
        raise RuntimeError(name)
    with ThreadPoolExecutor(max_workers=2) as pool:files=dict(pool.map(grab,FILES))
    ob=dict(repository=MODEL,revision=REV,files=files,wall_s=time.perf_counter()-start,cpu_s=time.process_time()-cpu)
    (dest/'receipt.json').write_text(json.dumps(ob,indent=2)+'\n');print(ob,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('destination',type=Path);run(p.parse_args().destination)
