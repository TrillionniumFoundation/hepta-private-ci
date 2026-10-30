"""Post-freeze numerical diagnostics for zero/rank-one/ill-conditioned Gram states."""
import hashlib
import json
from pathlib import Path
import sys

import jax
jax.config.update("jax_enable_x64",True)
import jax.numpy as jnp
import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]))
from next.ridge.models import read_statistics,KEY_DIM,RIDGE
from next.ridge.run import verify_freeze

STANDARDS={"float32":{"normalized_residual":2e-5,"gradient_normalized_error":3e-3},
           "float64":{"normalized_residual":2e-12,"gradient_normalized_error":2e-7}}


def main():
    verify_freeze()
    k=np.ones(KEY_DIM)/np.sqrt(KEY_DIM)
    v=np.linspace(-.99,.99,7)
    rows=[]
    for dtype in (jnp.float32,jnp.float64):
        for scale in (0.,1e-8,.5,1.-1e-6):
            g=jnp.asarray((scale*np.outer(k,k))[None],dtype)
            h=jnp.asarray((scale*np.outer(k,v))[None],dtype)
            q=jnp.asarray(k[None],dtype)
            matrix=.5*(g+g.swapaxes(-1,-2))+RIDGE*jnp.eye(KEY_DIM,dtype=dtype)
            fitted=jnp.linalg.solve(matrix,h)
            residual=float(jnp.linalg.norm(matrix@fitted-h)/jnp.maximum(1.,jnp.linalg.norm(h)))
            loss=jax.jit(lambda gg,hh:jnp.sum(read_statistics(gg,hh,q)**2))
            grads=jax.jit(jax.grad(loss,argnums=(0,1)))(g,h)
            eps=2e-5 if dtype==jnp.float32 else 1e-6
            errors=[]
            for index,(value,gradient) in enumerate(zip((g,h),grads)):
                direction=np.arange(value.size,dtype=np.float64).reshape(value.shape)+1.
                if index==0:direction=.5*(direction+direction.swapaxes(-1,-2))
                direction=jnp.asarray(direction/np.linalg.norm(direction),dtype)
                plus=value+eps*direction;minus=value-eps*direction
                finite=(loss(plus,h)-loss(minus,h))/(2*eps) if index==0 else (loss(g,plus)-loss(g,minus))/(2*eps)
                analytic=jnp.sum(gradient*direction)
                errors.append(float(jnp.abs(finite-analytic)/jnp.maximum(1.,jnp.abs(analytic))))
            eig=np.linalg.eigvalsh(np.asarray(matrix)[0].astype(np.float64))
            finite=all(np.isfinite(np.asarray(a)).all() for a in (fitted,*grads))
            tol=STANDARDS[jnp.dtype(dtype).name]
            passed=bool(finite and residual<=tol["normalized_residual"]
                        and max(errors)<=tol["gradient_normalized_error"] and eig.min()>0)
            rows.append(dict(dtype=jnp.dtype(dtype).name,scale=scale,
                minimum_eigenvalue=float(eig.min()),condition=float(eig.max()/eig.min()),
                normalized_residual=residual,gradient_normalized_errors=errors,
                largest_gradient=float(max(np.max(np.abs(np.asarray(a))) for a in grads)),passed=passed))
    result=dict(passed=all(r["passed"] for r in rows),standards=STANDARDS,runs=rows,
        model_sha256=hashlib.sha256((HERE/"models.py").read_bytes()).hexdigest(),
        diagnostic_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        scope="No task data or training; reachable rank-one statistics approach the condition bound; gradient finite differences test the implemented read map")
    (HERE/"stress_solve_results.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))


if __name__=="__main__":main()
