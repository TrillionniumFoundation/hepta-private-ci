"""Bounded initial-amplitude map for a fixed finite linear delay equation.

Probability and signed content share the same propagator. Up to sixteen basis
directions ride in signed-content channels per forward call. This transparent
small-grid reference is not a scalable n512 adjoint.
"""

from fractions import Fraction
import math
import time

import numpy as np

from qualification.hcsn_boundary_audit.refractory_transport import Packet
from qualification.hcsn_boundary_audit.spatial_generator import KilledSpatialGenerator
from qualification.hcsn_graded.model import GradedJointModel
from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from qualification.hcsn_joint_dde.model import JointModel


FIELDS = ("active", "upper", "refractory", "events", "discounted_events",
          "discounted_active_time", "discounted_remaining_phase")


def pack(row):
    """Rows are interior active nodes, upper, refractory, M, H, A and Z."""
    return np.vstack([np.asarray(row[name]) if name=="active" else
                      np.asarray(row[name])[None,:] for name in FIELDS])


def validate(model, query_times, supports):
    uniform = type(model) is JointModel and type(model.spatial) is KilledSpatialGenerator
    graded = type(model) is GradedJointModel and type(model.spatial) is GradedSpatialGenerator
    if not (uniform or graded):
        raise ValueError("an explicit frozen uniform or graded finite model is required")
    times=np.asarray(query_times,dtype=float)
    if (not 4<=model.spatial.intervals<=32 or times.ndim!=1 or not 1<=len(times)<=5 or
        not np.all(np.isfinite(times)) or np.any(times<0) or np.any(np.diff(times)<=0) or
        times[-1]>min(.6,3*model.delay) or not isinstance(supports,tuple) or len(supports)>8):
        raise ValueError("small-grid/time/support budget exceeded")
    checked=[]
    for pair in supports:
        if not isinstance(pair,tuple) or len(pair)!=2 or any(type(v) not in (int,float,Fraction) for v in pair):
            raise ValueError("fixed rational/finite real support pairs are required")
        if any(not math.isfinite(float(v)) for v in pair):
            raise ValueError("finite fixed supports required")
        left,right=(v if isinstance(v,Fraction) else Fraction(str(v)) for v in pair)
        if not 0<=left<=right<=Fraction(str(model.delay)):
            raise ValueError("fixed remaining-time support differs")
        checked.append((left,right))
    directions=model.spatial.intervals+len(checked)
    map_scalars=len(times)*(model.spatial.intervals+5)*directions
    if directions>40 or map_scalars>7400:
        raise ValueError("initial-map storage budget exceeded")
    return times,tuple(checked),directions,map_scalars


def initial_map(model, query_times, supports=(), *, rtol=2e-11, atol=2e-13, max_step=.01):
    """Return G[t,output-coordinate,input-amplitude] with exact fixed supports.

    Input amplitudes are active nodes 1..N (including upper escape), followed
    by one amplitude per remaining-time packet. There is no lower hit atom.
    The probability carrier is an auxiliary nonnegative finite measure; only
    signed-direction channels supply the returned operator.
    """
    times,supports,directions,map_scalars=validate(model,query_times,supports)
    count=model.spatial.intervals
    result=np.empty((len(times),count+5,directions))
    costs=[]
    for start in range(0,directions,16):
        stop=min(start+16,directions)
        width=stop-start
        probability=np.zeros(count+1)
        probability[1]=1.
        content=np.zeros((count+1,width))
        phase_content=np.zeros((len(supports),width))
        for direction in range(start,stop):
            if direction<count:
                content[direction+1,direction-start]=1.
            else:
                phase_content[direction-count,direction-start]=1.
        packets=tuple(Packet(f"carrier-{j}",left,right,Fraction(1),
                      tuple(Fraction(int(v)) for v in phase_content[j]))
                      for j,(left,right) in enumerate(supports))
        wall,cpu=time.perf_counter(),time.process_time()
        flow=model.solve(times,probability,content,packets,rtol=rtol,atol=atol,max_step=max_step)
        result[:,:,start:stop]=np.stack([pack(row)[:,1:] for row in flow["rows"]])
        costs.append(dict(directions=[start,stop],signed_channels=width,
                          internal_steps=flow["internal_steps"],wall_seconds=time.perf_counter()-wall,
                          cpu_seconds=time.process_time()-cpu))
    if not np.all(np.isfinite(result)):
        raise ArithmeticError("initial-amplitude map is nonfinite")
    return dict(operator=result,times=times,fixed_supports=supports,
                basis_forward_calls=len(costs),basis_costs=costs,map_scalars=map_scalars,
                directions=directions,physics_gradients=False,support_gradients=False,
                migration_gradients=False,large_grid_qualified=False)


def direct_flow(model, query_times, active, content, phase_mass, phase_content, supports, **options):
    """Unchanged candidate forward on actual amplitudes, for independent checks."""
    times,supports,_,_=validate(model,query_times,supports)
    active=np.asarray(active,dtype=float)
    content=np.asarray(content,dtype=float)
    full_active=np.r_[0.,active]
    full_content=np.vstack([np.zeros((1,content.shape[1])),content])
    packets=tuple(Packet(f"actual-{j}",left,right,Fraction(str(float(phase_mass[j]))),
                  tuple(Fraction(str(float(v))) for v in phase_content[j]))
                  for j,(left,right) in enumerate(supports))
    rows=model.solve(times,full_active,full_content,packets,**options)
    return np.stack([pack(row) for row in rows["rows"]])
