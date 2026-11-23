"""Two point-source neurons with a stationary optimal trigger and finite marked renewal.

No optimization. Each neuron's eight physical/economic parameters are independent.
From the repository root, run with --help for source and output paths.
"""
import argparse
from hashlib import sha256
import inspect
import json
import math
from pathlib import Path
import sys

import numpy as np
from scipy.special import lambertw, ndtr

NAMES = ('mu','sigma','discount','log_reset','refractory','gain','maintenance','spike_cost')
A = (-.15, .35, .2, 1., .25, 1., .4, .3)
B = (-.4, .6, .35, 1.2, .4, .7, .3, .5)
A_INITIAL = .72
HORIZONS = (.67, .91)
OFFSET, DIRECT, SIGNED = .32, .31, .48
MARKS = ([.8, -.35], [-.42, .73])
RESET_MAPS = ([[-.45,.2],[.16,.6]], [[.71,-.11],[.23,-.48]])
PROJECTION = [.63, -.41]
EDGES, FRACTIONS, POINTS = [0,.12,.39,.82,1.43], [0,.25,.7,1], [.09,.32,.87]
STEPS = [1e-5, 5e-6]
GRADIENT_ATOL, GRADIENT_RTOL = 3e-8, 2e-6
BOUNDARY_SHA = '60bf3cc067f75a05f83f0f29978c7939fa91a7815858b5cc2becf0e62428dc3f'
RENEWAL_SHA = '17dc69be5af6e2f5e44bffd7496fef182985beb3697e93357bb81dad352c3fc2'


def scalar_boundary(theta):
    """Principal real Lambert-W root for the stationary affine-reward impulse problem."""
    mu, sigma, rho, reset, delay, gain, maintenance, cost = theta
    k = 2*rho / (math.hypot(mu, math.sqrt(2*rho)*sigma) - mu)
    eta = math.exp(-rho*delay)
    d0 = -math.expm1(-rho*delay)*(reset+mu/rho-maintenance/gain) + 1/k + cost*rho/gain
    arg = -eta*math.exp(-k*d0)
    if not -1/math.e < arg < 0:
        raise ArithmeticError('reference left the interior threshold regime')
    return reset - d0 - float(lambertw(arg, k=0).real)/k


def scalar_first_hit(z, t, mu, sigma):
    if t <= 0:
        return 0.
    std = sigma*math.sqrt(t)
    return float(ndtr((-z-mu*t)/std) + math.exp(-2*mu*z/sigma**2)*ndtr((-z+mu*t)/std))


def scalar_neuron(theta, initial, horizon, mark, reset_map):
    """Total marked hits and the final refractory probability without bins or Torch."""
    boundary = scalar_boundary(theta)
    mu, sigma, _, reset, refractory, *_ = theta
    x, a = initial-boundary, reset-boundary
    assert x > 0 and a > 0
    signed = np.zeros(len(mark))
    phase = 0.
    hits = []
    for k in range(math.ceil(horizon/refractory)):
        distance, t = x + k*a, horizon-k*refractory
        hit = scalar_first_hit(distance, t, mu, sigma)
        hits.append(hit)
        signed += hit * np.linalg.matrix_power(np.asarray(reset_map),k).dot(mark)
        phase += hit - scalar_first_hit(distance, t-refractory, mu, sigma)
    return dict(boundary=boundary, hit_probabilities=hits, marked_hits=signed, terminal_phase=phase)


def independent(theta):
    source = scalar_neuron(theta[:8], A_INITIAL, HORIZONS[0], MARKS[0], RESET_MAPS[0])
    signed = float(np.dot(PROJECTION, source['marked_hits']))
    next_initial = OFFSET + DIRECT*source['boundary'] + SIGNED*signed
    target = scalar_neuron(theta[8:], next_initial, HORIZONS[1], MARKS[1], RESET_MAPS[1])
    return source, target, next_initial


def reference_gradient(theta, step):
    rows = []
    for j in range(len(theta)):
        delta = np.zeros_like(theta)
        delta[j] = step
        plus, minus = independent(theta+delta)[1], independent(theta-delta)[1]
        rows.append((plus['terminal_phase']-minus['terminal_phase'])/(2*step))
    return np.asarray(rows)


def verify(qvi_root, renewal_root):
    sys.path[:0] = [str(qvi_root), str(renewal_root)]
    import torch
    from qualification.hcsn_differentiable.neural_control import PARAMETER_NAMES, optimal_boundary
    from qualification.hcsn_halfline_transport.finite_marked import finite_marked_state
    torch.set_num_threads(1)
    assert tuple(PARAMETER_NAMES) == NAMES
    sources = {}
    for label, function, expected_dir in [('qvi',optimal_boundary,qvi_root),
                                           ('renewal',finite_marked_state,renewal_root)]:
        path = Path(inspect.getsourcefile(function)).resolve()
        assert path.is_relative_to(expected_dir.resolve())
        sources[label] = dict(file=path.relative_to(expected_dir.resolve()).as_posix(),
                              sha256=sha256(path.read_bytes()).hexdigest())
    assert sources['qvi']['sha256'] == BOUNDARY_SHA and sources['renewal']['sha256'] == RENEWAL_SHA
    def tensor(x):
        return torch.as_tensor(x, dtype=torch.float64)
    def graph(raw, *, freeze_first_root=False, stop_boundary_message=False, stop_mark_message=False):
        parameters = tensor(raw).clone().requires_grad_()
        aa, bb = parameters[:8], parameters[8:]
        geometry = tuple(map(tensor,(EDGES,FRACTIONS,POINTS)))
        def state(t, b, initial, index):
            return finite_marked_state(initial-b,t[0],t[1],t[3]-b,t[4],tensor(HORIZONS[index]),
                                       tensor(MARKS[index]),tensor(RESET_MAPS[index]),*geometry)
        b1 = optimal_boundary(aa)
        if freeze_first_root:
            b1 = b1.detach()
        first = state(aa,b1,tensor(A_INITIAL),0)
        signed = torch.dot(tensor(PROJECTION),first.marked_cumulative_hits)
        bm = b1.detach() if stop_boundary_message else b1
        sm = signed.detach() if stop_mark_message else signed
        initial2 = OFFSET + DIRECT*bm + SIGNED*sm
        b2 = optimal_boundary(bb)
        second = state(bb,b2,initial2,1)
        phase_count = len(FRACTIONS)-1
        risk = second.state.probability[0,-phase_count:].sum()
        assert torch.allclose(risk,second.phase_by_hit.sum(),rtol=0.,atol=2e-15)
        grad = torch.autograd.grad(risk, parameters,retain_graph=True)[0].detach().numpy()
        snapshot = {}
        for title, out, boundary, initial, t in [('A',first,b1,tensor(A_INITIAL),aa),('B',second,b2,initial2,bb)]:
            snapshot[title] = dict(boundary=float(boundary.detach()),absolute_initial=float(initial.detach()),
                                   initial_margin=float((initial-boundary).detach()),reset_margin=float((t[3]-boundary).detach()),
                                   mass=float(out.state.probability.detach().sum()),terminal_phase=float(out.phase_by_hit.detach().sum()),
                                   hit_probabilities=out.event_probability_by_hit.detach().tolist(),
                                   marked_hits=out.marked_cumulative_hits.detach().tolist())
        snapshot['signed_message'] = float(signed.detach())
        return grad, snapshot
    theta=np.array(A+B)
    grad, snapshot = graph(theta)
    sf, target, next_initial = independent(theta)
    comparisons=[]
    for key, reference in [('A',sf),('B',target)]:
        panel=snapshot[key]
        for field in ('boundary','marked_hits','hit_probabilities','terminal_phase'):
            real, ref=np.asarray(panel[field]),np.asarray(reference[field])
            comparisons.append(float(np.max(np.abs(real-ref))))
        assert abs(panel['mass']-1) < 4e-12
    assert abs(snapshot['B']['absolute_initial']-next_initial) < 2e-13 and max(comparisons)<2e-12
    fd_by_step={}
    for step in STEPS:
        fd = reference_gradient(theta,step)
        np.testing.assert_allclose(grad,fd,atol=GRADIENT_ATOL,rtol=GRADIENT_RTOL)
        fd_by_step[str(step)] = dict(values=fd.tolist(),max_error=float(np.max(abs(grad-fd))))
    direct, direct_snapshot = graph(theta,stop_mark_message=True)
    marked, marked_snapshot = graph(theta,stop_boundary_message=True)
    frozen, frozen_snapshot = graph(theta,freeze_first_root=True)
    both, both_snapshot = graph(theta,stop_mark_message=True,stop_boundary_message=True)
    for s in (direct_snapshot,marked_snapshot,frozen_snapshot,both_snapshot):
        assert s == snapshot
    np.testing.assert_allclose(direct[:8]+marked[:8],grad[:8],atol=5e-13,rtol=4e-13)
    assert np.array_equal(both[:8],np.zeros(8))
    economics = [2,5,6,7]
    assert np.array_equal(frozen[economics],np.zeros(4))
    assert np.min(np.abs(grad[economics]))>1e-7 and np.min(np.abs(grad[8+np.array(economics)]))>1e-7
    np.testing.assert_array_equal(both[8:], grad[8:])
    perturbations = {}
    for coordinate in ('gain', 'spike_cost'):
        changed = theta.copy()
        changed[NAMES.index(coordinate)] += .01
        _, new = graph(changed)
        reference_source, reference_target, _ = independent(changed)
        assert abs(new['B']['terminal_phase']-reference_target['terminal_phase']) < 2e-12
        assert abs(new['A']['boundary']-reference_source['boundary']) < 2e-12
        db = new['A']['boundary']-snapshot['A']['boundary']
        dg = new['B']['terminal_phase']-snapshot['B']['terminal_phase']
        assert abs(db) > 1e-5 and abs(dg) > 1e-5
        perturbations[coordinate] = dict(increase=.01, boundary_change_A=db,
            marked_vector_change_A=(np.asarray(new['A']['marked_hits']) - snapshot['A']['marked_hits']).tolist(),
            terminal_phase_B=new['B']['terminal_phase'], terminal_phase_change_B=dg)
    return dict(perturbations=perturbations,protocol=dict(theta_names=NAMES,theta_A=A,theta_B=B,horizons=HORIZONS,log_initial_A=A_INITIAL,
                              input_B_coefficients=dict(offset=OFFSET,boundary=DIRECT,signed_hits=SIGNED),
                              projection=PROJECTION,marks=MARKS,linear_reset_maps=RESET_MAPS,active_edges=EDGES,
                              phase_fractions=FRACTIONS,density_probes=POINTS,gradient_atol=GRADIENT_ATOL,
                              gradient_rtol=GRADIENT_RTOL),sources=sources,torch_version=str(torch.__version__),
                snapshot=snapshot,maximum_reference_forward_error=max(comparisons),
                terminal_risk_gradient_A=grad[:8].tolist(),terminal_risk_gradient_B=grad[8:].tolist(),
                numerical_reference=fd_by_step,controls_A=dict(boundary_message_only=direct[:8].tolist(),
                    marked_message_only=marked[:8].tolist(),fixed_source_root=frozen[:8].tolist(),
                    both_messages_fixed=both[:8].tolist()),receipt='finite stationary two-cell CPU FP64 probe')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qvi-root', required=True, type=Path,
                        help='checkout root containing qualification/hcsn_differentiable/neural_control.py')
    parser.add_argument('--renewal-root',required=True,type=Path,help='checkout root containing the finite marked candidate')
    parser.add_argument('--output',type=Path)
    cfg=parser.parse_args()
    text=json.dumps(verify(cfg.qvi_root,cfg.renewal_root),sort_keys=True,indent=2,allow_nan=False)+'\n'
    if cfg.output:
        cfg.output.write_text(text)
    else:
        print(text,end='')
