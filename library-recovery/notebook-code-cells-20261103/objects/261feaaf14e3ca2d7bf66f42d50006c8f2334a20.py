"""Analytic first-passage kernels and a solvable reset-threshold neuron.

Research validation only: no trained SNN, biological fit, or Hepta deployment.
All times and states in this script are dimensionless. Dependencies: numpy,
scipy, matplotlib. Run: python analytic_neuron.py --output results

The kernel is classical drifted-Brownian first passage. The Lambert-W policy
is derived for the explicitly stated scalar stationary impulse-control model,
not asserted to be a new theorem or a result in He and Xiong (2012).
"""
from __future__ import annotations

import argparse
import json
import math
import platform
from pathlib import Path

import numpy as np
import scipy
from scipy.integrate import quad
from scipy.optimize import minimize_scalar
from scipy.special import lambertw, log_ndtr, ndtr
from scipy.sparse import diags
from scipy.sparse.linalg import splu


def _domain(x, t, sigma):
    if np.any(np.asarray(x) <= 0) or np.any(np.asarray(t) <= 0) or sigma <= 0:
        raise ValueError("This reference implementation requires x,t,sigma > 0.")


def first_hit_cdf(x, t, mu, sigma):
    """P(tau <= t) for X=x+mu*t+sigma*W, absorbed at zero."""
    _domain(x, t, sigma)
    x, t = np.asarray(x, dtype=float), np.asarray(t, dtype=float)
    scale = sigma * np.sqrt(t)
    log_a = log_ndtr((-x - mu * t) / scale)
    log_b = -2 * mu * x / sigma**2 + log_ndtr((-x + mu * t) / scale)
    return np.exp(np.minimum(np.logaddexp(log_a, log_b), 0.0))


def first_hit_density(x, t, mu, sigma):
    _domain(x, t, sigma)
    x, t = np.asarray(x, dtype=float), np.asarray(t, dtype=float)
    log_f = (np.log(x) - math.log(sigma) - 0.5 * math.log(2 * math.pi)
             - 1.5 * np.log(t) - (x + mu * t)**2 / (2 * sigma**2 * t))
    return np.exp(log_f)


def discounted_hit(x, t, mu, sigma, rho):
    """E[exp(-rho*tau) 1(tau<=t)]; not a probability CDF if rho>0."""
    _domain(x, t, sigma)
    if rho < 0:
        raise ValueError("rho must be nonnegative")
    x, t = np.asarray(x, dtype=float), np.asarray(t, dtype=float)
    nu = np.sqrt(mu**2 + 2 * rho * sigma**2)
    scale = sigma * np.sqrt(t)
    log_a = (-mu + nu) * x / sigma**2 + log_ndtr((-x - nu*t) / scale)
    log_b = (-mu - nu) * x / sigma**2 + log_ndtr((-x + nu*t) / scale)
    return np.exp(np.minimum(np.logaddexp(log_a, log_b), 0.0))


def killed_density(y, x, t, mu, sigma):
    """Joint density of (X_t=y, tau>t); integral is survival probability."""
    _domain(x, t, sigma)
    y = np.asarray(y, dtype=float)
    if np.any(y < 0):
        raise ValueError("y must be nonnegative")
    gaussian = np.exp(-(y-x-mu*t)**2/(2*sigma**2*t)) / (sigma*np.sqrt(2*np.pi*t))
    return gaussian * (-np.expm1(-2*x*y/(sigma**2*t)))


def value_operator(x, t, mu, sigma, rho, running, terminal, recovery):
    """Feynman-Kac readout: running reward + surviving payoff + hit payoff."""
    if rho <= 0:
        raise ValueError("Use an integral/continuous limit for rho=0.")
    survival = 1.0 - first_hit_cdf(x, t, mu, sigma)
    hit = discounted_hit(x, t, mu, sigma, rho)
    alive = np.exp(-rho*t) * survival
    occupancy = (1.0-alive-hit)/rho
    return running*occupancy + terminal*alive + recovery*hit


def optimal_reset_threshold(a, sigma, rho, cost, reset=0.0, refractory=0.0):
    """Threshold maximizing E sum exp(-rho*T_n)(Y_T_n-cost).

    Active evidence: dY=a dt+sigma dW. After a spike, wait refractory time,
    then restart at reset. No reward/cost/input accrues in that waiting period.
    Assumptions: cost>reset, rho,sigma>0, refractory>=0.
    """
    if not (sigma > 0 and rho > 0 and cost > reset and refractory >= 0):
        raise ValueError("Require sigma,rho>0, cost>reset, refractory>=0")
    root = np.sqrt(a*a + 2*rho*sigma*sigma)
    k = 2*rho/(root+a) if a >= 0 else (root-a)/(sigma*sigma)
    d = 1 + k*(cost-reset)
    arg = -np.exp(-rho*refractory-d)
    h = cost + (1 + float(lambertw(arg, k=0).real))/k
    return h, k


def threshold_policy_value(h, a, sigma, rho, cost, reset, refractory):
    """Independent renewal-value expression for a fixed threshold h>cost."""
    root = np.sqrt(a*a + 2*rho*sigma*sigma)
    k = 2*rho/(root+a) if a >= 0 else (root-a)/(sigma*sigma)
    laplace = np.exp(-k*(h-reset))
    return laplace*(h-cost)/(-np.expm1(-rho*refractory-k*(h-reset)))


def backward_pde_cdf(x, t, mu, sigma, xmax=12.0, dx=0.01, nsteps=2000):
    """Independent method-of-lines reference for F_t=mu F_x+D F_xx.

    F(0,t)=1, F(xmax,t)=0, F(x,0)=0. Crank-Nicolson with two initial
    backward-Euler half-steps (Rannacher smoothing) at the incompatible corner.
    A finite xmax is an approximation and convergence is measured below.
    """
    _domain(x, t, sigma)
    n = int(round(xmax/dx))
    dx = xmax/n
    interior = n-1
    D = sigma*sigma/2
    lower = D/dx**2-mu/(2*dx)
    upper = D/dx**2+mu/(2*dx)
    diag = -2*D/dx**2
    generator = diags([np.full(interior-1, lower), np.full(interior, diag),
                       np.full(interior-1, upper)], [-1, 0, 1], format='csc')
    ident = diags([np.ones(interior)], [0], format='csc')
    dt = t/nsteps
    forcing = np.zeros(interior)
    forcing[0] = lower
    half_lu = splu(ident-dt*generator/2)
    v = np.zeros(interior)
    for _ in range(2):
        v = half_lu.solve(v+dt*forcing/2)
    lhs = splu(ident-dt*generator/2)
    rhs = ident+dt*generator/2
    for _ in range(nsteps-1):
        v = lhs.solve(rhs @ v + dt*forcing)
    grid = np.linspace(0, xmax, n+1)
    return float(np.interp(x, grid, np.concatenate(([1.0], v, [0.0]))))


def validate(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    x, mu, sigma, horizon, rho = 1.0, -0.7, 0.8, 1.0, 0.4
    theory = float(first_hit_cdf(x, horizon, mu, sigma))
    terminal_only = float(ndtr((-x-mu*horizon)/(sigma*np.sqrt(horizon))))
    discount_theory = float(discounted_hit(x, horizon, mu, sigma, rho))
    density_integral = quad(lambda t: first_hit_density(x,t,mu,sigma), 0, horizon,
                            epsabs=1e-12, epsrel=1e-12)[0]
    hit_quadrature = quad(lambda t: np.exp(-rho*t)*first_hit_density(x,t,mu,sigma),
                          0,horizon,epsabs=1e-12,epsrel=1e-12)[0]
    kernel_mass = quad(lambda y: killed_density(y,x,horizon,mu,sigma),
                       0,np.inf,epsabs=1e-12,epsrel=1e-12)[0]
    pde_coarse = backward_pde_cdf(x,horizon,mu,sigma,dx=0.02,nsteps=1000)
    pde_fine = backward_pde_cdf(x,horizon,mu,sigma,dx=0.01,nsteps=2000)

    seeds = [101, 211, 307, 401, 503]
    n_per_seed = 100_000
    samples = []
    renewal_samples = []
    xr, dead_time, count_horizon = 0.8, 0.15, 2.0
    for seed in seeds:
        rng = np.random.default_rng(seed)
        # For mu<0: inverse Gaussian mean x/(-mu), shape x^2/sigma^2.
        hits = rng.wald(x/(-mu), x*x/(sigma*sigma), size=n_per_seed)
        samples.append(float(np.mean(hits <= horizon)))
        # Exact IID renewal simulation, not one Bernoulli spike per time bin.
        event_times = hits.copy()
        counts = np.zeros(n_per_seed, dtype=np.int32)
        active = np.flatnonzero(event_times <= count_horizon)
        while active.size:
            counts[active] += 1
            event_times[active] += dead_time + rng.wald(
                xr/(-mu), xr*xr/(sigma*sigma), size=active.size)
            active = active[event_times[active] <= count_horizon]
        renewal_samples.append([float(np.mean(counts)), float(np.mean(counts>=2))])
    pde_errors = [abs(pde_coarse-theory), abs(pde_fine-theory)]
    analytic_tails = []
    for n in range(1, 100):
        available = count_horizon-(n-1)*dead_time
        if available <= 0:
            break
        analytic_tails.append(float(first_hit_cdf(x+(n-1)*xr,available,mu,sigma)))
    analytic_count_mean = sum(analytic_tails)

    costs = [0.2, 0.5, 1.0, 2.0]
    thresholds = []
    for cost in costs:
        a, reset = -mu, 0.0
        h,k = optimal_reset_threshold(a,sigma,rho,cost,reset,dead_time)
        opt = minimize_scalar(lambda h_: -threshold_policy_value(
            h_,a,sigma,rho,cost,reset,dead_time),
            bounds=(cost+1e-8,cost+50),method='bounded',options={'xatol':1e-12})
        residual = 1/k-(h-cost+np.exp(-rho*dead_time+k*(reset-h))/k)
        thresholds.append({'cost':cost,'threshold':h,'numeric_optimum':float(opt.x),
                           'absolute_difference':abs(h-opt.x),
                           'value_matching_residual':abs(residual),
                           'stationary_rate_for_positive_a':1/(h/a+dead_time)})

    # Diverse regimes to detect sign, discount, and mass errors.
    regime_errors = []
    for xx,mm,ss,tt,rr in [(0.2,-1,0.5,0.3,0.1),(1,0,0.8,1,0.4),
                          (1,0.7,0.8,1,0.4),(2,-0.2,1.2,3,1.3),
                          (0.8,1.5,0.3,2,0.2)]:
        ff=float(first_hit_cdf(xx,tt,mm,ss))
        gg=float(discounted_hit(xx,tt,mm,ss,rr))
        qf=quad(lambda s: first_hit_density(xx,s,mm,ss),0,tt,epsabs=1e-12)[0]
        qg=quad(lambda s: np.exp(-rr*s)*first_hit_density(xx,s,mm,ss),0,tt,
                epsabs=1e-12)[0]
        mass=quad(lambda y: killed_density(y,xx,tt,mm,ss),0,np.inf,epsabs=1e-12)[0]
        regime_errors.append({'x':xx,'mu':mm,'sigma':ss,'t':tt,'rho':rr,
            'cdf_quadrature_error':abs(ff-qf),'discount_quadrature_error':abs(gg-qg),
            'mass_error':abs(mass+ff-1)})
        if not (-1e-12 <= gg <= ff+1e-12 <= 1+2e-12):
            raise AssertionError('probability/discount ordering failure')

    result = {
      'scope':'Mathematical/numerical scalar-operator verification only; no trained SNN or benchmark advantage.',
      'date':'2026-10-29','units':'dimensionless',
      'environment':{'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__},
      'parameters':{'x':x,'mu':mu,'sigma':sigma,'horizon':horizon,'rho':rho},
      'first_hit':{'analytic_cdf':theory,'endpoint_below_zero_probability':terminal_only,
                   'missed_probability_mass_by_endpoint_check':theory-terminal_only,
                   'density_integral':density_integral,'killed_kernel_mass':kernel_mass,
                   'mass_error':abs(theory+kernel_mass-1),
                   'pde_coarse':pde_coarse,'pde_fine':pde_fine,'pde_absolute_errors':pde_errors,
                   'mc_seeds':seeds,'mc_samples_per_seed':n_per_seed,'mc_cdf_by_seed':samples,
                   'mc_pooled_cdf':float(np.mean(samples)),
                   'pooled_theoretical_standard_error':math.sqrt(theory*(1-theory)/(len(seeds)*n_per_seed))},
      'discounted_hit':{'analytic':discount_theory,'quadrature':hit_quadrature,
                       'absolute_error':abs(discount_theory-hit_quadrature)},
      'renewal':{'x_initial':x,'x_reset':xr,'refractory':dead_time,'horizon':count_horizon,
                  'analytic_mean_count':analytic_count_mean,'analytic_probability_at_least_two':analytic_tails[1],
                  'mc_mean_count':float(np.mean([z[0] for z in renewal_samples])),
                  'mc_probability_at_least_two':float(np.mean([z[1] for z in renewal_samples]))},
      'thresholds':thresholds,'regime_checks':regime_errors,
      'limitations':['Constant coefficients and fixed absorbing boundary only.',
        'Finite-domain PDE comparison is numerical, not a symbolic proof.',
        'Monte Carlo samples use the known inverse-Gaussian law, not biological recordings.',
        'The threshold problem has linear spike reward, fixed reset, no running cost, and frozen resource parameters.',
        'No resource-maturity network was trained; no energy, runtime, accuracy or Hepta benefit claim.']}
    if not (pde_errors[1]<2e-5 and pde_errors[1]<pde_errors[0]):
        raise AssertionError('PDE convergence criterion failed')
    if max(z['absolute_difference'] for z in thresholds)>1e-5:
        raise AssertionError('Lambert-W optimum mismatch')
    if abs(np.mean(samples)-theory)>5*result['first_hit']['pooled_theoretical_standard_error']:
        raise AssertionError('Unexpected Monte Carlo discrepancy')
    (output/'validation_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'DejaVu Sans','axes.spines.top':False,
                         'axes.spines.right':False,'figure.facecolor':'#f7f9fc',
                         'axes.facecolor':'#f7f9fc','font.size':11})
    fig,axs=plt.subplots(2,2,figsize=(12,8),layout='constrained')
    ts=np.linspace(0.02,3,300)
    axs[0,0].plot(ts,first_hit_cdf(x,ts,mu,sigma),color='#155e75',lw=2.6,label='Hit at any time up to t')
    axs[0,0].plot(ts,ndtr((-x-mu*ts)/(sigma*np.sqrt(ts))),color='#b45309',lw=2,ls='--',label='Below boundary only at t')
    axs[0,0].errorbar([1],[np.mean(samples)],yerr=[1.96*result['first_hit']['pooled_theoretical_standard_error']],
                      fmt='o',color='#0f172a',label='Monte Carlo (500,000)')
    axs[0,0].set(title='A  Crossing probability is not endpoint probability',xlabel='Time',ylabel='Probability',ylim=(0,1))
    axs[0,0].legend(fontsize=9,loc='lower right')
    ys=np.linspace(0,4,400)
    gaussian=np.exp(-(ys-x-mu*horizon)**2/(2*sigma**2*horizon))/(sigma*np.sqrt(2*np.pi*horizon))
    axs[0,1].plot(ys,gaussian,color='#b45309',ls='--',label='Unconstrained endpoint density')
    axs[0,1].plot(ys,killed_density(ys,x,horizon,mu,sigma),color='#155e75',lw=2.6,label='Joint surviving density K')
    axs[0,1].fill_between(ys,killed_density(ys,x,horizon,mu,sigma),color='#155e75',alpha=.12)
    axs[0,1].set(title='B  Survival removes paths that already crossed',xlabel='Distance from boundary y',ylabel='Density')
    axs[0,1].legend(fontsize=9)
    cc=np.linspace(.05,2.5,200)
    hh=np.array([optimal_reset_threshold(-mu,sigma,rho,c,0,dead_time)[0] for c in cc])
    axs[1,0].plot(cc,hh,color='#155e75',lw=2.6,label='Lambert-W threshold')
    axs[1,0].scatter(costs,[r['numeric_optimum'] for r in thresholds],color='#b45309',zorder=3,label='Direct numerical optimum')
    axs[1,0].set(title='C  Higher emission cost raises the optimal threshold',xlabel='Per-spike cost c',ylabel='Evidence threshold h')
    axs[1,0].legend(fontsize=9)
    xs=np.arange(1,6)
    axs[1,1].bar(xs,analytic_tails[:5],color='#155e75',width=.6)
    axs[1,1].set(title='D  More than one spike can occur in an interval',xlabel='Minimum spike count n by time 2',ylabel='P(N >= n)',xticks=xs,ylim=(0,1))
    fig.suptitle('Analytic neuron primitives: verified scalar cases',fontsize=18,fontweight='bold',color='#0f172a')
    fig.savefig(output/'analytic_neuron_validation.png',dpi=180)
    plt.close(fig)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


