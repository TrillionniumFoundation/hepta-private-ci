"""Independent 80-digit checks of the explicitly compensated FP32 primitives."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import float32_pair as fp


def run(output, oracle_path):
    if output.exists():
        raise ValueError('Evidence already exists')
    if oracle_path:
        sys.path.insert(0, str(oracle_path))
    from mpmath import mp
    mp.dps = 80
    cv = lambda x: mp.mpf(float(x.hi)) + mp.mpf(float(x.lo))
    rng = np.random.default_rng(20261101)
    results = []
    for i in range(128):
        parts = []
        for _ in range(2):
            high = np.float32(rng.uniform(-10,10) * 10 ** rng.uniform(-6,6))
            low = np.float32(rng.uniform(-.4,.4)) * np.spacing(high)
            parts.append(fp.Pair(high,low))
        a,b = parts; ar,br = map(cv,parts)
        for name, actual, expected in [('add',a+b,ar+br),('sub',a-b,ar-br),('mul',a*b,ar*br),('div',a/b,ar/br)]:
            error=float(abs(cv(actual)-expected)/max(1,abs(expected)))
            results.append(dict(kind=name,case=i,inputs=[[float(x.hi),float(x.lo)] for x in parts],scaled_error=error))
    functions=[
        ('exp',fp.exp,mp.exp,[-90,-30,-5,-.5,-.01,0,.1,1,10,70]),
        ('expm1',fp.expm1,mp.expm1,[-2,-.1,-1e-7,0,1e-7,.1,1,5]),
        ('log',fp.log,mp.log,[1e-20,1e-8,.1,.9,1,10,1e10]),
        ('sqrt',fp.sqrt,mp.sqrt,[1e-20,1e-8,.1,1,3,1e10]),
        ('cdf',fp.cdf,lambda x:mp.erfc(-x/mp.sqrt(2))/2,[-90,-40,-10,-5,-1.5,-1.41421356237,-1,-.1,0,.1,1,1.41421356237,1.5,5,10,40]),
        ('logcdf',fp.logcdf,lambda x:mp.log(mp.erfc(-x/mp.sqrt(2))/2),[-90,-40,-10,-5,-1.5,-1.41421356237,-1,-.1,0,.1,1,1.41421356237,1.5,5,10,40])]
    for name,fn,oracle,values in functions:
        for i,value in enumerate(values):
            for relative_low in [0.,-.25,.25]:
                hi=np.float32(value);lo=np.float32(relative_low)*np.spacing(hi)
                x=fp.Pair(hi,lo);actual=fn(x);expected=oracle(cv(x))
                error=float(abs(cv(actual)-expected)/max(1,abs(expected)))
                results.append(dict(kind=name,case=i,input=[float(hi),float(lo)],scaled_error=error))
    maxima={name:max(r['scaled_error'] for r in results if r['kind']==name) for name in {r['kind'] for r in results}}
    result=dict(schema='hcsn.compensated-fp32-primitive-development.v1',
        arithmetic='two float32 words, extended significand; not ordinary one-word FP32',
        reference='mpmath 80 decimal digits, exact binary FP32 word inputs',
        seed=20261101,checks=len(results),diagnostic_scaled_gate=5e-12,
        passed=all(v<=5e-12 for v in maxima.values()),maxima=maxima,rows=results,
        source_sha256=hashlib.sha256(Path(fp.__file__).read_bytes()).hexdigest(),
        note='Scaled errors use max(1,abs(reference)); subnormal underflow is not a relative-tail accuracy claim.')
    with output.open('x') as f:json.dump(result,f,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--oracle-pythonpath',type=Path)
    args=p.parse_args();run(args.output,args.oracle_pythonpath)
