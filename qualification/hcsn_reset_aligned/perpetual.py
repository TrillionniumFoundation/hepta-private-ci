"""Implicit perpetual-value derivatives from the same reset-aligned generator."""

import math

import numpy as np

from qualification.hcsn_reset_aligned.mesh import aligned_model


def perpetual_partials(theta, geometry):
    """Return values at nodes 1..N plus reset, and their five partials.

    Upper value is the permanently-active a/q value; the lower cemetery is
    excluded. This differentiates the discrete shared-generator closure, not
    a continuum surrogate or an externally fixed physical-prior migration.
    """
    model, derivatives = aligned_model(theta, **geometry)
    transient, lower, _, reset = model.ingredients()
    q, a, h, delay = model.discount, model.active_reward, model.hit_reward, model.delay
    operator = q*np.eye(len(lower))-transient
    phi = np.linalg.solve(operator, lower)
    dq = np.array([0., 0., 0., 0., 1.])
    rhs = (derivatives[:, 1:-1, 0] + np.einsum("pij,j->pi", derivatives[:, 1:-1, 1:-1], phi)
           - dq[:, None]*phi)
    dphi = np.linalg.solve(operator, rhs.T).T
    rho, drho = float(reset@phi), dphi@reset
    base, eta = a/q, math.exp(-q*delay)
    dbase, deta = -a*dq/q**2, -delay*eta*dq
    numerator, denominator = base*(1-rho)+h*rho, 1-eta*rho
    reset_value = numerator/denominator
    dn = dbase*(1-rho)+(h-base)*drho
    dd = -deta*rho-eta*drho
    dreset = (dn-reset_value*dd)/denominator
    coefficient = h+eta*reset_value-base
    dc = deta*reset_value+eta*dreset-dbase
    values = np.r_[base+phi*coefficient, base, reset_value]
    jacobian = np.vstack(((dbase[:, None]+dphi*coefficient+phi*dc[:, None]).T,
                          dbase[None], dreset[None]))
    if not np.isfinite(values).all() or not np.isfinite(jacobian).all():
        raise ArithmeticError("shared-generator continuation derivative unresolved")
    return values, jacobian
