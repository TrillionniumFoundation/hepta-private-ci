import argparse
import json
from pathlib import Path
import numpy as np
from model import Cell,gradient,parent,predict,prep,sha


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('law',type=Path);ap.add_argument('out',type=Path);a=ap.parse_args()
    rng=np.random.default_rng(70123);x=rng.normal(size=(96,128));law=Cell(a.law)
    p=parent(x,2021,law);t=prep(x[:9],p);y=np.eye(6)[rng.integers(0,6,len(t))]
    gradients=gradient(t,y,p,law);rows={}
    for name,g in zip(('w1','w2','w3'),gradients):
        w=p[name];checks=[]
        for _ in range(12):
            d=rng.normal(size=w.shape);d/=np.linalg.norm(d)
            h=2.e-7
            p[name]=w+h*d;l1=float(np.mean((predict(t,p,law)-y)**2))
            p[name]=w-h*d;l0=float(np.mean((predict(t,p,law)-y)**2))
            p[name]=w
            obs=(l1-l0)/(2*h);exact=float((g*d).sum());checks.append([exact,obs,abs(exact-obs)])
        rows[name]=checks
        assert max(r[2] for r in checks)<3e-5,checks
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps({'seed':70123,'law_sha256':sha(a.law),'directions':rows},indent=2))
