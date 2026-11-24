"""Independently reconstruct both holdouts for every saved adaptation candidate."""

import argparse
import json
from pathlib import Path
import time

import numpy as np

if __package__:
    from .verify_predictions import metrics, sha
else:
    from verify_predictions import metrics, sha


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-root', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root, output = Path(args.run_root), Path(args.output)
    if output.exists():
        raise FileExistsError('verification output is create-only')
    started = time.perf_counter()
    protocol = json.loads((root / 'PROTOCOL_FROZEN.json').read_text())
    train_seal = sha(root / 'training' / 'SEAL.json')
    adapt_seal = sha(root / 'adaptation' / 'GLOBAL_ADAPTATION_SEAL.json')
    records = []
    for n in protocol['independent_neurons']:
        for seed in protocol['seeds']:
            name = f'n{n}-qvi_full-s{seed}'
            directory = root / 'adaptation' / name
            final = json.loads((directory / 'FINAL_RESULTS.json').read_text())
            if final['training_seal_sha256'] != train_seal or final['global_adaptation_seal_sha256'] != adapt_seal:
                raise ValueError('adaptation holdout does not bind both seals')
            for method, row in final['results'].items():
                path = directory / method
                individual = json.loads((path / 'test_result.json').read_text())
                if individual != {k: v for k, v in row.items() if k != 'complete_cost_including_result_write'}:
                    raise ValueError('individual and aggregate adaptation result differ')
                if row['status'] != 'evaluated':
                    records.append({'attempt': name, 'method': method, 'status': 'unavailable'})
                    continue
                if sha(path / 'test_predictions.json') != row['predictions_sha256']:
                    raise ValueError('adaptation prediction bytes changed')
                raw = json.loads((path / 'test_predictions.json').read_text())
                errors = []
                for split in ('old', 'new'):
                    data = raw[split]
                    values = metrics(data['all_prefix_logits'], data)
                    a = np.asarray(data['all_prefix_logits'][-1], dtype=np.float64)
                    target = 2 * np.eye(2)[data['labels']] - 1
                    values['signed_target_mse'] = float(np.square(a - target).mean())
                    for key, value in values.items():
                        expected = row['metrics'][split][key]
                        if isinstance(value, dict):
                            if value != expected:
                                raise ValueError('adaptation per-source accuracy differs')
                        else:
                            error = abs(value - expected)
                            errors.append(error)
                            if error > 2e-12:
                                raise ValueError('adaptation metric differs: ' + name + ':' + method + ':' + key)
                records.append({'attempt': name, 'method': method, 'status': 'verified',
                                'max_scalar_error': max(errors), 'scalar_checks': len(errors)})
    report = {'method': 'independent NumPy; no model, Torch or trainer imports', 'rows': records,
              'training_seal_sha256': train_seal, 'adaptation_seal_sha256': adapt_seal,
              'max_scalar_error': max((r.get('max_scalar_error', 0) for r in records), default=0),
              'wall_seconds': time.perf_counter() - started,
              'verifier_sha256': sha(__file__), 'metric_helper_sha256': sha(Path(__file__).with_name('verify_predictions.py'))}
    with output.open('x') as handle:
        json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'verified_adaptation_candidates': sum(r['status'] == 'verified' for r in records),
                      'max_scalar_error': report['max_scalar_error']}))


if __name__ == '__main__':
    main()
