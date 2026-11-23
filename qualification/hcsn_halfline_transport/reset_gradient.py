"""Regression for the reset-location VJP of the *complete* one-renewal successor."""
import math

import torch
from scipy.integrate import quad
from scipy.special import ndtr

from qualification.hcsn_regenerative.tensor import TensorDiffusion, TensorReset
from .transport import once_renewed_state


def _normal_interval(left, right):
    if left >= 0:
        return ndtr(-left) - ndtr(-right)
    return ndtr(right) - ndtr(left)


def _release_reference(margin, time, derivative=False):
    """Independent adaptive time integral of the Gaussian image formula or its analytic derivative."""
    x, mu, sigma = .5, -.12, .5
    lo, hi = .5, .75
    h = time - .2
    log_density = lambda t: math.log(x / (sigma * math.sqrt(2 * math.pi))) - 1.5 * math.log(t) - (x + mu*t)**2 / (2 * sigma*sigma*t)
    log_scale = log_density(h)
    image = math.exp(-2 * mu * margin / sigma**2)

    def integrand(z):
        # Remaining active time is h*z^2. The time Jacobian makes the edge gradient integrable at z=0.
        s = h * (1-z) * (1+z)
        if s <= 0 or z <= 0:
            return 0.
        remaining = h * z*z
        width = sigma * math.sqrt(remaining)
        zlo, zhi = ((edge-margin-mu*remaining)/width for edge in (lo, hi))
        wlo, whi = ((edge+margin-mu*remaining)/width for edge in (lo, hi))
        image_interval = _normal_interval(wlo, whi)
        if derivative:
            normal_pdf = lambda v: math.exp(-v*v/2) / math.sqrt(2*math.pi)
            weight = ((normal_pdf(zlo)-normal_pdf(zhi)) / width
                      + 2*mu*image*image_interval / sigma**2
                      + image*(normal_pdf(wlo)-normal_pdf(whi)) / width)
        else:
            weight = _normal_interval(zlo,zhi) - image*image_interval
        return 2*h*z*math.exp(log_density(s)-log_scale)*weight

    offset = abs(margin-lo)/(sigma*math.sqrt(h))
    panels = sorted({0., 1., .01, .1, .25, .5, .75, *(v for v in (offset/8,offset,offset*8) if 0<v<1)})
    total = math.fsum(quad(integrand, a, b, epsabs=1e-15, epsrel=3e-12)[0]
                      for a,b in zip(panels,panels[1:]))
    return math.exp(log_scale)*total


def certify(time, tensor, fd_second):
    """Check both originally fixed deadlines; derivatives hold initial distance and bin edges fixed."""
    process = TensorDiffusion(tensor(-.12),tensor(.5),tensor(.15))
    reset = TensorReset(.5,.2)
    args = (process,reset,tensor(.5),tensor(time),tensor([0.,.25,.5,.75,1.,2.]),
            tensor([0.,.1,.195,.2]),tensor([-.4,.75]))
    fixed = once_renewed_state(*args)
    boundary, absolute_reset = tensor(.01,True),tensor(math.exp(.51),True)
    margin = absolute_reset.log()-boundary
    state = once_renewed_state(*args,reset_margin=margin)
    for name in ("original_survivors","released_survivors","first_phase","second_phase","first_event","second_event","marked_second_event"):
        if not torch.equal(getattr(state,name),getattr(fixed,name)):
            raise ArithmeticError("fixed and differentiable forward fields differ: "+name)
    if not torch.equal(state.state.probability,fixed.state.probability) or not torch.equal(state.state.content_mass,fixed.state.content_mass):
        raise ArithmeticError("fixed and differentiable full state mismatch")
    try:
        TensorReset(margin,.2)
    except ValueError:
        pass
    else:
        raise ArithmeticError("upstream fixed reset contract changed")

    # Frozen bin [.5,.75) has its left edge exactly at the nominal reset.
    def grad(output, independent=margin):
        return torch.autograd.grad(output, independent, retain_graph=True)[0].item()

    ref = _release_reference(.5,time,derivative=True)
    rel = lambda value, expected: abs(value/expected-1.)
    fd_rows=[]
    for step in (4e-8,2e-8):
        approximation = (_release_reference(.5+step,time)-_release_reference(.5-step,time))/(2*step)
        fd_rows.append(dict(step=step,gradient=approximation,relative_error=rel(approximation,ref)))
    event_step=2e-7
    event_fd=(fd_second(.5,.5+event_step,time,-.12,.5)-fd_second(.5,.5-event_step,time,-.12,.5))/(2*event_step)
    outputs = {
        "isolated_release_bin": (grad(state.released_survivors[2]),ref),
        "full_successor_bin": (grad(state.state.probability[0,2]),ref),
        "full_signed_content_bin": (grad(state.state.content_mass[0,2,0]),-.4*ref),
        "full_bin_log_boundary_at_fixed_initial_distance": (grad(state.state.probability[0,2],boundary),-ref),
        "full_bin_absolute_reset_at_fixed_initial_distance": (grad(state.state.probability[0,2],absolute_reset),ref/math.exp(.51)),
        "second_event": (grad(state.second_event),event_fd),
        "second_phase_sum": (grad(state.second_phase.sum()),event_fd),
        "signed_second_event": (grad(state.marked_second_event[0]),-.4*event_fd),
    }
    checks={name:dict(autograd=value,independent=expected,relative_error=rel(value,expected))
            for name,(value,expected) in outputs.items()}
    if max(item["relative_error"] for name,item in checks.items() if name not in ("second_event","second_phase_sum","signed_second_event"))>2e-9:
        raise ArithmeticError("reset derivative of full survivor or content failed against differentiated integral")
    if max(item["relative_error"] for item in checks.values())>3e-5 or max(row["relative_error"] for row in fd_rows)>3e-5:
        raise ArithmeticError("reset derivative failed independent adaptive finite differences")
    return dict(upstream_tensor_reset_requires_fixed_float=True,default_float_forward_bitwise_identical=True,
                fixed_initial_distance=.5,reset_distance=.5,frozen_surviving_bin=[.5,.75],
                release_bin_centered_differences=fd_rows,second_event_fd_step=event_step,checks=checks)
