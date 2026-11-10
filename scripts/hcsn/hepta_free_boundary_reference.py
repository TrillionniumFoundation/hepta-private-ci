#!/usr/bin/env python3
"""Hepta free-boundary research reference, 2026-11-05.

Run: python hepta_free_boundary_reference.py
Dependencies: Python 3.10+, numpy, scipy.
Prints a JSON report and fails if its stated numerical checks fail.

This is an independent numerical reference, not a trained HCSN or a Hepta
runtime integration. It implements:
  * Brownian log-margin first-passage CDF, discounted CDF, density, Laplace kernel;
  * He--Xiong's stationary finite-maturity debt, boundary, and equity formulas;
  * a separately labelled constant-carry, no-rollover equity special case;
  * independent quadrature, generator-residual, and derivative checks.

Source for HX formulas: Zhiguo He and Wei Xiong (2012), Rollover Risk and Credit
Risk, Journal of Finance 67(2), DOI 10.1111/j.1540-6261.2012.01721.x,
equations (8), (9), (12), (A5), (A7).
https://zhiguohe.net/wp-content/uploads/2023/12/The-Journal-of-Finance-2012-HE-Rollover-Risk-and-Credit-Risk.pdf

For x=log(V/b)>0, dx=mu*dt+sigma*dW. Lower-boundary crossing is absorption.
The density is a first-event density, NOT the stationary rate of a resetting
neuron. The functions are evaluated on the surviving domain; no hidden clamp
or smooth extension across the boundary is applied. Boundary risk is not a
vanilla put. Value functions do not define a recurrent vector field.

Scope: float64 reference at regular parameters. HX equity intentionally requires
positive liquidity premium and is not engineered for zero-premium limits,
extreme tails, near-zero horizons/volatilities, low precision, or trainable
moving boundaries. Those require analytic limits and further numerical work.
Gradient checks here concern interior formulas, not tensor-autograd, event
resets, full-network BPTT, or empirical learning performance.
"""

from dataclasses import dataclass, replace
import json
import math
import numpy as np
from scipy.integrate import quad
from scipy.special import ndtr, log_ndtr


def _exp_phi(exponent, argument):
    """Evaluate exp(exponent)*Phi(argument) without separate tail underflow."""
    return np.exp(exponent + log_ndtr(argument))


def first_passage_cdf(x, horizon, mu, sigma):
    """P(tau_0 <= horizon), x>=0, horizon>0, sigma>0. No reset."""
    scale = sigma * np.sqrt(horizon)
    return ndtr((-x-mu*horizon)/scale) + _exp_phi(
        -2*mu*x/sigma**2, (-x+mu*horizon)/scale)


def discounted_first_passage(x, horizon, mu, sigma, discount):
    """E[exp(-discount*tau_0) 1(tau_0<=horizon)]."""
    chi = np.sqrt(mu**2 + 2*discount*sigma**2)
    scale = sigma*np.sqrt(horizon)
    return _exp_phi((-mu+chi)*x/sigma**2,
                    (-x-chi*horizon)/scale) + _exp_phi(
        (-mu-chi)*x/sigma**2, (-x+chi*horizon)/scale)


def first_passage_density(time, x, mu, sigma):
    """d/dtime P(tau_0<=time), for x>0 and time>0."""
    return x/(sigma*np.sqrt(2*np.pi*time**3))*np.exp(
        -(x+mu*time)**2/(2*sigma**2*time))


def discounted_boundary_claim(x, mu, sigma, discount):
    """E[exp(-discount*tau_0) 1(tau_0<infinity)], discount>0."""
    rate = (mu+np.sqrt(mu**2+2*discount*sigma**2))/sigma**2
    return np.exp(-rate*x)


def cdf_x_derivative(x, horizon, mu, sigma):
    scale = sigma*np.sqrt(horizon)
    arg = (-x-mu*horizon)/scale
    reflected = _exp_phi(-2*mu*x/sigma**2,
                         (-x+mu*horizon)/scale)
    return -2*np.exp(-arg**2/2)/(np.sqrt(2*np.pi)*scale) - (
        2*mu/sigma**2)*reflected


def simple_equity_ratio(x, gamma):
    """E/V for a constant-carry NO-ROLLOVER model, x>=0.

    E=V-K/r+(b/gamma)*(b/V)**gamma,
    b=(K/r)*gamma/(1+gamma),
    gamma=(mu+sqrt(mu**2+2*r*sigma**2))/sigma**2,
    mu=r-delta-sigma**2/2. This is NOT full He--Xiong equity.
    A stable expm1 representation reduces cancellation near x=0.
    """
    return -(1+1/gamma)*np.expm1(-x) + np.expm1(-(gamma+1)*x)/gamma


@dataclass(frozen=True)
class HX:
    r: float = 0.05
    delta: float = 0.02
    sigma: float = 0.20
    coupon: float = 5.0
    principal: float = 100.0
    maturity: float = 1.0
    tax: float = 0.25
    recovery: float = 0.60
    liquidity_intensity: float = 1.0
    sale_cost: float = 0.01

    @property
    def q(self):
        return self.r+self.liquidity_intensity*self.sale_cost

    @property
    def mu(self):
        return self.r-self.delta-self.sigma**2/2

    @property
    def c(self):
        return self.coupon/self.maturity

    @property
    def p(self):
        return self.principal/self.maturity

    def roots(self):
        a = self.mu/self.sigma**2
        z = np.sqrt(a*a+2*self.r/self.sigma**2)
        zq = np.sqrt(a*a+2*self.q/self.sigma**2)
        return a, z, zq, z-a, z+a


def hx_boundary(par):
    """Original stationary closed-form boundary, Eq.12; regular parameters."""
    a, z, zq, eta, _ = par.roots()
    sm = par.sigma*np.sqrt(par.maturity)

    def little_b(u):
        return (np.exp(-par.q*par.maturity)*ndtr(u*sm)
                - np.exp(-(par.q-par.r)*par.maturity)*ndtr(-z*sm))/(z+u)

    def big_b(u):
        return (ndtr(u*sm)-_exp_phi(
            0.5*(z*z-u*u)*sm*sm, -z*sm))/(z+u)

    capital_b_sum = big_b(-zq)+big_b(zq)
    numerator = ((1-par.tax)*par.coupon
                 - np.expm1(-par.q*par.maturity)*(par.p-par.c/par.q))/eta
    numerator += (par.p-par.c/par.q)*(little_b(-a)+little_b(a))
    numerator += par.c/par.q*capital_b_sum
    denominator = par.delta/(eta-1)+par.recovery/par.maturity*capital_b_sum
    return numerator/denominator


def hx_debt(x, horizon, par, boundary=None):
    """Eq.8; x is a log-margin, not absolute firm value."""
    boundary = hx_boundary(par) if boundary is None else boundary
    f = first_passage_cdf(x, horizon, par.mu, par.sigma)
    g = discounted_first_passage(x, horizon, par.mu, par.sigma, par.q)
    return par.c/par.q + np.exp(-par.q*horizon)*(par.p-par.c/par.q)*(1-f) + (
        par.recovery*boundary/par.maturity-par.c/par.q)*g


def hx_equity(x, par):
    """Eq.A7 on x>=0, with stationary optimal boundary from Eq.12.

    Uses positive liquidity premium; the q->r removable singularity is
    deliberately not concealed with epsilons or a mathematically wrong clamp.
    """
    if np.real(par.q-par.r) <= 0:
        raise ValueError("This reference A7 implementation requires q>r.")
    boundary = hx_boundary(par)
    a, z, zq, eta, gamma = par.roots()
    sm = par.sigma*np.sqrt(par.maturity)
    sm2 = sm*sm

    def K(y):
        exponent = 0.5*((gamma-a)**2-y*y)*sm2
        constant = ndtr(y*sm)-_exp_phi(exponent, (gamma-a)*sm)
        return constant*np.exp(-gamma*x) + _exp_phi(
            exponent-gamma*x, (-x+(gamma-a)*sm2)/sm) - _exp_phi(
            -(a+y)*x, (-x+y*sm2)/sm)

    def small_k(y):
        exponent = 0.5*((-eta-a)**2-y*y)*sm2
        return _exp_phi(exponent+eta*x, (-x+(-eta-a)*sm2)/sm) - _exp_phi(
            -(a+y)*x, (-x+y*sm2)/sm)

    def cap_A(y):
        return (K(y)+small_k(-y))/(z-y)+(K(-y)+small_k(y))/(z+y)

    fixed_cost = (1-par.tax)*par.coupon - np.expm1(
        -par.q*par.maturity)*(par.p-par.c/par.q)
    result = boundary*np.exp(x) - (
        par.delta*boundary/(z*par.sigma**2))*np.exp(-gamma*x)/(gamma+1)
    result -= fixed_cost/(z*par.sigma**2)*(
        1/eta - np.expm1(-gamma*x)/gamma)
    result += (np.exp(-par.q*par.maturity)*(par.p-par.c/par.q)*cap_A(a) - (
        par.recovery*boundary/par.maturity-par.c/par.q)*cap_A(zq))/(z*par.sigma**2)
    return result


def _cs_derivative(function, x):
    """Complex-step derivative, for analytic interior expressions only."""
    return np.imag(function(x+1e-25j))/1e-25


def _second_derivative(function, x, step=1e-4):
    # Central difference of a complex-step first derivative.
    return (_cs_derivative(function, x+step)-_cs_derivative(function, x-step))/(2*step)


def validate():
    cdf_err = []
    discounted_err = []
    laplace_err = []
    for mu in [-0.08, 0.0, 0.08]:
        for sigma in [0.20, 0.50]:
            for x in [0.05, 0.20, 0.70, 1.20]:
                pdf = lambda t: first_passage_density(t, x, mu, sigma)
                for horizon in [0.25, 1.0, 3.0]:
                    integral = quad(pdf, 0, horizon, epsabs=1e-11, epsrel=1e-11)[0]
                    cdf_err.append(abs(integral-first_passage_cdf(x,horizon,mu,sigma)))
                    disc = quad(lambda t: np.exp(-0.03*t)*pdf(t), 0, horizon,
                                epsabs=1e-11, epsrel=1e-11)[0]
                    discounted_err.append(abs(disc-discounted_first_passage(
                        x,horizon,mu,sigma,0.03)))
                infinite = quad(lambda t: np.exp(-0.03*t)*pdf(t), 0, np.inf,
                                epsabs=1e-11, epsrel=1e-11)[0]
                laplace_err.append(abs(infinite-discounted_boundary_claim(x,mu,sigma,0.03)))

    gradient_errors = []
    for mu in [-0.10,0.0,0.10]:
        for x in [0.10,0.40,1.0]:
            h = 1e-5
            fd = (first_passage_cdf(x+h,1,mu,0.3)-first_passage_cdf(x-h,1,mu,0.3))/(2*h)
            gradient_errors.append(abs(fd-cdf_x_derivative(x,1,mu,0.3)))

    # Full HX stationary formulas: independently check differential equations.
    par = HX()
    boundary = hx_boundary(par)
    equ = lambda x: hx_equity(x,par)
    equity_residuals = []
    debt_residuals = []
    for x in [0.03,0.10,0.40,1.0]:
        ex, exx = _cs_derivative(equ,x), _second_derivative(equ,x)
        running = par.delta*boundary*np.exp(x)-(1-par.tax)*par.coupon + (
            hx_debt(x,par.maturity,par)-par.p)
        equity_residuals.append(abs(par.mu*ex+0.5*par.sigma**2*exx-par.r*equ(x)+running))
        for horizon in [0.25,0.80]:
            debt_x = lambda xx: hx_debt(xx,horizon,par)
            dt = _cs_derivative(lambda tt: hx_debt(x,tt,par),horizon)
            rhs = (par.mu*_cs_derivative(debt_x,x) + 0.5*par.sigma**2*
                   _second_derivative(debt_x,x)+par.c-par.q*debt_x(x))
            debt_residuals.append(abs(dt-rhs))

    # Sensitivity of the exact boundary with respect to liquidity intensity.
    boundary_xi = lambda xi: hx_boundary(replace(par,liquidity_intensity=xi))
    h = 1e-4
    cs = _cs_derivative(boundary_xi,1.0)
    fd = (boundary_xi(1+h)-boundary_xi(1-h))/(2*h)

    # The standalone special case has both value matching and smooth pasting.
    gamma = (par.mu+np.sqrt(par.mu**2+2*par.r*par.sigma**2))/par.sigma**2
    a0 = simple_equity_ratio(0.0,gamma)
    ax0 = _cs_derivative(lambda x: simple_equity_ratio(x,gamma),0.0)
    lower_risk_slope = cdf_x_derivative(0.0,1.0,0.0,0.30)

    checks = {
        "first_passage_cdf_vs_density_integral_max_abs": float(max(cdf_err)),
        "discounted_cdf_vs_density_integral_max_abs": float(max(discounted_err)),
        "infinite_discounted_claim_vs_integral_max_abs": float(max(laplace_err)),
        "cdf_analytic_gradient_vs_central_difference_max_abs": float(max(gradient_errors)),
        "hx_equity_ode_residual_max_abs": float(max(equity_residuals)),
        "hx_debt_pde_residual_max_abs": float(max(debt_residuals)),
        "hx_equity_value_at_boundary_abs": float(abs(equ(0.0))),
        "hx_equity_logmargin_derivative_at_boundary_abs": float(abs(_cs_derivative(equ,0.0))),
        "hx_debt_value_matching_abs": float(abs(hx_debt(0.0,0.8,par)-par.recovery*boundary/par.maturity)),
        "hx_boundary_parameter_gradient_error_abs": float(abs(cs-fd)),
        "simple_equity_boundary_value_abs": float(abs(a0)),
        "simple_equity_boundary_derivative_abs": float(abs(ax0)),
    }
    tolerances = {
        key: (2e-5 if "residual" in key else 2e-7 if "gradient" in key else 2e-8)
        for key in checks
    }
    report = {
        "scope": "Scalar stationary analytic kernels; no network training, moving-boundary proof, reset gradient, or speed/energy benchmark",
        "quadrature_cases": {"finite_horizon":len(cdf_err),"infinite_horizon":len(laplace_err)},
        "checks":checks,
        "tolerances":tolerances,
        "all_checks_pass":bool(all(checks[k]<=tolerances[k] for k in checks)),
        "example": {
            "hx_stationary_boundary":float(boundary),
            "hx_d_boundary_d_liquidity_intensity":float(cs),
            "risk_right_slope_at_boundary_mu0_sigma03_horizon1":float(lower_risk_slope),
            "constant_absorbed_extension_left_slope":0.0,
            "risk_extension_is_C1":False,
            "simple_no_rollover_gamma":float(gamma),
        },
        "parameters":par.__dict__,
    }
    print(json.dumps(report,indent=2,allow_nan=False))
    if not report["all_checks_pass"]:
        raise AssertionError("At least one numerical reference check failed.")
    return report


if __name__ == "__main__":
    validate()
