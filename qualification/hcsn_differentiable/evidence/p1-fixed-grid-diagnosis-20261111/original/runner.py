"""Execute the already frozen 48-case local-mechanism study; no HCSN adoption.

Only Python standard library code is used. The Gauss node function is extracted
verbatim from the source identified below and independently hash-bound. No
model, checkpoint, posterior, E, Torch, NumPy, or native training is loaded.
"""

import ast
from fractions import Fraction
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import resource
import sys
import time


ROOT = Path('/workspace/scratch/c385a7439f8e/hcsn-repo')
PLAN_PATH = ROOT / 'qualification/hcsn_differentiable/evidence/p0p5-terminal-numerics-20261110/mathematical-diagnosis/FOLLOWUP-PLAN.json'
SOURCE_PATH = ROOT / 'qualification/hcsn_differentiable/operator.py'
OUTPUT = Path(__file__).with_name('FIXED-GRID-48-RESULT.json')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run():
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    plan_bytes, source_bytes = PLAN_PATH.read_bytes(), SOURCE_PATH.read_bytes()
    plan = json.loads(plan_bytes)
    source = source_bytes.decode()
    parsed = ast.parse(source)
    node = next(n for n in parsed.body if isinstance(n, ast.FunctionDef) and n.name == '_gauss_legendre_unit')
    segment = ast.get_source_segment(source, node)
    scope = {'math': math, 'lru_cache': lru_cache}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE_PATH), 'exec'), scope)
    gauss = scope['_gauss_legendre_unit']
    rows, nodes_used = [], []
    root2, root2pi = math.sqrt(2), math.sqrt(2 * math.pi)

    def sf(x):
        return math.erfc(x / root2) / 2

    def density(x):
        return math.exp(-x * x / 2) / root2pi

    def b(x):
        return density(x) - x * sf(x)

    for width in plan['active']['widths']:
        for order in plan['active']['node_orders']:
            nodes, weights = gauss(order)
            nodes_used.append({'width': width, 'order': order, 'nodes': nodes, 'weights': weights})
            sigma = plan['active']['sigma']
            h_star = (width * min(nodes) / sigma) ** 2
            horizons = [h_star * f for f in (1e-4, 1e-2, 1, 1e2, 1e4)] + [1e-7, 8e-7]
            for position, h in enumerate(horizons):
                scale = sigma * math.sqrt(h)
                a = width / scale
                reference = scale / width * (density(0) - 2 * b(a) + b(2 * a))
                terms = [sf(width * n / scale) - sf(width * (1 + n) / scale) for n in nodes]
                fixed = math.fsum(w * q for w, q in zip(weights, terms))
                # A simple diagnostic forward-roundoff allowance, not an interval proof.
                exact_roundoff_estimate = 32 * sys.float_info.epsilon * scale / width * (density(0) + 2 * abs(b(a)) + abs(b(2 * a)))
                rows.append({
                    'kind': 'free_adjacent_cell', 'width': width, 'order': order,
                    'h': h, 'schedule_index': position, 'h_star': h_star,
                    'h_over_h_star': h / h_star, 'sigma': sigma, 'mu': 0,
                    'exact_uniform_gaussian_probability': reference,
                    'fixed_node_probability': fixed,
                    'exact_over_sqrt_h': reference / math.sqrt(h),
                    'fixed_over_sqrt_h': fixed / math.sqrt(h),
                    'exact_over_h': reference / h, 'fixed_over_h': fixed / h,
                    'absolute_difference': abs(fixed - reference),
                    'relative_difference': abs(fixed - reference) / reference,
                    'reference_roundoff_diagnostic': exact_roundoff_estimate,
                    'reference_positive_resolved': reference > exact_roundoff_estimate,
                    'fixed_all_terms_underflowed': all(q == 0 for q in terms),
                    'fixed_nonzero_terms': sum(q != 0 for q in terms),
                    'status': 'observed_scalar_only',
                })

    phase = plan['phase']
    omega = Fraction(str(phase['delay'])) / phase['m']
    t = Fraction(str(phase['observation_time']))
    j = phase['initial_j_one_based']
    for ratio in phase['h_over_phase_width']:
        p = Fraction(str(ratio))
        h = omega * p
        n = t / h
        assert n.denominator == 1
        n = n.numerator
        release = math.fsum(math.comb(n, k) * float(p)**k * float(1-p)**(n-k) for k in range(j, n+1))
        actual_uniform_release = max(Fraction(0), min(Fraction(1), (t - (j-1)*omega)/omega))
        rows.append({
            'kind': 'isolated_phase', 'omega': float(omega), 'j': j,
            'h_over_omega': float(p), 'h': float(h), 'observed_time': float(t),
            'steps': n, 'projected_release_probability': release,
            'original_uniform_release_probability': float(actual_uniform_release),
            'projected_mean_wait': float(j * omega),
            'original_uniform_mean_wait': float((Fraction(j)-Fraction(1,2)) * omega),
            'projected_wait_variance': float(j * (1-p) * omega**2),
            'original_uniform_wait_variance': float(omega**2 / 12),
            'limit_wait_variance': float(j * omega**2),
            'status': 'observed_scalar_only',
        })

    tail = plan['tail']
    mu, sigma, rho = tail['mu'], tail['sigma'], tail['discount']
    kappa = 2 * rho / (math.sqrt(mu * mu + 2 * rho * sigma * sigma) - mu)
    for shift in tail['law_shifts']:
        rows.append({
            'kind': 'equal_mass_distinct_tail', 'tail_coefficient': 1.0,
            'endpoint': 4.8, 'tail_rate': 1.0, 'shift': shift,
            'mu': mu, 'sigma': sigma, 'discount': rho, 'kappa': kappa,
            'continuum_laplace_moment': math.exp(-kappa * (4.8 + shift)) / (1+kappa),
            'ratio_to_unshifted': math.exp(-kappa * shift),
            'status': 'observed_scalar_only',
        })
    assert len(rows) == 48
    after_plan, after_source = PLAN_PATH.read_bytes(), SOURCE_PATH.read_bytes()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = {
        'schema': 'hcsn-fixed-grid-mechanism-diagnosis-48-v1',
        'authorization': 'Current user instruction 全量冲 supersedes prior design-only authorization status; no archived plan was edited.',
        'source_path': str(SOURCE_PATH), 'source_sha256': sha(source_bytes),
        'plan_path': str(PLAN_PATH), 'plan_sha256': sha(plan_bytes),
        'gauss_function_sha256': sha(segment.encode()),
        'runner_sha256': sha(Path(__file__).read_bytes()),
        'source_unchanged': source_bytes == after_source,
        'plan_unchanged': plan_bytes == after_plan,
        'python': sys.version, 'executed_on': 'assistant cloud local isolated process',
        'all_planned_cases': 48, 'executed_cases': len(rows), 'unrun_cases': 0,
        'nodes': nodes_used, 'rows': rows,
        'resources': {'wall_seconds': time.perf_counter()-start_wall, 'cpu_seconds': time.process_time()-start_cpu,
                      'max_rss_bytes': usage.ru_maxrss*1024, 'children_user_seconds': 0, 'children_system_seconds': 0,
                      'workers': 1, 'threads': 1, 'retries': 0, 'network_calls': 0},
        'qualification': {'whole_training_domain': 'HOLD', 'scientific_benefit': 'HOLD', 'production_admission': False},
        'scope': 'Free Gaussian scalar source integration, isolated phase law and analytic tail moment only; no model/posterior, full operator, gradients, original 12 failed sentinels, training or adoption executed.',
    }
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ('all_planned_cases','executed_cases','unrun_cases','resources','qualification')}, sort_keys=True))


if __name__ == '__main__':
    run()
