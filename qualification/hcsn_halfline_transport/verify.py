"""Verify rare killed transport, two-time composition and a single reset against positive integrals."""
import argparse
import hashlib
import importlib
import json
import math
import platform
import sys
from pathlib import Path

import mpmath as mp
import numpy as np
import scipy
import torch
from scipy.integrate import quad
from scipy.special import log_ndtr

from qualification.hcsn_differentiable.contract import GridSpec, PhysicalParameters
from qualification.hcsn_differentiable.operator import DifferentiableDistributionOperator, _first_hit_logprob
from qualification.hcsn_halfline_readout import verify as prior
from qualification.hcsn_regenerative.tensor import TensorDiffusion, TensorReset, regenerative_transition
from qualification.hcsn_regenerative.tensor_state import _convolution
from qualification.hcsn_split_mesh import test_split
from .transport import once_renewed_state, point_state, released_once
from .reset_gradient import certify as certify_reset_gradient

SOURCE = Path(__file__).parent
PLAN = json.loads((SOURCE / "protocol.json").read_bytes())
REPAIR = json.loads((SOURCE / "repair_protocol.json").read_bytes())
GATE = PLAN["gates"]
T = prior.tensor
require = prior.require
PHASE = [0., .1, .195, .2]
MARK = [-.4, .75]


def pdf(y, x, t, mu, sigma):
    variance = sigma*sigma*t
    return (math.exp(-.5*(y-x-mu*t)**2/variance) * -math.expm1(-2*x*y/variance)
            / math.sqrt(2*math.pi*variance))


def interval(x, t, mu, sigma, lo, hi):
    # Positive killed density, scaled before integration for far Gaussian tails.
    variance = sigma*sigma*t
    peak = min(hi, max(lo, x+mu*t))
    log_scale = -.5*(peak-x-mu*t)**2/variance - .5*math.log(2*math.pi*variance)
    if log_scale < -745:
        return 0.
    def integrand(y):
        return math.exp(-.5*((y-x-mu*t)**2-(peak-x-mu*t)**2)/variance) * -math.expm1(-2*x*y/variance)
    return math.exp(log_scale) * quad(integrand, lo, hi, epsabs=0., epsrel=3e-12)[0]


def log_hit(x, t, mu, sigma):
    if t <= 0:
        return -math.inf
    scale = sigma*math.sqrt(t)
    return np.logaddexp(log_ndtr((-x-mu*t)/scale), -2*mu*x/sigma**2+log_ndtr((-x+mu*t)/scale))


def density_log(x, t, mu, sigma):
    return math.log(x/sigma)-.5*math.log(2*math.pi)-1.5*math.log(t)-(x+mu*t)**2/(2*sigma*sigma*t)


def integrate_panels(fun, panels):
    return math.fsum(quad(fun, a, b, epsrel=2e-10, epsabs=0., limit=120)[0]
                     for a, b in zip(panels, panels[1:]) if b > a)


def first_semigroup(x, t, mu, sigma, bounds=None):
    s = t*PLAN["semigroup"]["split_fraction"]
    # Full half-line integration; breakpoints cover both the early-hit bridge and central bulk.
    if bounds is None:
        conditional = lambda y: math.exp(log_hit(y, t-s, mu, sigma))
    else:
        conditional = lambda y: interval(y, t-s, mu, sigma, *bounds)
    def continuation(y):
        weight = pdf(y, x, s, mu, sigma)
        return weight*conditional(y) if weight else 0.
    branch = integrate_panels(continuation, [0., .04, .1, .2, .3, .4, .5, .6, .8, 1.2, 2., math.inf])
    initial = math.exp(log_hit(x, s, mu, sigma)) if bounds is None else 0.
    return initial, branch


def fd(func, inputs):
    gradient = []
    for j, v in enumerate(inputs):
        delta = 1e-6 * max(.05, abs(v))
        lo, hi = list(inputs), list(inputs)
        lo[j] -= delta
        hi[j] += delta
        gradient.append((func(*hi)-func(*lo))/(2*delta))
    return gradient


def relative(actual, expected):
    return abs(actual/expected-1.)


def source_checks():
    past = prior.verify_source()
    require(prior.sha256((SOURCE/"protocol.json").read_bytes()) == REPAIR["first_protocol_sha256"], "repair protocol has wrong primary source")
    require(REPAIR["same_relative_tolerance"] == GATE["one_reset_relative"] and REPAIR["same_times"] == PLAN["second_times"], "recovery gate drift")
    require(prior.sha256(prior.PROTOCOL.read_bytes()) == PLAN["previous_protocol_sha256"], "wrong first-passage protocol")
    require(prior.sha256(Path(prior.__file__).read_bytes()) == PLAN["previous_verifier_sha256"], "wrong first-passage verifier")
    for path, expected in PLAN["upstream_blobs"].items():
        _, package, suffix = path.split("/", 2)
        root = Path(next(iter(importlib.import_module("qualification."+package).__path__)))
        data = (root/suffix).read_bytes()
        actual = hashlib.sha1(b"blob "+str(len(data)).encode()+b"\x00"+data).hexdigest()
        require(actual == expected, "upstream Git blob mismatch: "+path)
    return dict(previous=past, additional_git_blobs=len(PLAN["upstream_blobs"]))


def first_row(edges, t, theta):
    x, deadline, mu, sigma = [T(v, True) for v in (.5, t, theta[1], theta[2])]
    params = PhysicalParameters(T(theta[0]), mu, sigma, T(theta[3]), T(theta[4]))
    mark = T(MARK, True)
    state = point_state(x, deadline, params, T(edges), T(PHASE), mark)
    row = state.probability[0]
    direct = row[:len(edges)-1].detach().tolist()
    old = TensorDiffusion(mu, sigma, params.discount).transition(x, deadline, T(edges)).survivor_bins.detach().tolist()
    check = [interval(.5, t, theta[1], theta[2], lo, hi) for lo, hi in zip(edges, edges[1:])]
    normal = [i for i, v in enumerate(check) if v >= sys.float_info.min]
    normal_error = max(relative(direct[i], check[i]) for i in normal)
    lost = [i for i in normal if old[i] == 0 and direct[i] > 0]
    tail_reference = interval(.5,t,theta[1],theta[2],edges[-1],math.inf)
    tail_error = relative(row[len(edges)-1].item(),tail_reference)
    mass_error = abs(row.sum().item()-1.)
    mark_error = float((state.content_mass.sum(1)-T(MARK)).abs().max().detach())
    require(normal_error < GATE["normal_bin_relative"] and mass_error < GATE["mass_absolute"], "one-step bins or total mass failed")
    require(tail_error < GATE["normal_bin_relative"], "survivor tail")
    deadlines = [mp.mpf(t) - (mp.mpf(PHASE[-1])-mp.mpf(edge)) for edge in PHASE]
    cumulative = [prior.reflected(.5,h,theta[1],theta[2]) if h>0 else mp.mpf(0) for h in deadlines]
    ref_phase = [b-a for a,b in zip(cumulative,cumulative[1:])]
    actual_phase = row[len(edges):].detach().tolist()
    phase_error = max(prior.rel(v,ref) if ref else abs(v) for v,ref in zip(actual_phase,ref_phase))
    require(phase_error < GATE["rare_phase_relative"], "separate refractory windows")
    phase_mass = row[len(edges):].sum().item()
    hit = float(prior.reflected(.5, t, theta[1], theta[2]))
    require(relative(phase_mass, hit) < GATE["rare_phase_relative"], "rare hit lost in refractory branch")
    rare_mark = state.content_mass[0,len(edges):].sum(0)
    rare_mark_grad = torch.autograd.grad(rare_mark.sum(), mark, retain_graph=True)[0]
    rare_mark_error = max(relative(v.item(),m*hit) for v,m in zip(rare_mark,MARK))
    rare_mark_gradient_error = max(relative(v.item(),hit) for v in rare_mark_grad)
    require(mark_error < GATE["marked_absolute"], "identity mark mass")
    require(max(rare_mark_error,rare_mark_gradient_error)<GATE["rare_phase_relative"], "rare refractory signed mass and gradient")
    # Gradients of a small left bin must be correct in relative units.
    grads = [v.item() for v in torch.autograd.grad(row[0], (x, deadline, mu, sigma))]
    fd_values = fd(lambda d, h, m, s: interval(d, h, m, s, edges[0], edges[1]), [.5, t, theta[1], theta[2]])
    gradient_error = max(relative(v, ref) for v, ref in zip(grads, fd_values))
    require(gradient_error < GATE["independent_gradient_relative"], "rare bin gradient")
    early, later = first_semigroup(.5, t, theta[1], theta[2])
    semigroup = {"hit_relative_error": relative(early+later, hit), "first_subinterval_hit": early,
                 "second_subinterval_hit_unconditional": later, "interval_relative_errors": {}}
    for i in PLAN["semigroup"]["interval_indexes"]:
        _, composed = first_semigroup(.5, t, theta[1], theta[2], (edges[i], edges[i+1]))
        semigroup["interval_relative_errors"][str(i)] = relative(composed, direct[i])
    require(max(semigroup["hit_relative_error"], *semigroup["interval_relative_errors"].values()) < GATE["semigroup_relative"], "continuous killed semigroup")
    return dict(horizon=t, normal_bins=len(normal), normal_bin_max_relative_error=normal_error, legacy_lost_normal_bins=lost,
                original_tail_difference_first_bin=old[0], stable_first_bin=direct[0], positive_integral_first_bin=check[0],
                first_bin_gradient=grads, first_bin_fd_max_relative_error=gradient_error,
                survivor_upper_tail=row[len(edges)-1].item(), survivor_upper_tail_relative_error=tail_error,
                phase_bin_probabilities=actual_phase, max_phase_bin_relative_error=phase_error,
                phase_probability=phase_mass, rare_phase_signed_mass=rare_mark.detach().tolist(),
                rare_mark_relative_error=rare_mark_error, rare_mark_gradient_relative_error=rare_mark_gradient_error, absolute_mass_error=mass_error, signed_mark_max_absolute_error=mark_error,
                semigroup=semigroup)


def second_integral(x, a, t, mu, sigma):
    h = t-.2
    log_scale = -(x+a)**2/(2*sigma**2*h)-mu*(x+a)/sigma**2
    def integrand(u):
        s = h*u
        return h*math.exp(density_log(x,s,mu,sigma) + log_hit(a,h-s,mu,sigma)-log_scale)
    return math.exp(log_scale)*integrate_panels(integrand,[0., .125, .25, .375, .5, .625, .75, .875, 1.])


def second_mp(x, a, t, mu, sigma):
    x,a,t,mu,sigma = map(mp.mpf, (x,a,t,mu,sigma))
    h = t-mp.mpf(.2)
    scale = -(x+a)**2/(2*sigma**2*h)-mu*(x+a)/sigma**2
    def integrand(u):
        if u <= 0 or u >= 1:
            return 0
        s = h*u
        dens = x*mp.exp(-(x+mu*s)**2/(2*sigma**2*s)-scale)/(sigma*mp.sqrt(2*mp.pi*s**3))
        return h*dens*prior.reflected(a,h-s,mu,sigma)
    return mp.exp(scale)*mp.quad(integrand,[0,.25,.375,.5,.625,.75,1])


def release_bin_integral(x, t, mu, sigma):
    h = t-.2
    def integrand(u):
        s=h*u
        return h*math.exp(density_log(x,s,mu,sigma))*interval(.5,h-s,mu,sigma,.5,.75)
    return integrate_panels(integrand,[0.,.125,.25,.5,.75,.9,.98,.995,1.])


def renewal(t):
    vals = (.5,.5,t,-.12,.5)
    x, a, duration, mu, sigma = [T(v,True) for v in vals]
    process = TensorDiffusion(mu,sigma,T(.15))
    reset = TensorReset(.5,.2)
    horizon = duration-reset.refractory
    second = _first_hit_logprob(x+a,horizon,mu,sigma).exp()
    gradients = [v.item() for v in torch.autograd.grad(second,(x,a,duration,mu,sigma))]
    oracle = second_mp(*vals)
    error = prior.rel(second.item(),oracle)
    independent = second_integral(*vals)
    gradient_error = max(relative(v, ref) for v,ref in zip(gradients,fd(second_integral,vals)))
    require(max(error, prior.rel(independent,oracle)) < GATE["one_reset_relative"] and gradient_error < GATE["independent_gradient_relative"],"second event or its gradients")
    edges=T(REPAIR["same_bins"])
    transition=regenerative_transition(process,reset,x,duration,edges,quadrature_order=96)
    released = _convolution(process,x,horizon,reset,edges,192)[2].item()
    # Released survivors in [.5,.75); freeze release geometry, integrate rather than difference aggregate states.
    h = t-.2
    independent_release=release_bin_integral(.5,t,-.12,.5)
    # Survivor increment + second event = mass of paths that released by the observation deadline.
    released_total = _convolution(process,x,horizon,reset,edges,192).sum().item()
    released_reference = float(prior.reflected(.5,h,-.12,.5))
    released_error = relative(released,independent_release)
    balance = relative(released_total+second.item(),released_reference)
    # Retain the original 192-point relative result. A separately declared time change addresses
    # the endpoint square-root term when the reset lies exactly on the destination bin edge.
    coarse = released_once(process,reset,x,duration,edges,order=64)
    corrected = released_once(process,reset,x,duration,edges,order=128)
    new_release_error = relative(corrected[2].item(),independent_release)
    new_balance = relative(corrected.sum().item()+second.item(),released_reference)
    order_difference = relative(coarse[2].item(),corrected[2].item())
    release_grads = torch.autograd.grad(corrected[2],(x,duration,mu,sigma))
    release_gradient_error = max(relative(v.item(),ref) for v,ref in zip(
        release_grads,fd(release_bin_integral,[.5,t,-.12,.5])))
    require(max(new_release_error,new_balance,order_difference) < GATE["one_reset_relative"],
            "endpoint-transformed released survivors")
    require(release_gradient_error < GATE["independent_gradient_relative"],"released survivor gradient")
    require(balance < GATE["one_reset_relative"],"original release total mass")
    m1 = prior.reflected(.5,t,-.12,.5)
    ref_phase = float(m1-prior.reflected(.5,h,-.12,.5)+oracle)
    phase=transition.refractory_bins.sum().item()
    active=transition.active_probability.item()
    require(abs(phase-ref_phase)<GATE["mass_absolute"] and abs(active+phase-1)<GATE["mass_absolute"], "original reset law mass")
    difference=(transition.expected_hits-transition.first_hit_probability).item()
    mark = T(MARK,True)
    assembled = once_renewed_state(process, reset, x, duration, edges, T(PHASE), mark)
    full_mass_error = abs(assembled.state.probability.sum().item()-1.)
    full_mark_error = (assembled.state.content_mass.sum(1)-mark).abs().max().item()
    gradients_mark = torch.autograd.grad(assembled.marked_second_event.sum(),mark)[0]
    event_mark_error = max(prior.rel(v.item(),oracle) for v in gradients_mark)
    one_phase_times = [mp.mpf(t)-(mp.mpf(.2)-mp.mpf(edge)) for edge in PHASE]
    one_cdf = [prior.reflected(.5,h,-.12,.5) if h>0 else mp.mpf(0) for h in one_phase_times]
    second_cdf = [second_integral(.5,.5,float(h),-.12,.5) if h>mp.mpf(.2) else 0. for h in one_phase_times]
    def phase_err(cdf, actual):
        return max(prior.rel(val.item(),b-a) if b>a else abs(val.item())
                   for val,a,b in zip(actual,cdf,cdf[1:]))
    first_phase_err = phase_err(one_cdf,assembled.first_phase)
    second_phase_err = phase_err(second_cdf,assembled.second_phase)
    require(max(full_mass_error, full_mark_error)<GATE["mass_absolute"] and
            max(event_mark_error,first_phase_err,second_phase_err)<GATE["one_reset_relative"],
            "full successor and its marked rare phases")
    return dict(horizon=t,second_event=second.item(),positive_convolution=mp.nstr(oracle,42),second_relative_error=error,
                second_gradient=gradients,independent_fd_gradient_max_relative_error=gradient_error,
                aggregate_expected_minus_first=difference,original_reset_active=active,original_reset_refractory=phase,
                original_expected_hits=transition.expected_hits.item(),original_mass_residual=transition.mass_residual.item(),
                full_successor_mass_error=full_mass_error,full_successor_mark_error=full_mark_error,
                first_phase_bin_relative_error=first_phase_err,second_phase_bin_relative_error=second_phase_err,
                first_phase_bins=assembled.first_phase.detach().tolist(),second_phase_bins=assembled.second_phase.detach().tolist(),
                second_event_mark=assembled.marked_second_event.detach().tolist(),second_mark_gradient_relative_error=event_mark_error,
                isolated_released_surviving_bin=released,positive_released_bin_integral=independent_release,
                original_released_bin_relative_error=released_error,original_released_bin_relative_gate_pass=bool(released_error<GATE["one_reset_relative"]),
                original_release_budget_relative_error=balance,original_renewal_terms=transition.terms,
                corrected_released_bin=corrected[2].item(),corrected_released_bin_relative_error=new_release_error,
                corrected_release_budget_relative_error=new_balance,corrected_order_relative_difference=order_difference,
                corrected_release_bin_gradients=[g.item() for g in release_grads],corrected_release_bin_fd_relative_error=release_gradient_error)


def mark_adapter():
    # Test a real caller on its own supported grid; its second step performs an explicit basis projection.
    grid = GridSpec(active_cells=8,endpoint=2.,phase_cells=4,refractory=.2,quadrature_order=16)
    operator = DifferentiableDistributionOperator(grid)
    params = PhysicalParameters(T(.01),T(-.12),T(.5),T(math.exp(.51)),T(.15))
    mark=T(MARK, True)
    state=point_state(T(.5),T(.01),params,T(grid.active_edges),T(grid.phase_edges),mark)
    flow=operator.advance(state.probability,state.content_mass,T([.005]),params)
    error=(flow.content_mass - flow.probability[...,None]*mark).abs().max().item()
    grads=torch.autograd.grad(flow.content_mass.sum(),mark)[0]
    gradient_error=(grads-1).abs().max().item()
    require(max(error,gradient_error)<GATE["marked_absolute"],"upstream signed-mark flow")
    return dict(grid_active_cells=8,phase_cells=4,initial_mark=MARK,projected_next_duration=.005,
                max_entrywise_content_mass_error=error,unit_mark_gradient_error=gradient_error,
                advanced_mass_residual=flow.mass_residual.item())


def evidence():
    mp.mp.dps=85
    source=source_checks()
    fixture=test_split.SplitMesh()
    fixture.setUp()
    theta=fixture.theta.copy()
    theta[2]=.5
    first=[]
    for geometry in test_split.GEOMETRIES:
        model,_=test_split.split_model(theta,**geometry)
        first.append(dict(geometry=geometry,rows=[first_row(model.spatial.nodes,t,theta) for t in PLAN["first_times"]]))
    result=dict(source_sha256={name:prior.sha256((SOURCE/name).read_bytes()) for name in ("protocol.json","repair_protocol.json","transport.py","verify.py","reset_gradient.py")},
                runtime=dict(python=platform.python_version(),numpy=np.__version__,torch=torch.__version__,scipy=scipy.__version__,mpmath=mp.__version__),
                upstream=PLAN["upstream"],scope=PLAN["scope"],sources=source,first=first,
                renewal=[renewal(t) for t in PLAN["second_times"]],marked_interface=mark_adapter(),
                reset_margin_gradient={str(t):certify_reset_gradient(t,T,second_integral)
                                       for t in PLAN["second_times"]})
    require(source_checks()==source,"upstream source drift")
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    body=json.dumps(evidence(),indent=2,allow_nan=False)+"\n"
    if args.output:
        args.output.write_text(body)
    else:
        print(body,end="")
