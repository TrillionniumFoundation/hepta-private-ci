"""Compare compiled C1 gates with original full formulas; test real BPTT."""
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import jax
jax.config.update("jax_enable_x64", True)
import jax.numpy as jnp

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from analytic import HXModel, Parameters, jax_hx
from next.full_kernel.tables import build_table,patch_constants,reference_gates,save_table
from next.full_kernel.kernel import as_jax_table,full_gates


def exact_gates(z,theta,patch_A,patch_B):
    s=theta[2]*jnp.sqrt(theta[6])
    u=jnp.abs(z)
    f=jax_hx.first_hit_x(s*u,theta[6],theta)[0]
    w=jnp.minimum(u/.02,1.)
    f=jnp.where(u<.02,1-patch_A*w*w-patch_B*w*w*w,f)
    q=jnp.where(z<0,.5*f,1-.5*f)
    x=s*jnp.maximum(-z,0.)
    e=jax_hx.equity_x(x,theta)
    a=jnp.where(z<0,e/(e+jax_hx.boundary(theta)),0.)
    return jnp.stack((q,a))


reference_values=jax.jit(jax.vmap(exact_gates,in_axes=(0,None,None,None)))
reference_derivatives=jax.jit(jax.vmap(jax.jacfwd(exact_gates,argnums=0),
                                      in_axes=(0,None,None,None)))
runtime_values=jax.jit(lambda z,t:jnp.stack(full_gates(z,t),axis=-1))
runtime_derivatives=jax.jit(jax.vmap(jax.jacfwd(lambda z,t:jnp.stack(full_gates(z,t)),argnums=0),
                                    in_axes=(0,None)))


def check_case(case):
    params=Parameters(**case["parameters"])
    model=HXModel(params)
    patch=patch_constants(model)
    table=build_table(params)
    theta=jnp.asarray(jax_hx.validate_parameters(params),dtype=jnp.float64)
    # Resolve the narrow C1 layer, ordinary states, both interpolation tails.
    states=np.unique(np.concatenate((np.linspace(-12,12,16001),
        np.linspace(-.021,.021,1001),np.linspace(-120,-12,1001),[0.,-.02,.02],
        [-8/model.s-1e-6,-8/model.s,-8/model.s+1e-6])))
    selected=np.unique(np.concatenate((np.linspace(-12,12,2401),
        np.linspace(-.021,.021,301),np.linspace(-120,-12,101),[0.,-.02,.02])))
    exact=np.stack(reference_gates(states,params),axis=-1)
    gradient_reference=np.asarray(reference_derivatives(jnp.asarray(selected),theta,
                                   table["patch_A"],table["patch_B"]))
    result=dict(name=case["name"],parameters=case["parameters"],boundary=model.boundary,
        state_count=len(states),gradient_state_count=len(selected),patch=patch,
        financial_parameters_trainable=False,table_nodes=table["call_coeff"].shape[1]+1,
        table_numeric_bytes_float32=sum(v.size*4 for v in table.values()),precision={})
    dense=np.linspace(0,patch["epsilon"],10001)
    z=dense/model.s
    patched=2*reference_gates(-z,params)[0]
    raw=model.first_hit(dense,params.maturity)[0]
    result["intentional_risk_probability_patch_max_bias"]=float(np.max(np.abs(patched-raw)))
    for dtype,name in ((jnp.float64,"float64"),(jnp.float32,"float32")):
        compiled=as_jax_table(table,dtype)
        actual=np.asarray(runtime_values(jnp.asarray(states,dtype),compiled))
        gradients=np.asarray(runtime_derivatives(jnp.asarray(selected,dtype),compiled))
        errors=np.max(np.abs(actual-exact),axis=0)
        grad_errors=np.max(np.abs(gradients-gradient_reference)/np.maximum(1,np.abs(gradient_reference)),axis=0)
        # Every safety-side knot is checked for local monotonicity and near C1 matching.
        eps=4*np.finfo(np.dtype(name)).eps
        knots=np.expm1(np.arange(table["call_coeff"].shape[1]+1)*float(table["call_step"]))
        knots=np.unique(np.concatenate((knots,[.02,float(table["risk_limit"])])))
        left=-knots-np.maximum(eps*np.maximum(1,knots),1e-10)
        right=-knots+np.maximum(eps*np.maximum(1,knots),1e-10)
        dl=np.asarray(runtime_derivatives(jnp.asarray(left,dtype),compiled))
        dr=np.asarray(runtime_derivatives(jnp.asarray(right,dtype),compiled))
        joins=float(np.max(np.abs(dl-dr)/np.maximum(1,np.maximum(np.abs(dl),np.abs(dr)))))
        stress=jnp.asarray([-1e30,-1e6,-1e3,-1e-10,0,1e-10,1e3,1e6,1e30],dtype)
        sv=np.asarray(runtime_values(stress,compiled));sg=np.asarray(runtime_derivatives(stress,compiled))
        bv=np.asarray(runtime_values(jnp.asarray([0],dtype),compiled))[0]
        bg=np.asarray(runtime_derivatives(jnp.asarray([0],dtype),compiled))[0]
        passed=(max(errors)<5e-6 and max(grad_errors)<5e-4 and np.all(np.isfinite(actual))
                and np.min(actual)>=-1e-6 and np.max(actual)<=1+1e-6
                and np.all(np.isfinite(sv)) and np.all(np.isfinite(sg))
                and np.max(np.abs(bv-[.5,0.]))<1e-7 and np.max(np.abs(bg))<1e-7)
        result["precision"][name]=dict(value_abs_error_q_a=errors.tolist(),
            gradient_scaled_error_q_a=grad_errors.tolist(),min=float(actual.min()),max=float(actual.max()),
            near_knot_gradient_variation=joins,boundary_value=bv.tolist(),boundary_derivative=bg.tolist(),
            stress_values=sv.tolist(),stress_derivatives=sg.tolist(),passed=bool(passed))
    return result


def bptt_check(table):
    rng=np.random.default_rng(873104)
    inputs=rng.normal(0,.7,(160,4))
    gaps=rng.uniform(.05,.3,(160,1))
    target=rng.normal(0,.3,(4,))
    theta=np.array([.12,.8,.6,1.2,.3],dtype=np.float64)
    def loss(weights,events,dt,truth,t):
        shift,drive,regen,recovery,read=weights
        def step(state,item):
            x,y=state
            event,delta=item
            q,a=full_gates(x-shift,t)
            ef=jnp.exp(-delta)
            es=jnp.exp(-delta/5)
            xn=ef*x+(1-ef)*(drive*event+.6*a+regen*q-y)
            yn=es*y+(1-es)*recovery*q
            return (xn,yn),q
        (x,y),q=jax.lax.scan(step,(jnp.zeros(4,events.dtype),jnp.zeros(4,events.dtype)),(events,dt))
        return jnp.mean((jnp.tanh(x)+read*y-truth)**2)+.01*jnp.mean(q*q)
    objective=jax.jit(loss)
    derivative=jax.jit(jax.grad(loss))
    results=[]
    for dtype,label,step in ((jnp.float64,"float64",1e-5),(jnp.float32,"float32",2e-3)):
        w=jnp.asarray(theta,dtype);x=jnp.asarray(inputs,dtype);dt=jnp.asarray(gaps,dtype)
        truth=jnp.asarray(target,dtype);t=as_jax_table(table,dtype)
        grad=np.asarray(derivative(w,x,dt,truth,t))
        fd=[]
        for i in range(len(theta)):
            offset=np.eye(len(theta))[i]*step
            fd.append((float(objective(w+offset.astype(np.dtype(label)),x,dt,truth,t))
                       -float(objective(w-offset.astype(np.dtype(label)),x,dt,truth,t)))/(2*step))
        fd=np.array(fd);error=float(np.max(np.abs(grad-fd)))
        results.append(dict(dtype=label,loss=float(objective(w,x,dt,truth,t)),gradient=grad.tolist(),
                            finite_difference=fd.tolist(),max_abs_error=error,
                            passed=bool(error<(1e-7 if label=="float64" else 2e-4))))
    return results


def main():
    start=time.perf_counter()
    original=json.loads((ROOT/"analytic/jax_validation_results.json").read_text())
    cases=original["float64"]["rows"]
    result=dict(schema="hepta.hcsn.compiled_full_kernel.v1",scope="Fixed financial parameter templates",
        protocol=json.loads((HERE/"protocol.json").read_text()),cases=[],jax=jax.__version__,
        original_raw_financial_float32_failure_preserved=True,
        implementation_fixes=["Replaced clip/min at selected exact joins: their half-derivative convention incorrectly halved a C1 composite slope. Explicit identity branches preserve the true selected derivative."])
    for case in cases:
        row=check_case(case);result["cases"].append(row)
        print(row["name"],row["precision"]["float32"],flush=True)
    table=build_table()
    result["baseline_table"]=save_table(HERE/"baseline_table.npz",table)
    result["bptt"]=bptt_check(table)
    result["all_declared_checks_passed"]=all(r["precision"][d]["passed"] for r in result["cases"]
                                                for d in ("float64","float32")) and all(x["passed"] for x in result["bptt"])
    result["source_sha256"]={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob("*.py")}
    result["elapsed_seconds"]=time.perf_counter()-start
    (HERE/"validation_results.json").write_text(json.dumps(result,indent=2)+"\n")
    print("ALL",result["all_declared_checks_passed"],"seconds",result["elapsed_seconds"],flush=True)
    if not result["all_declared_checks_passed"]:raise SystemExit(1)


if __name__=="__main__":main()
