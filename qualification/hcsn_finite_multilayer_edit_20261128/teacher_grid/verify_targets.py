"""Certify author-style projected linear writes, forward value retrieval and old KL curvature on true support audio."""
import argparse
import json
import sys
from pathlib import Path
import numpy as np
from scipy.special import softmax
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fit_model import Cell,fields,forward,standardized
from sensitivity import response
from named import alpha_step,local_response,old_geometry,preserved_projection


def run(a):
    results=[]
    raw=fields(a.original/'old_cal.npz');ix=np.random.default_rng(588559).choice(len(raw['x']),16,replace=False)
    for arch in ('literal','smooth'):
        for seed in (271,577,911):
            d=a.models/f'{arch}_{seed}';p=fields(d/'parent.npz');m=[p['encoder'],p['W']];x=standardized(raw['x'][ix],p)
            law=Cell(a.law if arch=='literal' else d/'smooth.npz');z,j=response(x,m,p,law,True)
            z0,keys,res=local_response(x,m,p,law)
            reconstructed=np.concatenate([np.einsum('ntjo,nti->noij',r,k,optimize=True).reshape(len(x),10,-1) for k,r in zip(keys,res)],axis=-1)
            err=float(np.max(abs(j-reconstructed)));assert err<1.e-9
            eig,meta=old_geometry(x,m,p,law,'alpha')
            base=preserved_projection(eig,.2)
            dw,v,dt=alpha_step(x,np.eye(10)[raw['y'][ix]],m,p,law,base,True)
            eig2,metac=old_geometry(x,m,p,law,'crisp');e,q=eig2[0]
            rng=np.random.default_rng(seed);v0=rng.normal(size=(len(e),));v0/=np.linalg.norm(v0)
            predicted=float(np.sum(e*(q.T@v0)**2));prob=softmax(z,axis=-1);pieces=[v0[:m[0].size].reshape(m[0].shape),v0[m[0].size:].reshape(m[1].shape)]
            errors=[]
            for h in (1e-3,1e-4,1e-5):
                kl=[]
                for sign in (-1,1):
                    prop=[w+sign*h*v for w,v in zip(m,pieces)];s=softmax(forward(x,prop,p,law)[0],axis=-1)
                    kl.append(float((prob*np.log(prob/s)).sum(1).mean()))
                errors.append({'epsilon':h,'residual':abs(sum(kl)/h**2-predicted)})
            assert min(k['residual'] for k in errors)<2e-5
            results.append(dict(arch=arch,seed=seed,target_jacobian_error=err,initial_output_error=float(abs(z-z0).max()),
                 preserved_key_ranks=[r['rank'] for r in meta['spectra']],alpha_approx_dims=[b.shape[1] for b in base],
                 alpha_reduced_dense=v,crisp_KL_curvature=predicted,finite_KL_comparison=errors))
    a.out.write_text(json.dumps(results,indent=1)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('models','original','law','out'):p.add_argument(n,type=Path)
    run(p.parse_args())
