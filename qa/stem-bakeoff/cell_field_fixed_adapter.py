"""Development adapter for inherited real Head/Adam Reference tangent maps.

No dataset loader, training, policy optimization or nonlinear branch execution.
The caller must separately verify development artifact provenance and budgets.
"""
import numpy as np
from cell_field_fixed_actions import fixed_library
from cell_field_fixed_summary import inherited_scales, predict_observation_projection, projection_diagnostics


def fixed_impulse_predictions(reference, action_id, *, mode="q4"):
    """Use frozen original Reference maps; one fixed action then zero suffix.

    Action is a velocity: E already includes dt and fixed state scaling.
    Return loss deviations, not absolute losses and not measured outcomes.
    """
    if mode not in ("q4", "loss2", "full"):
        raise ValueError("q4/loss2/full mode required")
    p = reference.state.parameter_count
    pool = dict(fixed_library(p))
    if action_id not in pool:
        raise ValueError("registered fixed action ID required")
    h = reference.horizon
    if type(h) is not int or not 1 <= h <= 256:
        raise ValueError("bounded nonempty reference required")
    n = 3*p
    A, C, scales, states = (np.asarray(v, dtype=np.float64) for v in
                            (reference.A, reference.C, reference.scales, reference.states))
    if (A.shape != (h,n,n) or C.shape != (h+1,4,n) or scales.shape != (n,)
            or states.shape != (h+1,n) or not 0 < reference.dt <= 1
            or not all(np.isfinite(v).all() for v in (A,C,scales,states))
            or not np.array_equal(scales, inherited_scales(states[0]))
            or not np.array_equal(states[0], reference.state.vector())):
        raise ValueError("finite, anchor-fixed, original reference coordinates required")
    B, E = reference.action_matrix("all")
    expected = np.vstack((reference.dt*np.eye(p),np.zeros((2*p,p))))/scales[:,None]
    if (not np.array_equal(B,np.eye(p)) or np.shape(E)!=(h,n,p)
            or not np.array_equal(E,np.tile(expected,(h,1,1)))):
        raise ValueError("post-Adam theta-only action map required")
    actions=np.zeros((h,p)); actions[0]=pool[action_id]
    if mode == "full":
        z=np.zeros((h+1,n))
        for k in range(h):z[k+1]=A[k]@z[k]+E[k]@actions[k]
        fields=np.einsum("kij,kj->ki",C[:,:2],z)
        observations=None
        ranks=[]
    else:
        width=4 if mode=="q4" else 2
        fields, observations=predict_observation_projection(A,E,C[:,:width],actions)
        ranks=[{key:value for key,value in projection_diagnostics(c).items() if key!="inverse"}
               for c in C[:,:width]]
    if not np.isfinite(fields).all():raise ValueError("nonfinite predicted loss path")
    return {"fields":fields,"observations":observations,"actions":actions,
            "projection_diagnostics":ranks,"mode":mode,
            "scope":"frozen tangent prediction; not a measured branch or authority"}
