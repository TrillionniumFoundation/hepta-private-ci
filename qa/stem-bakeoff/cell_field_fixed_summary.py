"""Analytic synthetic checks of inherited V3 four-output observations.

Not a Cell model or real-data runner. Quadratic probes provide exact gradients
and Hessians to test definitions already present in cell_field_control.py.
"""
import numpy as np


def _state(vector):
    x = np.asarray(vector, dtype=np.float64)
    if (x.ndim != 1 or not len(x) or len(x) % 3 or not np.isfinite(x).all()
            or np.any(x[2 * (len(x)//3):] < 0)):
        raise ValueError("finite theta/m/v state with nonnegative v required")
    return x, len(x)//3


def inherited_scales(anchor):
    """Fixed at anchor, not recomputed at each perturbed/reference state."""
    x, p = _state(anchor)
    with np.errstate(over="ignore",invalid="ignore"):
        result = np.concatenate([np.full(p, max(float(np.sqrt(np.mean(block*block))), floor))
                                 for block, floor in zip(np.split(x, 3), (.05, .001, 1e-6))])
    if not np.isfinite(result).all():
        raise ValueError("nonfinite inherited scale result")
    return result


def quadratic_observe(vector, hessians, linear, constants):
    """[Lc,Lo,gc.raw_m,go.raw_m], exact physical-state Jacobian.

    Probe gradients contain no L2, clipping or Adam bias correction. Hessians
    are explicitly symmetric. v is admissible state, not a summary input.
    """
    x, p = _state(vector)
    H, b, c = (np.asarray(a, dtype=np.float64) for a in (hessians, linear, constants))
    if (H.shape != (2,p,p) or b.shape != (2,p) or c.shape != (2,)
            or not all(np.isfinite(a).all() for a in (H,b,c))
            or not np.array_equal(H, H.transpose(0,2,1))):
        raise ValueError("two finite symmetric quadratic probe definitions required")
    theta, m = x[:p], x[p:2*p]
    g = np.einsum("aij,j->ai", H, theta) + b
    losses = .5*np.einsum("i,aij,j->a", theta,H,theta) + b@theta + c
    values = np.r_[losses, g@m]
    J = np.zeros((4,3*p))
    J[:2,:p] = g
    J[2:,:p] = np.einsum("aji,j->ai", H,m)
    J[2:,p:2*p] = g
    if not np.isfinite(values).all() or not np.isfinite(J).all():
        raise ValueError("nonfinite synthetic observation")
    return values,J


def scaled_jacobian(jacobian, scales):
    J, s = np.asarray(jacobian), np.asarray(scales)
    if (J.ndim != 2 or s.shape != (J.shape[1],) or np.any(s<=0)
            or not np.isfinite(J).all() or not np.isfinite(s).all()):
        raise ValueError("finite Jacobian and positive fixed state scales required")
    with np.errstate(over="ignore",invalid="ignore"):
        result=J*s[None,:]
    if not np.isfinite(result).all():
        raise ValueError("nonfinite scaled Jacobian result")
    return result


def projection_diagnostics(C):
    C = np.asarray(C,dtype=np.float64)
    if C.ndim != 2 or min(C.shape)<1 or not np.isfinite(C).all():
        raise ValueError("finite nonempty observation matrix required")
    singular = np.linalg.svd(C,compute_uv=False)
    cutoff = 1e-10*singular[0]
    return {"singular_values":singular,"cutoff":float(cutoff),
            "rank":int(np.count_nonzero(singular>cutoff)),
            "inverse":np.linalg.pinv(C,rcond=1e-10)}


def predict_observation_projection(A,E,C,actions):
    """Synthetic reference-array projection; scores actions, never optimizes them.

    Raw output convention and fixed scaled-state coordinates must already agree
    across A/E/C. The charged physical losses are always the first two outputs.
    """
    A,E,C,u=(np.asarray(x,dtype=np.float64) for x in (A,E,C,actions))
    if A.ndim!=3 or E.ndim!=3 or C.ndim!=3 or u.ndim!=2:
        raise ValueError("rank-compatible tangent inputs required")
    h,n,n2=A.shape;q=C.shape[1];p=u.shape[1]
    if (h<1 or n<1 or n2!=n or q not in (2,4) or p<1
            or E.shape!=(h,n,p) or C.shape!=(h+1,q,n) or u.shape!=(h,p)
            or not all(np.isfinite(x).all() for x in (A,E,C,u))):
        raise ValueError("finite consistent loss2/extended reference inputs required")
    predicted=np.zeros((h+1,q))
    for k in range(h):
        predicted[k+1]=C[k+1]@A[k]@projection_diagnostics(C[k])["inverse"]@predicted[k]+C[k+1]@E[k]@u[k]
    if not np.isfinite(predicted).all():raise ValueError("nonfinite projected result")
    return predicted[:,:2],predicted
