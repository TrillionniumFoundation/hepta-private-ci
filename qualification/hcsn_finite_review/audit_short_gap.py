"""Independent continuum finite-gap audit of the exposed original laws.

No new model runs. Nodal hat migration is hypothetical: JointModel.solve
currently rejects its lower-boundary atom. It is not attributed to an executed
JointModel rollout. All continuum references use reflected Brownian first hits.
"""

import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
from numpy.polynomial.legendre import leggauss
from scipy.sparse import bmat, csr_matrix, diags, eye
from scipy.sparse.linalg import expm_multiply
from scipy.special import ndtr


BASE = Path('/workspace/scratch/c06d659c1e72')
INPUT = BASE / 'visited-originals/training-domain-original/run/audit'
OUTPUT = Path(__file__).parent / 'attempt002'
GAPS = (.001, .003, .02, .04, .08, .16)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def continuum(t, x, mu=-.11999999999999998, sigma=.35, q=.15):
    """Independent first-hit F/G and killed discounted active occupation A."""
    t, x = np.broadcast_arrays(np.asarray(t, dtype=float), np.asarray(x, dtype=float))
    safe = np.where(t > 0, t, 1.)
    den = sigma * np.sqrt(safe)
    kappa = math.sqrt(mu * mu + 2 * q * sigma * sigma)
    f = ndtr((-x-mu*safe)/den) + np.exp(-2*mu*x/sigma**2)*ndtr((-x+mu*safe)/den)
    g = (np.exp((-mu+kappa)*x/sigma**2)*ndtr((-x-kappa*safe)/den)
         + np.exp((-mu-kappa)*x/sigma**2)*ndtr((-x+kappa*safe)/den))
    a = -np.expm1(-q*safe)/q - (g-np.exp(-q*safe)*f)/q
    return np.stack([np.where(t > 0, value, 0.) for value in (f,g,a)], axis=-1)


def source_weights(nodes, endpoint=4.8, cells=16, tail_rate=1.):
    """Exact nonnegative hat-weight integrals, including explicit upper escape."""
    weights = np.zeros((cells+1, len(nodes)))
    for k,(left,right) in enumerate(zip(np.linspace(0,endpoint,cells+1)[:-1],
                                        np.linspace(0,endpoint,cells+1)[1:])):
        for i,(a,b) in enumerate(zip(nodes[:-1],nodes[1:])):
            l,r = max(left,a),min(right,b)
            if r > l:
                mass=(r-l)/(right-left)
                weights[k,i] += mass*(b-(l+r)/2)/(b-a)
                weights[k,i+1] += mass*((l+r)/2-a)/(b-a)
    for i,(a,b) in enumerate(zip(nodes[:-1],nodes[1:])):
        l,r=max(endpoint,a),b
        if r > l:
            d=r-l; factor=math.exp(-tail_rate*(l-endpoint))
            zeroth=factor*-math.expm1(-tail_rate*d)
            first=factor*(-math.expm1(-tail_rate*d)/tail_rate-d*math.exp(-tail_rate*d))
            weights[-1,i] += ((b-l)*zeroth-first)/(b-a)
            weights[-1,i+1] += ((l-a)*zeroth+first)/(b-a)
    weights[-1,-1] += math.exp(-tail_rate*(nodes[-1]-endpoint))
    if weights.min() < -1e-13 or np.max(abs(weights.sum(1)-1)) > 1e-13:
        raise ValueError('law migration weights unresolved')
    return weights


class NodalKernels:
    def __init__(self, intervals, endpoint=8., mu=-.11999999999999998, sigma=.35, q=.15):
        self.nodes=np.linspace(0,endpoint,intervals+1); self.q=q
        h=endpoint/intervals; down=sigma*sigma/(2*h*h)-mu/(2*h); up=sigma*sigma/(2*h*h)+mu/(2*h)
        size=intervals+1
        generator=diags([np.full(size-1,down),np.full(size,-down-up),np.full(size-1,up)],[-1,0,1],format='lil')
        generator[0,:]=0;generator[-1,:]=0;generator=generator.tocsr()
        discounted=generator-diags(np.r_[0.,np.full(size-1,q)])
        # F'=Q F, J_F'=F, G'=Q_discounted G. Initial boundary value F0=G0=1.
        self.matrix=bmat([[generator,None,None],[eye(size),csr_matrix((size,size)),None],[None,None,discounted]],format='csr')
        self.initial=np.zeros(3*size);self.initial[0]=self.initial[2*size]=1
        self.cache={};self.weights=source_weights(self.nodes)

    def at(self,t):
        key=round(max(t,0.),14)
        if key not in self.cache:
            f,j,g=np.split(expm_multiply(key*self.matrix,self.initial),3)
            a=-math.expm1(-self.q*key)/self.q-(g-math.exp(-self.q*key)*f)/self.q
            a[0]=0. # Known lower-cemetery reward, not numerical clipping.
            self.cache[key]=(f,g,a,j)
        return self.cache[key]

    def basis(self,t,reset,delay=.2):
        q=self.q; f,g,a,_=self.at(t)
        result=np.zeros((25,3));result[:17]=self.weights @ np.stack([f,g,a],axis=-1)
        edges=np.linspace(0,delay,9)
        for k,(left,right) in enumerate(zip(edges[:-1],edges[1:])):
            if left >= t:continue
            lo,hi=max(0.,t-right),t-left
            fl,gl,_,jl=self.at(lo);fh,gh,_,jh=self.at(hi)
            ig=((math.exp(q*hi)*gh-fh)-(math.exp(q*lo)*gl-fl))/q
            m=(jh-jl)/(right-left)
            hd=math.exp(-q*t)*ig/(right-left)
            i_exp=math.exp(q*lo)*math.expm1(q*(hi-lo))/q
            ad=math.exp(-q*t)*(i_exp-(hi-lo)-ig+jh-jl)/q/(right-left)
            result[17+k]=[np.interp(reset,self.nodes,v) for v in (m,hd,ad)]
        return result


def continuum_basis(t,reset,order=128,delay=.2):
    u,w=leggauss(order);result=np.zeros((25,3));edges=np.linspace(0,4.8,17)
    for k,(left,right) in enumerate(zip(edges[:-1],edges[1:])):
        result[k]=w @ continuum(t,left+(right-left)*(u+1)/2)/2
    # On these short gaps tail hits are negligible, but retain the integral.
    x=4.8+35.2*(u+1)/2
    result[16]=w @ (continuum(t,x)*np.exp(-(x-4.8))[:,None])*35.2/2
    result[16,2] += math.exp(-35.2)*-math.expm1(-.15*t)/.15
    edges=np.linspace(0,delay,9)
    for k,(left,right) in enumerate(zip(edges[:-1],edges[1:])):
        end=min(t,right)
        if end <= left:continue
        release=left+(end-left)*(u+1)/2
        values=continuum(t-release,reset)
        values[:,1:] *= np.exp(-.15*release)[:,None]
        result[17+k]=w@values*(end-left)/(2*(right-left))
    return result


def main():
    started,cpu=time.perf_counter(),time.process_time()
    OUTPUT.mkdir(exist_ok=False)
    original_summary=(INPUT/'SUMMARY.json').read_bytes()
    if sha(original_summary)!='12fa561e6b5e6f710d1239d2a00bcf596da9d0060bf4691473ff337b7b5d0822':raise ValueError('summary identity')
    summary=json.loads(original_summary);visits=[];inputs={}
    for arm in summary['arms']:
        raw=(INPUT/arm['derived_trace_file']).read_bytes()
        if sha(raw)!=arm['derived_trace_sha256']:raise ValueError('trace identity')
        inputs[arm['derived_trace_file']]=sha(raw)
        lines=[json.loads(line) for line in raw.splitlines()]
        if lines[-1]['truncated'] or lines[-1]['retained_records']!=arm['expected_visits']:raise ValueError('coverage')
        visits.extend(lines[1:-1])
    if len(visits)!=14336:raise ValueError('all visits required')
    physics={tuple(v['parameters'][k] for k in ('mu','sigma','discount')) for v in visits}
    if len(physics)!=1:raise ValueError('this fixed-physics probe requires the original single law')
    kernels={n:NodalKernels(n) for n in (128,256,512)};references={};candidate={n:{} for n in kernels};rows=[]
    quadrature_disagreement=0.;old_reference_disagreement=0.
    for v in visits:
        t=v['dt'][0];p=v['parameters'];reset=math.log(p['absolute_reset'])-p['log_boundary'];key=(t,reset)
        if t not in GAPS:raise ValueError('unexpected gap')
        if key not in references:
            references[key]=continuum_basis(t,reset)
            checked=continuum_basis(t,reset,order=64)
            quadrature_disagreement=max(quadrature_disagreement,float(np.max(abs(checked-references[key]))))
            for n,kernel in kernels.items():candidate[n][key]=kernel.basis(t,reset)
        prior=np.asarray(v['prior'])[0];posterior=np.asarray(v['posterior'])[0]
        exact_prior=prior@references[key];exact_posterior=posterior@references[key]
        old_reference_disagreement=max(old_reference_disagreement,abs(exact_prior[0]-v['expected_events'][0]))
        row=[t,reset,*exact_prior,*exact_posterior]
        for n in kernels:row.extend(prior@candidate[n][key]);row.extend(posterior@candidate[n][key])
        rows.append(row)
    values=np.asarray(rows);np.savez_compressed(OUTPUT/'ALL_VISITS_FINITE.npz',values=values,
        columns=np.asarray(['dt','reset','reference_prior_M','reference_prior_H','reference_prior_A',
            'reference_posterior_M','reference_posterior_H','reference_posterior_A']+
            [f'n{n}_{law}_{metric}' for n in kernels for law in ('prior','posterior') for metric in ('M','H','A')]))
    reports=[]
    for j,n in enumerate(kernels):
        for law,k in (('prior',0),('posterior',1)):
            ref=values[:,2+3*k:5+3*k];actual=values[:,8+6*j+3*k:11+6*j+3*k];error=actual-ref
            reports.append({'intervals':n,'law':law,'maximum_absolute_error_M_H_A':np.max(abs(error),axis=0).tolist(),
                'mean_absolute_error_M_H_A':np.mean(abs(error),axis=0).tolist(),
                'maximum_relative_M_where_reference_at_least_1e-12':float(np.max(abs(error[:,0][ref[:,0]>=1e-12])/ref[:,0][ref[:,0]>=1e-12]))})
    first=[]
    for n,kernel in kernels.items():
        for t in GAPS:
            ref=continuum_basis(t,.62)[0];actual=kernel.basis(t,.62)[0]
            first.append({'intervals':n,'dt':t,'lower_atom':kernel.weights[0,0],
                          'reference_M_H_A':ref.tolist(),'hat_nodal_M_H_A':actual.tolist(),
                          'absolute_error_M_H_A':(actual-ref).tolist()})
    result={'schema':'hcsn-independent-finite-gap-original-laws-v1','scope':'hypothetical nodal hat-law migration; not an executed JointModel.solve rollout',
        'admission':'DIAGNOSTIC_ONLY_NO_PREDECLARED_FINITE_GATE','original_visits':14336,'source_sha256':sha(Path(__file__).read_bytes()),
        'old_source_reference_expected_events_maximum_absolute_difference':old_reference_disagreement,
        'continuum_quadrature_64_128_maximum_difference':quadrature_disagreement,'first_uniform_cell':first,'all_visits':reports,
        'input_sha256':inputs,'unique_gap_reset_laws':len(references),'wall_seconds':time.perf_counter()-started,'cpu_seconds':time.process_time()-cpu,
        'new_model_executions':0,'full_candidate_qualified':False}
    (OUTPUT/'SUMMARY.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('input_sha256','first_uniform_cell')}))


if __name__=='__main__':main()
