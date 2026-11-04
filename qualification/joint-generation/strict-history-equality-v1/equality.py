"""Canonical equality on parsed finite JSON only; no hash or freshness shortcut."""
import math,json

def canonical_equal(a,b):
    return json.dumps(a,sort_keys=True,separators=(',',':'),allow_nan=False)==json.dumps(b,sort_keys=True,separators=(',',':'),allow_nan=False)

def equal(a,b):
    try:return _equal(a,b)
    except RecursionError:return canonical_equal(a,b)

def _equal(a,b):
    t=type(a)
    if t is not type(b):return False
    if t is dict:
        if any(type(k)is not str for k in a) or any(type(k)is not str for k in b):raise ValueError('JSON keys')
        if a.keys()!=b.keys():return canonical_equal(a,b)
        return all(_equal(v,b[k]) for k,v in a.items())
    if t is list:return len(a)==len(b) and all(_equal(x,y) for x,y in zip(a,b))
    if t is float:
        if not math.isfinite(a) or not math.isfinite(b):raise ValueError('finite JSON')
        return a==b and (a!=0 or math.copysign(1,a)==math.copysign(1,b))
    if t is str:return a==b or canonical_equal(a,b)
    if t in (int,bool) or a is None:return a==b
    raise ValueError('parsed JSON domain')
