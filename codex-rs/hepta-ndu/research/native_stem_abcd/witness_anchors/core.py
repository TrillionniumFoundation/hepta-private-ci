"""R25 rational candidate repair and frozen residual-anchor global lower."""
from __future__ import annotations
from fractions import Fraction as F
import hashlib,csv
from functools import lru_cache
from pathlib import Path
import numpy as np
import eliminate as e
old=e.old
ARCHIVE_SHA='75b7f84db4fa749c48b502c4ff1fe23af02e8b7fa5fd045f99c487e80c1f1d99'
INDEX_SHA='cb548fed6aa074b8494cc47d4860d6f18ba82c40810f4279429d8936559148c5'
WITNESS_INFO={
 3:('w3-s6-bfgs','-0x1.5f9cdbe52ec1ap-1|-0x1.1c8e673797689p+0|-0x1.575748e5d4b19p-1','3b93b227b433cd15a8c622a3eed07886dbff3b009aac8667cabf2e4fe987f5c9'),
 4:('w4-s2-bfgs','-0x1.66683e0169ed7p-1|-0x1.048e59aa2dde9p+0|-0x1.66cefff0ca02cp-1|0x1.3ad9bd112edafp-2','1fe54d7dc88fd92f3dcd86a9f8784481b5584fc183f3e2fe58e8f11cbb8fa47e')}
TRIALS=(('w3_repair',3,'historic_witness','r24_hybrid'),
        ('w4_anchor',4,'original','fixed_anchors'),
        ('w4_witness_anchor',4,'historic_witness','fixed_anchors'))
CAP=4000
THRESHOLD=F(1,100)

def sha(path):
    with open(path,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def verify_provenance(archive,index,witness_input):
    if sha(archive)!=ARCHIVE_SHA:raise ValueError('original archive mismatch')
    if sha(index)!=INDEX_SHA:raise ValueError('original hex index mismatch')
    with open(witness_input,newline='') as stream:
        rows=list(csv.DictReader(stream))
    if len(rows)!=3:raise ValueError('incomplete fixed witness census')
    result={}
    for r in rows:
        n=int(r['width'])
        if n in (3,4):
            name,hexstr,expected=WITNESS_INFO[n]
            if (r['name'],r['binary64_hex_vector'],r['tensor_sha256'])!=(name,hexstr,expected):
                raise ValueError('unexpected frozen witness identity')
            vector=np.asarray([float.fromhex(x) for x in hexstr.split('|')],dtype='<f8')
            if len(vector)!=n or hashlib.sha256(vector.tobytes()).hexdigest()!=expected:
                raise ValueError('forged weight bytes')
            result[n]=tuple(F.from_float(float(v)) for v in vector)
    if set(result)!={3,4}:raise ValueError('missing witnesses')
    return result

def nearest_eighth(x):
    v=F(x)*8
    k=v.numerator//v.denominator
    lower=F(k);upper=F(k+1)
    if v-lower<upper-v:return F(k,8)
    if v-lower>upper-v:return F(k+1,8)
    return F(k if abs(k)<abs(k+1) else k+1,8)

@lru_cache(maxsize=1)
def anchor_details():
    point=tuple((F(v),F(v)) for v in old.CANDIDATES[4])
    ans=[]
    for x in (-1,1):
        low,hi=e.residual_interval(point,x)
        if low!=hi:raise ArithmeticError('original candidate point not a point')
        ans.append((x,low,nearest_eighth(low)))
    return tuple(ans)

@lru_cache(maxsize=100000)
def anchor_scalar_lower(lo,hi,p0):
    if lo>hi:raise ValueError('reversed scalar interval')
    best=e.scalar_box_lower(lo,hi,p0)
    for _,_,z0 in anchor_details():
        value,grad=e.scalar_F(z0,p0)
        dl=lo-z0;dh=hi-z0
        lower=value.lo+min(e.quadratic_min(dl,dh,grad.lo),e.quadratic_min(dl,dh,grad.hi))
        if lower>best:best=lower
    return best

def anchored_lower(box):
    base=e.hybrid_lower(box)
    total=F(0)
    for x in (-1,1):
        rl,rh=e.residual_interval(box,x)
        for p0 in (0,1):total+=anchor_scalar_lower(rl,rh,p0)/4
    reg=sum((old.square(coord)[0] for coord in box),F(0))/4
    return max(base,total+reg)

def candidate_vector(width,kind,witnesses):
    if kind=='original':return tuple(F(s) for s in old.CANDIDATES[width])
    if kind=='historic_witness':return witnesses[width]
    raise ValueError('unknown candidate')

def interval(box):return tuple((x,x) for x in box)
