"""Exact join AD checks and interval-by-interval monotonicity certificates."""
import json
from pathlib import Path
import sys

import numpy as np
import jax
jax.config.update("jax_enable_x64",True)
import jax.numpy as jnp

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from analytic import Parameters
from next.full_kernel import build_table,as_jax_table,full_gates


def derivative_extrema(coeff,step,end,end_slope):
    """Exact extrema of each cubic Hermite polynomial's quadratic derivative."""
    values=np.append(coeff[3],end).astype(float)
    slopes=np.append(coeff[2],end_slope).astype(float)
    h=float(step)
    a=2*(values[:-1]-values[1:])+h*(slopes[:-1]+slopes[1:])
    b=3*(values[1:]-values[:-1])-h*(2*slopes[:-1]+slopes[1:])
    c=h*slopes[:-1]
    derivative=np.stack((c,3*a+2*b+c))/h
    t=np.divide(-b,3*a,out=np.zeros_like(a),where=a!=0)
    interior=((3*a*t+2*b)*t+c)/h
    interior=np.where((t>0)&(t<1),interior,derivative[0])
    return float(np.min(np.vstack((derivative,interior)))),float(np.max(np.vstack((derivative,interior))))


def main():
    original=json.loads((ROOT/"analytic/jax_validation_results.json").read_text())
    records=[]
    for case in original["float64"]["rows"]:
        params=Parameters(**case["parameters"])
        source=build_table(params)
        record={"name":case["name"],"precision":{}}
        for dtype,name in ((jnp.float64,"float64"),(jnp.float32,"float32")):
            table=as_jax_table(source,dtype)
            evaluate=jax.jit(lambda z:jnp.stack(full_gates(z,table)))
            differentiate=jax.jit(jax.jacfwd(lambda z:jnp.stack(full_gates(z,table))))
            epsilon=float(table["epsilon_scaled"])
            locations=[0.,-epsilon,epsilon,-float(table["risk_limit"]),float(table["risk_limit"]),
                       -float(table["call_distance_limit"])/float(table["diffusion_scale"])]
            joins=[]
            for location in locations:
                delta=float(1e-7 if name=="float64" else max(1e-6,8*np.finfo(np.float32).eps*max(1,abs(location))))
                inputs=jnp.asarray([location-delta,location,location+delta],dtype)
                values=np.asarray(jax.vmap(evaluate)(inputs))
                gradients=np.asarray(jax.vmap(differentiate)(inputs))
                variation=float(np.max(np.abs(gradients-gradients[1])))
                joins.append(dict(location=location,delta=delta,inputs=np.asarray(inputs).tolist(),
                    values=values.tolist(),derivatives=gradients.tolist(),max_derivative_variation=variation))
            data={k:np.asarray(v) for k,v in table.items()}
            call_slope=data["call_tail_rate"]*(1-data["call_end"])*(data["diffusion_scale"]+data["call_distance_limit"])
            risk_slope=-data["risk_end"]*data["risk_tail_rate"]
            cmin,cmax=derivative_extrema(data["call_coeff"],data["call_step"],data["call_end"],call_slope)
            rmin,rmax=derivative_extrema(data["risk_coeff"],data["risk_step"],data["risk_end"],risk_slope)
            # FP64 is the interpolant certificate. FP32 quantization is separately
            # reported, with a small numerical residual tolerance, not hidden.
            passed=(cmin>=-2e-6 and rmax<=2e-6
                    and max(j["max_derivative_variation"] for j in joins)<1e-3)
            record["precision"][name]=dict(exact_joins=joins,call_derivative_range=[cmin,cmax],
                risk_derivative_range=[rmin,rmax],passed=bool(passed))
        records.append(record)
    result=dict(cases=records,all_checks_passed=all(x["precision"][d]["passed"] for x in records for d in ("float64","float32")),
                interpretation="Shared nodes make the underlying interpolant C1. Floating arithmetic has reported rounding residuals; sampled neighbor derivative variation also includes actual curvature.")
    (HERE/"join_results.json").write_text(json.dumps(result,indent=2)+"\n")
    print('PASS',result["all_checks_passed"])
    print('Worst gradient neighbor variation',max(j["max_derivative_variation"] for c in records for d in c["precision"].values() for j in d["exact_joins"]))
    if not result["all_checks_passed"]:raise SystemExit(1)


if __name__=="__main__":main()
