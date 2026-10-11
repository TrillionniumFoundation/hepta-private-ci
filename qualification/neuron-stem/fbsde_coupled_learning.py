"""Learn a small continuation-field proposal, then correct the ORIGINAL FBSDE.

This learns a numerical surrogate for one fixed mathematical profile, not text
reasoning. No random features are described as pretrained Encoder observations.
The proposal never substitutes its training loss for a global residual check.
"""
from dataclasses import asdict
import hashlib
from pathlib import Path
import time

from four_gate_common import require, write_once
from four_gate_capture import tensor_digest
from fbsde_coupled import CoupledProfile, continuation_fields, solve_global, residual_report, trace_fields
from fbsde_coupled_reference import monolithic_reference


def fit_field(torch, p, fields, *, steps=400, seed=271828):
    p.validate()
    require(fields['profile'] == asdict(p) and not fields['reset_at'], 'unaltered continuation training target')
    require(type(steps) is int and 1 <= steps <= 800, 'bounded field training')
    start = time.process_time_ns()
    torch.manual_seed(seed)
    scale = max(abs(v) for v in fields['grids'][-1])
    nn = torch.nn
    net = nn.Sequential(nn.Linear(2, 32), nn.Tanh(), nn.Linear(32, 32), nn.Tanh(), nn.Linear(32, 1)).double()
    inputs, targets = [], []
    for k in range(p.steps):
        stride = max(1, len(fields['grids'][k])//64)
        for x, y in list(zip(fields['grids'][k], fields['values'][k]))[::stride]:
            inputs.append([k/p.steps, x/scale])
            targets.append(y)
    x, y = torch.tensor(inputs, dtype=torch.float64), torch.tensor(targets, dtype=torch.float64)
    optimizer = torch.optim.Adam(net.parameters(), lr=.004)
    losses = []
    for step in range(steps):
        optimizer.zero_grad()
        prediction = p.y_bound*net(x).squeeze(-1).tanh()
        loss = (prediction-y).square().mean()
        require(torch.isfinite(loss).item(), 'nonfinite continuation fit')
        loss.backward()
        nn.utils.clip_grad_norm_(net.parameters(), 1.)
        optimizer.step()
        if step in (0, steps-1):
            losses.append(float(loss.item()))
    net.eval().requires_grad_(False)
    return net, {'profile': asdict(p), 'scale': scale, 'seed': seed, 'steps': steps,
                 'parameters': sum(v.numel() for v in net.parameters()), 'training_rows': len(inputs),
                 'loss_first_last': losses, 'training_cpu_ns': time.process_time_ns()-start,
                 'weight_tensor_sha256': {k: tensor_digest(v) for k, v in net.state_dict().items()},
                 'target_kind': 'tabulated_discrete_decoupling_field_not_language_labels'}


def propose(torch, p, x0, net, meta):
    p.validate()
    require(meta['profile'] == asdict(p), 'proposal/profile mismatch')
    require(type(x0) in (float, int) and abs(x0) <= p.radius, 'initial proposal domain')
    x, y = [float(x0)], []
    with torch.inference_mode():
        for k in range(p.steps):
            inp = torch.tensor([[k/p.steps, value/meta['scale']] for value in x], dtype=torch.float64)
            values = (p.y_bound*net(inp).squeeze(-1).tanh()).tolist()
            require(all(abs(v) <= p.y_bound for v in values), 'invalid neural proposal')
            y.extend(values)
            x = [state+p.a*p.h*value+sign*p.sigma*p.h**.5
                 for state, value in zip(x, values) for sign in (-1, 1)]
    return y


def experiment(output, *, training_steps=400):
    import torch
    torch.set_num_threads(2)
    p = CoupledProfile()
    if output is not None:
        output.mkdir(parents=True, exist_ok=False)
        write_once(output/'design.json', {'schema': 'hepta.fbsde.learned-field-design.v1',
            'profile': asdict(p), 'training_steps': training_steps, 'seed': 271828,
            'field_spacing': .03125, 'initials': [-.83, -.57, -.21, .17, .53, .89],
            'network_widths': [2, 32, 32, 1], 'dtype': 'float64',
            'source_sha256': {n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
                              for n in ('fbsde_coupled.py', 'fbsde_coupled_learning.py', 'fbsde_coupled_reference.py')},
            'not_independent_preregistration': True, 'not_language_training': True})
    start = time.process_time_ns()
    fields = continuation_fields(p, .03125)
    preparation_cpu = time.process_time_ns()-start
    net, meta = fit_field(torch, p, fields, steps=training_steps)
    rows = []
    cold_sum = proposed_sum = corrected_sum = reference_sum = table_sum = 0
    for x0 in (-.83, -.57, -.21, .17, .53, .89):
        begin = time.process_time_ns()
        reference = monolithic_reference(asdict(p), x0)
        reference_cpu = time.process_time_ns()-begin
        begin = time.process_time_ns()
        cold = solve_global(p, x0)
        cold_cpu = time.process_time_ns()-begin
        begin = time.process_time_ns()
        table = trace_fields(p, x0, fields)
        table_corrected = solve_global(p, x0, initial=table['y'])
        table_cpu = time.process_time_ns()-begin
        begin = time.process_time_ns()
        candidate = propose(torch, p, x0, net, meta)
        candidate_report = residual_report(p, x0, candidate)
        proposed_cpu = time.process_time_ns()-begin
        begin = time.process_time_ns()
        corrected = solve_global(p, x0, initial=candidate)
        correct_cpu = time.process_time_ns()-begin
        uncorrected_error = max(abs(a-b) for a, b in zip(candidate, reference['y']))
        corrected_error = max(abs(a-b) for a, b in zip(corrected['y'], reference['y']))
        require(uncorrected_error <= candidate_report['y_error_bound_exact_arithmetic']+1e-11,
                'uncorrected output exceeds discrete error estimate')
        require(corrected_error <= corrected['report']['y_error_bound_exact_arithmetic']+1e-11,
                'corrected result disagrees with independent monolithic root')
        rows.append({'x0': x0, 'proposal_y': candidate, 'proposal_report': candidate_report,
                     'uncorrected_y_sup_error': uncorrected_error, 'corrected_y_sup_error': corrected_error,
                     'cold_map_calls': cold['map_calls'], 'corrected_map_calls': corrected['map_calls'],
                     'cold_cpu_ns': cold_cpu, 'table_runtime_cpu_ns': table_cpu,
                     'table_corrector_map_calls': table_corrected['map_calls'], 'proposal_including_check_cpu_ns': proposed_cpu,
                     'correction_cpu_ns': correct_cpu, 'reference_cpu_ns': reference_cpu,
                     'corrected_report': corrected['report']})
        cold_sum += cold_cpu
        table_sum += table_cpu
        proposed_sum += proposed_cpu
        corrected_sum += correct_cpu
        reference_sum += reference_cpu
    after = {k: tensor_digest(v) for k, v in net.state_dict().items()}
    require(after == meta['weight_tensor_sha256'], 'selected field mutated during inference')
    report = {'schema': 'hepta.fbsde.learned-field-study.v1', 'model': meta, 'rows': rows,
              'field_preparation_cpu_ns': preparation_cpu,
              'standalone_cold_cpu_ns': cold_sum,
              'standalone_tabulated_observed_cpu_ns': preparation_cpu+table_sum,
              'tabulated_runtime_only_cpu_ns': table_sum,
              'standalone_learned_observed_cpu_ns': preparation_cpu+meta['training_cpu_ns']+proposed_sum+corrected_sum,
              'learned_runtime_only_cpu_ns': proposed_sum+corrected_sum,
              'independent_reference_cpu_ns': reference_sum,
              'cpu_envelope_before_persistence_ns': time.process_time_ns()-start,
              'future_uses_assumed_for_amortization': 0, 'interval_arithmetic_certificate': False,
              'measured_component_totals_not_full_deployment_lifecycle': True,
              'fixed_equation_function_approximation_only': True, 'real_encoder_executed': False,
              'policy_optimality_claimed': False, 'production_promotion_permitted': False}
    if output is not None:
        torch.save({'state_dict': net.state_dict(), 'metadata': meta}, output/'field.pt')
        report['own_trained_field_file_sha256'] = hashlib.sha256((output/'field.pt').read_bytes()).hexdigest()
        write_once(output/'learned-field.json', report)
    return report
