"""Two-coordinate conditional edit for a prescribed endogenous boundary and one preserved receiver."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time

import torch

from qualification.hcsn_differentiable.neural_control import boundary_residual, optimal_boundary
from qualification.hcsn_halfline_transport.finite_marked import finite_marked_state
from qualification.hcsn_halfline_transport import verify_qvi_finite_bridge as setup

HERE = Path(__file__).resolve().parent
PROTOCOL = json.loads((HERE / "protocol.json").read_text())
torch.set_num_threads(1)


def tensor(value):
    return torch.as_tensor(value,dtype=torch.float64)


def theta(cost):
    return torch.cat((tensor(setup.A[:-1]),cost.reshape(1)))


def source_message(b,params,initial):
    # The readout needs the signed expected cumulative hits, shared by both methods.
    result = cell(b,params,tensor(initial),0)
    return tensor(setup.PROJECTION) @ result.marked_cumulative_hits


def cell(b,params,initial,i):
    return finite_marked_state(initial-b,params[0],params[1],params[3]-b,params[4],tensor(setup.HORIZONS[i]),
                               tensor(setup.MARKS[i]),tensor(setup.RESET_MAPS[i]),tensor(setup.EDGES),tensor(setup.FRACTIONS),tensor(setup.POINTS))


def receiver_start(b,params,initial,offset):
    return offset+setup.DIRECT*b+setup.SIGNED*source_message(b,params,initial)


def receiver_features(initial,local_theta,local_b):
    r=cell(local_b,local_theta,initial,1)
    return torch.cat([v.flatten() for v in (r.state.probability,r.state.content_mass,r.density_by_release,r.density_content,
                                           r.event_probability_by_hit,r.event_rate_by_hit,r.marked_cumulative_hits,r.marked_event_rate)])


def one(method):
    started=time.perf_counter()
    intervals=PROTOCOL["other_initials"]
    anchor=PROTOCOL["anchor_initial"]
    original=tensor([setup.A[-1],setup.OFFSET])
    initial_theta=theta(original[0])
    old_b=optimal_boundary(initial_theta)
    target=old_b+PROTOCOL["target_first_boundary_displacement"]
    keep=receiver_start(old_b,initial_theta,anchor,original[1])
    calls=0
    if method=="structural":
        # The exact boundary residual has unit coefficient on the spike cost.
        cost=original[0]-boundary_residual(target,initial_theta)
        adjusted_theta=theta(cost)
        offset=keep-setup.DIRECT*target-setup.SIGNED*source_message(target,adjusted_theta,anchor)
        chosen=torch.stack((cost,offset))
    elif method=="BP":
        chosen=original.clone().requires_grad_()
        opt=torch.optim.LBFGS([chosen],**PROTOCOL["solver"])
        def closure():
            nonlocal calls
            calls+=1
            opt.zero_grad()
            params=theta(chosen[0])
            b=optimal_boundary(params)
            y=receiver_start(b,params,anchor,chosen[1])
            loss=(b-target).square()+(y-keep).square()
            loss.backward()
            return loss
        opt.step(closure)
        chosen=chosen.detach()
    elif method=="unchanged":
        chosen=original
    else:
        raise ValueError(method)
    with torch.no_grad():
        picked=theta(chosen[0]);new_b=optimal_boundary(picked)
        second=tensor(setup.B);receiver_boundary=optimal_boundary(second)
        checks=[]
        for point in [anchor,*intervals]:
            old_y=receiver_start(old_b,initial_theta,point,original[1])
            new_y=receiver_start(new_b,picked,point,chosen[1])
            orig=receiver_features(old_y,second,receiver_boundary)
            new=receiver_features(new_y,second,receiver_boundary)
            checks.append(dict(initial=point,receiver_start_delta=float(new_y-old_y),
                               receiver_feature_count=orig.numel(),max_feature_change=float((new-orig).abs().max())))
        limit=PROTOCOL["gates"]
        cost_delta,offset_delta=(chosen-original).tolist()
        boundary_error=abs(float(new_b-target))
        passed=(boundary_error<=limit["boundary_abs"] and checks[0]["max_feature_change"]<=limit["anchor_receiver_features_inf"]
                and max(abs(cost_delta),abs(offset_delta))<=limit["max_abs_parameter_delta"])
        # All per-query receiver outputs are available before the inclusive clock is stopped.
        seconds=time.perf_counter()-started
        return dict(cost_delta=cost_delta,offset_delta=offset_delta,target=float(target),boundary=float(new_b),
                    boundary_error=boundary_error,checks=checks,passed=passed,optimizer_closures=calls),seconds


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    variants=("unchanged","structural","BP")
    for v in variants:
        one(v)
    results={};timings={v:[] for v in variants}
    for pair in range(5):
        order=variants if pair%2==0 else variants[::-1]
        for v in order:
            row,seconds=one(v)
            if v in results and row!=results[v]:
                raise RuntimeError("numerical output changed across repetitions")
            results[v]=row;timings[v].append(seconds)
    report=dict(source=PROTOCOL["source"],torch=str(torch.__version__),thread_count=torch.get_num_threads(),arms=results,
                times=timings,median_inclusive_seconds={v:statistics.median(t) for v,t in timings.items()},
                protocol_sha256=hashlib.sha256((HERE/"protocol.json").read_bytes()).hexdigest())
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")


if __name__=="__main__":
    main()
