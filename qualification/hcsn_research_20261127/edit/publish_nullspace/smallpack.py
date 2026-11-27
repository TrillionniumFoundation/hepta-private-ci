"""Losslessly split any large file into size-bounded ZIP members and restore it by digest."""
import argparse,hashlib,json,zipfile
from pathlib import Path
MAX_PIECE=300_000
MAX_PAYLOAD=390_000
def digest(b):return hashlib.sha256(b).hexdigest()
def file_digest(p):
    with p.open('rb') as fp:return hashlib.file_digest(fp,'sha256').hexdigest()
def pack(named,dest):
    dest.mkdir(parents=True,exist_ok=True);archives=[];entries={};group=[];used=0
    def flush():
        nonlocal group,used
        if not group:return
        p=dest/f'evidence-{len(archives):03d}.zip'
        with zipfile.ZipFile(p,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for item,raw in group:
                info=zipfile.ZipInfo(item,(1980,1,1,0,0,0));z.writestr(info,raw,compress_type=zipfile.ZIP_DEFLATED,compresslevel=6)
        assert p.stat().st_size<512_000
        with zipfile.ZipFile(p) as z:assert z.testzip() is None
        archives.append(dict(file=p.name,size=p.stat().st_size,sha256=file_digest(p)));group=[];used=0
    for path,source in sorted(named.items()):
        assert not Path(path).is_absolute() and '..' not in Path(path).parts
        record={'size':source.stat().st_size,'sha256':file_digest(source),'parts':[]}
        with source.open('rb') as f:
            i=0
            while True:
                data=f.read(MAX_PIECE)
                if not data:break
                if used+len(data)>MAX_PAYLOAD:flush()
                item=f'part/{len(entries):05d}-{i:04d}'
                record['parts'].append([len(archives),item,digest(data)]);group.append((item,data));used+=len(data);i+=1
        entries[path]=record
    flush()
    idx={'files':entries,'archives':archives,'schema':'independently-verifiable-zip-pieces/v1'}
    (dest/'evidence-index.json').write_text(json.dumps(idx,sort_keys=True,separators=(',',':'))+'\n')
    return idx
def restore(src,dest=None):
    idx=json.loads((src/'evidence-index.json').read_text());files={}
    for i,z in enumerate(idx['archives']):
        p=src/z['file'];assert file_digest(p)==z['sha256']
        with zipfile.ZipFile(p) as f:
            for n in f.namelist():files[(i,n)]=f.read(n)
    for name,r in idx['files'].items():
        calc=hashlib.sha256();n=0;out=None
        if dest is not None:
            path=dest/name;assert path.resolve().is_relative_to(dest.resolve());path.parent.mkdir(parents=True,exist_ok=True);out=path.open('wb')
        try:
            for zi,entry,sha in r['parts']:
                blob=files[(zi,entry)];assert digest(blob)==sha;calc.update(blob);n+=len(blob)
                if out is not None:out.write(blob)
        finally:
            if out is not None:out.close()
        assert n==r['size'] and calc.hexdigest()==r['sha256']
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('source',type=Path);ap.add_argument('--dest',type=Path)
    args=ap.parse_args();restore(args.source,args.dest)
