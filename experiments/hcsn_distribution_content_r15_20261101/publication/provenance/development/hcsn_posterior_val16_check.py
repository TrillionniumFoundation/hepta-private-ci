import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from experiments.hcsn_distribution_content_r15_20261101.data import dataset, DOMAINS
from experiments.hcsn_distribution_content_r15_20261101.models import restore, PRIMARY
from experiments.hcsn_validation_r14_20261101.content.engine import ValueController, public_times

torch.set_num_threads(1)
torch.set_num_interop_threads(1)
base = Path('/workspace/scratch/e8334174d4c2/development02')
output = Path('/workspace/scratch/e8334174d4c2/hepta/experiments/hcsn_distribution_content_r15_20261101/development_posterior_diagnostics.json')
begin = time.process_time()
rows = []
for task in ('recall', 'binding'):
    path = base / 'fits' / f'{task}_s15100_value' / 'selected.pt'
    deadline = time.monotonic()+600
    while not path.exists():
        if time.monotonic() > deadline:
            raise TimeoutError(str(path))
        time.sleep(2)
    checkpoint = torch.load(path, map_location='cpu', weights_only=False)
    checkpoint_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    controller = ValueController()
    controller.load_state_dict(checkpoint['controller'])
    for family in PRIMARY:
        model = restore(checkpoint, family)
        for domain in DOMAINS[task]:
            values = dataset(task, 'val', domain)
            x = torch.from_numpy(values['x'][:16])
            dt = torch.from_numpy(values['dt'][:16])
            times = public_times(dt)
            trace = []
            with torch.no_grad():
                encoded = model.encoder(x, dt)
                state = model.core.initial_state(len(x), x.device, x.dtype)
                q0 = controller(model.readout(torch.zeros(len(x), 16)), *(v[:, 0] for v in times))
                active = q0[:, 1] > q0[:, 0]
                read_count = torch.zeros(len(x), dtype=torch.long)
                greedy_max_loss = float(state['probability'][:, -1].max())
                previous_loss = state['probability'][:, -1].clone()
                for index in range(x.shape[1]):
                    propagated = model.core.propagate(state, dt[:, index])
                    state = model.core.observe(propagated, encoded[:, index])
                    p, m = state['probability'], state['content_moment']
                    active_mass = p[:, :-1].sum(-1)
                    mean = (p[:, :-1]*model.core.positions).sum(-1)/active_mass.clamp_min(1e-300)
                    near_upper = model.core.positions >= model.core.reference.upper-1.
                    tail = p[:, :-1][:, near_upper].sum(-1)
                    loss = p[:, -1]
                    if active.any():
                        greedy_max_loss = max(greedy_max_loss, float(loss[active].max()))
                    read_count[active] += 1
                    trace.append(dict(step=index+1, physical_time_max=float(times[0][:, index+1].max()),
                        mass_max_abs_error=float((p.sum(-1)-1).abs().max()), min_probability=float(p.min()),
                        max_upper_loss=float(loss.max()), mean_upper_loss=float(loss.mean()),
                        max_upper_loss_increment=float((loss-previous_loss).max()),
                        min_upper_loss_increment=float((loss-previous_loss).min()),
                        observation_changed_cemetery=float((loss-propagated['probability'][:, -1]).abs().max()),
                        last_active_node_mass_max=float(p[:, -2].max()), near_upper_mass_max=float(tail.max()),
                        active_mean_position_min=float(mean.min()), active_mean_position_max=float(mean.max()),
                        active_conditional_max_probability=float((p[:, :-1]/active_mass[:, None].clamp_min(1e-300)).max()),
                        moment_bound_excess=float((m.abs()-p[..., None]).max()),
                        probability_finite=bool(torch.isfinite(p).all()), moment_finite=bool(torch.isfinite(m).all()),
                        greedy_occupied_rows=int(active.sum())))
                    previous_loss = loss.clone()
                    logits = model.readout(model.core.read_state(state))
                    q = controller(logits, *(v[:, index+1] for v in times))
                    active &= q[:, 1] > q[:, 0]
                    if index+1 == x.shape[1]:
                        active[:] = False
            maxima = dict(max_upper_loss=max(r['max_upper_loss'] for r in trace),
                max_near_upper_mass=max(r['near_upper_mass_max'] for r in trace),
                max_mass_error=max(r['mass_max_abs_error'] for r in trace),
                min_probability=min(r['min_probability'] for r in trace),
                max_moment_bound_excess=max(r['moment_bound_excess'] for r in trace),
                max_observation_cemetery_change=max(r['observation_changed_cemetery'] for r in trace),
                min_loss_increment=min(r['min_upper_loss_increment'] for r in trace))
            row = dict(task=task, family=family, domain=domain, split='val', rows=16,
                checkpoint_sha256=checkpoint_sha, selected_step=checkpoint['step'],
                data_sha256=values['sha256'], partition_ids=values['partition_ids'][:16].tolist(),
                config=model.core.config, trace=trace, maxima=maxima,
                greedy_max_upper_loss=greedy_max_loss, greedy_read_counts=read_count.tolist(),
                final_loss_each_row=state['probability'][:, -1].tolist(),
                original_initial_atom_upper_loss_limit=1e-7,
                original_initial_atom_limit_exceeded_on_read_all=maxima['max_upper_loss']>1e-7,
                original_initial_atom_limit_exceeded_on_greedy=greedy_max_loss>1e-7,
                finite_state_invariants_pass=bool(maxima['max_mass_error']<=2e-9 and maxima['min_probability']>=-2e-12 and maxima['max_moment_bound_excess']<=2e-6 and maxima['max_observation_cemetery_change']==0 and maxima['min_loss_increment']>=-2e-12 and all(r['probability_finite'] and r['moment_finite'] for r in trace)))
            rows.append(row)
            print(json.dumps(dict(task=task,family=family,domain=domain,selected_step=checkpoint['step'],maxima=maxima,greedy_max_upper_loss=greedy_max_loss,greedy_read_counts=read_count.tolist())),flush=True)
report = dict(rows=rows, cpu_seconds=time.process_time()-begin,
    helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    no_test_split_read=True, all_finite_invariants_pass=all(r['finite_state_invariants_pass'] for r in rows),
    scope='Development-trained selected weights, first 16 validation objects per domain. Full read-all prefixes and occupied greedy prefixes distinguished. Original initial-atom truncation limit is a diagnostic, not a certificate on all learned posterior states.')
with output.open('x') as stream:
    json.dump(report,stream,indent=2,sort_keys=True,allow_nan=False)
    stream.write('\n')
