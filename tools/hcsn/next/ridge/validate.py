"""Predeclared finite precision, SPD, exact retention and BPTT checks."""
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
from next.ridge.models import (init_model,apply_model,matched_width,count_parameters,
    update_statistics,read_statistics,closed_write,KEY_DIM,RIDGE)

STANDARDS=dict(statistics_absolute_error_float32=3e-5,
    statistics_absolute_error_float64=2e-12,
    gradient_absolute_error_float32=3e-3,
    gradient_absolute_error_float64=2e-6,
    state_bound_roundoff_float32=2e-5,state_bound_roundoff_float64=2e-12,
    exact_closed_write_retention=True,stress_sequence_length=4096)


def statistics_check(dtype,rng):
    count,batch,width=STANDARDS["stress_sequence_length"],3,11
    keys=np.tanh(rng.normal(0,3,(count,batch,KEY_DIM)))/np.sqrt(KEY_DIM)
    values=np.tanh(rng.normal(0,3,(count,batch,width)))
    scores=rng.normal(size=(count,batch,1))
    arrays=tuple(jnp.asarray(a,dtype=dtype) for a in (keys,values,scores))
    writes=closed_write(arrays[2])
    initial=(jnp.zeros((batch,KEY_DIM,KEY_DIM),dtype),
        jnp.zeros((batch,KEY_DIM,width),dtype),jnp.ones((batch,1),dtype))
    def step(state,item):
        state=update_statistics(*state,*item)
        return state,None
    final,_=jax.jit(lambda:jax.lax.scan(step,initial,(arrays[0],arrays[1],writes)))()
    gram,cross,mass=map(np.asarray,final)
    # Independent direct weighted sums use the actual rounded input keys/values.
    k,v,w=(np.asarray(a,dtype=np.float64) for a in (arrays[0],arrays[1],writes))
    total=1.+w.sum(axis=0)
    expected_g=np.einsum("tbi,tbj,tb->bij",k,k,w[...,0])/total[...,None]
    expected_h=np.einsum("tbi,tbj,tb->bij",k,v,w[...,0])/total[...,None]
    error=max(np.max(np.abs(gram-expected_g)),np.max(np.abs(cross-expected_h)),
              np.max(np.abs(mass-1./total)))
    eigen=np.linalg.eigvalsh(.5*(gram+gram.swapaxes(-1,-2)))
    matrix_eigen=eigen+RIDGE
    hold=update_statistics(*final,arrays[0][0],arrays[1][0],jnp.zeros((batch,1),dtype))
    exact=all(np.array_equal(np.asarray(a),np.asarray(b)) for a,b in zip(final,hold))
    read=read_statistics(*final[:2],arrays[0][0])
    reference=np.stack([k[0,b]@np.linalg.solve(expected_g[b]+RIDGE*np.eye(KEY_DIM),expected_h[b])
                        for b in range(batch)])
    tol=STANDARDS[f"state_bound_roundoff_{jnp.dtype(dtype).name}"]
    bound=bool(eigen.min()>=-tol and np.trace(gram,axis1=1,axis2=2).max()<=1.+tol
        and np.linalg.norm(cross,axis=1).max()<=1.+tol and mass.min()>0 and mass.max()<=1)
    passed=bool(error<=STANDARDS[f"statistics_absolute_error_{jnp.dtype(dtype).name}"] and exact and bound)
    return dict(dtype=jnp.dtype(dtype).name,passed=passed,weighted_sum_max_error=float(error),
        minimum_gram_eigenvalue=float(eigen.min()),maximum_gram_trace=float(np.trace(gram,axis1=1,axis2=2).max()),
        maximum_cross_column_norm=float(np.linalg.norm(cross,axis=1).max()),
        minimum_regularized_eigenvalue=float(matrix_eigen.min()),
        maximum_matrix_condition=float(np.max(matrix_eigen[:,-1]/matrix_eigen[:,0])),
        inverse_mass_range=[float(mass.min()),float(mass.max())],exact_closed_retention=exact,
        read_max_error=float(np.max(np.abs(np.asarray(read)-reference))))


def gradient_check(kind,dtype,rng):
    x=jnp.asarray(rng.normal(size=(3,19,16)),dtype)
    dt=jnp.asarray(rng.uniform(.05,2.,size=(3,19)),dtype)
    p=jax.tree_util.tree_map(lambda a:a.astype(dtype),init_model(kind,jax.random.PRNGKey(19),16,12,4))
    loss=jax.jit(lambda params,xx,dd:jnp.mean(apply_model(params,xx,dd,kind)**2))
    value,grad=jax.jit(jax.value_and_grad(loss))(p,x,dt)
    eps=1e-5 if dtype==jnp.float64 else 2e-3
    checks=[]
    for name in p:
        coordinate=(0,)*p[name].ndim
        plus=dict(p);minus=dict(p)
        plus[name]=p[name].at[coordinate].add(eps)
        minus[name]=p[name].at[coordinate].add(-eps)
        fd=float((loss(plus,x,dt)-loss(minus,x,dt))/(2*eps))
        ad=float(grad[name][coordinate])
        checks.append(dict(parameter=name,ad=ad,finite_difference=fd,absolute_error=abs(ad-fd)))
    dx,dd=jax.jit(jax.grad(loss,argnums=(1,2)))(p,x,dt)
    for name,input_array,input_grad in (("input",x,dx),("time_gap",dt,dd)):
        index=(0,)*input_array.ndim
        plus=input_array.at[index].add(eps);minus=input_array.at[index].add(-eps)
        fd=float((loss(p,plus,dt)-loss(p,minus,dt))/(2*eps)) if name=="input" else float((loss(p,x,plus)-loss(p,x,minus))/(2*eps))
        ad=float(input_grad[index])
        checks.append(dict(parameter=name,ad=ad,finite_difference=fd,absolute_error=abs(ad-fd)))
    output,aux=jax.jit(lambda pp,xx,dd:apply_model(pp,xx,dd,kind,True))(p,x*1e6,dt*100.)
    finite=all(np.isfinite(np.asarray(a)).all() for a in jax.tree_util.tree_leaves((grad,dx,dd,output,aux)))
    neuron_bounds=bool(np.max(np.abs(np.asarray(aux["fast"])))<=9.0001
                       and np.min(np.asarray(aux["slow"]))>=-1e-5
                       and np.max(np.asarray(aux["slow"]))<=6.0001)
    maximum=max(c["absolute_error"] for c in checks)
    width,count=matched_width(kind,16,4)
    actual=count_parameters(init_model(kind,jax.random.PRNGKey(0),16,width,4))
    return dict(kind=kind,dtype=jnp.dtype(dtype).name,loss=float(value),checks=checks,
        maximum_gradient_absolute_error=maximum,all_gradient_and_stress_outputs_finite=finite,
        bounded_fast_slow_stress=neuron_bounds,matched_width=width,parameter_count=count,
        passed=bool(finite and neuron_bounds and count==actual and maximum<STANDARDS[f"gradient_absolute_error_{jnp.dtype(dtype).name}"]))


def main():
    rng=np.random.default_rng(2862917)
    scores=jnp.asarray([-1e30,-1.,-1e-6,0.,1e-6,1.-1e-6,1.,1.+1e-6,1e30])
    gate=[]
    for dtype in (jnp.float32,jnp.float64):
        s=scores.astype(dtype)
        values=jax.vmap(closed_write)(s);slopes=jax.vmap(jax.grad(closed_write))(s)
        finite=bool(np.isfinite(np.asarray(values)).all() and np.isfinite(np.asarray(slopes)).all())
        passed=bool(finite and np.array_equal(np.asarray(values[:4]),np.zeros(4))
                    and np.array_equal(np.asarray(slopes[:4]),np.zeros(4)) and float(slopes[6])==.5)
        gate.append(dict(dtype=jnp.dtype(dtype).name,scores=np.asarray(s).tolist(),
            values=np.asarray(values).tolist(),derivatives=np.asarray(slopes).tolist(),passed=passed))
    statistics=[statistics_check(dtype,rng) for dtype in (jnp.float32,jnp.float64)]
    gradients=[]
    for dtype in (jnp.float32,jnp.float64):
        for kind in ("full_hx","hcsn","sigmoid","ridge_memory_only"):
            row=gradient_check(kind,dtype,rng);gradients.append(row)
            print(kind,row["dtype"],row["maximum_gradient_absolute_error"],row["passed"],flush=True)
    result=dict(standards=STANDARDS,passed=all(r["passed"] for r in gate+statistics+gradients),
        gate=gate,statistics=statistics,gradients=gradients,
        source_sha256={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in ("models.py","validate.py")},
        scope="Discrete BPTT and bounded state/SPD checks; does not prove good task accuracy or uniformly bounded long-time gradients")
    (HERE/"validation.json").write_text(json.dumps(result,indent=2)+"\n")
    print("PASSED",result["passed"],flush=True)


if __name__=="__main__":main()
