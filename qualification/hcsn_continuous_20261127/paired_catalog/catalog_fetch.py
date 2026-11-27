"""Fetch a public original-style product catalog from one immutable Hugging Face revision.
Only fetch parquet data, capped at 650 MB total. Preserve SHA256 for all approved input shards.
"""
from pathlib import Path
import json,hashlib,urllib.request,urllib.parse,time,sys
ROOT=Path(__file__).resolve().parent/'paired_catalog';ROOT.mkdir(exist_ok=True)
repo='HEBA2002/fashion-product-images-small'
def request(url):
    for i in range(3):
        try:return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Hepta reproducible paired retrieval research'}),timeout=60)
        except Exception:
            if i==2:raise
            time.sleep(2+i)
def main():
    with request('https://huggingface.co/api/datasets/'+repo) as r:meta=json.load(r)
    rev=meta['sha']
    with request('https://huggingface.co/api/datasets/'+repo+'/tree/'+rev+'?recursive=true&expand=true&limit=100') as r:files=json.load(r)
    shards=[f for f in files if f['path'].endswith('.parquet')];total=sum(f['size'] for f in shards)
    if not shards:
        with request('https://huggingface.co/api/datasets/'+repo+'/tree/refs%2Fconvert%2Fparquet?recursive=true&expand=true&limit=100') as r:files=json.load(r)
        shards=[f for f in files if f['path'].endswith('.parquet')];total=sum(f['size'] for f in shards)
        # Only proceed with named immutable revision, never resolve bytes through a moving reference.
        with request('https://huggingface.co/api/datasets/'+repo+'/revision/refs%2Fconvert%2Fparquet') as r:rev=json.load(r)['sha']
    print('revision',rev,'shards',[(f['path'],f['size']) for f in shards],flush=True)
    assert 0<total<=650000000
    receipt=[]
    for f in shards:
        p=ROOT/Path(f['path']).name
        expected=f.get('lfs',{}).get('oid')
        if not p.is_file():
            part=p.with_suffix('.part')
            with request('https://huggingface.co/datasets/'+repo+'/resolve/'+rev+'/'+urllib.parse.quote(f['path'])) as r,part.open('wb') as out:
                for b in iter(lambda:r.read(1024*1024),b''):
                    if out.tell()+len(b)>f['size']:raise ValueError('unexpected size')
                    out.write(b)
            assert part.stat().st_size==f['size'];part.replace(p)
        digest=hashlib.sha256(p.read_bytes()).hexdigest()
        if expected:assert digest==expected
        receipt.append({'path':f['path'],'size':p.stat().st_size,'sha256':digest})
    (ROOT/'source.json').write_text(json.dumps({'repo':repo,'revision':rev,'shards':receipt},indent=2))
    print('verified',receipt,flush=True)
if __name__=='__main__':main()
