"""Independent component refinement of one pinned reconstructed law."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time

import mpmath as mp
import torch

ROOT = Path('/dev/shm/hcsn-gradient-hosted-source-001')
sys.path.insert(0, str(ROOT))
from qualification.hcsn_differentiable.contract import GridSpec, PhysicalParameters
from qualification.hcsn_differentiable.operator import DifferentiableDistributionOperator
from qualification.hcsn_differentiable.training_domain import read_trace, source_hashes
from qualification.hcsn_differentiable.value import perpetual_basis_value


def independent_basis(grid, parameters, active_reward, hit_reward):
    b, mu, sigma, reset, rho = map(mp.mpf, parameters)
    decay = (mu + mp.sqrt(mu*mu+2*rho*sigma*sigma))/(sigma*sigma)
    g_reset = mp.exp(-decay*(mp.log(reset)-b))
    delay = mp.exp(-rho*grid.refractory)
    at_reset = (active_reward*(1-g_reset)/rho+hit_reward*g_reset)/(1-delay*g_reset)
    weight = hit_reward+delay*at_reset-active_reward/rho
    edges = list(map(mp.mpf, grid.active_edges))
    result = [active_reward/rho+weight*(mp.exp(-decay*lo)-mp.exp(-decay*hi))/(decay*(hi-lo))
              for lo, hi in zip(edges[:-1], edges[1:])]
    result.append(active_reward/rho+weight*mp.exp(-decay*grid.endpoint)*grid.tail_rate/(grid.tail_rate+decay))
    edges = list(map(mp.mpf, grid.phase_edges))
    result += [at_reset*(mp.exp(-rho*lo)-mp.exp(-rho*hi))/(rho*(hi-lo))
               for lo, hi in zip(edges[:-1], edges[1:])]
    return result


torch.set_num_threads(1)
started, cpu_started = time.perf_counter(), time.process_time()
out = Path('/dev/shm/hcsn-value-isolation-001')
audit_path = Path('/dev/shm/hcsn-training-domain-hosted-001/audit/seed11-c0_b0.audit.json')
trace_path = audit_path.with_name('seed11-c0_b0.derived.jsonl')
audit_bytes = audit_path.read_bytes()
assert hashlib.sha256(audit_bytes).hexdigest() == '69edd3e81cb18db014032c09f291eccbf32ec36b8c03dc3e4703779390dfc67f'
audit = json.loads(audit_bytes)
parent_path = Path('/dev/shm/hcsn-value-refinement-001/RESULT.json')
parent_bytes = parent_path.read_bytes()
assert hashlib.sha256(parent_bytes).hexdigest() == 'ee724f8fae03751643c773bad798b3299c48084c1b80d04716d226afa91131ba'
parent = json.loads(parent_bytes)
header, visits, footer, trace_sha = read_trace(trace_path)
source = source_hashes()
assert trace_sha == audit['trace_sha256'] and source == header['sources'] == footer['sources_after']
assert footer['source_unchanged'] and not footer['truncated'] and audit['complete_retained_coverage']
chosen = max(audit['visits'], key=lambda row: row['maximum_scaled_value_error'])
assert chosen == parent['case']
visit = visits[chosen['index']]
assert visit['index'] == 39 and chosen['model_sha256'] == visit['model_sha256']
grid, config = GridSpec(**visit['grid']), visit['operator']
p = torch.tensor(visit['posterior'][0], dtype=torch.float64)
duration = visit['dt'][0]
values = [visit['parameters'][name] for name in ('log_boundary','mu','sigma','absolute_reset','discount')]
params = PhysicalParameters(*(torch.tensor(value, dtype=torch.float64) for value in values))
rows = []
with mp.workdps(80), torch.no_grad():
    a, h = mp.mpf(config['active_reward']), mp.mpf(config['hit_reward'])
    reference = float(mp.fsum(mp.mpf(float(w))*v for w,v in zip(p, independent_basis(grid, values, a, h))))
    assert abs(reference-chosen['continuum_value'][0]) < 2e-12
    for name, active_factor, phase_factor in [('common_q32',1,1),('active_only',16,1),('phase_only',1,16)]:
        settings = asdict(grid)
        settings.update(active_cells=grid.active_cells*active_factor,
                        phase_cells=grid.phase_cells*phase_factor, quadrature_order=32)
        fine = GridSpec(**settings)
        lifted = torch.cat((p[:grid.active_cells].repeat_interleave(active_factor)/active_factor,
                            p[grid.active_cells:grid.active_count],
                            p[grid.active_count:].repeat_interleave(phase_factor)/phase_factor))
        fine_reference = float(mp.fsum(mp.mpf(float(w))*v for w,v in zip(lifted, independent_basis(fine, values, a, h))))
        assert abs(fine_reference-reference) < 2e-12 and abs(float(lifted.sum()-p.sum())) < 2e-15
        operator = DifferentiableDistributionOperator(fine, active_reward=config['active_reward'],
            hit_reward=config['hit_reward'], terminal_reward=config['terminal_reward'], reset_enabled=config['reset_enabled'])
        t0, c0 = time.perf_counter(), time.process_time()
        solution = perpetual_basis_value(operator, params, duration)
        value = float(lifted @ solution.value)
        error = abs(value-fine_reference)/max(1.,abs(fine_reference))
        rows.append(dict(name=name,grid=settings,value=value,continuum_value=fine_reference,
            scaled_value_error=error,meets_original_one_percent_limit=error<=audit['limits']['scaled_value_error'],
            continuum_initial_law_difference=abs(fine_reference-reference),
            bellman_residual_maximum=float(solution.bellman_residual.abs().max()),
            rounded_residual_error_estimate=float(solution.residual_error_estimate),
            matrix_build_and_solve_wall_seconds=time.perf_counter()-t0,
            matrix_build_and_solve_cpu_seconds=time.process_time()-c0,
            state_count=fine.state_count,probability_content_bytes_width4=8*fine.state_count*5))
assert source_hashes() == source
assert hashlib.sha256(audit_path.read_bytes()).hexdigest() == hashlib.sha256(audit_bytes).hexdigest()
assert hashlib.sha256(trace_path.read_bytes()).hexdigest() == trace_sha
assert parent_path.read_bytes() == parent_bytes
report = dict(schema='hcsn-retrospective-active-phase-isolation-v1', status='completed',
    selected_case=chosen, fixed_dt=duration, physical_parameters=visit['parameters'],
    source_identity=source, input_identities={str(audit_path):hashlib.sha256(audit_bytes).hexdigest(),
                                            str(trace_path):trace_sha,
                                            str(parent_path):hashlib.sha256(parent_bytes).hexdigest()},
    probe_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), rows=rows,
    selection='Same post-hoc maximum case in seed11/c0_b0 as parent refinement; not an independent test source.',
    scientific_admission='HOLD_NO_GO', numerical_domain_qualified=False, training_repeated=False,
    initial_law_exactly_preserved_by_uniform_subdivision=True,
    cost_scope='one uncached table build and Bellman solve per row; shared CPU, no inference throughput claim',
    wall_seconds=time.perf_counter()-started,cpu_seconds=time.process_time()-cpu_started)
with (out/'RESULT.json').open('x') as stream:
    json.dump(report,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
print(json.dumps(report,indent=2))
