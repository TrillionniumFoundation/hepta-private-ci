"""One deterministic trust-region fit and independent fixed-step PGD baseline.

Inputs are only frozen TRAIN hidden features, own-model probabilities and b0.
No teacher posterior, validation target, task reward or direct-solver oracle is
accepted by the PGD routine. Certificates are floating numerical diagnostics;
the stored-IEEE parameter radius checks use exact Fraction arithmetic.
"""
from fractions import Fraction
import time
import numpy as np

REGULARIZATION = 1e-4
RADIUS_FRACTION = .5
SAFE_FACTOR = 1. - 1e-8
STORE_ROUNDOFF_FACTOR = 1. - 1e-12
PGD_MAX_STEPS = 20000
FW_TOLERANCE = 1e-8

def exact_squared(values):
    return sum((Fraction.from_float(float(x)) ** 2 for x in values), Fraction(0))

def rational(x): return {'numerator': str(x.numerator), 'denominator': str(x.denominator)}

def radius_certificate(b, b0, safe_radius):
    # Differences are exact rational subtraction of the two stored IEEE values,
    # not the separately rounded numpy subtraction b-b0.
    delta = [Fraction.from_float(float(x)) - Fraction.from_float(float(y)) for x, y in zip(b, b0)]
    actual = sum((x*x for x in delta), Fraction(0))
    original_bound = exact_squared(b0) / 4
    safe_bound = Fraction.from_float(float(safe_radius)) ** 2
    return {'actual_squared_delta': rational(actual), 'original_radius_squared': rational(original_bound),
            'safe_radius_squared': rational(safe_bound), 'within_original': actual <= original_bound,
            'within_safe': actual <= safe_bound, 'scope': 'Exact stored-IEEE real vector difference; no continuous-law claim.'}

def stored_candidate(b0, delta, safe_radius):
    b = np.asarray(b0 + delta, dtype=np.float64)
    certificate = radius_certificate(b, b0, safe_radius)
    repaired = False
    if not certificate['within_safe']:
        # Single declared numerical inward guard if floating projection/root
        # arithmetic or final storage leaves the exact safe ball. No search.
        b = np.asarray(b0 + (b - b0) * STORE_ROUNDOFF_FACTOR, dtype=np.float64)
        certificate = radius_certificate(b, b0, safe_radius); repaired = True
    if not certificate['within_safe'] or not certificate['within_original']:
        raise ArithmeticError('stored Belief candidate outside declared exact radius')
    return b, certificate, repaired

def prepare(H, p, b0, mm):
    start, wall = time.process_time(), time.perf_counter()
    H, p, b0 = np.asarray(H, dtype=np.float64), np.asarray(p, dtype=np.float64), np.asarray(b0, dtype=np.float64)
    assert H.ndim == 2 and H.shape[1] == len(b0) == 49 and p.shape == (len(H),)
    if not np.all(np.isfinite(H)) or not np.all(np.isfinite(b0)) or not np.all(np.isfinite(p)) or not np.all((0 < p) & (p < 1)):
        raise ArithmeticError('TRAIN features/Belief target invalid; finite strict0<p<1 required, no clipping')
    t = np.log(p) - np.log1p(-p)
    y = t - mm(H, b0)
    matrix = mm(H.T, H) / len(H) + REGULARIZATION * np.eye(49)
    matrix = (matrix + matrix.T) * .5
    rhs = mm(H.T, y) / len(H)
    eigenvalues, eigenvectors = np.linalg.eigh(matrix)
    if not np.all(np.isfinite(eigenvalues)) or eigenvalues[0] <= 0:
        raise ArithmeticError('regularized quadratic not numerically positive definite')
    original_radius = RADIUS_FRACTION * float(np.linalg.norm(b0))
    safe_radius = original_radius * SAFE_FACTOR
    if not np.isfinite(safe_radius) or safe_radius <= 0:
        raise ArithmeticError('nonpositive finite Belief radius')
    assert Fraction.from_float(safe_radius)**2 <= exact_squared(b0)/4
    L = 2 * float(eigenvalues[-1])
    return {'H': H, 'p': p, 't': t, 'b0': b0, 'matrix': matrix, 'rhs': rhs,
        'eigenvalues': eigenvalues, 'eigenvectors': eigenvectors, 'L': L,
        'original_radius_float': original_radius, 'safe_radius': safe_radius,
        'setup_cpu_seconds': time.process_time()-start, 'setup_wall_seconds': time.perf_counter()-wall}

def diagnostics(problem, b, mm):
    H, t, b0, radius = [problem[k] for k in ('H', 't', 'b0', 'safe_radius')]
    delta = b - b0
    residual = mm(H, b) - t
    gradient = 2 * mm(H.T, residual) / len(H) + 2 * REGULARIZATION * delta
    gram_gradient = 2 * (mm(problem['matrix'], delta) - problem['rhs'])
    gradient_norm = float(np.linalg.norm(gradient))
    gap = float(np.sum(gradient * delta) + radius * gradient_norm)
    data_mse = float(np.mean(residual**2)); penalty = REGULARIZATION * float(np.sum(delta**2))
    return {'objective': data_mse + penalty, 'own_bank_logit_mse': data_mse,
        'regularization_penalty': penalty, 'numerical_fw_gap': gap,
        'gradient_norm': gradient_norm, 'gradient': gradient.tolist(),
        'gradient_reference_vs_gram_linf': float(np.max(np.abs(gradient-gram_gradient))),
        'delta_l2': float(np.linalg.norm(delta)),
        'certificate': radius_certificate(b, b0, radius),
        'scope': 'Numerical convex diagnostics evaluated at stored b using original H/own targets; exact radius only, not a rigorously outward-rounded real optimization certificate.'}

def direct(problem, mm, budget):
    start, wall = time.process_time(), time.perf_counter()
    values, vectors, rhs, radius = [problem[k] for k in ('eigenvalues', 'eigenvectors', 'rhs', 'safe_radius')]
    projected_rhs = mm(vectors.T, rhs)
    def point(mu): return mm(vectors, projected_rhs / (values + mu))
    unconstrained = point(0.)
    bracket_steps = bisections = 0
    if np.linalg.norm(unconstrained) <= radius:
        mu = 0.; delta = unconstrained
    else:
        lo, hi = 0., max(1., float(np.linalg.norm(rhs))/radius)
        while np.linalg.norm(point(hi)) > radius:
            hi *= 2; bracket_steps += 1; budget()
            if bracket_steps > 64 or not np.isfinite(hi): raise ArithmeticError('root bracket failure')
        for _ in range(160):
            mid = (lo + hi)*.5
            if mid == lo or mid == hi: break
            if np.linalg.norm(point(mid)) > radius: lo = mid
            else: hi = mid
            bisections += 1
        mu = hi; delta = point(mu)
    b, certificate, repaired = stored_candidate(problem['b0'], delta, radius)
    state = diagnostics(problem, b, mm)
    system = problem['matrix'] + mu*np.eye(49)
    chol = np.linalg.cholesky(system)
    independent_delta = np.linalg.solve(chol.T, np.linalg.solve(chol, rhs))
    actual = b-problem['b0']
    equation_residual = mm(system, actual)-rhs
    kkt = np.asarray(state['gradient']) + 2*mu*actual
    state.update({'solver': 'eigh_scalar_lagrange_monotone_root', 'b': b.tolist(),
        'delta_float': actual.tolist(), 'lagrange_mu': float(mu), 'root_bracket_steps': bracket_steps,
        'root_bisections': bisections, 'storage_inward_guard_applied': repaired,
        'linear_equation_residual_linf': float(np.max(np.abs(equation_residual))),
        'independent_cholesky_delta_l2_difference': float(np.linalg.norm(independent_delta-actual)),
        'kkt_stationarity_linf': float(np.max(np.abs(kkt))),
        'complementarity_absolute': float(abs(mu*(np.sum(actual**2)-radius**2))),
        'converged_to_declared_FW_tolerance': bool(-1e-12 <= state['numerical_fw_gap'] <= FW_TOLERANCE),
        'solver_cpu_seconds': time.process_time()-start, 'solver_wall_seconds': time.perf_counter()-wall})
    budget()
    return b, state

def pgd(problem, mm, budget):
    start, wall = time.process_time(), time.perf_counter()
    matrix, rhs, radius = [problem[k] for k in ('matrix', 'rhs', 'safe_radius')]
    delta = np.zeros(49); step_size = 1/problem['L']; trace=[]; converged=False
    repair_count = 0; final = None; steps = 0
    for steps in range(PGD_MAX_STEPS+1):
        if steps % 100 == 0: budget()
        gradient = 2*(mm(matrix, delta)-rhs)
        gap = float(np.sum(gradient*delta)+radius*np.linalg.norm(gradient))
        if steps % 100 == 0 or gap <= FW_TOLERANCE or steps == PGD_MAX_STEPS:
            trace.append({'step': steps, 'numerical_gram_fw_gap': gap, 'delta_l2': float(np.linalg.norm(delta))})
        if gap <= FW_TOLERANCE or steps == PGD_MAX_STEPS:
            b, certificate, repaired = stored_candidate(problem['b0'], delta, radius)
            repair_count += int(repaired)
            final = diagnostics(problem, b, mm)
            # No use of direct result/objective, only this candidate's own gap.
            if -1e-12 <= final['numerical_fw_gap'] <= FW_TOLERANCE:
                converged=True; break
            if steps == PGD_MAX_STEPS: break
            delta = b-problem['b0']
            gradient = 2*(mm(matrix, delta)-rhs)
        delta -= step_size*gradient
        norm = float(np.linalg.norm(delta))
        if norm > radius: delta *= radius/norm
    final.update({'solver': 'projected_gradient_fixed_1_over_L', 'b': b.tolist(),
        'delta_float': (b-problem['b0']).tolist(), 'steps': steps, 'max_steps': PGD_MAX_STEPS,
        'step_size': step_size, 'L': problem['L'], 'FW_tolerance': FW_TOLERANCE,
        'converged_to_declared_FW_tolerance': converged,
        'stop_reason': 'own_stored_parameter_FW_gap' if converged else 'fixed_maximum_steps',
        'storage_inward_guard_applications': repair_count, 'trace_every_steps': 100, 'trace': trace,
        'solver_cpu_seconds': time.process_time()-start, 'solver_wall_seconds': time.perf_counter()-wall})
    budget()
    return b, final

def problem_record(problem):
    return {'H': problem['H'].tolist(), 'own_bank7': problem['p'].tolist(),
        'target_logit': problem['t'].tolist(), 'b0': problem['b0'].tolist(),
        'regularization': REGULARIZATION, 'matrix': problem['matrix'].tolist(),
        'rhs': problem['rhs'].tolist(), 'eigenvalues': problem['eigenvalues'].tolist(), 'L': problem['L'],
        'original_radius_float': problem['original_radius_float'], 'safe_radius': problem['safe_radius'],
        'safe_factor': SAFE_FACTOR, 'storage_roundoff_inward_guard_factor': STORE_ROUNDOFF_FACTOR,
        'shared_setup_cpu_seconds': problem['setup_cpu_seconds'], 'shared_setup_wall_seconds': problem['setup_wall_seconds'],
        'scope': 'Full original TRAIN hidden+bias and own model probability only; no teacher posterior or task reward enters this convex problem.'}
