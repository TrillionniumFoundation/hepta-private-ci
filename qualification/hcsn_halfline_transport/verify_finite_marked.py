"""Compare physical, marked and cross-layer paths against independent calculations."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from qualification.hcsn_differentiable.contract import GridSpec, PhysicalParameters
from qualification.hcsn_differentiable.operator import DifferentiableDistributionOperator
from qualification.hcsn_halfline_transport.finite_marked import finite_marked_state

HERE = Path(__file__).resolve().parent
SPEC = json.loads((HERE / "finite_marked_protocol.json").read_text())
REFERENCE = HERE / "finite_marked_reference" / "result.json"
PARAMETERS = ("x", "mu", "sigma", "a", "d", "T", "m0_0", "m0_1", "R00", "R01", "R10", "R11")


def tensor(v, grad=False):
    return torch.tensor(v, dtype=torch.float64, requires_grad=grad)


def values(T, config=SPEC):
    return [config[k] for k in ("x","mu","sigma","a","d")] + [T, *SPEC["m0"], *np.ravel(SPEC["R"])]


def run(v, edges=None, fractions=None, points=None):
    return finite_marked_state(*v[:6], v[6:8], v[8:].reshape(2,2),
                               tensor(SPEC["edges"] if edges is None else edges),
                               tensor(SPEC["phase_fraction_edges"] if fractions is None else fractions),
                               tensor(SPEC["target_y"] if points is None else points))


def objective(o):
    p, c = o.state.probability.flatten(), o.state.content_mass.squeeze(0)
    return (p @ (torch.arange(1,1+p.numel()).to(p)/p.numel())
            + (c * (torch.arange(1,1+c.numel()).to(c).reshape(c.shape)/c.numel())).sum()
            + tensor([.37,-.21]) @ o.marked_cumulative_hits + tensor([-.08,.04]) @ o.marked_event_rate)


def numpy(v):
    return v.detach().cpu().numpy()


def compare(o, ref):
    fields = {k:getattr(o,k) for k in ("active_by_release","density_by_release","phase_by_hit","event_probability_by_hit",
                                        "event_rate_by_hit","marks","density_content","marked_cumulative_hits","marked_event_rate")}
    fields.update(P=o.state.probability[0], C=o.state.content_mass[0], density=o.density_by_release.sum(0),
                  cumulative_hits=o.event_probability_by_hit.sum(), event_rate=o.event_rate_by_hit.sum(), objective=objective(o))
    worst_abs = worst_relative = 0.0
    for k, field in fields.items():
        actual, expected = numpy(field), np.asarray(ref[k])
        assert actual.shape == expected.shape, k
        # Elementwise relative comparison, including the rare first released tail around 10^-89.
        np.testing.assert_allclose(actual, expected, rtol=4e-10, atol=1e-290, err_msg=k)
        diff = np.abs(actual-expected)
        worst_abs = max(worst_abs, float(diff.max()))
        mask = abs(expected)>1e-280
        if np.any(mask):
            worst_relative = max(worst_relative,float((diff[mask]/abs(expected[mask])).max()))
    return dict(compared_entries=sum(field.numel() for field in fields.values()), maximum_absolute=worst_abs,
                maximum_relative_above_1e_minus_280=worst_relative,
                state_mass_error=abs(float(o.state.probability.detach().sum())-1),
                active_release_generations=len(o.active_by_release)-1, possible_hits=len(o.phase_by_hit))


def downstream(v):
    grid = GridSpec(active_cells=5, endpoint=1., phase_cells=3, refractory=.14, quadrature_order=16)
    o = run(v,grid.active_edges,[0,1/3,2/3,1])
    op = DifferentiableDistributionOperator(grid)
    param = PhysicalParameters(tensor(0.),tensor(-.19),tensor(.57),tensor(1.31),tensor(.15))
    out = op.advance(o.state.probability,o.state.content_mass,.07,param)
    contrast = torch.linspace(.05,.86,out.probability.shape[1],dtype=torch.float64)
    loss = out.probability[0] @ contrast + (out.content_mass[0,:,0]-out.content_mass[0,:,1]) @ contrast.flip( (0,) )
    return loss,out


def extra_controls():
    # Original identity-mark point and one-release operator for its fixed source geometry.
    from qualification.hcsn_halfline_transport.transport import point_state, once_renewed_state
    from qualification.hcsn_regenerative.tensor import TensorDiffusion, TensorReset
    v=tensor(values(.21)); x,mu,sigma,a,d,T = v[:6]
    mk, eye, edges, frac, pts = v[6:8],torch.eye(2,dtype=v.dtype),tensor(SPEC["edges"]),tensor(SPEC["phase_fraction_edges"]),tensor(SPEC["target_y"])
    param=PhysicalParameters(tensor(0.),mu,sigma,a.exp(),tensor(.15))
    old0=point_state(x,tensor(.09),param,edges,d*frac,mk)
    new0=finite_marked_state(x,mu,sigma,a,d,tensor(.09),mk,eye,edges,frac,pts)
    old1=once_renewed_state(TensorDiffusion(mu,sigma,tensor(.15)),TensorReset(float(a),float(d)),x,T,edges,d*frac,mk,reset_margin=a)
    new1=finite_marked_state(x,mu,sigma,a,d,T,mk,eye,edges,frac,pts)
    errors = [float((u-vv).abs().max()) for u,vv in ((old0.probability,new0.state.probability),(old1.state.probability,new1.state.probability),
                                                         (old1.state.content_mass,new1.state.content_mass))]
    assert max(errors)<4e-12
    # At an exact multiple the newly eligible branch has zero mass. Check continuity from both sides.
    exact=run(tensor(values(.28)))
    nearby=[run(tensor(values(.28+u))) for u in (-1e-8,1e-8)]
    spread=max(float((exact.state.probability-q.state.probability).abs().max()) for q in nearby)
    assert len(exact.active_by_release)==2 and len(exact.phase_by_hit)==2 and spread<2e-7
    # Distinct physical reset maps must leave p invariant while transporting different content.
    changed=run(v)
    assert torch.equal(changed.state.probability,new1.state.probability)
    content_norm=float((changed.state.content_mass-new1.state.content_mass).abs().sum())
    assert content_norm>1e-3
    return dict(identity_upstream_max_abs=errors, exact_multiple_neighborhood_max_abs=spread,
                changed_marks_probability_bit_identical=True, changed_content_l1=content_norm)


def precision_controls():
    import mpmath as mp
    from qualification.hcsn_halfline_transport.finite_marked_reference.reference import compute
    near = []
    for x, edge in ((1e-5,1e-5),(1e-7,1e-4)):
        v = tensor([x,0.,1.,.2,2.,1.,*SPEC["m0"],*np.ravel(SPEC["R"])],True)
        cell = run(v,[0,edge,1],fractions=[0,1]).active_by_release[0,0]
        derivative = torch.autograd.grad(cell,v)[0][0]
        with mp.workdps(70):
            distance,limit = mp.mpf(str(x)),mp.mpf(str(edge))
            def probability(start):
                def density(y):
                    return mp.exp(-(y-start)**2/2)*(-mp.expm1(-2*start*y))/mp.sqrt(2*mp.pi)
                return mp.quad(density,[0,limit])
            reference = float(probability(distance))
            reference_dx = float(mp.diff(probability,distance))
        relative=abs(float(cell.detach())/reference-1)
        relative_dx=abs(float(derivative)/reference_dx-1)
        assert max(relative,relative_dx)<2e-12
        near.append(dict(x=x,edge=edge,mass=float(cell.detach()),relative=relative,relative_dx=relative_dx))
    tiny_fraction = 1.-2.**-42
    v=tensor([1e-5,0.,1.,.2,2.,1.,*SPEC["m0"],*np.ravel(SPEC["R"])])
    tiny_phase=run(v,fractions=[0,tiny_fraction,1]).phase_by_hit[0,-1]
    with mp.workdps(70):
        lo=mp.mpf(1)-mp.mpf(2)**-41
        distance=mp.mpf('1e-5')
        phase_ref=float(mp.quad(lambda t: distance*mp.exp(-distance**2/(2*t))/mp.sqrt(2*mp.pi*t**3),[lo,1]))
    phase_relative=abs(float(tiny_phase)/phase_ref-1)
    assert phase_relative<2e-12
    positive=values(.61)
    positive[1]=.48
    other=run(tensor(positive))
    result=compare(other,compute(positive))
    try:
        finite_marked_state(*(tensor(y) for y in (.01,-1.,.01,.1,.1,.01,[1e307],[[1.]],[0,.01,.1],[0,1],[.01])))
    except FloatingPointError as exc:
        assert "marked output" in str(exc)
    else:
        raise AssertionError("unrepresentable marked emission must be rejected")
    return dict(near_absorbing_boundary=near,positive_drift=result,unrepresentable_marked_rate_rejected=True,
                narrow_phase_mass=float(tiny_phase),narrow_phase_relative=phase_relative)


def verify(reference=REFERENCE):
    fixture=json.loads(reference.read_text())
    report={"torch":str(torch.__version__),"reference_sha256":hashlib.sha256(reference.read_bytes()).hexdigest(), "panels":{}}
    for T in SPEC["horizons"]:
        report["panels"][str(T)]=compare(run(tensor(values(T))),fixture["horizons"][str(T)])
    rare=SPEC["rare"]
    r=run(tensor(values(rare["T"],rare)),rare["edges"],points=rare["target_y"])
    report["rare"]=compare(r,fixture["rare"])
    report["rare"].update(first_released_tail=float(r.active_by_release[1,-1]))
    v=tensor(values(.61),True)
    objective_value=objective(run(v))
    grad=torch.autograd.grad(objective_value,v)[0]
    fd=[fixture["objective_fd"][k]["h_1e-5"] for k in PARAMETERS]
    np.testing.assert_allclose(numpy(grad),fd,rtol=1e-7,atol=2e-9)
    report["objective"]=float(objective_value.detach())
    report["derivatives"]={k:dict(autograd=float(g), independent_fd=f, absolute_error=abs(float(g)-f)) for k,g,f in zip(PARAMETERS,grad,fd)}
    loss,out=downstream(v)
    downstream_grad=torch.autograd.grad(loss,v)[0]
    step=1e-5
    fd=[]
    for j in range(len(v)):
        delta=torch.zeros_like(v);delta[j]=step
        fd.append(float((downstream(v.detach()+delta)[0]-downstream(v.detach()-delta)[0])/(2*step)))
    np.testing.assert_allclose(numpy(downstream_grad),fd,rtol=1e-6,atol=2e-8)
    assert float(downstream_grad.abs().min())>1e-5
    report["next_native_operator"]=dict(loss=float(loss.detach()),mass_residual=abs(float(out.mass_residual.detach())),
        gradient_order=PARAMETERS,gradient=numpy(downstream_grad).tolist(),maximum_fd_error=float(np.abs(numpy(downstream_grad)-fd).max()))
    report["controls"]=extra_controls()
    report["precision_controls"]=precision_controls()
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path)
    parser.add_argument("--reference",type=Path,default=REFERENCE)
    args=parser.parse_args()
    result=json.dumps(verify(args.reference),indent=2,allow_nan=False)+"\n"
    if args.output:
        args.output.write_text(result)
    else:
        print(result,end="")
