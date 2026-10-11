"""Analytic/local/global FBSDE mechanisms; not a general solvability certificate.

Profile A: dX=Y dt, dY=-c X dt, X0=1, YT=g XT. Profile B:
dX=Y dt+sigma dW, dY=Z dW, YT=XT. Both use scalar decoupling
fields. A uses independent matrix shooting and backwards interface transport.
"""
from dataclasses import dataclass
import math
import random

from four_gate_common import integer, number, require


@dataclass(frozen=True)
class LinearProfile:
    horizon: float = .8
    c: float = .25
    terminal_slope: float = 1.
    denominator_floor: float = 1e-6
    slope_ceiling: float = 1e5

    def pole(self):
        if self.c == 0:
            return 1 / self.terminal_slope
        r = math.sqrt(self.c)
        return (math.pi / 2 - math.atan(self.terminal_slope / r)) / r

    def admit(self):
        for key in ('horizon', 'terminal_slope', 'denominator_floor', 'slope_ceiling'):
            number(getattr(self, key), key, 1e-12)
        number(self.c, 'c')
        require(self.horizon < self.pole(), 'global regular field crosses a pole')
        f = exact_matrix(self.horizon, self.c)
        denominator = f[3] - self.terminal_slope * f[1]
        require(denominator >= self.denominator_floor, 'global denominator below floor')
        slope = (self.terminal_slope * f[0] - f[2]) / denominator
        require(slope <= self.slope_ceiling, 'global field slope exceeds profile')
        return {'pole': self.pole(), 'denominator': denominator, 'max_slope': slope}


def multiply(a, b):
    return (a[0]*b[0]+a[1]*b[2], a[0]*b[1]+a[1]*b[3],
            a[2]*b[0]+a[3]*b[2], a[2]*b[1]+a[3]*b[3])


def exact_matrix(t, c):
    if c == 0:
        return (1., t, 0., 1.)
    r = math.sqrt(c)
    return (math.cos(r*t), math.sin(r*t)/r, -r*math.sin(r*t), math.cos(r*t))


def field_start(matrix, end_slope):
    denominator = matrix[3] - end_slope * matrix[1]
    require(denominator > 0 and math.isfinite(denominator), 'unsupported local field')
    return (end_slope * matrix[0] - matrix[2]) / denominator


def segment(h, steps, c, end_slope, x0):
    """Euler matrix shooting on ONE segment, with externally supplied continuation."""
    transition = (1., h, -c*h, 1.)
    total = (1., 0., 0., 1.)
    for _ in range(steps):
        total = multiply(transition, total)
    y = field_start(total, end_slope) * x0
    states = [(x0, y)]
    for _ in range(steps):
        x, y = states[-1]
        states.append((x+h*y, y-c*h*x))
    return states, total


def solve(profile, steps, segments=1, *, reset_terminal=False):
    """Reject global profile failures BEFORE changing mesh or local segment count."""
    admission = profile.admit()
    integer(steps, 'steps', 4, 65536)
    integer(segments, 'segments', 1, steps)
    require(steps % segments == 0, 'segment grid mismatch')
    h, width = profile.horizon / steps, steps // segments
    boundaries = [profile.terminal_slope] * (segments + 1)
    # Independently computed backwards interface fields; not an analytic oracle.
    _, transition = segment(h, width, profile.c, 0., 0.)
    if not reset_terminal:
        for k in reversed(range(segments)):
            boundaries[k] = field_start(transition, boundaries[k+1])
    pieces, x = [], 1.
    for k in range(segments):
        states, _ = segment(h, width, profile.c, boundaries[k+1], x)
        pieces.append(states)
        x = states[-1][0]
    local = max(abs(p[-1][1] - boundaries[k+1]*p[-1][0]) for k, p in enumerate(pieces))
    jumps = [abs(pieces[k][-1][1]-pieces[k+1][0][1]) for k in range(segments-1)]
    xjumps = [abs(pieces[k][-1][0]-pieces[k+1][0][0]) for k in range(segments-1)]
    recurrence = max(max(abs(p[j+1][0]-p[j][0]-h*p[j][1]),
                         abs(p[j+1][1]-p[j][1]+profile.c*h*p[j][0]))
                     for p in pieces for j in range(width))
    oracle_y = field_start(exact_matrix(profile.horizon, profile.c), profile.terminal_slope)
    trajectory_error = 0.
    for k, p in enumerate(pieces):
        for j, (xx, yy) in enumerate(p):
            f = exact_matrix((k*width+j)*h, profile.c)
            trajectory_error = max(trajectory_error, abs(xx-(f[0]+f[1]*oracle_y)),
                                   abs(yy-(f[2]+f[3]*oracle_y)))
    return {'steps': steps, 'segments': segments, 'reset_terminal': reset_terminal,
            'initial_y': pieces[0][0][1], 'analytic_initial_y': oracle_y,
            'max_trajectory_error': trajectory_error, 'local_terminal_residual': local,
            'global_terminal_residual': abs(pieces[-1][-1][1]-profile.terminal_slope*x),
            'x_interface_residual': max(xjumps, default=0.),
            'y_interface_residual': max(jumps, default=0.), 'local_dynamics_residual': recurrence,
            'same_discrete_global_problem': max([local, recurrence, *jumps, *xjumps]) < 1e-9,
            'admission': admission, 'interface_states': [[list(p[0]), list(p[-1])] for p in pieces]}


def stochastic_experiment(seed=917, paths=128, finest=1024):
    """Coupled Brownian profile with an exact SAME-NOISE Gaussian-integral oracle.

    q=1-T+t; Y=x0/q0+sigma*integral(1/q dW); X=qY; Z=sigma/q.
    On each finest interval jointly sample dW and the exact integral, including
    its independent Brownian-bridge component. Coarse dW is an aggregate of the
    same path, not an independent Monte Carlo run masquerading as convergence.
    """
    integer(paths, 'paths', 4, 4096)
    integer(finest, 'finest mesh', 64, 8192)
    require(finest & (finest-1) == 0, 'power-of-two common Brownian grid')
    horizon, sigma = .6, .3
    dt, q0 = horizon/finest, 1-horizon
    rng = random.Random(seed)
    noises, integrals = [], []
    for _ in range(paths):
        dw, di = [], []
        for j in range(finest):
            q, qn = q0+j*dt, q0+(j+1)*dt
            cov = math.log1p(dt/q)
            variance = dt/(q*qn)
            bridge_var = variance-cov*cov/dt
            require(bridge_var >= -1e-13, 'invalid Brownian integral covariance')
            w = math.sqrt(dt)*rng.gauss(0, 1)
            dw.append(w)
            di.append(cov/dt*w+math.sqrt(max(0., bridge_var))*rng.gauss(0, 1))
        noises.append(dw)
        integrals.append(di)
    result = []
    for n in (8, 16, 32, 64):
        require(finest % n == 0, 'nested Brownian mesh')
        step, block = horizon/n, finest//n
        x_error = y_error = defect = 0.
        for w, integral in zip(noises, integrals):
            x, y, accumulated = 1., 1/q0, 0.
            for j in range(n):
                q = q0+j*step
                delta_w = sum(w[j*block:(j+1)*block])
                x += step*y+sigma*delta_w
                new_y = x/(q+step)
                accumulated += (new_y-y)-sigma/q*delta_w
                y = new_y
            exact_y = 1/q0+sigma*sum(integral)
            x_error += (x-exact_y)**2  # q(T)=1
            y_error += (y-exact_y)**2
            defect += accumulated**2
        result.append({'steps': n, 'paths': paths,
                       'terminal_x_rmse': math.sqrt(x_error/paths),
                       'terminal_y_rmse': math.sqrt(y_error/paths),
                       'global_bsde_left_rule_defect_rmse': math.sqrt(defect/paths)})
    return {'profile': 'dX=Ydt+0.3dW;dY=ZdW;YT=XT;T=0.6',
            'seed': seed, 'same_noise_exact_integral_oracle': True,
            'rows': result, 'stochastic_scheme': 'Euler forward; exact decoupling field readout',
            'sample_convergence_not_general_theorem': True}


def experiment():
    profile = LinearProfile()
    grid = (8, 16, 32, 64, 128, 256, 512)
    rows = [{'whole': solve(profile, n), 'stitched': solve(profile, n, 4),
             'wrong_reset': solve(profile, n, 4, reset_terminal=True)} for n in grid]
    critical = profile.pole()
    boundaries = []
    for horizon in (.9*critical, critical-1e-9, critical, critical+1e-3):
        for n in (16, 256, 4096):
            try:
                r = solve(LinearProfile(horizon=horizon), n, 4)
                boundaries.append({'horizon': horizon, 'steps': n, 'status': 'admitted',
                                   'error': r['max_trajectory_error']})
            except ValueError as e:
                boundaries.append({'horizon': horizon, 'steps': n, 'status': 'unsupported_profile',
                                   'reason': str(e)})
    return {'schema': 'hepta.fbsde.local-study.v1', 'profile': 'dX=Ydt;dY=-0.25Xdt;YT=XT',
            'mesh': rows, 'regularity_checks': boundaries, 'stochastic': stochastic_experiment(),
            'production_promotion_permitted': False, 'general_global_existence_proved': False}
