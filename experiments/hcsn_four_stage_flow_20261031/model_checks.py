"""Development-only causal and state checks on generated inputs, no heldout data."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import traceback

for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[name] = '1'

import torch
from torch.nn import functional as F

from . import models


PROTOCOL = dict(seed=861103, batch=2, steps=6, input_dim=7, classes=8,
                float32_atol=5e-6, zero_observation_min_gap=1e-7,
                boundary_gradient_min_norm=1e-10,
                scope='Development on seeded generated inputs only; no task data or heldout outcomes')


def run(out):
    torch.set_num_threads(1)
    torch.manual_seed(PROTOCOL['seed'])
    rows = []

    def check(name, passed, **details):
        row = dict(name=name, passed=bool(passed), **details)
        rows.append(row)
        with (out / 'cases.jsonl').open('a') as stream:
            stream.write(json.dumps(row, allow_nan=False) + '\n')

    def close(name, actual, reference):
        error = float((actual - reference).abs().max())
        check(name, bool(torch.isfinite(actual).all()) and error <= PROTOCOL['float32_atol'],
              max_absolute_difference=error, tolerance=PROTOCOL['float32_atol'])

    batch, steps = PROTOCOL['batch'], PROTOCOL['steps']
    x = torch.randn(batch, steps, PROTOCOL['input_dim'])
    dt = torch.tensor([[.125, .25, .5, .75, .375, .125], [.25, .5, .125, .375, .75, .25]])
    observed = torch.ones(batch, steps, dtype=torch.bool)
    observed[:, 2] = False
    for index, arm in enumerate(models.ARMS):
        torch.manual_seed(PROTOCOL['seed'] + 100 * index)
        model = models.ContentModel(arm, PROTOCOL['input_dim'], classes=PROTOCOL['classes']).eval()
        with torch.no_grad():
            original = model(x, dt, observed)
            future_x, future_dt, future_observed = x.clone(), dt.clone(), observed.clone()
            future_x[:, 3:] = 7 * torch.randn_like(future_x[:, 3:])
            future_dt[:, 3:] *= 13
            future_observed[:, 3:] = ~future_observed[:, 3:]
            future = model(future_x, future_dt, future_observed)
            close(arm + '/future_does_not_change_prefix', original[:, :3], future[:, :3])

            payload = x.clone(); payload[:, 2] = 11 * torch.randn_like(payload[:, 2])
            changed = model(payload, dt, observed)
            close(arm + '/missing_payload_not_retained', original[:, 3:], changed[:, 3:])

            neighbor_x, neighbor_dt = x.clone(), dt.clone()
            neighbor_x[1] = -9 * torch.randn_like(neighbor_x[1]); neighbor_dt[1] *= 11
            neighbor = model(neighbor_x, neighbor_dt, observed)
            alone = model(x[:1], dt[:1], observed[:1])
            close(arm + '/batch_neighbor_independence', original[:1], neighbor[:1])
            close(arm + '/single_example_independence', original[:1], alone)

            # Subdivide each physical interval by an unobserved placeholder.
            # Real observations and their physical times are identical.
            split_x = torch.zeros(batch, 2 * steps, x.shape[-1]); split_x[:, 1::2] = x
            split_dt = dt.repeat_interleave(2, dim=1) * .5
            split_observed = torch.zeros(batch, 2 * steps, dtype=torch.bool)
            split_observed[:, 1::2] = observed
            split = model(split_x, split_dt, split_observed)[:, 1::2]
            close(arm + '/no_observation_resampling', original[observed], split[observed])

            zeros = x.clone(); zeros[:, 2] = 0
            is_observation = observed.clone(); is_observation[:, 2] = True
            missing = model(zeros, dt, observed)
            seen_zero = model(zeros, dt, is_observation)
            gap = float((missing[:, 3:] - seen_zero[:, 3:]).abs().max())
            check(arm + '/missing_differs_from_observed_zero', gap >= PROTOCOL['zero_observation_min_gap'],
                  maximum_later_output_gap=gap, minimum_gap=PROTOCOL['zero_observation_min_gap'])

            infinite = dt.clone(); infinite[0, 1] = float('inf')
            try:
                model(x, infinite, observed); refused = False
            except ValueError:
                refused = True
            check(arm + '/infinite_duration_refused', refused)

    # Detach directly supplied probability/value/boundary features so a passing
    # gradient has to reach boundary control through transported content moments.
    torch.manual_seed(PROTOCOL['seed'] + 701)
    model = models.ContentModel('flow', PROTOCOL['input_dim'], classes=PROTOCOL['classes'])
    captured = []
    hook_control = model.control.register_forward_hook(lambda module, inputs, output: captured.append(output))
    memory_end = models.STATES * models.WIDTH
    physics_end = memory_end + models.STATES + 3

    def detach_direct_physics(module, inputs):
        features = inputs[0]
        return (torch.cat((features[:, :memory_end], features[:, memory_end:physics_end].detach(),
                           features[:, physics_end:]), -1),)

    hook_read = model.read.register_forward_pre_hook(detach_direct_physics)
    logits = model(x, dt, observed)
    loss = F.cross_entropy(logits[:, -1], torch.tensor([1, 6]))
    gradient, = torch.autograd.grad(loss, captured[0])
    boundary_gradient = gradient[..., 0]
    norm = float(boundary_gradient.norm())
    check('flow/boundary_gradient_through_content', bool(torch.isfinite(boundary_gradient).all())
          and norm >= PROTOCOL['boundary_gradient_min_norm'], gradient_norm=norm,
          boundary_gradients=boundary_gradient.detach().tolist(), direct_physics_features_detached=True)
    check('flow/missing_control_gradient_zero', bool((boundary_gradient[:, 2] == 0).all()),
          gradient=boundary_gradient[:, 2].detach().tolist())
    hook_control.remove(); hook_read.remove()
    return rows


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--out', required=True); args = parser.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=False)
    directory = Path(__file__).resolve().parent
    paths = [directory / name for name in ('model_checks.py', 'models.py', 'marked_flow.py')]
    frozen = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    snapshot = out / 'sources'; snapshot.mkdir()
    for path in paths:
        shutil.copyfile(path, snapshot / path.name)
    (out / 'SOURCE_FREEZE.json').write_text(json.dumps(frozen, indent=2))
    (out / 'PROTOCOL.json').write_text(json.dumps(PROTOCOL, indent=2))
    start, cpu = time.perf_counter(), time.process_time()
    try:
        rows = run(out)
    except Exception as error:
        (out / 'EXCEPTION.txt').write_text(traceback.format_exc())
        rows = [json.loads(line) for line in (out / 'cases.jsonl').read_text().splitlines()] if (out / 'cases.jsonl').exists() else []
        rows.append(dict(name='execution_exception', passed=False, error=str(error)))
    rows.append(dict(name='source_unchanged', passed=all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
                                                       for path, digest in frozen.items())))
    failures = [row for row in rows if not row['passed']]
    summary = dict(stage='development_only', checks=len(rows), failed=len(failures), success=not failures,
                   wall_seconds=time.perf_counter() - start, cpu_seconds=time.process_time() - cpu,
                   clock_scope='After imports', scope=PROTOCOL['scope'])
    (out / 'ALL_CHECKS.json').write_text(json.dumps(rows, indent=2))
    (out / 'FAILURES.json').write_text(json.dumps(failures, indent=2))
    (out / 'SUMMARY.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary)); return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
