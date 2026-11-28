"""Acquire authors' RSITMD source archive and confirm caption roster against versioned AMFMN."""
import argparse,hashlib,json,os,subprocess,time
from pathlib import Path
import urllib.request
from zipfile import ZipFile

AUTH='https://drive.usercontent.google.com/download?id=1NJY86TAAUd8BVs7hyteImv8I2_Lh95W6&export=download&confirm=t&study=hepta8559'
REPO='https://github.com/xiaoyuan1996/AMFMN.git'


def run(out):
    out.mkdir(parents=True,exist_ok=True)
    rev=subprocess.check_output(['git','ls-remote',REPO,'refs/heads/master'],text=True,timeout=50).split()[0]
    base='https://raw.githubusercontent.com/xiaoyuan1996/AMFMN/'+rev+'/AMFMN/data/rsitmd_precomp/'
    files={'test_filename.txt':base+'test_filename.txt','test_caps.txt':base+'test_caps.txt','original.zip':AUTH}
    meta={}
    for n,url in files.items():
        t=time.perf_counter();path=out/n
        for i in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'HCSN lab dataset verification'}),timeout=80) as src,path.with_suffix('.partial').open('wb') as f:
                    h=hashlib.sha256()
                    while payload:=src.read(1<<20):h.update(payload);f.write(payload)
                    headers={k:src.headers.get(k) for k in ('ETag','Content-Length','Content-Type','Last-Modified')}
                os.replace(path.with_suffix('.partial'),path)
                if n=='original.zip':
                    with ZipFile(path) as z:assert len(z.infolist())>4000 and any('dataset_rsitmd.json' in v.filename.lower() for v in z.infolist())
                meta[n]={'bytes':path.stat().st_size,'sha256':h.hexdigest(),'headers':headers,'wall_s':time.perf_counter()-t};print(n,meta[n],flush=True);break
            except Exception as e:
                print('retry',n,i,type(e).__name__,str(e)[:95],flush=True)
                if i==2:raise
                time.sleep(2*(i+1))
    (out/'public_source.json').write_text(json.dumps({'author_repo':REPO,'author_rev':rev,'author_google_drive_id':'1NJY86TAAUd8BVs7hyteImv8I2_Lh95W6','assets':meta},indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);run(p.parse_args().out)
