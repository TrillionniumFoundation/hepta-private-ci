"""Fetch the three independently published Neuromatch Steinmetz session archives."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request

def get(item):
    j,ident,out=item;url=f'https://osf.io/{ident}/download';meta=f'https://api.osf.io/v2/files/{ident}/';ref={}
    try:
        with urllib.request.urlopen(meta,timeout=20) as f:ref=json.load(f)['data']['attributes'].get('extra',{}).get('hashes',{})
    except (OSError,ValueError,KeyError):pass
    target=out/f'part{j}.npz';h=hashlib.sha256();md5=hashlib.md5()
    if not target.exists():
        path=target.with_suffix('.part')
        with urllib.request.urlopen(url,timeout=120) as f,path.open('wb') as dst:
            while chunk:=f.read(1048576):dst.write(chunk)
        path.replace(target)
    with target.open('rb') as f:
        while chunk:=f.read(1048576):h.update(chunk);md5.update(chunk)
    if ref.get('sha256') and h.hexdigest()!=ref['sha256']:raise ValueError('public archive SHA mismatch')
    if ref.get('md5') and md5.hexdigest()!=ref['md5']:raise ValueError('public archive MD5 mismatch')
    return {'part':j,'id':ident,'url':url,'sha256':h.hexdigest(),'md5':md5.hexdigest(),'provider_hashes':ref,'size':target.stat().st_size}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as pool:rows=list(pool.map(get,[(i,k,a.out) for i,k in enumerate(('agvxh','uv3mw','ehmw2'))]))
    (a.out/'SOURCES.json').write_text(json.dumps(rows,indent=1)+'\n');print([(r['part'],r['size']) for r in rows])
