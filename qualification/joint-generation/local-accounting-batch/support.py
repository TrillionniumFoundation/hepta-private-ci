"""Bounded immutable metadata only; no numerical imports or scientific authority."""
import hashlib, json, math, os, stat
from pathlib import Path
from decimal import Decimal
ROOT=Path(__file__).resolve().parent
SCHEMA='endpoint-local-segmented-study-v1'
CELLS=tuple((s,a,m) for s in (41011,41023) for a in ('C','E') for m in ('S','A','N'))
MINIMUM=18348
REQUESTS=6116
CAP=Decimal('800')

def canonical(v):return (json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode('ascii')
def sha(b):return hashlib.sha256(b).hexdigest()
def digest(x):
    if type(x) is not str or len(x)!=64 or any(c not in '0123456789abcdef' for c in x):raise ValueError('SHA256')
    return x

def decode(b):
    def unique(pairs):
        d={}
        for k,v in pairs:
            if k in d:raise ValueError('duplicate JSON key')
            d[k]=v
        return d
    return json.loads(b,object_pairs_hook=unique,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))

def read(p,limit=8*2**20):
    p=Path(p)
    if not p.is_absolute() or p.resolve()!=p or p.is_symlink():raise ValueError('canonical no-symlink path')
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        st=os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_size>limit:raise ValueError('bounded regular file')
        b=f.read(limit+1)
    if len(b)>limit:raise ValueError('extent')
    return b

def write(p,v):
    p=Path(p);b=canonical(v)
    with p.open('xb') as f:f.write(b);f.flush();os.fsync(f.fileno())
    if read(p,len(b))!=b:raise ValueError('readback')
    fd=os.open(p.parent,os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    return {'path':str(p),'sha256':sha(b)}

def metadata(r):
    if type(r) is not dict or set(r)!={'path','sha256'}:raise ValueError('exact reference')
    b=read(r['path'])
    if sha(b)!=digest(r['sha256']):raise ValueError('reference changed')
    return decode(b)

def number(x):
    if type(x) not in (int,float,str):raise ValueError('nonboolean CPU number')
    d=Decimal(str(x))
    if not d.is_finite() or d<0:raise ValueError('finite nonnegative CPU')
    return d

def integer(x):
    if type(x) is not int or x<0:raise ValueError('nonboolean nonnegative integer')
    return x

def cell_id(c):
    if type(c) not in (tuple,list) or tuple(c) not in CELLS:raise ValueError('exact twelve-cell inventory')
    return '%d-%s-%s'%tuple(c)

def source_only(event,args):
    if event=='open' and args and isinstance(args[0],(str,bytes)):
        p=os.fsdecode(args[0])
        if p.startswith('/workspace/') and p.endswith('.pyc'):raise FileNotFoundError('source only')

def produced_bytes(roots):
    """Exact current regular-file extent over nonoverlapping owned roots.

    Acceptance/admission measurement, not an OS-enforced aggregate disk quota.
    """
    selected=[]
    for p in sorted({Path(x).absolute() for x in roots},key=lambda x:(len(x.parts),str(x))):
        if p.resolve()!=p or p.is_symlink():raise ValueError('no output alias')
        if not any(p==r or r in p.parents for r in selected):selected.append(p)
    total=0
    for root in selected:
        if not root.exists():continue
        paths=[root] if root.is_file() else root.rglob('*')
        for p in paths:
            if p.is_symlink():raise ValueError('no output symlink')
            if p.is_file():total+=p.stat().st_size
    return total
