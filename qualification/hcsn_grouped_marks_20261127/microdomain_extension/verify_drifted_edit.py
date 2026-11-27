import argparse,json,math,sys
from pathlib import Path
import numpy as np
import torch
from microdomain import IndependentFirstHit
from drifted_edit import invert_drifted_probability


def main():
    cli=argparse.ArgumentParser();cli.add_argument('out',type=Path);cli.add_argument('--reference-dir',type=Path,default=Path(__file__).resolve().parent.parent);args=cli.parse_args()
    sys.path.insert(0,str(args.reference_dir));from parent_cell import Published
    source=Published();v=source.B0*math.exp(.18);p=source.p.P0;alpha=source.bc*source.p.C;beta=source.bp;fraction=.28
    rows=[]
    for mu in (source.mu,-source.mu,0.):
        for copies in (1,2,4,8):
            law=IndependentFirstHit(copies,mu,source.p.sigma,.25,.30);errors=[];drives=[];iterations=[]
            def prob(a):
                b=alpha+beta*p*(1+fraction*math.tanh(a));return law(torch.tensor(math.log(v/b),dtype=torch.float64)).release.item()
            for a in np.linspace(-1.3,.4,31):
                q=prob(a);r=invert_drifted_probability(q,v,p,alpha,beta,fraction,law,tolerance=1e-12)
                errors.append(abs(prob(r.local.preactivation)-q));iterations.append(r.iterations);drives.append(abs(r.local.preactivation-a))
            rows.append({'drift':mu,'copies':copies,'targets':len(errors),'max_probability_error':max(errors),'max_drive_error':max(drives),'max_iterations':max(iterations),'median_iterations':float(np.median(iterations))})
    assert max(r['max_probability_error'] for r in rows)<=1.001e-12
    try:invert_drifted_probability(.99,v*10,p,alpha,beta,fraction,law)
    except ValueError as e:rejected=str(e)
    else:raise AssertionError('unreachable target accepted')
    rec={'registered_source_drift':source.mu,'float':'64-bit','checks':rows,'total_targets':sum(r['targets'] for r in rows),'unreachable':rejected};args.out.write_text(json.dumps(rec,sort_keys=True,indent=2)+'\n');print(rec['total_targets'],max(r['max_probability_error'] for r in rows),[(r['copies'],r['max_iterations']) for r in rows[:4]])


if __name__=='__main__':main()
