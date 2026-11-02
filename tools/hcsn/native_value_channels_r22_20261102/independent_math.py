"""Separate Volterra/Laplace mathematical audit of financial value channels.

No candidate, verifier, or reference imports.  The boundary uses an unbounded
Laplace/Mills-ratio integral, adaptive tanh-sinh quadrature, and complex steps.
The complete output law is differentiated as a whole, without hand-coded array
derivatives.  Formal indices are fixed here before their points are opened.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time

import mpmath as mp


PARAMETERS = ("r", "delta", "alpha", "tax", "coupon", "principal", "sigma",
              "liquidity", "maturity")
FORMAL_INDICES = (0, 46, 95, 142, 189, 194)
OLD_POINTS = (
    (.08,.02,.6,.27,6.39,61.68,.3,.02,1.3,.01),
    (.08,.02,.6,.27,6.39,61.68,.3,.02,1.3,.2),
)

VALUE_ATOL, VALUE_RTOL = 2e-9, 2e-11
JACOBIAN_ATOL, JACOBIAN_RTOL = 2e-8, 2e-10
HIGH_PRECISION_CONSISTENCY = mp.mpf("1e-40")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def b_laplace(z, scale, y):
    """B = s phi(ys) integral u exp(-u²/2-zsu) exprel((z+y)su) du.

    This follows by representing both Gaussian probabilities with the Mills
    integral, subtracting the two exponentials analytically, then using exprel.
    It needs neither normal probabilities nor a divided difference of them.
    """
    def integrand(u):
        w = (z + y) * scale * u
        exprel = mp.expm1(w) / w if w else mp.mpf(1)
        return u * mp.exp(-u*u/2 - z*scale*u) * exprel

    integral = mp.quad(integrand, [0, 1, 2, 4, 8, mp.inf], method="tanh-sinh")
    return scale * mp.exp(-(y*scale)**2/2) * integral / mp.sqrt(2*mp.pi)


def independent_boundary(theta):
    r, delta, alpha, tax, coupon, principal, sigma, liquidity, maturity = theta
    variance = sigma**2
    total_rate = r + liquidity
    drift_ratio = (r - delta) / variance - mp.mpf(1)/2
    root = mp.sqrt(drift_ratio**2 + 2*r/variance)
    liquid_root = mp.sqrt(drift_ratio**2 + 2*total_rate/variance)
    eta, gamma = root - drift_ratio, root + drift_ratio
    scale = sigma * mp.sqrt(maturity)
    coupon_rate = coupon / maturity
    debt_rate = principal / maturity - coupon_rate / total_rate
    discount = mp.exp(-total_rate*maturity)
    after_tax_cost = (1-tax)*coupon + (1-discount)*debt_rate
    liquid_B = sum(b_laplace(root, scale, sign*liquid_root) for sign in (-1, 1))
    drift_B = sum(b_laplace(root, scale, sign*drift_ratio) for sign in (-1, 1))
    numerator = (after_tax_cost/eta + debt_rate*discount*drift_B
                 + coupon_rate/total_rate*liquid_B)
    denominator = variance*(gamma+1)/2 + alpha/maturity*liquid_B
    return numerator / denominator



def independent_law(point):
    parameters,x=point[:9],point[9]
    r,delta,alpha,tax,coupon,principal,sigma,liquidity,maturity=parameters
    b=independent_boundary(parameters)
    variance=sigma*sigma;rate=r+liquidity;a=(r-delta)/variance-mp.mpf(1)/2
    z=mp.sqrt(a*a+2*r/variance);zt=mp.sqrt(a*a+2*rate/variance)
    eta,gamma=z-a,z+a;s=sigma*mp.sqrt(maturity);c=coupon/maturity
    q=principal/maturity-c/rate;discount=mp.exp(-rate*maturity)
    normal=lambda v:mp.erfc(-v/mp.sqrt(2))/2
    def risk(u):
        f=normal(-u/s-a*s)+mp.exp(-2*a*u)*normal(-u/s+a*s)
        g=mp.exp((-a+zt)*u)*normal(-u/s-zt*s)+mp.exp((-a-zt)*u)*normal(-u/s+zt*s)
        return f,g
    def debt(u):
        f,g=risk(u)
        return c/rate+discount*q*(1-f)+(alpha*b/maturity-c/rate)*g
    def integrand(t):
        u=x*t;distance=x-u
        kernel=mp.exp(-gamma*distance)*mp.expm1(2*z*distance)
        flow=delta*b*mp.exp(u)-(1-tax)*coupon+debt(u)-principal/maturity
        return kernel*flow
    equity=-x/(z*variance)*mp.quad(integrand,[0,mp.mpf('.5'),1],method='tanh-sinh')
    f,g=risk(x)
    return [b,equity,f,g,debt(x)]


def computed(point,dps,step):
    with mp.workdps(dps):
        theta=list(map(mp.mpf,map(float,point)));values=independent_law(theta);columns=[]
        for j in range(10):
            perturbed=theta.copy();perturbed[j]+=mp.j*mp.mpf(step)
            columns.append([mp.im(v)/mp.mpf(step) for v in independent_law(perturbed)])
        jacobian=[[columns[j][k] for j in range(10)] for k in range(5)]
        return values,jacobian


def compare(native,gold,atol,rtol):
    if len(native)!=len(gold) or not all(mp.isfinite(v) for v in list(native)+list(gold)):
        raise ValueError('Shape/nonfinite mathematical reference')
    return dict(maximum_normalized_error=float(max(abs(mp.mpf(a)-b)/(atol+rtol*abs(b)) for a,b in zip(native,gold))),
                maximum_absolute_error=float(max(abs(mp.mpf(a)-b) for a,b in zip(native,gold))))


def density_check(point):
    with mp.workdps(70):
        p=list(map(mp.mpf,map(float,point)));r,delta,_,_,_,_,sigma,liquidity,m=p[:9];x=p[9]
        drift=r-delta-sigma*sigma/2;R=r+liquidity;s=sigma*mp.sqrt(m);a=drift/(sigma*sigma);zt=mp.sqrt(a*a+2*R/(sigma*sigma))
        normal=lambda v:mp.erfc(-v/mp.sqrt(2))/2
        exactf=normal(-x/s-a*s)+mp.exp(-2*a*x)*normal(-x/s+a*s)
        exactg=mp.exp((-a+zt)*x)*normal(-x/s-zt*s)+mp.exp((-a-zt)*x)*normal(-x/s+zt*s)
        def density(u,discounted):
            if u==0:return mp.mpf(0)
            t=m*u*u
            hit=x/(sigma*mp.sqrt(2*mp.pi*t**3))*mp.exp(-(x+drift*t)**2/(2*sigma*sigma*t))
            return 2*m*u*hit*(mp.exp(-R*t) if discounted else 1)
        f=mp.quad(lambda u:density(u,False),[0,.001,.01,.1,.5,1]);g=mp.quad(lambda u:density(u,True),[0,.001,.01,.1,.5,1])
        err=max(abs(f-exactf),abs(g-exactg))
        return dict(point=list(map(float,p)),F_absolute_error=mp.nstr(abs(f-exactf),30),G_absolute_error=mp.nstr(abs(g-exactg),30),passed=bool(err<mp.mpf('1e-40')))


def main():
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True);group.add_argument('--binary',type=Path);group.add_argument('--raw',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    start=time.monotonic();cpu=time.process_time();child=resource.getrusage(resource.RUSAGE_CHILDREN);here=Path(__file__).resolve().parent
    if args.raw:
        protocol=json.loads((here/'PROTOCOL.json').read_text());publication=json.loads((here/'PUBLICATION.json').read_text());summary=json.loads((args.raw/'SUMMARY.json').read_text())
        identities={n:sha256(here/n) for n in protocol['sources']}
        if (not publication['readback_verified'] or identities!=publication['source_sha256'] or identities!=summary['source_sha256'] or identities.get('independent_math.py')!=sha256(Path(__file__).resolve()) or protocol['independent_math_selected_indices']!=list(FORMAL_INDICES) or not summary['passed'] or summary['cases']!=195 or summary['namespace']!=protocol['confirmation_namespace']):raise ValueError('Unfrozen mathematical audit')
        raw=gzip.decompress((args.raw/'RAW.json.gz').read_bytes())
        if hashlib.sha256(raw).hexdigest()!=summary['raw_sha256']:raise ValueError('Raw identity mismatch')
        payload=json.loads(raw);selected=[payload['rows'][i] for i in FORMAL_INDICES]
        if any(row['index']!=i for row,i in zip(selected,FORMAL_INDICES)):raise ValueError('Raw index mismatch')
        rows=[(row['index'],row['point'],row['native'],row['reference']) for row in selected]
        provenance=dict(mode='formal_selected_raw',raw_sha256=summary['raw_sha256'],source_sha256=identities)
    else:
        c=subprocess.run([str(args.binary.resolve())],input=''.join(' '.join(map(repr,p))+'\n' for p in OLD_POINTS),text=True,capture_output=True,check=True)
        native=list(map(json.loads,c.stdout.splitlines()));rows=[(i,list(p),n,None) for i,(p,n) in enumerate(zip(OLD_POINTS,native))]
        if len(native)!=len(OLD_POINTS):raise ValueError('Old batch count')
        provenance=dict(mode='old_baseline_only',binary_sha256=sha256(args.binary))
    records=[]
    for index,point,native,reference in rows:
        old,oldjac=computed(point,80,'1e-25');values,jac=computed(point,90,'1e-35')
        with mp.workdps(90):
            consistency=max([abs(a-b)/(1+abs(b)) for a,b in zip(old,values)]+[abs(a-b)/(1+abs(b)) for ar,br in zip(oldjac,jac) for a,b in zip(ar,br)])
            vm=compare(native['values'],values,VALUE_ATOL,VALUE_RTOL);jm=[compare(a,b,JACOBIAN_ATOL,JACOBIAN_RTOL) for a,b in zip(native['jacobian'],jac)]
            row=dict(index=index,point=point,native_values=vm,native_jacobians=jm,precision_consistency=mp.nstr(consistency,30),values_decimal=list(map(str,values)),jacobian_decimal=[list(map(str,r)) for r in jac])
            passed=vm['maximum_normalized_error']<=1 and all(r['maximum_normalized_error']<=1 for r in jm) and consistency<mp.mpf('1e-40')
            if reference:
                row['primary_values']=compare(reference['values'],values,VALUE_ATOL,VALUE_RTOL);row['primary_jacobians']=[compare(a,b,JACOBIAN_ATOL,JACOBIAN_RTOL) for a,b in zip(reference['jacobian'],jac)]
                passed &= row['primary_values']['maximum_normalized_error']<=1 and all(r['maximum_normalized_error']<=1 for r in row['primary_jacobians'])
            row['passed']=bool(passed);records.append(row);print(json.dumps(dict(index=index,passed=row['passed'])),flush=True)
    density=[density_check(list(p)) for p in OLD_POINTS]
    end=resource.getrusage(resource.RUSAGE_CHILDREN)
    report=dict(passed=all(r['passed'] for r in records) and all(r['passed'] for r in density),cases=records,first_passage_density=density,provenance=provenance,script_sha256=sha256(Path(__file__).resolve()),selected_indices=list(FORMAL_INDICES),body_cpu_seconds=time.process_time()-cpu,child_cpu_seconds=end.ru_utime+end.ru_stime-child.ru_utime-child.ru_stime,body_wall_seconds=time.monotonic()-start,scope='Separate Volterra/Laplace/complex-step numerical path at fixed selected points, not a uniform error proof or blind human review. Full external meter supersedes inner timing.')
    with args.output.open('x') as stream:json.dump(report,stream,sort_keys=True,indent=2);stream.write('\n')
    print(json.dumps(dict(passed=report['passed'],cases=len(records))),flush=True);raise SystemExit(not report['passed'])


if __name__=='__main__':main()
