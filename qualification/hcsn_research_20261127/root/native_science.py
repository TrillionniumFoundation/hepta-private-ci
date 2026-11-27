"""Verify all raw inputs, load pinned code, then train complete independent panels."""
import argparse,hashlib,io,json,os,subprocess,sys,time,zipfile
from pathlib import Path
from urllib.request import Request,urlopen
BASE='https://raw.githubusercontent.com/TrillionniumFoundation/hepta-private-ci/'
def main():
    p=argparse.ArgumentParser()
    p.add_argument('kind',choices=['raw','literal'])
    p.add_argument('--root',type=Path,required=True);p.add_argument('--ref',required=True);p.add_argument('--workers',type=int,default=4)
    a=p.parse_args();root=a.root.resolve()
    # Each campaign works in its own source area. The transferred immutable bundle is verified independently.
    work=root/(a.kind+'-campaign')
    work.mkdir(exist_ok=True)
    for _ in range(300):
        if (root/'raw-transfer.json').is_file():break
        time.sleep(2)
    info=json.loads((root/'raw-transfer.json').read_bytes())
    data=b''.join((root/n).read_bytes() for n in info['parts'])
    assert len(data)==info['size'] and hashlib.sha256(data).hexdigest()==info['sha256']
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in z.namelist():
            if n.startswith('/') or '..' in Path(n).parts:raise ValueError('archive path')
        z.extractall(work)
    proj='qualification/hcsn_research_20261127/'
    sources=['root/bridge.py','root/raw_train.py','root/run_science.py','root/summarize_bridge.py','root/RAW_PROTOCOL.md','literal/cell.py','literal/study.py','literal/PROTOCOL.md','literal/SOURCE_EXT.md']
    for f in sources:
        path=work/(f.split('/',1)[1] if f.startswith('root/') else f)
        for attempt in range(4):
            try:
                req=Request(BASE+a.ref+'/'+proj+f,headers={'User-Agent':'Hepta study'})
                with urlopen(req,timeout=60) as stream:path.write_bytes(stream.read())
                break
            except OSError:
                if attempt==3:raise
                time.sleep(2)
    # The sibling pinned source bootstrap validates all historical physics file hashes.
    assert (root/'physics/qualification/hcsn_closure_20261124/boundary_fix.py').is_file()
    env={**os.environ,'PYTHONPATH':str(root/'physics'),'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'}
    for n in ([192,1536] if a.kind=='raw' else [128]):
        sub=subprocess.run([sys.executable,'-u',str(work/'run_science.py'),a.kind,'--steps',str(n),'--workers',str(a.workers),'--out',str(work/f'results_{n}')],cwd=work,env=env)
        if sub.returncode:raise RuntimeError('nonzero campaign '+str(n))
if __name__=='__main__':main()
