"""Float32-ready C1 compiled full-model gates for batched JAX recurrence."""
import jax.numpy as jnp


def as_jax_table(table,dtype=jnp.float32):
    return {key:jnp.asarray(value,dtype=dtype) for key,value in table.items()}


def _hermite(t,y0,y1,m0,m1,step):
    """Shared endpoint basis: exact endpoint values even after coefficient casting."""
    one=1-t
    # Incremental form avoids cancellation of two O(1) basis derivatives when
    # adjacent values are close, especially for risk near one and Call tails.
    return (y0+(y1-y0)*t*t*(3-2*t)
            +step*m0*t*one*one+step*m1*t*t*(t-1))


def _uniform_cubic(u,coeff,step,end_value,end_slope):
    count=coeff.shape[1]
    index=jnp.clip(jnp.floor(u/step).astype(jnp.int32),0,count-1)
    offset=u-index.astype(u.dtype)*step
    following=jnp.minimum(index+1,count-1)
    y0=jnp.take(coeff[3],index);m0=jnp.take(coeff[2],index)
    y1=jnp.where(index<count-1,jnp.take(coeff[3],following),end_value)
    m1=jnp.where(index<count-1,jnp.take(coeff[2],following),end_slope)
    return _hermite(offset/step,y0,y1,m0,m1,step)


def full_gates(z,table):
    """Return (q,a), z=log(Vb/V)/(sigma*sqrt(m)); any batch shape is valid.

    q is explicitly modified first-hit risk, mirrored into the danger phase.
    a approximates full A7 normalized by E+Vb, extended by zero on default.
    Mathematical spline/patch/tail joins are C1. No surrogate gradient is used.
    """
    z=jnp.asarray(z)
    t=table
    risk_u=jnp.abs(z)
    epsilon=t["epsilon_scaled"]
    w=jnp.minimum(risk_u/epsilon,1.)
    # Use the very same endpoint value/slope as the first table interval.
    patch=_hermite(w,1.,t["risk_coeff"][3,0],0.,t["risk_coeff"][2,0],epsilon)
    # Select the identity at exact joins. clip/min conventionally halve the
    # derivative at their bounds, which would corrupt the composite C1 gradient.
    interior_u=jnp.where(risk_u<epsilon,epsilon,
                        jnp.where(risk_u>t["risk_limit"],t["risk_limit"],risk_u))-epsilon
    risk_tail_slope=-t["risk_end"]*t["risk_tail_rate"]
    risk=_uniform_cubic(interior_u,t["risk_coeff"],t["risk_step"],t["risk_end"],risk_tail_slope)
    tail=t["risk_end"]*jnp.exp(-t["risk_tail_rate"]*jnp.maximum(risk_u-t["risk_limit"],0.))
    risk=jnp.where(risk_u>t["risk_limit"],tail,risk)
    risk=jnp.where(risk_u<epsilon,patch,risk)
    q=jnp.where(z<0,.5*risk,1-.5*risk)
    safe=t["diffusion_scale"]*jnp.maximum(-z,0.)
    call_u=jnp.log1p(safe/t["diffusion_scale"])
    safe_call_u=jnp.where(call_u>t["call_limit"],t["call_limit"],call_u)
    call_tail_slope=t["call_tail_rate"]*(1-t["call_end"])*(t["diffusion_scale"]+t["call_distance_limit"])
    call=_uniform_cubic(safe_call_u,t["call_coeff"],t["call_step"],t["call_end"],call_tail_slope)
    call_tail=1-(1-t["call_end"])*jnp.exp(-t["call_tail_rate"]*jnp.maximum(safe-t["call_distance_limit"],0.))
    call=jnp.where(safe>t["call_distance_limit"],call_tail,call)
    a=jnp.where(z<0,call,0.)
    return q,a
