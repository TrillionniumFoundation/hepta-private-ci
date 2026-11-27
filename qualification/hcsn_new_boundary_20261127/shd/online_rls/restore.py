"""Restore SHA-verified under-root payloads from the small ordinary ZIP bundles."""
from pathlib import Path
import hashlib,io,json,sys,zipfile
def digest(x):return hashlib.sha256(x).hexdigest()
def main(root):
    m=json.loads((root/'bundle.json').read_text());pieces={}
    for name,sha in m['archives'].items():
        raw=(root/name).read_bytes();assert digest(raw)==sha,name
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            for f in z.namelist():pieces[f]=z.read(f)
    for rel,desc in m['files'].items():
        p=Path(rel);assert not p.is_absolute() and '..' not in p.parts
        dest=root/p;raw=b''.join(pieces[k] for k in desc['chunks'])
        assert digest(raw)==desc['sha256'] and len(raw)==desc['bytes'],rel
        if dest.exists():assert dest.read_bytes()==raw,rel
        else:dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
    print(len(m['files']),'logical payloads restored and verified')
if __name__=='__main__':main(Path(sys.argv[1] if len(sys.argv)>1 else '.'))
