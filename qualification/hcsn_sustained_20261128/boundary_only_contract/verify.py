"""Generate all four input boundaries with the existing independent quadrature."""
import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys
import numpy as np

from boundary_only import from_boundaries
from contract_inverse import Probe, Surface


def quotes(solution, p, m, scales, margins):
    result=[]
    for t in m:
        rows=[]
        for s in scales:
            q=p.copy()
            q[6]*=s
            q[7]=t
            rows.append(solution(q,np.asarray(margins)))
        result.append(rows)
    return np.array(result)


def main(reference):
    sys.path.insert(0,str(reference.parent))
    from reference import solution
    import hx_reference
    data=json.loads(reference.with_name("reference.json").read_text())
    rows=[]
    cross=[]
    matrix_check=[]
    for cid,record in enumerate(data["cases"]):
        p=np.array(record["contract"])
        surf=Surface(*p[[0,1,2,7,8]])
        truth=p[[5,6,4,3]]
        for mratio,samp in (((.5,2.),.28),((.8,1.2),.16),((.95,1.05),.08)):
            ms=np.array(mratio)*surf.maturity
            ss=np.array([1-samp,1+samp])
            b=quotes(solution,p,ms,ss,[.16])[:,:,0,0]
            est=from_boundaries(surf,ms,ss,b)
            # Independent linear solve using uneliminated matching equations.
            matrix=[]
            rhs=[]
            for i,m in enumerate(ms):
                k=Probe.at(replace(surf,maturity=m),0.)
                for j,s in enumerate(ss):
                    matrix.append([k.a*s/m, -b[i,j]*k.g/m, (k.g-k.a)/m, 1/k.eta])
                    rhs.append(b[i,j]*k.d0)
            par,alpha,y,h=np.linalg.solve(matrix,rhs)
            money=k.q*y
            alt=np.array([money,par,alpha,1-h/money])
            matrix_check.append(np.max(abs(est-alt)/truth))
            written=p.copy()
            written[[5,6,4,3]]=est
            val_ms=np.array([.66,1.,1.5])*surf.maturity
            sc=[.79,1.,1.18]
            xs=[.035,.2,.36,.61]
            external=quotes(solution,written,val_ms,sc,xs)-quotes(solution,p,val_ms,sc,xs)
            cross.append(np.max(abs(external),axis=(0,1,2)))
            rows.append(dict(case=cid,maturity=ms.tolist(),scales=ss.tolist(),four_boundaries=b.tolist(),
                             recovered=est.tolist(),relative_error=float(np.max(abs(est/truth-1)))))
    p=np.array(data["cases"][0]["contract"])
    surf=Surface(*p[[0,1,2,7,8]])
    truth=p[[5,6,4,3]]
    rng=np.random.default_rng(85391)
    noise=[]
    for ms in ((.5,2.),(.8,1.2),(.95,1.05)):
        for amp in (.28,.04):
            ss=np.array([1-amp,1+amp])
            b=quotes(solution,p,ms,ss,[.16])[:,:,0,0]
            for scale in (1e-5,.002):
                errors=[]; inadmissible=0; failed=0
                for _ in range(1000):
                    try:
                        z=from_boundaries(surf,ms,ss,b*(1+rng.normal(0,scale,(2,2))))
                    except (ValueError,ArithmeticError):
                        failed+=1
                        continue
                    errors.append(np.max(abs(z/truth-1)))
                    inadmissible+=int(z[0]<=0 or not 0<=z[2]<=1 or not 0<=z[3]<=1)
                noise.append(dict(maturities=ms,principal_half_range=amp,relative_noise_sd=scale,
                       failed=failed,inadmissible_of_returned=inadmissible,
                       median_error_among_returned=np.median(errors),p95_error_among_returned=np.quantile(errors,.95)))
    e=max(k["relative_error"] for k in rows)
    ex=np.max(cross,axis=0)
    if e>1e-8 or max(ex)>1e-6 or max(matrix_check)>1e-8:
        raise RuntimeError((e,ex,max(matrix_check)))
    return dict(cases=12,inversions=len(rows),true_noise_free_max_relative_parameter_error=e,
                independent_matrix_max_relative_difference=max(matrix_check),cross_maturity_replay_max_abs=ex.tolist(),
                cross_maturity_relative=[.66,1.,1.5],cross_scales=[.79,1.,1.18],
                cross_log_margins=[.035,.2,.36,.61],channel_order=["B","E","credit_loss","F","G"],
                parameter_order=["C","P","recovery","tax"],noise=noise,cases_and_recovery=rows,
                reference_sha256=sha256(reference.read_bytes()).hexdigest(),
                first_passage_reference_sha256=sha256(Path(hx_reference.__file__).read_bytes()).hexdigest())


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("reference",type=Path)
    ap.add_argument("output",type=Path)
    args=ap.parse_args()
    result=main(args.reference)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps({k:result[k] for k in ("true_noise_free_max_relative_parameter_error","cross_maturity_replay_max_abs","noise")},indent=2))
