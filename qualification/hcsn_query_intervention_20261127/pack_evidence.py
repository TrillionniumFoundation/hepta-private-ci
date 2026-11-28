"""Pack original compressed evidence files from one run into size-bounded ordinary ZIP files."""
import argparse
from pathlib import Path
import json
import hashlib
from zipfile import ZipFile,ZIP_DEFLATED

def run(source,out,limit):
    out.mkdir(parents=True,exist_ok=True)
    paths=sorted(p for p in source.iterdir() if p.is_file() and p.suffix in ('.npz','.json'))
    pending=[];n=0;parts=[]
    def write(members):
        path=out/f'part{len(parts):03d}.zip'
        with ZipFile(path,'w',compression=ZIP_DEFLATED,compresslevel=5) as f:
            for p in members:f.write(p,p.name)
        with ZipFile(path) as f:
            if f.testzip() is not None:raise ValueError('CRC mismatch')
            for p in members:
                if f.read(p.name)!=p.read_bytes():raise ValueError('archive mismatch')
        parts.append(dict(file=path.name,bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                          members=[p.name for p in members]))
    for path in paths:
        sz=path.stat().st_size
        if n+sz>limit and pending:
            write(pending);pending=[];n=0
        pending.append(path);n+=sz
    if pending:write(pending)
    (out/'manifest.json').write_text(json.dumps(parts,indent=1)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('out',type=Path);p.add_argument('--limit',type=int,default=245760)
    a=p.parse_args();run(a.source,a.out,a.limit)
