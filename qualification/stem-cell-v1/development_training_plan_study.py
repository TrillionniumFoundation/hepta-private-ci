"""Predeclared synthetic variable-budget fits; no trained allocation policy.

Both timed arms perform the SAME per-Cell work. The original scalar fitter is
retained as the reference, including a measured unchanged copy at zero steps.
Each profile uses 16 heldout source inputs and four correlated task definitions,
not independent tasks per replicated Cell. Outputs precede all heldout scoring.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import platform

import numpy as np
import torch

from development_ablation import PhaseClock, fit_candidate
from development_head_training import SwiGLUCellHead, fit_gated_cells
from development_tensors import parameter_digest

PROFILES = ((1, 16, 8, 2, 8), (64, 384, 8, 4, 8),
            (256, 384, 8, 4, 8), (4096, 64, 4, 2, 8))
SEEDS = (1919, 2929, 3939)


def write_new(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    with path.open('xb') as stream:
        stream.write(raw)
    return hashlib.sha256(raw).hexdigest()


def run_study(output, *, seed):
    if type(seed) is not int or seed not in SEEDS:
        raise ValueError('seed must belong to the predeclared set')
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    source_names = ('development_training_plan_study.py', 'development_head_training.py',
                    'development_ablation.py', 'development_tensors.py')
    source_hashes = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                     for name in source_names}
    write_new(root/'predeclared.json', {'seed': seed, 'profiles': PROFILES,
              'limits_pattern': [0, 1, 4, 8], 'source_sha256': source_hashes,
              'absolute_tolerance': 2e-6, 'relative_tolerance': 2e-5,
              'parent_sha': '28626b8e055e49df124c305fe1f5f05183856999',
              'synthetic_features': True, 'selected_from_scores': False})
    old_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    whole = PhaseClock()
    reports = []
    try:
        with torch.random.fork_rng(devices=[]):
            warm_clock = PhaseClock()
            torch.manual_seed(seed)
            warm_x = torch.randn(4, 4)
            warm_heads = tuple(SwiGLUCellHead(4, 2, 2) for _ in range(2))
            warm_gold = (torch.tensor([0, 1, 0, 1]),) * 2
            for i, head in enumerate(warm_heads):
                fit_candidate(head, warm_x, warm_gold[i], steps=1, seed=seed+i)
            fit_gated_cells(warm_heads, warm_x, (torch.arange(4),) * 2, warm_gold,
                            seeds=(seed, seed+1), steps=1, step_counts=(1, 1))
            warmup = {**warm_clock.finish(), "example_updates_per_arm": 8,
                      "uses_study_features": False}
            for count, width, hidden, classes, ceiling in PROFILES:
                setup = PhaseClock()
                torch.manual_seed(seed + count)
                x, test = torch.randn(64, width), torch.randn(16, width)
                heads = tuple(SwiGLUCellHead(width, hidden, classes) for _ in range(count))
                rows = (torch.arange(64),) * count
                # Labels depend only on supplied features, not Cell identity alone.
                targets = tuple(((x[:, i % 4] > 0).long() +
                                 (x[:, (i+1) % 4] > 0).long() * 2).remainder(classes)
                                for i in range(count))
                plan = (ceiling,) if count == 1 else tuple((0, 1, 4, 8)[i % 4] for i in range(count))
                seeds = tuple(seed + i for i in range(count))
                initial = tuple(map(parameter_digest, heads))
                setup_receipt = setup.finish()
                results, times, receipts = {}, {}, {}
                order = ('scalar', 'grouped') if SEEDS.index(seed) % 2 == 0 else ('grouped', 'scalar')
                # All registered seeds alternate by profile as well, avoiding one fixed order.
                if len(reports) % 2:
                    order = tuple(reversed(order))
                for arm in order:
                    clock = PhaseClock()
                    if arm == 'scalar':
                        candidates, cells = [], []
                        for i, limit in enumerate(plan):
                            if limit:
                                candidate, row = fit_candidate(heads[i], x[rows[i]], targets[i],
                                                               steps=limit, seed=seeds[i])
                            else:
                                candidate = deepcopy(heads[i]).eval()
                                row = {'steps': 0, 'examples_processed': 0}
                            candidates.append(candidate)
                            cells.append(row)
                        candidates = tuple(candidates)
                        receipts[arm] = {'cells': cells,
                                         'optimizer_steps': sum(plan)}
                    else:
                        candidates, receipt = fit_gated_cells(heads, x, rows, targets, seeds=seeds,
                                                              steps=ceiling, step_counts=plan, group_size=32)
                        receipts[arm] = receipt
                    times[arm] = clock.finish()
                    results[arm] = candidates
                checking = PhaseClock()
                errors, equivalent = [], True
                for left, right in zip(results['scalar'], results['grouped']):
                    for a, b in zip(left.parameters(), right.parameters()):
                        errors.append(float((a.detach() - b.detach()).abs().max()))
                        equivalent &= bool(torch.allclose(a, b, atol=2e-6, rtol=2e-5))
                with torch.inference_mode():
                    logits = {arm: torch.stack([h(test) for h in candidates]).numpy()
                              for arm, candidates in results.items()}
                    frozen = torch.stack([h(test) for h in heads]).numpy()
                payload = root / f'predictions-{count}.npz'
                with payload.open('xb') as stream:
                    np.savez_compressed(stream, scalar=logits['scalar'], grouped=logits['grouped'],
                                        frozen=frozen, inputs=test.numpy(), step_counts=np.array(plan))
                # Scoring begins only after ALL inference payloads for this profile are fixed.
                truth = np.stack([((test[:, i % 4] > 0).long() +
                                   (test[:, (i+1) % 4] > 0).long() * 2).remainder(classes).numpy()
                                  for i in range(count)])
                disagreement = int(np.count_nonzero(logits['scalar'].argmax(-1) != logits['grouped'].argmax(-1)))
                output_error = float(np.max(np.abs(logits['scalar'] - logits['grouped'])))
                equivalent &= bool(np.allclose(logits['scalar'], logits['grouped'], atol=2e-6, rtol=2e-5))
                useful = sum(plan) * 32
                observed = {arm: sum(c['examples_processed'] for c in row['cells'])
                            for arm, row in receipts.items()}
                if observed != {'scalar': useful, 'grouped': useful} or tuple(map(parameter_digest, heads)) != initial:
                    raise RuntimeError('work or source immutability mismatch')
                report = {'heads': count, 'width': width, 'hidden': hidden, 'classes': classes,
                          'step_counts': plan, 'zero_step_cells': plan.count(0), 'order': order,
                          'timings': times, 'setup': setup_receipt, 'verification': checking.finish(),
                          'scalar_to_grouped_wall_ratio': times['scalar']['wall_ns']/times['grouped']['wall_ns'],
                          'useful_example_updates': observed,
                          'scalar_optimizer_steps': sum(plan),
                          'grouped_optimizer_steps': sum(g['optimizer_steps'] for g in receipts['grouped']['groups']),
                          'physical_grouped_example_lanes': sum(g['physical_example_lanes'] for g in receipts['grouped']['groups']),
                          'maximum_parameter_error': max(errors), 'maximum_logit_error': output_error,
                          'classification_disagreements': disagreement, 'within_tolerance': bool(equivalent),
                          'correct': {arm: int(np.count_nonzero(value.argmax(-1) == truth))
                                      for arm, value in {**logits, 'frozen': frozen}.items()},
                          'prediction_positions': count*16, 'heldout_source_inputs': 16,
                          'predictions_file': payload.name,
                          'predictions_sha256': hashlib.sha256(payload.read_bytes()).hexdigest(),
                          'grouped_receipt': receipts['grouped'], 'production_authorized': False}
                write_new(root/f'report-{count}.json', report)
                reports.append(report)
                if not equivalent or disagreement:
                    raise RuntimeError('paired numerical gate failed; outputs retained')
        if source_hashes != {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                             for name in source_names}:
            raise RuntimeError('source changed during study')
        summary = {'seed': seed, 'reports': reports, 'total': whole.finish(),
                   'source_sha256': source_hashes, 'warmup': warmup, 'torch': torch.__version__,
                   'python': platform.python_version(), 'platform': platform.platform(),
                   'threads': 1, 'encoder_executed': False, 'learned_allocator': False,
                   'production_authorized': False, 'energy_or_rss_measured': False}
        write_new(root/'summary.json', summary)
        return summary
    except Exception as error:
        write_new(root/'FAILED.json', {'type': type(error).__name__, 'message': str(error),
                                       'source_sha256': source_hashes})
        raise
    finally:
        torch.set_num_threads(old_threads)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic', action='store_true', required=True)
    parser.add_argument('--seed', type=int, choices=SEEDS, required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = run_study(args.output, seed=args.seed)
    print(json.dumps({'seed': args.seed, 'report': str(Path(args.output)/'summary.json'),
                      'production_authorized': False}))
