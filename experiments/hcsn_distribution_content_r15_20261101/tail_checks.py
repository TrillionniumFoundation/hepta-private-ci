"""Independent tail discretization checks and validation-only weight migration."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from experiments.hcsn_validation_r14_20261101.numerics.zero_delay import ZeroDelayFlow
from experiments.hcsn_validation_r14_20261101.numerics.continuous_reference import successor
from experiments.hcsn_validation_r14_20261101.content.engine import ValueController, public_times, READ_FEE, TIME_FEE
from .tail_grid import TailGridFlow
from .law_core import DistributionContentCore


PROFILES = {"old_uniform": dict(tail_spacing=None, tail_upper=40.),
            "tail_half_upper40": dict(tail_spacing=.5, tail_upper=40.),
            "tail_quarter_upper40": dict(tail_spacing=.25, tail_upper=40.),
            "tail_half_upper60": dict(tail_spacing=.5, tail_upper=60.)}


def numerics():
    begin = time.process_time()
    rows, checks = [], []
    edges = [0., .25, .5, 1., 2., 4., 8., np.inf]
    reference = {t: successor(dict(x=1., mu=-.25, sigma=1., reset=.8, horizon=t), edges, 3)
                 for t in (.25, 1., 1.75, 4.)}
    uniform = ZeroDelayFlow(1., -.25, 1., .8, .1, upper=2.1, count_cap=3)
    reduced = TailGridFlow(1., -.25, 1., .8, .1, fine_positions=8,
                          tail_spacing=.1, upper=2.1, count_cap=3)
    error = float(abs(uniform.operator.toarray()-reduced.operator.toarray()).max())
    checks.append(dict(name="uniform_limit_matches_original_R14", error=error,
                       threshold=2e-11, passed=error <= 2e-11))
    old = DistributionContentCore(tail_spacing=None)
    for name, profile in PROFILES.items():
        if name == "old_uniform":
            continue
        model = DistributionContentCore(**profile)
        law = model.reference
        drift = law.up*law.right_steps-law.down*law.left_steps
        variance = law.up*law.right_steps**2+law.down*law.left_steps**2
        for kind, error, limit in (("local_drift", float(abs(drift+.25).max()), 2e-12),
                ("local_variance", float(abs(variance-1.).max()), 2e-12),
                ("same_fine_anchor_basis", float((old.position_basis-model.position_basis[:182]).abs().max()), 0.),
                ("same_fine_positions", float((old.positions-model.positions[:182]).abs().max()),
                    4*np.finfo(np.float64).eps*float(old.positions.max()))):
            checks.append(dict(name=name+"."+kind, error=error, threshold=limit, passed=error <= limit))
        tail_basis = model.position_basis[182:]
        constant_tail = bool((tail_basis[:, -1] == 1).all() and (tail_basis[:, :-1] == 0).all())
        checks.append(dict(name=name+".constant_anchor_extrapolation", passed=constant_tail))
        checks.append(dict(name=name+".nonnegative_rates", passed=bool(min(law.up.min(), law.down.min()) >= 0),
            minimum_up=float(law.up.min()), minimum_down=float(law.down.min()),
            holding_time_min=float((1./(law.up+law.down)).min()),
            holding_time_max=float((1./(law.up+law.down)).max())))
        fixture = model.initial_state(3)
        mass = torch.arange(1, model.n_positions+2, dtype=torch.float64)[None].expand(3, -1)
        fixture['probability'] = mass/mass.sum(-1, keepdim=True)
        fixture['content_moment'] = fixture['probability'].float()[..., None]*torch.randn_like(fixture['content_moment'])
        collapsed = model.collapse(fixture, 'mean_position')
        error = float(((collapsed['probability'][:, :-1]-fixture['probability'][:, :-1])*model.positions).sum(-1).abs().max())
        checks.append(dict(name=name+".nonuniform_mean_collapse", error=error, threshold=2e-12, passed=error <= 2e-12))
        fixture['content_moment'] = fixture['probability'].float()[..., None]*torch.tanh(torch.randn_like(fixture['content_moment']))
        matched = model.collapse(fixture, 'readout_independence')
        error = float((model.read_state(matched)-model.read_state(fixture)).abs().max().detach())
        checks.append(dict(name=name+".readout_independence_preserves_current_feature", error=error,
            threshold=2e-7, passed=error <= 2e-7))
        checks.append(dict(name=name+".readout_independence_preserves_probability",
            passed=bool(torch.equal(matched['probability'], fixture['probability']))))
        excess = float((matched['content_moment'].abs()-matched['probability'][..., None]).max().detach())
        checks.append(dict(name=name+".readout_independence_bounded", excess=excess, threshold=2e-7,
            passed=excess <= 2e-7))
        for t, target in reference.items():
            flow = TailGridFlow(1., -.25, 1., .8, 1/17, fine_positions=182,
                tail_spacing=profile['tail_spacing'], upper=profile['tail_upper'], count_cap=3)
            actual = flow.advance_to(t).observables(edges)
            errors = dict(first_hit=abs(actual['first_hit']-target['first_hit']),
                expected_count=abs(actual['expected_count']-target['expected_count']),
                count_pmf_l1=float(np.abs(np.array(actual['count_pmf_with_overflow'])-target['count_pmf_with_overflow']).sum()),
                active_bins_l1=float(np.abs(np.array(actual['active_bins'])-target['active_bins']).sum()),
                upper_loss=actual['upper_loss'], mass_error=abs(actual['mass']-1))
            limits = dict(first_hit=.0005, expected_count=.002, count_pmf_l1=.002,
                          active_bins_l1=.003, upper_loss=1e-7, mass_error=2e-9)
            rows.append(dict(profile=name, horizon=t, errors=errors, limits=limits,
                passed=all(errors[k] <= limit for k, limit in limits.items()),
                actual=actual, continuous=target, config=model.config))
    return dict(passed=all(r['passed'] for r in rows+checks), rows=rows, checks=checks,
                cpu_seconds=time.process_time()-begin,
                scope="Nonuniform finite process; four initial-state continuous references, not a uniform posterior certificate")


def migrated_model(checkpoint, family, profile):
    from .models import Model
    item = checkpoint['models'][family]
    config = dict(item['config']); config['core_config'] = dict(profile)
    model = Model(**config)
    copied = []
    with torch.no_grad():
        for name, parameter in model.named_parameters():
            source = item['state'][name]
            if source.shape != parameter.shape:
                raise ValueError('Learned parameter mismatch: '+name)
            parameter.copy_(source)
            if not torch.equal(parameter, source):
                raise AssertionError('Learned parameter changed: '+name)
            copied.append(name)
    model.eval()
    return model, copied


def validation_migration(checkpoint_root):
    from .data import dataset, DOMAINS
    begin, rows = time.process_time(), []
    for task in ('recall', 'binding'):
        path = checkpoint_root/'fits'/f'{task}_s15100_value'/'selected.pt'
        checkpoint = torch.load(path, map_location='cpu', weights_only=False)
        checkpoint_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        controller = ValueController(); controller.load_state_dict(checkpoint['controller'])
        for family in DistributionContentCore.FAMILIES:
            models = {name: migrated_model(checkpoint, family, profile) for name, profile in PROFILES.items()}
            for domain in DOMAINS[task]:
                values = dataset(task, 'val', domain)
                x, dt, y = (torch.from_numpy(values[k][:16]) for k in ('x', 'dt', 'y'))
                times = public_times(dt)
                outcomes = {}
                with torch.no_grad():
                    for profile, (model, copied) in models.items():
                        state = model.core.initial_state(len(x), x.device, x.dtype)
                        encoded = model.encoder(x, dt)
                        logits = [model.readout(torch.zeros(len(x), 16))]
                        trace = []
                        for index in range(x.shape[1]):
                            feature, state = model.core.step(encoded[:, index], state, dt[:, index])
                            logits.append(model.readout(feature))
                            p, m = state['probability'], state['content_moment']
                            trace.append(dict(max_upper_loss=float(p[:, -1].max()),
                                mass_error=float((p.sum(-1)-1).abs().max()), min_probability=float(p.min()),
                                moment_bound_excess=float((m.abs()-p[..., None]).max()),
                                highest_fine_tail_probability=float(p[:, 182:-1].sum(-1).max())))
                        logits = torch.stack(logits, 1)
                        q = controller(logits, *times)
                        read = q[..., 1] > q[..., 0]; read[:, -1] = False
                        stop = (~read).long().argmax(-1)
                        row_index = torch.arange(len(x))
                        prediction = logits[row_index, stop].argmax(-1)
                        fees = READ_FEE*stop+TIME_FEE*times[0][row_index, stop]
                        utility = (prediction == y).float()-fees
                        outcomes[profile] = dict(config=model.core.config, copied_parameter_names=copied,
                            max_upper_loss=max(r['max_upper_loss'] for r in trace),
                            max_mass_error=max(r['mass_error'] for r in trace),
                            minimum_probability=min(r['min_probability'] for r in trace),
                            max_moment_bound_excess=max(r['moment_bound_excess'] for r in trace),
                            trace=trace, logits=logits.tolist(), greedy_prediction=prediction.tolist(),
                            greedy_read_count=stop.tolist(), greedy_utility=utility.tolist(),
                            read_all_prediction=logits[:, -1].argmax(-1).tolist())
                comparisons = {}
                base = outcomes['tail_half_upper40']
                for candidate, result in outcomes.items():
                    comparisons[candidate] = dict(
                        max_prefix_logit_change=float(np.abs(np.array(result['logits'])-base['logits']).max()),
                        read_all_prediction_changes=int(np.sum(np.array(result['read_all_prediction']) != base['read_all_prediction'])),
                        greedy_prediction_changes=int(np.sum(np.array(result['greedy_prediction']) != base['greedy_prediction'])),
                        greedy_read_changes=int(np.sum(np.array(result['greedy_read_count']) != base['greedy_read_count'])),
                        mean_greedy_utility_difference=float(np.mean(np.array(result['greedy_utility'])-base['greedy_utility'])))
                row = dict(task=task, family=family, domain=domain, split='val', rows=16,
                    checkpoint_sha256=checkpoint_sha, selected_step=checkpoint['step'],
                    data_sha256=values['sha256'], profiles=outcomes, comparisons_to_tail_half_upper40=comparisons)
                rows.append(row)
                print(json.dumps(dict(task=task,family=family,domain=domain,
                    loss={k:v['max_upper_loss'] for k,v in outcomes.items()}, comparisons=comparisons)),flush=True)
    return dict(rows=rows, cpu_seconds=time.process_time()-begin, no_test_split_read=True,
        learned_parameters_unchanged=True,
        all_extended_profile_loss_below_1e7=all(v['max_upper_loss'] <= 1e-7 for row in rows for name,v in row['profiles'].items() if name!='old_uniform'),
        scope="Validation-only migration of existing development fits, learned parameters unchanged; ordinary stationary/mixing calibration recomputed under each declared extended physical grid")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('numerics','migration'), required=True)
    parser.add_argument('--checkpoint-root', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    result = numerics() if args.mode == 'numerics' else validation_migration(args.checkpoint_root)
    result['source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with args.output.open('x') as stream:
        json.dump(result,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','checks')}))
