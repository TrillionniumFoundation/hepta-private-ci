"""Independent numerical checks: Green quadrature, free-boundary BVP, debt PDE.

No reference solver calls the closed equity formula or the explicit boundary.
They may consume the separately PDE-checked closed debt forcing term.
"""

import math
import numpy as np
from scipy.integrate import quad, solve_bvp
from scipy.optimize import brentq
from scipy.sparse import diags, eye
from scipy.sparse.linalg import splu


def _layer_quad(function, left, right, model):
    """Do not let adaptive quadrature skip a short-maturity boundary layer."""
    s = model.s
    candidates = [s, 4*s, 12*s, abs(model.a)*s*s+12*s]
    cuts = [left]+sorted(set(x for x in candidates if left < x < right))+[right]
    return sum(quad(function, a, b, epsabs=1e-10, epsrel=2e-11, limit=200)[0]
               for a, b in zip(cuts[:-1], cuts[1:]))


def green_equity(model, x, boundary):
    """Solve the inhomogeneous equity ODE using its absorbing Green kernel."""
    x = float(x)
    if x == 0:
        return 0.
    gamma, eta = model.gamma, model.eta
    base = boundary*(math.exp(x)-math.exp(-gamma*x))
    base += model.constant_cost/model.p.r*math.expm1(-gamma*x)
    scale = model.z*model.s2
    lo = _layer_quad(lambda y: math.exp(-gamma*(x-y))*(-math.expm1(-2*model.z*y))
              *float(model.debt_decay(y, boundary))/scale,
              0., x, model)
    hi = _layer_quad(lambda y: math.exp(-eta*(y-x))*(-math.expm1(-2*model.z*x))
              *float(model.debt_decay(y, boundary))/scale,
              x, np.inf, model)
    return base+lo+hi


def boundary_from_quadrature(model):
    """Numerically solve E_x(0;b)=0; do not use Eq.(12)."""
    def slope(boundary):
        correction = _layer_quad(lambda y: math.exp(-model.eta*y)*float(model.debt_decay(y, boundary)),
                                0., np.inf, model)
        return boundary*(1+model.gamma)-model.constant_cost*model.gamma/model.p.r+2/model.s2*correction
    return brentq(slope, 1e-7, 100*(model.p.principal+model.p.coupon), xtol=1e-11)


def boundary_and_equity_bvp(model, tol=1e-7):
    """Collocation free-boundary solve with unknown b and 3 boundary conditions.

    A 1e-7 local residual target avoids roundoff-driven mesh overrefinement
    around the narrow short-maturity layer. Independent value and boundary
    acceptance thresholds are imposed separately by run_validation.py.
    """
    xmax = max(5., abs(model.a)*model.s2*model.p.maturity+10*model.s+1.)
    x = np.linspace(0, xmax, 400)
    guess_b = max(.2*model.p.principal, 1.)
    guess = np.vstack((guess_b*np.expm1(x), guess_b*np.exp(x)))

    def ode(xx, yy, parameter):
        b = parameter[0]
        forcing = model.net_cashflow(xx, b)
        return np.vstack((yy[1], 2/model.s2*(model.p.r*yy[0]-model.a*model.s2*yy[1]-forcing)))

    def bc(left, right, parameter):
        b = parameter[0]
        far = right[1]+model.gamma*right[0]-(model.gamma+1)*b*math.exp(xmax)
        far += model.gamma*model.constant_cost/model.p.r
        return np.array([left[0], left[1], far])

    def ode_jac(xx, yy, parameter):
        state_jac = np.zeros((2, 2, xx.size))
        state_jac[0, 1] = 1.
        state_jac[1, 0] = 2*model.p.r/model.s2
        state_jac[1, 1] = -2*model.a
        param_jac = np.zeros((2, 1, xx.size))
        _, g = model.first_hit(xx, model.p.maturity)
        param_jac[1, 0] = -2/model.s2*(model.p.delta*np.exp(xx)+model.p.alpha/model.p.maturity*g)
        return state_jac, param_jac

    def bc_jac(left, right, parameter):
        left_jac = np.array([[1., 0.], [0., 1.], [0., 0.]])
        right_jac = np.array([[0., 0.], [0., 0.], [model.gamma, 1.]])
        parameter_jac = np.array([[0.], [0.], [-(model.gamma+1)*math.exp(xmax)]])
        return left_jac, right_jac, parameter_jac

    sol = solve_bvp(ode, bc, x, guess, p=np.array([guess_b]), tol=tol, max_nodes=20000,
                    fun_jac=ode_jac, bc_jac=bc_jac)
    if not sol.success:
        location = float(sol.x[int(np.argmax(sol.rms_residuals))])
        raise RuntimeError(f"Free-boundary BVP failed: {sol.message}; "
                           f"max residual={max(sol.rms_residuals):.3g} at x={location:.6g}")
    return sol


def debt_pde(model, boundary, space_points=1200, time_steps=600):
    """Crank--Nicolson with two Rannacher-smoothed starting steps.

    Solve d_tau=.5 sigma^2 d_xx+a sigma^2 d_x-R d+c.
    The payoff/boundary corner is discontinuous; half-size backward Euler
    startup steps damp the resulting high-frequency modes.
    """
    xmax = max(3., abs(model.a)*model.s2*model.p.maturity+8*model.s+1.5)
    x = np.linspace(0, xmax, space_points+1)
    dx, dt = x[1]-x[0], model.p.maturity/time_steps
    d = model.s2/2
    drift = model.a*model.s2
    lower, diag, upper = d/dx**2-drift/(2*dx), -2*d/dx**2-model.R, d/dx**2+drift/(2*dx)
    n = space_points-1
    op = diags([np.full(n-1, lower), np.full(n, diag), np.full(n-1, upper)], [-1, 0, 1], format="csc")
    ident = eye(n, format="csc")
    cn_solve = splu(ident-.5*dt*op)
    be_solve = splu(ident-.5*dt*op)
    old_op = ident+.5*dt*op
    current = np.full(n, model.principal_unit)
    low_boundary = model.p.alpha*boundary/model.p.maturity

    def high_boundary(t):
        return model.c/model.R+math.exp(-model.R*t)*model.q

    # Four half steps consume two of time_steps steps.
    for k in range(4):
        t = (k+1)*dt/2
        rhs = current+dt/2*model.c
        rhs[0] += dt/2*lower*low_boundary
        rhs[-1] += dt/2*upper*high_boundary(t)
        current = be_solve.solve(rhs)
    for k in range(2, time_steps):
        rhs = old_op @ current+dt*model.c
        rhs[0] += dt*lower*low_boundary
        rhs[-1] += dt/2*upper*(high_boundary(k*dt)+high_boundary((k+1)*dt))
        current = cn_solve.solve(rhs)
    return x, np.r_[low_boundary, current, high_boundary(model.p.maturity)]
