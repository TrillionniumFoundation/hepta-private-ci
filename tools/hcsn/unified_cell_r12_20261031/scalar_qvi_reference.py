"""Independent scalar reference; not the R12 finite-horizon task objective.

Active state: dX=mu dt+sigma dW. A firing pays X-K, resets to r<K, then
FREEZES for tau before the same diffusion resumes. Discount rho>0, sigma>0.
Controls are adapted nonaccumulating firing times with integrable discounted
rewards; infinite waiting is allowed. This stationary upper-boundary impulse
problem is distinct from the financial HX lower-default boundary and from the
20-state task's belief/time/budget policy regions.

Global verification is algebraic, not inferred from a sampled grid: below b,
J-MJ=(exp(z)-1-z)/kappa>=0 and (L-rho)J=0. Above b, J=MJ and
(L-rho)J=-sigma^2*kappa/2-rho*(x-b)<=0. The C1 join removes the local-time
term. Linear growth and rho>0 provide the discounted localization limit;
the threshold policy attains the inequalities and has nonaccumulating cycles.
"""
from dataclasses import asdict, dataclass, replace
import math

import numpy as np
from scipy.optimize import minimize_scalar


SOURCE = {
    "commit": "4bcdecd2ff334b8705c565a5c77a4a97f05ba5e4",
    "directory": "experiments/hcsn_free_boundary_v1",
    "verified_sha256": {
        "MATH.md": "fd7e0c3c635083b3d2cc1b31e29e70e600280c0e39e8a8c77e58005bd919d9de",
        "oracle.py": "72f8171bb3c6121481235288033518516d25eb0644f68c9c9f7d775069eda248",
        "CONTRACT.md": "4da331cf20ab5b164f9e935fe9ee4d9db698ff2a9eac53dbefa5e009f0169a0a",
    },
    "benchmark_git_blob": "37160fabf02421aa9a888993551990608ffa33c3",
}
PARAMETERS = ("mu", "sigma", "rho", "K", "r", "tau")
OLD_CASES = (
    ((.25, .7, .4, .8, -.2, .3), 1.7688406740717135,
     (1.151763289090871, .6979128598847244, -1.2638607881970252,
      1.1923608498796887, -.19236084987968866, .0888866931785369)),
    ((-.35, .5, .4, .8, -.2, 0.), 1.0697906762396423,
     (.45828199716035983, .8413056896930489, -.12481930854284068,
      1.0095365303992438, -.009536530399243872, .0010389612838445244)),
    ((0., 1.1, .4, 1.2, -.5, 1.), 2.3485111838911634,
     (1.0449897752201465, .9346672692737891, -1.1980825740524637,
      1.0708101104058796, -.07081011040587962, .03483396847959865)),
    ((.8, .35, .6, .8, -.2, .4), 1.9695947010466928,
     (1.0906162315760526, .2715017584296805, -1.4197000908055353,
      1.2020761003354627, -.2020761003354626, .17046434625678764)),
)


@dataclass(frozen=True)
class ScalarParameters:
    mu: float = .25
    sigma: float = .7
    rho: float = .4
    K: float = .8
    r: float = -.2
    tau: float = .3


class ScalarQVI:
    """Unique stationary boundary, solved independently by bracket bisection.

    This reference deliberately restricts itself to positive diffusion. It
    does not silently use the formula for the zero-noise nonincreasing regime.
    Near r=K,tau=0 derivatives are ill-conditioned; they are never clipped.
    """
    def __init__(self, parameters=ScalarParameters()):
        p = parameters
        if (not all(math.isfinite(x) for x in asdict(p).values()) or p.sigma <= 0
                or p.rho <= 0 or p.tau < 0 or p.r >= p.K):
            raise ValueError("Finite parameters, sigma>0, rho>0, tau>=0 and r<K required")
        self.parameters = p
        self.omega = math.hypot(p.mu, math.sqrt(2*p.rho)*p.sigma)
        self.kappa = (2*p.rho/(self.omega+p.mu) if p.mu >= 0
                      else (self.omega-p.mu)/(p.sigma*p.sigma))
        k = self.kappa
        a = p.rho*p.tau+k*(p.K-p.r)
        low, high = 0., 1.
        for _ in range(100):
            middle = (low+high)/2
            residual = middle+math.expm1(-a-middle)
            if residual == 0:
                low = high = middle
                break
            if residual < 0:
                low = middle
            else:
                high = middle
        y = (low+high)/2
        self.boundary = p.K+y/k
        self.q = math.exp(-a-y)
        self.root_jacobian = k*(-math.expm1(-a-y))
        self.root_residual = y+math.expm1(-a-y)

    def value(self, x):
        delta = np.asarray(x, dtype=float)-self.boundary
        return np.where(delta < 0, np.exp(self.kappa*np.minimum(delta, 0))/self.kappa,
                        delta+1/self.kappa)

    def intervention(self, x):
        p = self.parameters
        return np.asarray(x, dtype=float)-p.K+math.exp(-p.rho*p.tau)*self.value(p.r)

    def obstacle_gap(self, x):
        """Nonnegative J-MJ; NOT a signed continue-versus-reset action value."""
        return self.value(x)-self.intervention(x)

    def spatial_derivatives(self, x):
        delta = np.asarray(x, dtype=float)-self.boundary
        exponential = np.exp(self.kappa*np.minimum(delta, 0))
        return np.where(delta < 0, exponential, 1.), np.where(delta < 0, self.kappa*exponential, 0.)

    def generator_residual(self, x):
        p = self.parameters
        first, second = self.spatial_derivatives(x)
        return p.mu*first+.5*p.sigma*p.sigma*second-p.rho*self.value(x)

    def boundary_gradients(self):
        p, k, q = self.parameters, self.kappa, self.q
        a = self.boundary-p.K-q*(self.boundary-p.r)
        d = self.root_jacobian
        dk = dict(mu=-k/self.omega, sigma=-p.sigma*k*k/self.omega, rho=1/self.omega)
        result = {name: -a*dk[name]/d for name in dk}
        result["rho"] += p.tau*q/d
        result.update(K=k/d, r=-k*q/d, tau=p.rho*q/d)
        return result

    def fixed_threshold_value(self, x, boundary):
        """Renewal value including every cycle for an arbitrary fixed b>K."""
        p, k = self.parameters, self.kappa
        if not math.isfinite(boundary) or boundary <= p.K:
            raise ValueError("Reward-positive boundary b>K required")
        log_q = -p.rho*p.tau-k*(boundary-p.r)
        at_boundary = (boundary-p.K)/(-math.expm1(log_q))
        x = np.asarray(x, dtype=float)
        below = np.exp(k*np.minimum(x-boundary, 0))*at_boundary
        above = x-p.K+math.exp(log_q)*at_boundary
        return np.where(x < boundary, below, above)


def run_scalar_reference():
    """Original benchmark, global identities and independent derivative checks."""
    records = []
    for values, old_boundary, old_gradients in OLD_CASES:
        parameters = ScalarParameters(*values)
        solution = ScalarQVI(parameters)
        b, k = solution.boundary, solution.kappa
        points = np.r_[np.linspace(b-12/k, b-.0001/k, 1001), b,
                       np.linspace(b+.0001/k, b+12/k, 1001)]
        gap = solution.obstacle_gap(points)
        generator = solution.generator_residual(points)
        gradients = solution.boundary_gradients()
        derivative_checks = {}
        for name in PARAMETERS:
            x = getattr(parameters, name)
            step = 1e-5*max(abs(x), 1.)
            if name == "tau" and x == 0:
                f1 = ScalarQVI(replace(parameters, tau=step)).boundary
                f2 = ScalarQVI(replace(parameters, tau=2*step)).boundary
                numerical = (-3*b+4*f1-f2)/(2*step)
            else:
                lower = ScalarQVI(replace(parameters, **{name: x-step})).boundary
                upper = ScalarQVI(replace(parameters, **{name: x+step})).boundary
                numerical = (upper-lower)/(2*step)
            derivative_checks[name] = dict(implicit=gradients[name], finite_difference=numerical,
                scaled_error=abs(numerical-gradients[name])/max(1., abs(gradients[name])))
        optimum = minimize_scalar(
            lambda threshold: -math.log(float(solution.fixed_threshold_value(parameters.r, threshold))),
            bounds=(parameters.K+1e-8, parameters.K+3/k), method="bounded", options={"xatol": 1e-12})
        h = 1e-6/k
        left_slope = (float(solution.value(b))-float(solution.value(b-h)))/h
        right_slope = (float(solution.value(b+h))-float(solution.value(b)))/h
        records.append(dict(
            parameters=asdict(parameters), boundary=b, kappa=k, cycle_discount_weight=solution.q,
            root_residual=solution.root_residual, root_jacobian=solution.root_jacobian,
            old_boundary=old_boundary, old_boundary_absolute_error=abs(b-old_boundary),
            old_gradient_max_absolute_error=max(abs(gradients[n]-v) for n, v in zip(PARAMETERS, old_gradients)),
            value_matching_error=float(abs(solution.value(b)-solution.intervention(b))),
            left_slope=left_slope, right_slope=right_slope,
            minimum_obstacle_gap=float(gap.min()), maximum_generator_residual=float(generator.max()),
            maximum_qvi_residual=float(np.max(np.abs(np.maximum(generator, -gap)))),
            separate_threshold_optimizer_error=abs(float(optimum.x)-b),
            separate_optimizer_success=bool(optimum.success), derivative_checks=derivative_checks))
    near = ScalarQVI(ScalarParameters(r=.8-1e-6, tau=0.))
    return dict(
        schema="hcsn.r12.scalar-stationary-reference.v1", source=SOURCE, cases=records,
        reference_role="Independent scalar reference only; not used to change or certify the finite-horizon task objective",
        global_verification=dict(
            continuation_obstacle="(exp(z)-1-z)/kappa >= 0 for z=kappa*(x-b)<0",
            continuation_generator="0 by sigma^2*kappa^2/2+mu*kappa-rho=0",
            intervention_obstacle="J=MJ",
            intervention_generator="-sigma^2*kappa/2-rho*(x-b) <= 0 for x>=b",
            smooth_fit="Both first spatial derivatives equal 1; second derivatives need not match",
            admissibility="Adapted nonaccumulating controls, integrable discounted rewards; frozen mandatory refractory; rho>0, sigma>0, r<K",
            conclusion="These identities verify the stated stationary scalar contract; sampled numerical checks are supplementary"),
        near_degenerate=dict(parameters=asdict(near.parameters), boundary=near.boundary,
                             root_jacobian=near.root_jacobian, gradients=near.boundary_gradients(),
                             scope="No clipping; approaching r=K,tau=0 is ill-conditioned"),
        finite_horizon_scalar_optimality_claimed=False, neural_network_optimality_claimed=False)
